#!/usr/bin/env python3
"""Select 15 diverse attack instances from the 180-task final benchmark.

No model outputs are used for selection. Requires numpy and scipy.optimize.milp.
Run: OPENBLAS_NUM_THREADS=1 python3 select_subset.py
"""
from pathlib import Path
from collections import Counter
import hashlib
import json
import os
import re

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

HERE = Path(__file__).resolve().parent
BENCH = HERE.parents[1]
ROOT = BENCH / "final_benchmark"
CATEGORIES = [
    ("static_prompt_injection", "C1"),
    ("static_script_injection", "C2"),
    ("dynamic_prompt_injection", "C3"),
    ("dynamic_script_injection/allow_additional_instruction_false", "C4−"),
    ("dynamic_script_injection/allow_additional_instruction_true", "C4+"),
    ("user_prompt_script_swap/no_args", "C5-no_args"),
    ("user_prompt_script_swap/args", "C5-args"),
    ("user_prompt_suffix_plant", "C6"),
]
SHORT = dict(CATEGORIES)


def classify(row, category):
    n = int(row["inject_goal"].split("_", 1)[0])
    goal = re.sub(r"^\d+_", "", row["inject_goal"]).removesuffix("_arg")
    if n in {9, 10, 11, 12}:
        group = "B"
    elif n in {22, 23, 28, 29}:
        group = "E"
    elif n in {7, 18, 19, 20, 21, 24, 25, 26, 27, 30, 31, 32}:
        group = "D"
    elif n in {13, 14, 15, 16, 17}:
        group = "C"
    elif n in {1, 2, 3, 4, 5, 6, 8}:
        group = "A"
    else:
        raise ValueError(row["inject_goal"])
    is_prompt = category in {"static_prompt_injection", "dynamic_prompt_injection"}
    args = "N/A" if is_prompt else "yes" if row["inject_goal"].endswith("_arg") else "no"
    assert row["leakage_type"] == ("internal" if group in {"D", "E"} else "external")
    return dict(semantic_goal=goal, goal_group=group,
                harm_type="explicit" if group in {"B", "E"} else "implicit",
                script_args=args, requires_runtime_information=group in {"C", "D", "E"})


def select():
    candidates = []
    for category, _ in CATEGORIES:
        path, = (ROOT / category).glob("selected_*_tasks_with_attack_config.json")
        for row in json.loads(path.read_text()):
            candidates.append(dict(row=row, category=category, source_json=path,
                                   **classify(row, category)))
    assert len(candidates) == 180
    vectors = sorted({x["row"]["inject_vector"] for x in candidates})
    n = len(candidates)
    k = n + len(vectors)
    matrix, lower, upper = [], [], []

    def add(indices, lo, hi):
        a = np.zeros(k)
        a[list(indices)] = 1
        matrix.append(a)
        lower.append(lo)
        upper.append(hi)

    def matching(predicate):
        return [i for i, x in enumerate(candidates) if predicate(x)]

    add(range(n), 15, 15)
    for task in sorted({x["row"]["task_id"] for x in candidates}):
        add(matching(lambda x: x["row"]["task_id"] == task), 1, 1)
    for category, _ in CATEGORIES:
        add(matching(lambda x: x["category"] == category), 1, 2)
    for goal in sorted({x["semantic_goal"] for x in candidates}):
        add(matching(lambda x: x["semantic_goal"] == goal), 0, 1)
    for leakage in ["internal", "external"]:
        add(matching(lambda x: x["row"]["leakage_type"] == leakage), 7, 8)
    for group in "ABCDE":
        add(matching(lambda x: x["goal_group"] == group), 1, np.inf)
    explicit = matching(lambda x: x["harm_type"] == "explicit")
    add(explicit, 4, 6)
    for fmt in ["py", "pyc", "elf"]:
        add(matching(lambda x: x["row"]["inject_vector"] == fmt), 2, 3)
    # Cover both a file vector and an application vector in static prompt injection.
    for is_app in [True, False]:
        add(matching(lambda x: x["category"] == "static_prompt_injection" and
                     (x["row"]["inject_vector"] in {"email", "calendar", "chat"}) == is_app), 1, 1)
    for j, vector in enumerate(vectors):
        indices = matching(lambda x: x["row"]["inject_vector"] == vector)
        a = np.zeros(k)
        a[indices], a[n+j] = -1, 1
        matrix.append(a)
        lower.append(-np.inf)
        upper.append(0)
        for i in indices:
            a = np.zeros(k)
            a[i], a[n+j] = 1, -1
            matrix.append(a)
            lower.append(-np.inf)
            upper.append(0)

    def solve(objective):
        result = milp(objective, integrality=np.ones(k),
                      bounds=Bounds(np.zeros(k), np.ones(k)),
                      constraints=LinearConstraint(matrix, lower, upper),
                      options={"time_limit": 60})
        if not result.success:
            raise RuntimeError(result.message)
        return result

    objective = np.zeros(k)
    objective[n:] = -1
    first = solve(objective)
    max_vectors = int(round(sum(first.x[n:])))
    add(range(n, k), max_vectors, max_vectors)
    # Subject to maximum vector coverage, make the explicit/implicit split as
    # balanced as semantic uniqueness permits (only six explicit goal semantics).
    objective = np.zeros(k)
    objective[explicit] = -1
    second = solve(objective)
    max_explicit = int(round(sum(second.x[explicit])))
    add(explicit, max_explicit, max_explicit)
    # Fixed deterministic tie-break; does not look at model scores or trajectories.
    objective = np.zeros(k)
    for i, x in enumerate(candidates):
        key = x["category"] + ":" + x["row"]["harmful_task_id"]
        objective[i] = int(hashlib.sha256(key.encode()).hexdigest()[:12], 16) / 16**12
    final = solve(objective)
    selected = [x for i, x in enumerate(candidates) if final.x[i] > .5]
    return selected, dict(max_distinct_vectors=max_vectors, max_explicit=max_explicit,
                         solver="scipy.optimize.milp / HiGHS", status="optimal")


