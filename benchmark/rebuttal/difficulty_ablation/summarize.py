#!/usr/bin/env python3
"""Summarize 15 matched conditions per difficulty using saved old-set results."""
import json
import math
from pathlib import Path
from statistics import mean

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BENCH = ROOT / "benchmark"
MODELS = {
    "gemini37": ("Gemini 3.7 Flash", ["historical", "gemini37_subset_6ec42a2a10c8", "gemini37_subset_d460da681561"]),
    "deepseekv4": ("DeepSeek Flash", ["deepseek_subset_be9eaed0c1eb", "deepseek_subset_7f1d3b6710af", "deepseek_subset_6b01a674aa46"]),
}
LEVELS = ("easy", "medium", "hard")


def read(path):
    return json.loads(path.read_text())


def record(path, slot):
    grade = read(path)
    score = grade.get("scoring_results", {}).get("final_score")
    trajectory = path.parent / "trajectory.json"
    status = read(trajectory).get("status") if trajectory.exists() else None
    policy = {}
    if status == "failed":
        logs = list((path.parents[2] / "logs").glob("*" + path.parent.name + "*"))
        if len(logs) == 1 and "Not finalized after 150 steps" in logs[0].read_text(errors="replace"):
            policy = {"score_source": "step_limit_150_failure_policy", "original_task_score": score,
                      "task_failure": "not_finalized_after_150_steps", "log_file": str(logs[0].relative_to(ROOT))}
            score = 0.0
    if not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
        raise ValueError(f"Invalid/missing score: {path}")
    if grade.get("attack_success") not in (0, 1):
        raise ValueError(f"Invalid/missing AS: {path}")
    if grade.get("attack_error") or grade.get("prompt_exposure_error"):
        raise ValueError(f"Judge error: {path}")
    if any(isinstance(rule, dict) and rule.get("error") for rule in grade.get("attack_rules", {}).values()):
        raise ValueError(f"Attack-rule judge error: {path}")
    if status is not None and status != "completed" and not policy:
        raise ValueError(f"Agent did not complete: {trajectory}")
    er = None if slot["category"].startswith("user_prompt_") else grade.get("prompt_exposure")
    if not slot["category"].startswith("user_prompt_") and er not in (0, 1):
        raise ValueError(f"Missing ER: {path}")
    return {"asr": grade["attack_success"], "er": er, "score": score,
            "grades_file": str(path.relative_to(ROOT)), **policy}


def metrics(rows):
    exposed = [r["er"] for r in rows if r["er"] is not None]
    return {"n": len(rows), "er_n": len(exposed), "asr": mean(r["asr"] for r in rows),
            "er": mean(exposed), "score": mean(r["score"] for r in rows)}


