from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
)
from litellm.experimental_mcp_client.tools import (
    transform_openai_tool_call_request_to_mcp_tool_call_request,
)

from runner.agents.react_toolbelt_agent.main import _mcp_tool_call_payload


def test_replayed_pydantic_tool_call_becomes_nested_plain_dict() -> None:
    tool_call = ChatCompletionMessageToolCall.model_validate(
        {
            "id": "call_test",
            "type": "function",
            "function": {
                "name": "filesystem_server_list_files",
                "arguments": '{"path":"/"}',
            },
        }
    )

    payload = _mcp_tool_call_payload(tool_call)

    assert isinstance(payload, dict)
    assert isinstance(payload["function"], dict)
    assert payload["function"]["name"] == "filesystem_server_list_files"
    assert payload["function"]["arguments"] == '{"path":"/"}'

    request = transform_openai_tool_call_request_to_mcp_tool_call_request(payload)
    assert request.name == "filesystem_server_list_files"
    assert request.arguments == {"path": "/"}
