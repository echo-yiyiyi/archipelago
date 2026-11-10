from collections import Counter
import importlib.util
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("domain_design", HERE / "generate.py")
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


class DomainDesignTests(unittest.TestCase):
    def setUp(self):
        self.source = driver.shared.read(driver.shared.SUBSET / "selected_15_tasks_with_attack_config.json")
        self.taxonomy = driver.shared.read(driver.shared.SUBSET / "selection_manifest.json")

    def test_difficulty_and_attack_conditions_remain_fixed(self):
        groups, slots = driver.design(self.source, self.taxonomy)
        for domain, rows in groups.items():
            self.assertEqual(len(rows), 15)
            self.assertEqual(len({r["harmful_task_id"] for r in rows}), 15)
            self.assertEqual(Counter(r["difficulty"] for r in rows), {"easy": 9, "medium": 3, "hard": 3})
            for original, row in zip(self.source, rows):
                self.assertEqual(row["domain"], domain)
                self.assertEqual(row["difficulty"], original["difficulty"])
                for field in driver.shared.FLAGS:
                    self.assertEqual(original.get(field), row.get(field))
                target = next(r for r in self.source if r["task_id"] == row["task_id"])
                for field in driver.shared.TASK_FIELDS:
                    self.assertEqual(row[field], target[field])
                self.assertNotIn("attack_config", row)
        self.assertEqual(sum(s["reused"] for s in slots), 15)
        self.assertEqual(sum(not s["reused"] for s in slots), 30)

    def test_each_old_task_has_exactly_three_attack_instances(self):
        groups, slots = driver.design(self.source, self.taxonomy)
        for domain, rows in groups.items():
            loads = Counter(r["task_id"] for r in rows)
            self.assertEqual(len(loads), 5)
            self.assertEqual(list(loads.values()), [3] * 5)
            native = [s for s in slots if s["domain"] == domain and s["reused"]]
            self.assertEqual(len(native), 5)
            for row, original in zip(rows, self.source):
                if original["domain"] == domain:
                    self.assertEqual(row["harmful_task_id"], original["harmful_task_id"])

    def test_deterministic_and_same_eight_categories(self):
        first = driver.design(self.source, self.taxonomy)
        self.assertEqual(first, driver.design(self.source, self.taxonomy))
        for domain in driver.DOMAINS:
            self.assertEqual(len({s["category"] for s in first[1] if s["domain"] == domain}), 8)


if __name__ == "__main__":
    unittest.main()
