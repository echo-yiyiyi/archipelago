#!/usr/bin/env python3
"""Compare a completed more15 run with the three valid local subset reruns."""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from statistics import mean, stdev
import time

HERE = Path(__file__).resolve().parent
BENCH = HERE.parents[1]
BUNDLE = HERE / "final_15_more"
BASELINES = ("deepseek_subset_be9eaed0c1eb", "deepseek_subset_7f1d3b6710af", "deepseek_subset_6b01a674aa46")


def read(path):
    return json.loads(path.read_text())


def collect(run, slots, *, old=False):
    manifest = read(run / "manifest.json")
    if manifest.get("finished_task_count") != 15 or manifest.get("interrupted"):
        raise ValueError(f"Run is incomplete: {run}")
    results = manifest.get("results", [])
    if not isinstance(results, list) or len(results) != 15 or any(r.get("returncode") != 0 for r in results):
        raise ValueError(f"Run has failed or missing task processes: {run}")
    summary = read(run / "score_summary.json")
    if summary["completed_task_count"] != 15:
        raise ValueError(f"Run has incomplete grading: {run}")
    rows = []
    for slot in slots:
        identifier = slot["source_harmful_task_id" if old else "harmful_task_id"]
        path = run / "tasks" / identifier / "grades.json"
        grade = read(path)
        score = grade.get("scoring_results", {}).get("final_score")
        er_defined = not slot["category"].startswith("user_prompt_")
        attack, exposure = grade.get("attack_success"), grade.get("prompt_exposure") if er_defined else None
        if attack not in (0, 1) or (er_defined and exposure not in (0, 1)):
            raise ValueError(f"Missing attack/exposure result: {path}")
        if grade.get("attack_error") or grade.get("prompt_exposure_error"):
            raise ValueError(f"Judge error: {path}")
        if not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError(f"Invalid task score: {path}")
        rows.append({**slot, "evaluated_harmful_task_id": identifier, "asr": attack, "er": exposure,
                     "score": score, "grades_file": str(path.relative_to(BENCH.parent))})
    totals = aggregate(rows)
    for key, value in (("average_attack_success", totals["asr"]), ("average_prompt_exposure", totals["er"]),
                       ("average_mean_score", totals["score"])):
        if not math.isclose(summary[key], value, abs_tol=1e-10):
            raise ValueError(f"Per-task grades disagree with {key}: {run}")
    return {"run_directory": str(run.relative_to(BENCH.parent)), "summary": totals, "tasks": rows}


def aggregate(rows):
    exposure = [r["er"] for r in rows if r["er"] is not None]
    return {"n": len(rows), "as_count": sum(r["asr"] for r in rows), "asr": mean(r["asr"] for r in rows),
            "er_n": len(exposure), "er_count": sum(exposure), "er": mean(exposure) if exposure else None,
            "score": mean(r["score"] for r in rows)}


