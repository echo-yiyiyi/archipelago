from __future__ import annotations

import unittest
from collections import Counter

from assign_balanced_file_types import (
    assign_balanced_file_types,
    build_output,
)
from rank_file_types import ALLOWED_FILE_TYPES


class AssignBalancedFileTypesTests(unittest.TestCase):
    def test_assignment_is_balanced_and_prefers_top_three(self):
        tasks = [{"task_id": f"task_{index}"} for index in range(15)]
        rankings = {}
        for index, task in enumerate(tasks):
            rotation = index % len(ALLOWED_FILE_TYPES)
            rankings[task["task_id"]] = list(
                ALLOWED_FILE_TYPES[rotation:] + ALLOWED_FILE_TYPES[:rotation]
            )

        assignments = assign_balanced_file_types(tasks, rankings)

        counts = Counter(assignments.values())
        self.assertEqual(sum(counts.values()), 15)
        self.assertEqual(sorted(counts.values()), [2, 2, 2, 2, 2, 2, 3])
        self.assertTrue(
            all(
                rankings[task["task_id"]].index(assignments[task["task_id"]]) < 3
                for task in tasks
            )
        )

    def test_output_matches_inject_vector_shape(self):
        tasks = [{"task_id": "task_1", "prompt": "Prompt", "keywords": ["A"]}]
        output = build_output(tasks, {"task_1": "email"})
        self.assertEqual(output[0]["prompt"], "Prompt")
        self.assertEqual(output[0]["inject_vector"], "email")
        self.assertEqual(output[0]["harmful_task_id"], "task_1_email")
        self.assertEqual(
            set(output[0]), set(tasks[0]) | {"inject_vector", "harmful_task_id"}
        )


if __name__ == "__main__":
    unittest.main()
