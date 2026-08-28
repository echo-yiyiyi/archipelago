from __future__ import annotations

import unittest

from analyze_file_type_rankings import analyze_rankings


class AnalyzeFileTypeRankingsTests(unittest.TestCase):
    def test_first_choice_top_three_and_rank_distributions(self):
        tasks = [
            {
                "task_id": "task_1",
                "file_type_ranking": [
                    "xlsx", "md", "html", "txt", "chat", "email", "calendar"
                ],
            },
            {
                "task_id": "task_2",
                "file_type_ranking": [
                    "md", "xlsx", "txt", "html", "email", "calendar", "chat"
                ],
            },
        ]

        stats = analyze_rankings(tasks)

        first_choice = {
            row["file_type"]: row
            for row in stats["first_choice_distribution"]
        }
        self.assertEqual(first_choice["xlsx"]["count"], 1)
        self.assertEqual(first_choice["xlsx"]["percentage_of_tasks"], 50.0)

        top_three = {
            row["file_type"]: row for row in stats["top_three_distribution"]
        }
        self.assertEqual(top_three["xlsx"]["count"], 2)
        self.assertEqual(top_three["xlsx"]["percentage_of_tasks"], 100.0)
        self.assertEqual(
            top_three["xlsx"]["percentage_of_top_three_slots"], 33.33
        )

        rank_two = {
            row["file_type"]: row
            for row in stats["distribution_by_rank"]["rank_2"]
        }
        self.assertEqual(rank_two["md"]["count"], 1)
        self.assertEqual(rank_two["xlsx"]["count"], 1)
        self.assertEqual(stats["task_rankings"][0]["first_choice"], "xlsx")
        self.assertEqual(len(stats["task_rankings"][0]["top_three"]), 3)
        self.assertEqual(len(stats["task_rankings"][0]["full_ranking"]), 7)


if __name__ == "__main__":
    unittest.main()
