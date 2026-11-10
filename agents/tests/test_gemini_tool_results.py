import copy
import json
import unittest

from litellm.litellm_core_utils.prompt_templates.factory import convert_to_gemini_tool_call_result
from runner.utils.gemini_tool_results import literal_schema_tool_results


class GeminiSchemaResponseTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.dumps({"json_schema": {
            "$defs": {"DeleteResult": {"type": "object", "properties": {"deleted": {"type": "boolean"}}}},
            "anyOf": [{"$ref": "#/$defs/DeleteResult"}, {"type": "null"}],
        }})

    def convert(self, message):
        return convert_to_gemini_tool_call_result(message, None, model="gemini-3.7-flash", custom_llm_provider="vertex_ai")

    def test_schema_is_literal_in_actual_vertex_function_response(self):
        message = {"role": "tool", "name": "slides_server_slides_schema", "tool_call_id": "call_1",
                   "content": [{"type": "text", "text": self.schema}]}
        before = copy.deepcopy(message)
        # Reproduce the structured $ref that triggered the production 400.
        unsafe = self.convert(message)["function_response"]["response"]
        self.assertEqual(unsafe["json_schema"]["anyOf"][0]["$ref"], "#/$defs/DeleteResult")
        safe = self.convert(literal_schema_tool_results([message])[0])["function_response"]["response"]
        self.assertEqual(safe, {"content": self.schema})
        self.assertEqual(json.loads(safe["content"]), json.loads(self.schema))
        self.assertEqual(message, before)

    def test_string_content_and_repeated_normalization(self):
        message = {"role": "tool", "name": "schema", "tool_call_id": "call_2", "content": self.schema}
        safe = literal_schema_tool_results([message])
        self.assertEqual(self.convert(safe[0])["function_response"]["response"], {"content": self.schema})
        self.assertEqual(literal_schema_tool_results(safe), safe)

    def test_ordinary_results_and_real_media_references_are_preserved(self):
        for content in ['{"ok":true}', 'plain text "$ref"', '{"$ref":"image_1"}',
                        [{"type": "text", "text": "done"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,a"}}]]:
            message = {"role": "tool", "name": "read", "content": content}
            self.assertIs(literal_schema_tool_results([message])[0], message)
        user = {"role": "user", "content": self.schema}
        self.assertIs(literal_schema_tool_results([user])[0], user)


if __name__ == "__main__":
    unittest.main()
