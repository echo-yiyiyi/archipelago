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
    return {"n": len(rows), "er_n": len(exposed), "attack_success_count": sum(r["asr"] for r in rows),
            "exposure_count": sum(exposed), "asr": mean(r["asr"] for r in rows),
            "er": mean(exposed), "score": mean(r["score"] for r in rows)}


def main():
    design = read(HERE / "design_manifest.json")
    source = read(HERE.parent / "subset/selected_15_tasks_with_attack_config.json")
    historical = {r["subset_id"]: r for r in read(HERE.parent / "subset/model_results.json")["Gemini 3.7 Flash"]["tasks"]}
    baseline_settings = read(HERE.parent / "single_run_baselines.json")
    output = {"method": "Combine one fixed original-set run with the added single-run instances; exactly one binary AS/ER observation per condition",
              "baseline_selection": baseline_settings, "source_set": "old", "models": {}}
    for model, (label, available_profiles) in MODELS.items():
        profiles = [baseline_settings["models"][model]]
        assert profiles[0] in available_profiles and profiles[0] != "historical"
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
                assert len(evidence) == 1 and evidence[0]["asr"] in (0, 1)
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
             "Each instance contributes one evaluated result; the fixed original-set baseline run is shared with the domain ablation.", ""]
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
              "- 每个模型固定选一轮原 subset 结果，easy/medium/hard 分别取其中 9/3/3 个实例，与新增 6/12/12 个实例的单轮结果合并。每个条件只贡献一次结果，不混用三轮均值。",
              "- 固定基线按 score_summary.updated_at 选择当时最近完成的本机运行，不按 ASR/ER/Score 选择；两种 ablation 共用 single_run_baselines.json。",
              *[f"- {model['label']} 基线：`{model['reused_profiles'][0]}`。" for model in output["models"].values()],
              "- ASR 是成功数/15，ER 是曝光数/9；百分比分别按 1/15 和 1/9 的步长变化。原 subset 三轮均值与标准差保留在独立的重复性汇总中，不用于本表拼接。",
              "- 本表是单轮完整 15 实例汇总，不报告三轮标准差。",
              "- 原始任务数量：easy=9、medium=3、hard=3。每组均为 15 个攻击实例，不能据此声称每组有 15 个独立原始任务。",
              "- 本表是描述性对比，不构成因果或显著性结论。", "",
              "## 数据来源", "", "新增结果："]
    import os
    for model in output["models"].values():
        for level, data in model["difficulties"].items():
            path = ROOT / data["new_run"] / "score_summary.json"
            lines.append(f"- [{model['label']} / {level}]({os.path.relpath(path, HERE)})")
    lines += ["", "复用结果：", "", "- [三轮原 subset 结果与来源](../subset/deepseek_repeat_comparison.md)",
              "- [原 Gemini 历史结果](../subset/model_results.json)", "- [实验条件映射](design_manifest.json)", "",
              "完整精度、单次成功/曝光计数及逐实例来源见 `difficulty_summary.json`；固定基线见 `../single_run_baselines.json`。", ""]
    (HERE / "difficulty_summary.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    (HERE / "difficulty_summary.md").write_text("\n".join(lines))
    print("\n".join(lines[:12]))


if __name__ == "__main__":
    main()