def main():
    design = read(HERE / "design_manifest.json")
    source = read(HERE.parent / "subset/selected_15_tasks_with_attack_config.json")
    historical = {r["subset_id"]: r for r in read(HERE.parent / "subset/model_results.json")["Gemini 3.7 Flash"]["tasks"]}
    output = {"method": "Average each reused condition over the three original-set runs; use its single added run otherwise; weight conditions equally",
              "source_set": "old", "models": {}}
    for model, (label, profiles) in MODELS.items():
        output["models"][model] = {"label": label, "reused_profiles": profiles, "difficulties": {}}
        for level in LEVELS:
            expected = read(HERE / level / "new_tasks_with_attack_config.json")
            candidates = []
            for path in (BENCH / "output/difficulty_ablation" / model / level).glob("*/manifest.json"):
                manifest = read(path)
                if manifest.get("interrupted") or manifest.get("finished_task_count") != len(expected):
                    continue
                if len(manifest.get("results", [])) != len(expected) or any(r["returncode"] for r in manifest["results"]):
                    continue
                if read(path.parent / "attack_config.json") != expected:
                    continue
                candidates.append(path.parent)
            if not candidates:
                raise ValueError(f"No completed matching run: {model}/{level}")
            run = max(candidates, key=lambda p: (p / "manifest.json").stat().st_mtime)
            rows = []
            for slot in (s for s in design["tasks"] if s["difficulty"] == level):
                evidence = []
                if slot["reused"]:
                    for profile in profiles:
                        if profile == "historical":
                            item = historical[slot["subset_id"]]
                            path = (HERE.parent / "subset" / item["grades_file"]).resolve()
                            if not path.is_file():
                                # Historical raw runs are not all present on this
                                # machine; use the preserved per-instance cache.
                                assert item["harmful_task_id"] == slot["harmful_task_id"]
                                assert not item.get("zero_filled")
                                assert item["attack_success"] in (0, 1)
                                assert isinstance(item["score"], (int, float)) and 0 <= item["score"] <= 1
                                er = item["prompt_exposure"]
                                if not slot["category"].startswith("user_prompt_"):
                                    assert er in (0, 1)
                                evidence.append({"asr": item["attack_success"], "er": er,
                                                 "score": item["score"],
                                                 "grades_file": "benchmark/rebuttal/subset/model_results.json",
                                                 "evidence_kind": "preserved historical per-instance results",
                                                 "original_grades_file": str(path.relative_to(ROOT))})
                                continue
                        else:
                            base = BENCH / "output/subset" / model / profile
                            if read(base / "attack_config.json") != source:
                                raise ValueError(f"Original subset config mismatch: {base}")
                            path = base / "tasks" / slot["harmful_task_id"] / "grades.json"
                        evidence.append(record(path, slot))
                else:
                    evidence.append(record(run / "tasks" / slot["harmful_task_id"] / "grades.json", slot))
                rows.append({"subset_id": slot["subset_id"], "harmful_task_id": slot["harmful_task_id"],
                             "domain": slot["domain"], "category": slot["category"], "reused": slot["reused"],
                             "asr": mean(e["asr"] for e in evidence),
                             "er": mean(e["er"] for e in evidence) if evidence[0]["er"] is not None else None,
                             "score": mean(e["score"] for e in evidence), "source_results": evidence})
            summary = metrics(rows)
            assert summary["n"] == 15 and summary["er_n"] == 9
            added = metrics([r for r in rows if not r["reused"]])
            raw = read(run / "score_summary.json")
            for raw_key, key in (("average_attack_success", "asr"), ("average_prompt_exposure", "er"), ("average_mean_score", "score")):
                assert math.isclose(raw[raw_key], added[key], abs_tol=1e-10), (model, level, key)
            alternatives = []
            for index, profile in enumerate(profiles):
                single = [{**r, **{k: r["source_results"][index if r["reused"] else 0][k] for k in ("asr", "er", "score")}} for r in rows]
                alternatives.append({"reused_profile": profile, "summary": metrics(single)})
            output["models"][model]["difficulties"][level] = {
                "summary": summary, "added_only": added, "new_run": str(run.relative_to(ROOT)),
                "single_profile_alternatives": alternatives, "tasks": rows}
    lines = ["# Old-set difficulty ablation", "", "每个难度覆盖同样的 15 种攻击条件，domain 各 5 个；仅使用 old set。", "",
             "Each difficulty group contains **n = 15 attack instances**, with **n_ER = 9** for ER. "
             "**N** denotes the number of distinct source tasks. Reused instances are averaged over three original-set runs; "
             "added instances are evaluated once. These are not three independent complete ablation runs.", ""]
    for model in output["models"].values():
        lines += [f"## {model['label']}", "",
                  "| Difficulty | ASR (%, n=15) | ER (%, n=9) | Mean Score (n=15) |", "|---|---:|---:|---:|"]
        maxima = {key: max(data["summary"][key] for data in model["difficulties"].values())
                  for key in ("asr", "er", "score")}
        for level, data in model["difficulties"].items():
            s = data["summary"]
            cells = []
            for key in ("asr", "er", "score"):
                value = f"{s[key]:.4f}" if key == "score" else f"{s[key]*100:.2f}"
                cells.append(f"**{value}**" if math.isclose(s[key], maxima[key], abs_tol=1e-12) else value)
            lines.append(f"| {level} | {' | '.join(cells)} |")
        lines.append("")
    lines += ["", "## 统计口径", "",
              "- 每组 ASR/Score 对 15 种攻击条件等权平均，ER 仅对定义曝光的 9 种条件平均。无缺失评分、无补零。",
              "- 原始实例按之前三轮结果逐实例取均值后复用；easy/medium/hard 各复用 9/3/3 个，其余新增 6/12/12 个各跑一次。不是仅统计新增实例，也没有按评测次数给复用实例更高权重。",
              "- Gemini 的三轮为历史一次＋本机两次；DeepSeek 为本机三次，与前面的新旧 set 对比口径一致。历史 Gemini 的执行代码和 exposure 评估未验证与当前完全相同。",
              "- 本机缺少部分历史 Gemini 原始 grades 文件，对应数值读取已保存的 `subset/model_results.json` 逐实例记录；没有把它们标记为本次重新核验的原始评分。",
              "- 新增实例只有单轮，因此本表没有整套实验的三轮标准差；不能将原实例的三次复用当作三套独立的完整 ablation。",
              "- 原始任务数量：easy=9、medium=3、hard=3。每组均为 15 个攻击实例，不能据此声称每组有 15 个独立原始任务。",
              "- 两模型的任务得分均随难度升高而下降，ASR 均有所上升；ER 的变化方向不同。这是本轮描述性结果，不构成因果或显著性结论。", "",
              "## 数据来源", "", "新增结果："]
    import os
    for model in output["models"].values():
        for level, data in model["difficulties"].items():
            path = ROOT / data["new_run"] / "score_summary.json"
            lines.append(f"- [{model['label']} / {level}]({os.path.relpath(path, HERE)})")
    lines += ["", "复用结果：", "", "- [三轮原 subset 结果与来源](../subset/deepseek_repeat_comparison.md)",
              "- [原 Gemini 历史结果](../subset/model_results.json)", "- [实验条件映射](design_manifest.json)", "",
              "完整精度、逐实例来源，以及分别使用每一轮旧结果的敏感性汇总，见 `difficulty_summary.json`。", ""]
    (HERE / "difficulty_summary.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    (HERE / "difficulty_summary.md").write_text("\n".join(lines))
    print("\n".join(lines[:12]))


if __name__ == "__main__":
    main()
