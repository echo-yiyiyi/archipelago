"""Keep JSON Schema references in tool output as literal text for Gemini."""
import json
from typing import Any


def _contains_local_ref(value: Any) -> bool:
    if isinstance(value, dict):
        reference = value.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/"):
            return True
        return any(_contains_local_ref(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_local_ref(item) for item in value)
    return False


def _literal_schema_text(text: Any) -> Any:
    if not isinstance(text, str) or '"$ref"' not in text:
        return text
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return text
    if not isinstance(value, dict) or not _contains_local_ref(value):
        return text
    # LiteLLM parses JSON object tool text into function_response.response.
    # Gemini interprets nested $ref objects there as multimodal file references,
    # rejecting ordinary schema pointers such as #/$defs/DeleteResult. Keeping
    # the original JSON as a string preserves every definition and reference.
    return json.dumps({"content": text}, ensure_ascii=False)


def literal_schema_tool_results(messages: list[Any]) -> list[Any]:
    """Copy affected tool messages without changing stored trajectory content."""
    result = []
    for message in messages:
        if message.get("role") != "tool":
            result.append(message)
            continue
        content = message.get("content")
        if isinstance(content, str):
            converted = _literal_schema_text(content)
        elif isinstance(content, list):
            converted = [
                {**part, "text": _literal_schema_text(part.get("text"))}
                if isinstance(part, dict) and part.get("type") == "text" else part
                for part in content
            ]
        else:
            result.append(message)
            continue
        if converted == content:
            result.append(message)
            continue
        copied = dict(message) if isinstance(message, dict) else message.model_dump(exclude_none=True)
        copied["content"] = converted
        result.append(copied)
    return result
