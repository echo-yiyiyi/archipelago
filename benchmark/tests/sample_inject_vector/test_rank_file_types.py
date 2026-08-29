from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from benchmark.sample_inject_vector.rank_file_types import (
    FILE_TYPE_SCHEMA,
    build_output,
    rank_one,
    validate_file_types,
)


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


class RankFileTypesTests(unittest.TestCase):
    def test_schema_requires_all_seven_allowed_types(self):
        file_types = FILE_TYPE_SCHEMA["properties"]["file_types"]
        self.assertEqual(file_types["minItems"], 7)
        self.assertEqual(file_types["maxItems"], 7)
        self.assertNotIn("uniqueItems", file_types)

    def test_rank_one_uses_prompt_and_gpt_5_4_model(self):
        client = FakeClient(
            [
                json.dumps(
                    {
                        "file_types": [
                            "xlsx",
                            "html",
                            "md",
                            "txt",
                            "email",
                            "chat",
                            "calendar",
                        ]
                    }
                )
            ]
        )
        task = {
            "task_id": "task_1",
            "keywords": ["DCF-Solv", "cash flow", "financial model"],
        }

        ranking = rank_one(
            task,
            client=client,
            model="gpt-5.4",
            reasoning_effort="low",
            retries=0,
            retry_delay=0,
        )

        self.assertEqual(
            ranking,
            ["xlsx", "html", "md", "txt", "email", "chat", "calendar"],
        )
        request = client.responses.calls[0]
        self.assertEqual(request["model"], "gpt-5.4")
        self.assertIn("DCF-Solv", request["input"])
        self.assertIn("financial model", request["input"])
        self.assertNotIn("task_prompt", request["input"])
        self.assertEqual(
            request["text"]["format"]["schema"], FILE_TYPE_SCHEMA
        )

    def test_validation_rejects_duplicates_and_unsupported_types(self):
        with self.assertRaises(ValueError):
            validate_file_types(
                ["md", "md", "xlsx", "html", "txt", "chat", "email"]
            )
        with self.assertRaises(ValueError):
            validate_file_types(
                ["md", "pdf", "xlsx", "html", "txt", "chat", "email"]
            )

    def test_output_preserves_fields_and_adds_only_ranking(self):
        tasks = [{"task_id": "task_1", "prompt": "Prompt", "turns": 4}]
        ranking = ["txt", "md", "html", "chat", "email", "calendar", "xlsx"]
        output = build_output(tasks, {"task_1": ranking})
        self.assertEqual(output[0]["prompt"], "Prompt")
        self.assertEqual(output[0]["turns"], 4)
        self.assertEqual(output[0]["file_type_ranking"], ranking)
        self.assertEqual(set(output[0]), set(tasks[0]) | {"file_type_ranking"})


if __name__ == "__main__":
    unittest.main()
