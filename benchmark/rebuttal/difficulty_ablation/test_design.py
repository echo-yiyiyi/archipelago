from collections import Counter
import copy
import importlib.util
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("difficulty_design", HERE / "generate.py")
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


class DesignTests(unittest.TestCase):
    def setUp(self):
        self.source = driver.read(driver.SUBSET / "selected_15_tasks_with_attack_config.json")
        self.taxonomy = driver.read(driver.SUBSET / "selection_manifest.json")

    def test_conditions_and_domains_are_identical_across_difficulty(self):
        groups, slots = driver.design(self.source, self.taxonomy)
        for level, rows in groups.items():
            self.assertEqual(Counter(r["domain"] for r in rows), {"banking": 5, "law": 5, "consulting": 5})
            self.assertEqual(len({r["harmful_task_id"] for r in rows}), 15)
            for old, row in zip(self.source, rows):
                for key in (*driver.FLAGS, "domain"):
                    self.assertEqual(old.get(key), row.get(key))
                self.assertEqual(row["difficulty"], level)
                self.assertNotIn("attack_config", row)
                target = next(r for r in self.source if r["task_id"] == row["task_id"])
                for key in driver.TASK_FIELDS:
                    self.assertEqual(row[key], target[key])
        self.assertEqual(sum(s["reused"] for s in slots), 15)
        self.assertEqual(sum(not s["reused"] for s in slots), 30)

    def test_native_assignments_and_task_load_are_preserved(self):
        groups, slots = driver.design(self.source, self.taxonomy)
        for level in driver.LEVELS:
            native = [s for s in slots if s["difficulty"] == level and s["reused"]]
            self.assertEqual(len(native), 9 if level == "easy" else 3)
            for row, old in zip(groups[level], self.source):
                if old["difficulty"] == level:
                    self.assertEqual(row["task_id"], old["task_id"])
                    self.assertEqual(row["harmful_task_id"], old["harmful_task_id"])
            for domain in ("banking", "law", "consulting"):
                loads = Counter(r["task_id"] for r in groups[level] if r["domain"] == domain)
                self.assertEqual(sorted(loads.values()), [1, 2, 2] if level == "easy" else [5])

    def test_rejects_changes_to_old_task_pool(self):
        source = copy.deepcopy(self.source)
        source[0]["difficulty"] = "easy"
        with self.assertRaises(ValueError):
            driver.design(source, self.taxonomy)

    def test_assignment_is_deterministic(self):
        self.assertEqual(driver.design(self.source, self.taxonomy), driver.design(self.source, self.taxonomy))


if __name__ == "__main__":
    unittest.main()
