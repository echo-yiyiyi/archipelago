#!/usr/bin/env python3
"""Call the sandbox mail MCP directly, without running an agent."""

import argparse
import asyncio
import json
from pathlib import Path

import httpx
from fastmcp import Client


MAIL_CONFIG = {
    "mcpServers": {
        "mail_server": {
            "transport": "stdio",
            "command": "uv",
            "args": ["run", "--no-sync", "python", "main.py"],
            "cwd": "/app/mcp_servers/mail/mcp_servers/mail_server",
            "env": {
                "APP_MAIL_DATA_ROOT": "/.apps_data/mail",
                "MCP_TRANSPORT": "stdio",
            },
        }
    }
}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--to", default="mcp-script-test@example.com")
    args = parser.parse_args()

    # A normal task world creates this during populate. This standalone test
    # has no world/agent, so create the same storage root explicitly.
    Path("/.apps_data/mail").mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=120) as http:
        response = await http.post(f"{args.base_url}/apps", json=MAIL_CONFIG)
        response.raise_for_status()
        configured = response.json()

    gateway = {
        "mcpServers": {
            "gateway": {
                "transport": "streamable-http",
                "url": f"{args.base_url}/mcp/",
            }
        }
    }
    async with Client(gateway) as client:
        tools = await client.list_tools()
        tool_names = [tool.name for tool in tools]
        mail_tool = next(
            (name for name in ("mail_server_mail", "mail") if name in tool_names),
            None,
        )
        if mail_tool is None:
            raise RuntimeError(f"mail tool not exposed: {tool_names}")

        sent = await client.call_tool(
            mail_tool,
            {
                "request": {
                    "action": "send",
                    "to_email": args.to,
                    "subject": "Direct MCP script test",
                    "body": "This simulated email was sent by a Python MCP client without an agent.",
                }
            },
        )
        sent_data = sent.structured_content or {}
        if sent_data.get("error") or not (sent_data.get("send") or {}).get("success"):
            raise RuntimeError(f"mail MCP send failed: {sent_data}")
        listed = await client.call_tool(
            mail_tool,
            {"request": {"action": "list", "limit": 10}},
        )

    print(json.dumps({
        "configured": configured,
        "mail_tool_name": mail_tool,
        "mail_tool_present": True,
        "send_result": str(sent),
        "list_result": str(listed),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
