import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from benchmark.utils.security_judge import responses_json, DEFAULT_MODEL
from benchmark.utils.judge_trace import capture_judges


class SecurityJudgeTests(unittest.TestCase):
    schema = {"type": "object", "properties": {
        "passed": {"type": "integer", "enum": [0, 1]}},
        "required": ["passed"], "additionalProperties": False}

    def call(self):
        return responses_json(prompt="Reference and evidence", schema_name="test",
                              schema=self.schema)

    def response(self, value, finish="stop"):
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(value)), finish_reason=finish)])

    @patch.dict("os.environ", {}, clear=True)
    def test_default_model_schema_and_review_capture(self):
        with patch("litellm.completion", return_value=self.response({"passed": 1})) as api:
            with capture_judges() as traces:
                self.assertEqual(self.call(), {"passed": 1})
        request = api.call_args.kwargs
        self.assertEqual(request["model"], DEFAULT_MODEL)
        self.assertEqual(request["response_format"]["json_schema"]["schema"], self.schema)
        self.assertTrue(request["response_format"]["json_schema"]["strict"])
        self.assertEqual(traces[0]["model"], DEFAULT_MODEL)
        self.assertEqual(traces[0]["request"]["prompt"], "Reference and evidence")
        self.assertEqual(traces[0]["response"], {"passed": 1})

    @patch.dict("os.environ", {}, clear=True)
    def test_invalid_and_truncated_outputs_are_recorded_as_errors(self):
        for value, finish in [({"passed": 2}, "stop"), ({"passed": 1}, "length")]:
            with self.subTest(value=value, finish=finish):
                with patch("litellm.completion", return_value=self.response(value, finish)):
                    with capture_judges() as traces:
                        with self.assertRaises(Exception):
                            self.call()
                self.assertTrue(traces[0]["error"])
                self.assertIsNone(traces[0]["response"])

    @patch.dict("os.environ", {"AZURE_SECURITY_JUDGE_MODEL": "old-deployment"}, clear=True)
    def test_existing_azure_override_still_works(self):
        with patch("benchmark.utils.azure_openai.build_client", return_value="client"), patch(
            "benchmark.utils.azure_openai.responses_json", return_value={"passed": 0}
        ) as api:
            self.assertEqual(self.call(), {"passed": 0})
        self.assertEqual(api.call_args.kwargs["model"], "old-deployment")
