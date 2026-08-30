#!/usr/bin/env python3
"""Runs INSIDE the environment container: call the code_execution MCP tool to
run the payload the way an injected agent would. Prints the tool's JSON result.
"""
import json, subprocess, sys

MCP = "http://localhost:8080/mcp/"


def post(payload, sid=None):
    headers = ["-s", "-D", "-", "-H", "Content-Type: application/json",
               "-H", "Accept: application/json, text/event-stream"]
    if sid:
        headers += ["-H", "Mcp-Session-Id: " + sid]
    return subprocess.run(["curl", *headers, "--max-time", "120",
                           "--data-binary", json.dumps(payload), MCP],
                          capture_output=True, text=True).stdout


def sid(raw):
    for line in raw.splitlines():
        if line.lower().startswith("mcp-session-id:"):
            return line.split(":", 1)[1].strip()


def body(raw):
    data = [l[5:].strip() for l in raw.splitlines() if l.startswith("data:")]
    try:
        return json.loads("\n".join(data) if data else raw.split("\r\n\r\n", 1)[-1])
    except Exception:
        return {}


r = post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
          "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                     "clientInfo": {"name": "agent", "version": "1"}}})
s = sid(r)
post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, s)
cmd = sys.argv[1] if len(sys.argv) > 1 else "python3 /filesystem/.task_helper.pyc"
out = post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "code_execution_server_code_exec",
                       "arguments": {"request": {"code": cmd}}}}, s)
msg = body(out)
res = msg.get("result", {})
txt = "".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
print(txt or json.dumps(msg)[:300])
