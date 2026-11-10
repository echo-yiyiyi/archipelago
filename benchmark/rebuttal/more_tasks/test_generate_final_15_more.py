import copy
import importlib.util
from pathlib import Path
import sys
import shutil
import tempfile
import os
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("more15", HERE / "generate_final_15_more.py")
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)
sys.path.insert(0, str(driver.ROOT))


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.old = driver.read(driver.SUBSET / "selected_15_tasks_with_attack_config.json")
        self.new = driver.read(HERE / "results/selected_15_tasks.json")
        self.taxonomy = driver.read(driver.SUBSET / "selection_manifest.json")

    def test_exact_slot_matching_without_stale_metadata(self):
        rows, mapping = driver.match_tasks(self.new, self.old, self.taxonomy)
        self.assertEqual({r["task_id"] for r in rows}, {r["task_id"] for r in self.new})
        for row, old, entry in zip(rows, self.old, mapping):
            for field in ("domain", "difficulty", *driver.FLAGS):
                self.assertEqual(row.get(field), old.get(field))
            for stale in ("attack_config", "attack_file", "populate_files", "watcher_config", "keywords"):
                self.assertNotIn(stale, row)
            self.assertEqual(entry["source_harmful_task_id"], old["harmful_task_id"])

    def test_reject_mismatched_quotas_and_reused_tasks(self):
        bad = copy.deepcopy(self.new)
        bad[0]["difficulty"] = "hard"
        with self.assertRaises(ValueError):
            driver.match_tasks(bad, self.old, self.taxonomy)
        bad = copy.deepcopy(self.new)
        bad[0]["task_id"] = self.old[0]["task_id"]
        with self.assertRaises(ValueError):
            driver.match_tasks(bad, self.old, self.taxonomy)

    def test_validator_accepts_reference_pipeline_bundles(self):
        # subset intentionally links outside itself. The new bundle must be
        # standalone, so dereference reference fixtures into a temporary bundle.
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for row in self.old:
                shutil.copytree(driver.SUBSET / row["harmful_task_id"], directory / row["harmful_task_id"])
                expected = {k: row[k] for k in ("task_id", "domain", "difficulty", "prompt", "harmful_task_id", *driver.FLAGS) if k in row}
                driver.validate_row(row, expected, directory)

    def test_validator_rejects_stale_prompt_and_missing_artifact(self):
        row = copy.deepcopy(self.old[9])
        expected = {"prompt": row["prompt"], "harmful_task_id": row["harmful_task_id"],
                    "add_user_prompt": True, "leakage_type": row["leakage_type"]}
        row["attack_config"]["original_task_prompt"] = "old prompt"
        with self.assertRaisesRegex(ValueError, "stale task prompt"):
            driver.validate_row(row, expected, driver.SUBSET)
        row = copy.deepcopy(self.old[9])
        row["populate_files"].append("missing.txt")
        with self.assertRaisesRegex(ValueError, "Missing or out-of-bundle"):
            driver.validate_row(row, expected, driver.SUBSET)


class AzureCredentialTests(unittest.TestCase):
    def test_project_endpoint_and_direct_key_skip_key_vault(self):
        from benchmark.utils.azure_openai import build_client
        with patch.dict(os.environ, {"BENCHMARK_GENERATION_PROVIDER": "azure",
                                    "AZURE_API_KEY": "test-key",
                                    "AZURE_OPENAI_BASE_URL": driver.ENDPOINT}, clear=True):
            with patch("openai.OpenAI") as client, patch(
                    "benchmark.utils.azure_openai.get_azure_api_key",
                    side_effect=AssertionError("unexpected Key Vault lookup")):
                build_client()
                client.assert_called_once_with(api_key="test-key", base_url=driver.ENDPOINT)

    def test_original_key_vault_path_still_works(self):
        from benchmark.utils.azure_openai import build_client, DEFAULT_AZURE_ENDPOINT
        with patch.dict(os.environ, {}, clear=True):
            with patch("openai.OpenAI") as client, patch(
                    "benchmark.utils.azure_openai.get_azure_api_key", return_value="vault-key"):
                build_client()
                client.assert_called_once_with(api_key="vault-key", base_url=DEFAULT_AZURE_ENDPOINT + "/openai/v1/")


if __name__ == "__main__":
    unittest.main()
