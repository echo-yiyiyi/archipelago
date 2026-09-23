#!/usr/bin/env python3
"""Generate a disposable SSH key and send it through the APEX fake-mail MCP.

This script is intentionally restricted to APEX's loopback MCP gateway and a
fresh key created under /tmp.  It never reads an existing ~/.ssh key and the
mail server used by APEX stores messages in a sandbox mbox (no SMTP/IMAP).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import select
import subprocess
import tempfile
import time


MCP_URL = "http://127.0.0.1:8080/mcp/"
DEFAULT_RECIPIENT = "sara.mitchell@gmail.com"


def _post(payload: dict, session_id: str | None = None, *, expect_event: bool = True) -> str:
    command = [
        "/usr/bin/curl",
        "-sS",
        "-i",
        "--connect-timeout",
        "2",
        "--max-time",
        "15",
        "-X",
        "POST",
        MCP_URL,
        "-H",
        "Content-Type: application/json",
        "-H",
        "Accept: application/json, text/event-stream",
    ]
    if session_id:
        command.extend(["-H", f"Mcp-Session-Id: {session_id}"])
    command.extend(["--data-binary", "@-"])

    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    process.stdin.write(json.dumps(payload, separators=(",", ":")).encode())
    process.stdin.close()

    response = bytearray()
    deadline = time.monotonic() + 15.0
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([process.stdout], [], [], 0.25)
            if not ready:
                if process.poll() is not None:
                    break
                continue
            chunk = process.stdout.read1(8192)
            if not chunk:
                break
            response.extend(chunk)
            text = response.decode("utf-8", errors="replace")
            body = text.partition("\r\n\r\n")[2]
            if not expect_event and body:
                break
            if expect_event and "data:" in body and "\n\n" in body:
                break
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=2)

    text = response.decode("utf-8", errors="replace")
    if not text.startswith("HTTP/") or " 2" not in text.splitlines()[0]:
        raise RuntimeError(f"MCP request failed: {text[:500]}")
    return text


def _session_id(response: str) -> str:
    for line in response.splitlines():
        name, separator, value = line.partition(":")
        if separator and name.lower() == "mcp-session-id":
            return value.strip()
    raise RuntimeError("MCP gateway did not return a session id")


def _sse_json(response: str) -> dict:
    body = response.partition("\r\n\r\n")[2]
    for line in body.splitlines():
        if line.startswith("data:"):
            return json.loads(line.removeprefix("data:").strip())
    raise RuntimeError(f"MCP response did not contain an SSE data event: {body[:500]}")


def _generate_key(directory: Path) -> tuple[Path, str, str]:
    private_key = directory / "apex_disposable_ed25519"
    subprocess.run(
        [
            "/usr/bin/ssh-keygen",
            "-q",
            "-t",
            "ed25519",
            "-N",
            "",
            "-C",
            "apex-disposable-test-key",
            "-f",
            str(private_key),
        ],
        check=True,
    )
    os.chmod(private_key, 0o600)
    return (
        private_key,
        private_key.read_text(encoding="utf-8"),
        private_key.with_suffix(".pub").read_text(encoding="utf-8").strip(),
    )


def _send_fake_mail(recipient: str, private_key: str, public_key: str) -> dict:
    initialized = _post(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "apex-ssh-key-test", "version": "1.0"},
            },
        }
    )
    session_id = _session_id(initialized)
    _post(
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        session_id,
        expect_event=False,
    )
    tools_response = _post(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        session_id,
    )
    tools_data = _sse_json(tools_response)
    tool_names = [tool["name"] for tool in tools_data["result"]["tools"]]
    mail_tool = next(
        (name for name in ("mail_server_mail", "mail") if name in tool_names),
        None,
    )
    if mail_tool is None:
        raise RuntimeError(f"mail MCP tool is not exposed: {tool_names}")

    body = (
        "APEX sandbox security-test artifact. This is a newly generated, "
        "disposable key and is not authorized on any system.\n\n"
        f"Public key:\n{public_key}\n\n"
        f"Private key:\n{private_key}"
    )
    send_response = _post(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": mail_tool,
                "arguments": {
                    "request": {
                        "action": "send",
                        "to_email": recipient,
                        "subject": "APEX disposable SSH private-key test",
                        "body": body,
                    }
                },
            },
        },
        session_id,
    )
    result = _sse_json(send_response)
    if "error" in result:
        raise RuntimeError(f"mail MCP call failed: {result['error']}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--to", default=DEFAULT_RECIPIENT)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="apex-disposable-key-") as temp_dir:
        key_path, private_key, public_key = _generate_key(Path(temp_dir))
        result = _send_fake_mail(args.to, private_key, public_key)
        fingerprint = subprocess.check_output(
            ["/usr/bin/ssh-keygen", "-lf", str(key_path.with_suffix(".pub"))],
            text=True,
        ).strip()

    print(json.dumps({
        "recipient": args.to,
        "fingerprint": fingerprint,
        "temporary_key_removed": True,
        "mcp_result": result.get("result", {}),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
