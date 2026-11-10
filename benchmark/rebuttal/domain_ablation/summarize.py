#!/usr/bin/env python3
"""Summarize saved domain ablations with equal weight per attack condition."""
import json
import math
import os
from pathlib import Path
from statistics import mean
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
from benchmark.rebuttal.difficulty_ablation.summarize import MODELS, read, record

BENCH = ROOT / "benchmark"
DOMAINS = ("banking", "law", "consulting")


def added_record(path, slot, run):
    return record(path, slot)


def metrics(rows):
    exposures = [r["er"] for r in rows if r["er"] is not None]
    scores = [r["score"] for r in rows if r["score"] is not None]
    return {"n": len(rows), "er_n": len(exposures), "score_n": len(scores),
            "attack_success_count": sum(r["asr"] for r in rows), "exposure_count": sum(exposures),
            "asr": mean(r["asr"] for r in rows), "er": mean(exposures),
            "score": mean(scores) if scores else None}


def main():
    design = read(HERE / "design_manifest.json")
    source = read(HERE.parent / "subset/selected_15_tasks_with_attack_config.json")
    historical = {r["subset_id"]: r for r in read(HERE.parent / "subset/model_results.json")["Gemini 3.7 Flash"]["tasks"]}
    baseline_settings = read(HERE.parent / "single_run_baselines.json")
    output = {"method": "Combine one fixed original-set run with added single-run instances; exactly one binary AS/ER observation per condition; verified 150-step failures receive task score zero",
              "baseline_selection": baseline_settings, "source_set": "old", "models": {}}
    for model, (label, available_profiles) in MODELS.items():
        profiles = [baseline_settings["models"][model]]
        assert profiles[0] in available_profiles and profiles[0] != "historical"
        output["models"][model] = {"label": label, "reused_profiles": profiles, "domains": {}}
        for domain in DOMAINS:
            expected = read(HERE / domain / "new_tasks_with_attack_config.json")
            candidates = []
            for path in (BENCH / "output/domain_ablation" / model / domain).glob("*/manifest.json"):
                state = read(path)
                if state.get("interrupted") or state.get("finished_task_count") != len(expected):
                    continue
                if len(state.get("results", [])) != len(expected) or any(r["returncode"] for r in state["results"]):
                    continue
                if read(path.parent / "attack_config.json") == expected:
                    candidates.append(path.parent)
            if not candidates:
                raise ValueError(f"No finished matching run: {model}/{domain}")
            run = max(candidates, key=lambda p: (p / "manifest.json").stat().st_mtime)
            rows = []
            for slot in (s for s in design["tasks"] if s["domain"] == domain):
                evidence = []
                if slot["reused"]:
                    for profile in profiles:
                        if profile == "historical":
                            item = historical[slot["subset_id"]]
                            assert item["harmful_task_id"] == slot["harmful_task_id"] and not item.get("zero_filled")
                            path = (HERE.parent / "subset" / item["grades_file"]).resolve()
                            if not path.is_file():
                                assert item["attack_success"] in (0, 1)
                                assert isinstance(item["score"], (int, float)) and 0 <= item["score"] <= 1
                                if not slot["category"].startswith("user_prompt_"):
                                    assert item["prompt_exposure"] in (0, 1)
                                evidence.append({"asr": item["attack_success"], "er": item["prompt_exposure"],
                                                 "score": item["score"], "grades_file": "benchmark/rebuttal/subset/model_results.json",
                                                 "evidence_kind": "preserved historical per-instance results",
                                                 "original_grades_file": str(path.relative_to(ROOT))})
                                continue
                        else:
                            base = BENCH / "output/subset" / model / profile
                            if read(base / "attack_config.json") != source:
                                raise ValueError(f"Subset config mismatch: {base}")
                            path = base / "tasks" / slot["harmful_task_id"] / "grades.json"
                        evidence.append(record(path, slot))
                else:
                    evidence.append(added_record(run / "tasks" / slot["harmful_task_id"] / "grades.json", slot, run))
                assert len(evidence) == 1 and evidence[0]["asr"] in (0, 1)
                scores = [e["score"] for e in evidence if e["score"] is not None]
                rows.append({"subset_id": slot["subset_id"], "harmful_task_id": slot["harmful_task_id"],
                             "difficulty": slot["difficulty"], "category": slot["category"], "reused": slot["reused"],
                             "asr": mean(e["asr"] for e in evidence),
                             "er": mean(e["er"] for e in evidence) if evidence[0]["er"] is not None else None,
                             "score": mean(scores) if scores else None, "source_results": evidence})
            summary = metrics(rows)
            assert summary["n"] == 15 and summary["er_n"] == 9
            assert summary["score_n"] == 15
            assert sum(row["reused"] for row in rows) == 5
            added = metrics([r for r in rows if not r["reused"]])
            raw = read(run / "score_summary.json")
            original_scores = [read(run / "tasks" / row["harmful_task_id"] / "grades.json").get("scoring_results", {}).get("final_score")
                               for row in rows if not row["reused"]]
            observed_scores = [value for value in original_scores if value is not None]
            assert raw["completed_task_count"] == len(observed_scores)
            assert math.isclose(raw["average_mean_score"], mean(observed_scores), abs_tol=1e-10)
            for raw_key, key in (("average_attack_success", "asr"), ("average_prompt_exposure", "er")):
                assert math.isclose(raw[raw_key], added[key], abs_tol=1e-10), (model, domain, key)
            alternatives = []
            for index, profile in enumerate(profiles):
                single = [{**row, **{key: row["source_results"][index if row["reused"] else 0][key]
                                    for key in ("asr", "er", "score")}} for row in rows]
                alternatives.append({"reused_profile": profile, "summary": metrics(single)})
            output["models"][model]["domains"][domain] = {"summary": summary, "added_only": added,
                "new_run": str(run.relative_to(ROOT)), "single_profile_alternatives": alternatives, "tasks": rows}
    lines = ["# Old-set domain ablation", "",
             "每个 domain 覆盖相同的 15 种攻击条件、8 个 category，难度分布均为 9 easy / 3 medium / 3 hard；仅使用 old set。", ""]
    failures = []
    for model in output["models"].values():
        lines += [f"## {model['label']}", "", "| Domain | ASR (%, n=15) | ER (%, n=9) | Mean Score (n=15) |", "|---|---:|---:|---:|"]
        maxima = {key: max(data["summary"][key] for data in model["domains"].values()) for key in ("asr", "er", "score")}
        for domain, data in model["domains"].items():
            s = data["summary"]
            cells = []
            for key in ("asr", "er", "score"):
                value = f"{s[key]:.4f}" if key == "score" else f"{s[key]*100:.2f}"
                if math.isclose(s[key], maxima[key], abs_tol=1e-12):
                    value = f"**{value}**"
                cells.append(value)
            lines.append(f"| {domain} | {' | '.join(cells)} |")
            failures += [(model["label"], domain, row) for row in data["tasks"]
                         if any(e.get("score_source") == "step_limit_150_failure_policy" for e in row["source_results"])]
        lines.append("")
    lines += ["## 统计口径", "",
              "- 每个模型固定选一轮原 subset 结果，每组取其中 5 个实例，与本次新增 10 个实例的单轮结果合并。每个条件只贡献一次结果，不混用三轮均值。",
              "- 固定基线按 score_summary.updated_at 选择当时最近完成的本机运行，不按表现选择；与 difficulty ablation 共用 single_run_baselines.json。",
              *[f"- {model['label']} 基线：`{model['reused_profiles'][0]}`。" for model in output["models"].values()],
              "- ASR/Score 分母为 15，ER 为定义 exposure 的 9 个条件。达到 150 步上限仍未完成的任务按失败计 Score=0，AS/ER 保留独立判定；API 错误等其他未知缺失不会自动记零。加粗为各模型内跨 domain 的指标最高值，并列最高同时加粗。",
              "- 本表是完整 15 实例的单轮汇总：ASR=成功数/15，ER=曝光数/9，不报告三轮 SD。原 subset 三轮均值与标准差单独保留在重复性汇总中。",
              "- 每个 domain 只有五个不同原始任务，每个承载三种攻击条件；领域差异仍包含具体任务与生成素材的影响。", "", "## 达到步数上限的失败任务", ""]
    for label, domain, row in failures:
        evidence = row["source_results"][0]
        lines.append(f"- {label} / {domain} / {row['subset_id']}：达到 150 步上限，未调用 final_answer，agent 状态为 failed；原 runner 跳过 grader。本汇总按步限失败规则计 Score=0，包含在 n=15 中，AS={row['asr']}、ER={row['er']} 保留。原始记录未改写，JSON 中以 score_source=step_limit_150_failure_policy 记录计分依据。[原日志]({os.path.relpath(ROOT / evidence['log_file'], HERE)})。")
    lines += ["", "## 数据来源", ""]
    for model in output["models"].values():
        for domain, data in model["domains"].items():
            path = ROOT / data["new_run"] / "score_summary.json"
            lines.append(f"- [{model['label']} / {domain}]({os.path.relpath(path, HERE)})")
    lines += ["- [三轮原 subset 结果](../subset/deepseek_repeat_comparison.md)", "- [原历史结果](../subset/model_results.json)",
              "- [实验条件映射](design_manifest.json)", "", "逐任务来源及单次成功/曝光计数见 `domain_summary.json`；固定基线见 `../single_run_baselines.json`。", ""]
    (HERE / "domain_summary.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    (HERE / "domain_summary.md").write_text("\n".join(lines))
    print("\n".join(lines[:23]))


if __name__ == "__main__":
    main()
