#!/usr/bin/env python3
"""Cross old-set attack conditions with domain while preserving difficulty."""
from collections import Counter, defaultdict
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
from benchmark.rebuttal.difficulty_ablation import generate as shared

DOMAINS = ("banking", "law", "consulting")


def design(source, taxonomy):
    # Check the same original pool/quota requirements as the difficulty design.
    shared.design(source, taxonomy)
    metadata = {r["harmful_task_id"]: r for r in taxonomy["tasks"]}
    buckets = defaultdict(list)
    for row in source:
        buckets[row["domain"], row["difficulty"]].append(row)
    groups, assignments = {}, []
    for domain in DOMAINS:
        counts = Counter(r["task_id"] for r in source if r["domain"] == domain)
        rows = []
        for template in source:
            reused = template["domain"] == domain
            target = template if reused else min(buckets[domain, template["difficulty"]],
                                                  key=lambda row: (counts[row["task_id"]], row["task_id"]))
            if not reused:
                counts[target["task_id"]] += 1
            row = {key: target[key] for key in shared.TASK_FIELDS}
            row.update({key: template[key] for key in shared.FLAGS if key in template})
            row["harmful_task_id"] = f"{row['task_id']}_{row['inject_vector']}_{row['inject_goal']}"
            info = metadata[template["harmful_task_id"]]
            assignments.append({"subset_id": info["subset_id"], "category": info["category"], "set": "old",
                                "domain": domain, "difficulty": row["difficulty"], "task_id": row["task_id"],
                                "harmful_task_id": row["harmful_task_id"], "source_domain": template["domain"],
                                "source_harmful_task_id": template["harmful_task_id"], "reused": reused,
                                **{key: template[key] for key in shared.FLAGS if key in template}})
            rows.append(row)
        groups[domain] = rows
    return groups, assignments


if __name__ == "__main__":
    shared.main(directory=HERE, axis="domain", levels=DOMAINS, design_fn=design)
