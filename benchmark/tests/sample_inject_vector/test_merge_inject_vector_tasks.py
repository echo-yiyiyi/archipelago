from __future__ import annotations

import unittest

from benchmark.sample_inject_vector.merge_inject_vector_tasks import merge_tasks


def task(task_id: str, difficulty: str, vector: str) -> dict[str, str]:
    return {
        "task_id": task_id,
        "difficulty": difficulty,
        "inject_vector": vector,
        "harmful_task_id": f"{task_id}_{vector}",
    }


class MergeInjectVectorTasksTests(unittest.TestCase):
    def test_sorts_by_difficulty_and_groups_same_task_id(self):
        file_tasks = [
            task("task_hard", "hard", "html"),
            task("task_easy", "easy", "xlsx"),
            task("task_medium", "medium", "email"),
        ]
        executable_tasks = [
            task("task_medium", "medium", "pyc"),
            task("task_hard", "hard", "elf"),
            task("task_easy", "easy", "py"),
        ]

        merged = merge_tasks(file_tasks, executable_tasks)

        self.assertEqual(
            [(row["task_id"], row["inject_vector"]) for row in merged],
            [
                ("task_easy", "xlsx"),
                ("task_easy", "py"),
                ("task_medium", "email"),
                ("task_medium", "pyc"),
                ("task_hard", "html"),
                ("task_hard", "elf"),
            ],
        )

    def test_rejects_mismatched_task_ids(self):
        with self.assertRaisesRegex(ValueError, "task IDs do not match"):
            merge_tasks(
                [task("task_1", "easy", "xlsx")],
                [task("task_2", "easy", "py")],
            )


if __name__ == "__main__":
    unittest.main()