def average_runs(runs):
    return {metric: {"mean": mean(r["summary"][metric] for r in runs),
                     "sample_sd": stdev(r["summary"][metric] for r in runs)} for metric in ("asr", "er", "score")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--wait", action="store_true", help="Wait for the selected run to finish; never rerun agents or judges")
    args = parser.parse_args()
    run = (args.run_dir or max((BENCH / "output/final_15_more/deepseekv4").iterdir(), key=lambda p: p.stat().st_mtime)).resolve()
    while not (run / "manifest.json").exists():
        if not args.wait:
            raise SystemExit(f"Run is still in progress: {run}; use --wait")
        summary = read(run / "score_summary.json")
        print(f"Waiting: {summary['completed_task_count']}/15 tasks graded", flush=True)
        time.sleep(30)
    slots = read(BUNDLE / "generation_manifest.json")["tasks"]
    new = collect(run, slots)
    baselines = [collect(BENCH / "output/subset/deepseekv4" / name, slots, old=True) for name in BASELINES]
    baseline = average_runs(baselines)
    historical = read(HERE.parent / "subset/model_results.json")["DeepSeek V4 Flash"]["summary"]
    delta = {key: new["summary"][key] - baseline[key]["mean"] for key in baseline}
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "new": new, "subset_runs": baselines,
              "subset_mean_and_sample_sd": baseline, "delta_new_minus_subset_mean": delta,
              "historical_subset": historical}
    lines = ["# 新增 15 个任务与原 subset 对比（DeepSeek）", "",
             "新任务一轮与原 subset 三次有效本机重跑比较；均使用配置后缀 `deepseekv4`。", "",
             "| 数据 | 轮数 | ASR（N=15） | ER（N=9） | Mean Score（N=15） |", "|---|---:|---:|---:|---:|"]
    for label, data in [("新增 15 个", new), *[(f"原 subset 重跑 {i}", r) for i, r in enumerate(baselines, 1)]]:
        s = data["summary"]
        lines.append(f"| {label} | 1 | {s['asr']:.2%} ({s['as_count']}/15) | {s['er']:.2%} ({s['er_count']}/9) | {s['score']:.4f} |")
    lines += [f"| 原 subset 均值 ± 样本 SD | 3 | {baseline['asr']['mean']*100:.2f} ± {baseline['asr']['sample_sd']*100:.2f}% | {baseline['er']['mean']*100:.2f} ± {baseline['er']['sample_sd']*100:.2f}% | {baseline['score']['mean']:.4f} ± {baseline['score']['sample_sd']:.4f} |",
              f"| 新任务 − subset 均值 | — | {delta['asr']*100:+.2f} pp | {delta['er']*100:+.2f} pp | {delta['score']:+.4f} |", "",
              f"历史主实验 subset 仅作参考：ASR {historical['asr']:.2%}，ER {historical['er']:.2%}，Score {historical['score']:.4f}。未与本机重跑混合计算。", ""]
    grouped = {}
    for field, title in (("category", "攻击类别"), ("domain", "Domain"), ("difficulty", "难度")):
        lines += [f"## 按{title}比较", "", "| 分组 | 新任务 N / ER N | 新 ASR | subset ASR 均值 | 新 ER | subset ER 均值 | 新 Score | subset Score 均值 |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|"]
        grouped[field] = {}
        for value in dict.fromkeys(r[field] for r in slots):
            n = aggregate([r for r in new["tasks"] if r[field] == value])
            old = [aggregate([r for r in b["tasks"] if r[field] == value]) for b in baselines]
            means = {k: mean(r[k] for r in old) if old[0][k] is not None else None for k in ("asr", "er", "score")}
            grouped[field][value] = {"new": n, "subset_mean": means}
            pct = lambda x: "—" if x is None else f"{x:.2%}"
            lines.append(f"| {value} | {n['n']} / {n['er_n']} | {pct(n['asr'])} | {pct(means['asr'])} | {pct(n['er'])} | {pct(means['er'])} | {n['score']:.4f} | {means['score']:.4f} |")
        lines.append("")
    report["grouped"] = grouped
    lines += ["## 对应槽位逐项比较", "", "同槽位保持 domain、difficulty、goal、vector 与变体开关一致，但原始任务和生成素材不同。subset 列为三次重跑均值。", "",
              "| 槽位 | Goal | Vector | 新 AS | subset AS 均值 | 新 ER | subset ER 均值 | 新 Score | subset Score 均值 |",
              "|---|---|---|---:|---:|---:|---:|---:|---:|"]
    for i, row in enumerate(new["tasks"]):
        old = [b["tasks"][i] for b in baselines]
        er = "—" if row["er"] is None else str(row["er"])
        old_er = "—" if old[0]["er"] is None else f"{mean(r['er'] for r in old):.3f}"
        lines.append(f"| {row['subset_id']} | {row['inject_goal']} | {row['inject_vector']} | {row['asr']} | {mean(r['asr'] for r in old):.3f} | {er} | {old_er} | {row['score']:.4f} | {mean(r['score'] for r in old):.4f} |")
    lines += ["", "## 口径和限制", "", "- ASR、Score 的分母为 15；ER 只对定义 exposure 的 9 个实例计算，其他 6 个不记为 0。",
              "- 每轮均要求完成 15/15、任务进程退出码为 0，且没有缺失评分或 judge error；逐任务数值与 score_summary 交叉核对。",
              "- subset 的 SD 衡量三次运行间波动；新任务目前只有一轮，不能据此判断统计显著性。",
              "- 原始任务与攻击素材同时变化，因此差异不能单独归因于任务更换；相同模型别名也不保证跨日期远端权重完全固定。历史运行与当前执行代码未验证完全一致。", "", "## 数据来源", ""]
    import os
    for data in [new, *baselines]:
        source = BENCH.parent / data["run_directory"] / "score_summary.json"
        lines.append(f"- [{source.parent.name}]({os.path.relpath(source, BUNDLE)})")
    lines += ["", "完整精度、逐任务评分路径和分组统计：`subset_comparison.json`。", ""]
    (BUNDLE / "subset_comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (BUNDLE / "subset_comparison.md").write_text("\n".join(lines))
    print(json.dumps({"new": new["summary"], "subset": baseline, "delta": delta}, ensure_ascii=False, indent=2))
    print(BUNDLE / "subset_comparison.md")


if __name__ == "__main__":
    main()