def main():
    selected, optimality = select()
    selected.sort(key=lambda x: ([c for c, _ in CATEGORIES].index(x["category"]),
                                 x["row"]["harmful_task_id"]))
    assert len(selected) == 15
    assert len({x["row"]["task_id"] for x in selected}) == 15
    assert len({x["semantic_goal"] for x in selected}) == 15
    assert set(x["goal_group"] for x in selected) == set("ABCDE")
    assert Counter(x["row"]["domain"] for x in selected) == {"banking": 5, "consulting": 5, "law": 5}
    assert Counter(x["row"]["difficulty"] for x in selected) == {"easy": 9, "medium": 3, "hard": 3}
    manifest = []
    for i, x in enumerate(selected, 1):
        row, cat = x["row"], x["category"]
        taskdir = row["harmful_task_id"]
        source = ROOT / cat / taskdir
        assert source.is_dir()
        link = HERE / taskdir
        if link.is_symlink():
            assert link.resolve() == source.resolve(), link
        elif link.exists():
            raise FileExistsError(link)
        else:
            link.symlink_to(os.path.relpath(source, HERE), target_is_directory=True)
        for field in ["attack_file", "watcher_file", "watcher_config"]:
            if row.get(field):
                assert (HERE / row[field]).is_file(), (field, row[field])
        for relative in row["populate_files"]:
            assert (HERE / relative).is_file(), relative
        # Config-side asset paths must also remain resolvable from this bundle.
        for value in row["attack_config"].values():
            if isinstance(value, str) and value.startswith(taskdir+"/"):
                assert (HERE / value).is_file(), value
        manifest.append(dict(subset_id=f"S{i:02d}", category=cat,
            source_task_json=os.path.relpath(x["source_json"], HERE),
            task_id=row["task_id"], harmful_task_id=row["harmful_task_id"],
            domain=row["domain"], difficulty=row["difficulty"],
            attack_goal=row["inject_goal"], vector=row["inject_vector"],
            leakage_type=row["leakage_type"],
            **{key: x[key] for key in ["semantic_goal", "goal_group", "harm_type", "script_args", "requires_runtime_information"]}))
    stats = {key: dict(Counter(r[key] for r in manifest)) for key in
             ["category", "vector", "domain", "difficulty", "leakage_type", "harm_type", "script_args", "goal_group"]}
    (HERE / "selected_15_tasks_with_attack_config.json").write_text(
        json.dumps([x["row"] for x in selected], ensure_ascii=False, indent=2)+"\n")
    (HERE / "selection_manifest.json").write_text(json.dumps(dict(
        task_count=15, distinct_original_tasks=15, distinct_semantic_goals=15,
        distinct_vectors=len(stats["vector"]), coverage=stats, optimality=optimality,
        taxonomy_source="../../../../latex/APEX_Harm/section/appendix/goals.tex",
        tasks=manifest), ensure_ascii=False, indent=2)+"\n")
    write_readme(manifest, stats)
    print(json.dumps(dict(tasks=15, unique_semantic_goals=15, coverage=stats,
                          optimality=optimality), ensure_ascii=False, indent=2))


