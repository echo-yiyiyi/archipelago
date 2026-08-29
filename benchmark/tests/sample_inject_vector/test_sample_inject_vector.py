from __future__ import annotations

import unittest
from collections import Counter

from benchmark.sample_inject_vector.sample_inject_vector import assign_inject_vectors


class SampleInjectVectorTests(unittest.TestCase):
    def test_balanced_assignment_preserves_fields_and_builds_id(self):
        tasks = [
            {
                "task_id": f"task_{index}",
                "prompt": f"Prompt {index}",
                "keywords": ["one", "two", "three"],
            }
            for index in range(15)
        ]

        output = assign_inject_vectors(tasks, seed=7)

        self.assertEqual(
            Counter(item["inject_vector"] for item in output),
            {"py": 5, "pyc": 5, "elf": 5},
        )
        for source, result in zip(tasks, output, strict=True):
            self.assertEqual(result["prompt"], source["prompt"])
            self.assertEqual(result["keywords"], source["keywords"])
            self.assertEqual(
                result["harmful_task_id"],
                f'{source["task_id"]}_{result["inject_vector"]}',
            )
            self.assertEqual(
                set(result), set(source) | {"inject_vector", "harmful_task_id"}
            )

    def test_seed_makes_assignment_reproducible(self):
        tasks = [{"task_id": f"task_{index}"} for index in range(15)]
        self.assertEqual(
            assign_inject_vectors(tasks, seed=123),
            assign_inject_vectors(tasks, seed=123),
        )

    def test_rejects_wrong_task_count(self):
        with self.assertRaisesRegex(ValueError, "expected 15 tasks"):
            assign_inject_vectors([{"task_id": "task_1"}])


if __name__ == "__main__":
    unittest.main()
