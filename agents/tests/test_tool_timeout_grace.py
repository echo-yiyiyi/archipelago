import asyncio
from types import SimpleNamespace

import pytest
from mcp.types import CallToolResult, TextContent
from runner.agents.react_toolbelt_agent import main
from runner.utils import mcp


@pytest.mark.asyncio
@pytest.mark.parametrize('finishes', [True, False])
async def test_timeout_preserves_grace_result(monkeypatch, finishes):
    async def call(*args):
        await asyncio.sleep(0.02 if finishes else 10)
        return CallToolResult(content=[TextContent(type='text', text='Files restored')])

    monkeypatch.setattr(main, 'call_openai_tool', call)
    monkeypatch.setattr(mcp, 'SHIELDED_TASK_GRACE_SECONDS', 0.1)
    agent = main.ReActAgent.__new__(main.ReActAgent)
    agent.messages = []
    agent.toolbelt = {'restore'}
    agent.tool_call_timeout = 0.001
    agent.model = 'openai/gpt-4o'
    tool = SimpleNamespace(id='call-1', function=SimpleNamespace(name='restore', arguments='{}'))
    await agent._execute_mcp_tool(SimpleNamespace(session=None), tool, [])
    output = str(agent.messages)
    if finishes:
        assert 'Files restored' in output
        assert 'timed out' not in output
    else:
        assert 'may still complete' in output
        assert 'before retrying' in output