def write_readme(rows, stats):
    lines = ["# 15 个覆盖型攻击任务子集", "",
        "从 final_benchmark 的 180 个攻击实例中选取 15 个，未读取模型表现来决定选样。15 个原始任务各出现一次，15 个语义目标各出现一次。", "",
        "## 约束与覆盖", "",
        "- 8 个类别/变体全部覆盖，每类 1–2 个；15 个样本下为 7 类各 2 个、1 类 1 个，是数量上最均衡的分配。",
        "- Attack goal 先去掉数字前缀和 `_arg` 后缀再去重，避免把同一个行为的参数版和非参数版当成不同目标；最终 15 个目标语义均不同。",
        "- 按论文 Appendix Attack Goals 的 A–E 五组分类，五组全部覆盖。explicit 为 B/E，implicit 为 A/C/D。",
        "- 15 个原始任务全部覆盖，因此 domain 各 5 个，difficulty 为 easy=9、medium=3、hard=3，与原始任务集一致。",
        "- 静态 prompt 同时覆盖一个文件载体和一个应用载体；PY、PYC、ELF 脚本各 2–3 个。",
        "- 素材通过相对软链接引用原始 final_benchmark 目录，JSON 中原始字段和配置保持不变。不是独立可搬移的素材副本。", "",
        "### 为什么不是 15 种不同 vector", "",
        "原始 180 个实例只有 14 种 inject_vector 标签（9 种静态 prompt 载体、3 种脚本格式、2 种动态注入）。在每类最多 2 个且覆盖 8 类的约束下，静态 prompt 最多贡献 2 种，其余最多贡献 3 种脚本格式和 2 种动态注入，因此上限为 7 种。该子集达到此上限，整数规划求解状态为 optimal。", "",
        "### Args 字段的含义", "",
        "`script_args` 仅表示脚本是否需要 agent 提供运行时参数；prompt 攻击为 N/A，并不等于不需要读取任务信息。另有 `requires_runtime_information` 字段记录论文目标组定义中的运行时信息需求。", "",
        "## 覆盖统计", "", "| 维度 | 分布 |", "|---|---|"]
    for key, counts in stats.items():
        lines.append(f"| {key} | "+"; ".join(f"{k}: {v}" for k, v in counts.items())+" |")
    lines += ["", "## 类别编号", "", "| 编号 | Category |", "|---|---|"]
    for category, short in CATEGORIES:
        lines.append(f"| {short} | {category} |")
    lines += ["", "## 选择清单", "",
        "| ID | Category | Domain | Difficulty | Attack goal | Vector | Leakage | Script args | Harm | Group |",
        "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['subset_id']} | {SHORT[r['category']]} | {r['domain']} | {r['difficulty']} | {r['attack_goal']} | {r['vector']} | {r['leakage_type']} | {r['script_args']} | {r['harm_type']} | {r['goal_group']} |")
    lines += ["", "## 任务 ID 与素材", "", "| ID | Original task ID | Harmful task / asset directory |", "|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['subset_id']} | `{r['task_id']}` | [`{r['harmful_task_id']}`]({r['harmful_task_id']}/) |")
    lines += ["", "## 文件", "",
        "- `selected_15_tasks_with_attack_config.json`：保留原始字段的完整 15 行任务配置，可作为 benchmark runner 的 `--task-json` 输入。",
        "- `selection_manifest.json`：各任务来源、分类依据、覆盖统计及最优性记录。",
        "- `select_subset.py`：可重复执行的约束选择与素材路径检查脚本，依赖 numpy/scipy。",
        "- 本次仅完成选样、配置与素材路径核验，未启动 Docker、模型调用或重新评测。", ""]
    (HERE / "README.md").write_text("\n".join(lines))
    # Preserve the requested results section when regenerating the selection.
    from update_results import update_readme
    update_readme()


if __name__ == "__main__":
    main()
