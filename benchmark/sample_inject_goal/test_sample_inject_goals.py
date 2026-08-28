from __future__ import annotations

import random
import unittest
from collections import Counter, defaultdict

from sample_inject_goals import (
    EXECUTABLE_GOAL_IDS,
    EXECUTABLE_TARGET_COUNTS,
    EXECUTABLE_VECTORS,
    FILE_TYPE_GOAL_IDS,
    FILE_TYPE_TARGET_COUNTS,
    expand_tasks,
    random_balanced_samples,
)


class SampleInjectGoalsTests(unittest.TestCase):
    def test_random_samples_are_balanced_distinct_and_reproducible(self):
        first = random_balanced_samples(
            FILE_TYPE_GOAL_IDS,
            item_count=15,
            variants_per_item=3,
            rng=random.Random(19),
        )
        second = random_balanced_samples(
            FILE_TYPE_GOAL_IDS,
            item_count=15,
            variants_per_item=3,
            rng=random.Random(19),
        )

        self.assertEqual(first, second)
        self.assertTrue(all(len(sample) == len(set(sample)) == 3 for sample in first))
        counts = Counter(goal_id for sample in first for goal_id in sample)
        self.assertEqual(sorted(counts.values()), [5, 5, 5, 6, 6, 6, 6, 6])

    def test_expand_creates_three_variants_and_balances_both_groups(self):
        tasks = []
        for index in range(15):
            tasks.append(
                {
                    "task_id": f"task_{index}",
                    "inject_vector": "xlsx",
                    "harmful_task_id": f"task_{index}_xlsx",
                }
            )
            tasks.append(
                {
                    "task_id": f"task_{index}",
                    "inject_vector": ("py", "pyc", "elf")[index % 3],
                    "harmful_task_id": f"task_{index}_binary",
                }
            )

        output = expand_tasks(tasks, seed=7)

        self.assertEqual(len(output), 90)
        variants = defaultdict(list)
        for row in output:
            source_id = row["harmful_task_id"].removesuffix(
                f'_{row["inject_goal"]}'
            )
            variants[source_id].append(row["inject_goal"])
        self.assertEqual(len(variants), 30)
        self.assertTrue(
            all(len(goals) == len(set(goals)) == 3 for goals in variants.values())
        )
        goals_by_task_id = defaultdict(list)
        for row in output:
            goals_by_task_id[row["task_id"]].append(row["inject_goal"])
        self.assertEqual(len(goals_by_task_id), 15)
        self.assertTrue(
            all(
                len(goals) == len(set(goals)) == 6
                for goals in goals_by_task_id.values()
            )
        )

        file_counts = Counter(
            row["inject_goal"]
            for row in output
            if row["inject_vector"] not in EXECUTABLE_VECTORS
        )
        executable_counts = Counter(
            row["inject_goal"]
            for row in output
            if row["inject_vector"] in EXECUTABLE_VECTORS
        )
        self.assertEqual(set(file_counts), set(FILE_TYPE_GOAL_IDS))
        self.assertEqual(sorted(file_counts.values()), [5, 5, 5, 6, 6, 6, 6, 6])
        self.assertEqual(dict(file_counts), FILE_TYPE_TARGET_COUNTS)
        self.assertEqual(set(executable_counts), set(EXECUTABLE_GOAL_IDS))
        self.assertEqual(dict(executable_counts), EXECUTABLE_TARGET_COUNTS)

        counts_by_vector = defaultdict(Counter)
        for row in output:
            counts_by_vector[row["inject_vector"]][row["inject_goal"]] += 1
        for vector, counts in counts_by_vector.items():
            allowed_goals = (
                EXECUTABLE_GOAL_IDS
                if vector in EXECUTABLE_VECTORS
                else FILE_TYPE_GOAL_IDS
            )
            values = [counts[goal_id] for goal_id in allowed_goals]
            self.assertLessEqual(max(values) - min(values), 1)


if __name__ == "__main__":
    unittest.main()
