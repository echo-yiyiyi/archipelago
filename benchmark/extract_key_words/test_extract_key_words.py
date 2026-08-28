from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from extract_key_words import (
    KeywordRecord,
    build_json_output,
    extract_one,
    load_completed_records,
    validate_keywords,
)
from prompt import build_keyword_extraction_prompt


class FakeResponses:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = []

    def create(self, **request):
        self.calls.append(request)
        return SimpleNamespace(output_text=next(self.outputs))


class FakeClient:
    def __init__(self, outputs):
        self.responses = FakeResponses(outputs)


class ExtractKeywordsTests(unittest.TestCase):
    def test_prompt_contains_task_and_json_contract(self):
        prompt = build_keyword_extraction_prompt("Analyze ACME's revenue workbook.")
        self.assertIn("Analyze ACME's revenue workbook.", prompt)
        self.assertIn("valid JSON object", prompt)

    def test_validate_keywords(self):
        self.assertEqual(validate_keywords([" ACME ", "Revenue", "Workbook"]), ["ACME", "Revenue", "Workbook"])
        with self.assertRaises(ValueError):
            validate_keywords(["only", "two"])

    def test_extract_one_uses_strict_schema_and_retries(self):
        client = FakeClient(["not json", json.dumps({"keywords": ["ACME", "Revenue", "Workbook"]})])
        result = extract_one(
            {"task_id": "task_1", "domain": "Law", "task_name": "Example", "prompt": "Analyze ACME."},
            client=client,
            model="test-model",
            reasoning_effort="low",
            retries=1,
            retry_delay=0,
        )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.attempts, 2)
        request = client.responses.calls[-1]
        self.assertEqual(request["text"]["format"]["schema"]["properties"]["keywords"]["minItems"], 3)
        self.assertEqual(request["model"], "test-model")

    def test_json_output_preserves_every_task_field_and_adds_keywords(self):
        tasks = [{
            "task_id": "task_1",
            "domain": "banking",
            "turns": 12,
            "difficulty": "hard",
            "prompt": "Analyze ACME.",
        }]
        records = [KeywordRecord("task_1", "banking", None, ["ACME", "Revenue", "Workbook"], "completed")]

        output = build_json_output(tasks, records)

        self.assertEqual(output[0]["prompt"], "Analyze ACME.")
        self.assertEqual(output[0]["turns"], 12)
        self.assertEqual(output[0]["keywords"], ["ACME", "Revenue", "Workbook"])
        self.assertEqual(set(output[0]), set(tasks[0]) | {"keywords"})

    def test_completed_records_can_resume_from_array_output(self):
        tasks = [{"task_id": "task_1", "domain": "banking", "prompt": "Analyze ACME."}]
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "keywords.json"
            output_path.write_text(json.dumps([{**tasks[0], "keywords": ["ACME", "Revenue", "Workbook"]}]))

            records = load_completed_records(output_path, tasks)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].keywords, ["ACME", "Revenue", "Workbook"])


if __name__ == "__main__":
    unittest.main()
