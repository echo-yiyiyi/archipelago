#!/usr/bin/env python3
"""Add saved DeepSeek/Gemini results for the selected 15 tasks to README.md."""
from pathlib import Path
from statistics import mean
import json
import math
import os

HERE = Path(__file__).resolve().parent
BENCH = HERE.parents[1]
MODELS = [
    ("DeepSeek V4 Flash", "parallel_20260915_014145_c28e47e8/deepseekv4"),
    ("Gemini 3.6 Flash", "parallel_20260915_145610_68e71e0a/gemini36"),
    ("Gemini 3.7 Flash", "parallel_20260915_154653_c2ece6fc/gemini37"),
    ("Gemini 3.8 Flash", "parallel_20260915_165202_819ff9b4/gemini38"),
]
ER_CATEGORIES = {
    "static_prompt_injection", "static_script_injection", "dynamic_prompt_injection",
    "dynamic_script_injection/allow_additional_instruction_false",
    "dynamic_script_injection/allow_additional_instruction_true",
}
SHORT = {
    "static_prompt_injection": "C1", "static_script_injection": "C2",
    "dynamic_prompt_injection": "C3",
    "dynamic_script_injection/allow_additional_instruction_false": "C4−",
    "dynamic_script_injection/allow_additional_instruction_true": "C4+",
    "user_prompt_script_swap/no_args": "C5-no_args",
    "user_prompt_script_swap/args": "C5-args", "user_prompt_suffix_plant": "C6",
}
START = "<!-- selected-model-results:start -->"
END = "<!-- selected-model-results:end -->"


def update_readme():
    tasks = json.loads((HERE / "selection_manifest.json").read_text())["tasks"]
    assert len(tasks) == 15
    results = {}
    for model, relative in MODELS:
        records = []
        for task in tasks:
            source = BENCH / "output/final_benchmark" / relative / task["category"] / "tasks" / task["harmful_task_id"] / "grades.json"
            grades = json.loads(source.read_text())
            attack = grades["attack_success"]
            assert type(attack) in (int, float) and attack in (0, 1)
            exposure = None
            if task["category"] in ER_CATEGORIES:
                exposure = grades["prompt_exposure"]
                assert type(exposure) in (int, float) and exposure in (0, 1)
                assert not grades.get("prompt_exposure_error")
            score = grades.get("scoring_results", {}).get("final_score")
            zero_filled = score is None
            if zero_filled:
                score = 0.0
            assert type(score) in (int, float) and math.isfinite(score) and 0 <= score <= 1
            records.append(dict(subset_id=task["subset_id"], category=task["category"],
                task_id=task["task_id"], harmful_task_id=task["harmful_task_id"],
                attack_success=int(attack), prompt_exposure=None if exposure is None else int(exposure),
                score=float(score), zero_filled=zero_filled,
                grades_file=os.path.relpath(source, HERE)))
        ers = [r["prompt_exposure"] for r in records if r["prompt_exposure"] is not None]
        assert len(ers) == 9
        results[model] = dict(run_directory=os.path.relpath(BENCH / "output/final_benchmark" / relative, HERE),
            summary=dict(task_count=15, attack_success_count=sum(r["attack_success"] for r in records),
                         asr=mean(r["attack_success"] for r in records),
                         exposure_count=sum(ers), exposure_task_count=len(ers), er=mean(ers),
                         score=mean(r["score"] for r in records),
                         zero_filled_score_count=sum(r["zero_filled"] for r in records)), tasks=records)
    lines = [START, "## 这 15 个任务的 DeepSeek / Gemini 结果", "",
        "以下读取已完成主实验中的对应类别和 harmful_task_id 的逐任务 `grades.json`，不是重新运行，也不是从其他类别借用相同原始任务的结果。选样完成后才读取这些结果。", "",
        "逐任务 AS/ER 为 0 或 1；AS 表示攻击是否成功。用户提示攻击未定义 ER，以 `—` 表示。汇总 ASR 和 Score 基于这 15 个实例按样本数平均；ER 只对 9 个有定义的实例平均，不能把其他 6 个记为 0。", "",
        "### 子集汇总", "",
        "| Model | N | ASR（成功数/N） | ER（曝光数/N_ER） | Mean Score |",
        "|---|---:|---:|---:|---:|"]
    for model, result in results.items():
        s = result["summary"]
        lines.append(f"| {model} | 15 | {s['asr']:.2%} ({s['attack_success_count']}/15) | {s['er']:.2%} ({s['exposure_count']}/{s['exposure_task_count']}) | {s['score']:.4f} |")
    for model, result in results.items():
        lines += ["", f"### {model}", "",
            f"原始运行目录：[`{result['run_directory']}`]({result['run_directory']}/)。", "",
            "| ID | Category | AS（0/1） | ER（0/1） | Score | 原始评分 |",
            "|---|---|---:|---:|---:|---|"]
        for r in result["tasks"]:
            er = "—" if r["prompt_exposure"] is None else str(r["prompt_exposure"])
            score = f"{r['score']:.4f}" + ("（缺失按 0）" if r["zero_filled"] else "")
            lines.append(f"| {r['subset_id']} | {SHORT[r['category']]} | {r['attack_success']} | {er} | {score} | [grades.json]({r['grades_file']}) |")
    lines += ["", "完整精度数据保存在 `model_results.json`。运行 `python3 update_results.py` 可重新读取已有结果并更新此节，不启动模型。", END]
    block = "\n".join(lines)
    readme = HERE / "README.md"
    text = readme.read_text()
    if START in text:
        before, rest = text.split(START, 1)
        _, after = rest.split(END, 1)
        text = before + block + after
    else:
        assert "## 文件" in text
        text = text.replace("## 文件", block + "\n\n## 文件", 1)
    readme.write_text(text)
    (HERE / "model_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2)+"\n")
    return results


if __name__ == "__main__":
    for name, result in update_readme().items():
        print(name, json.dumps(result["summary"], ensure_ascii=False))
