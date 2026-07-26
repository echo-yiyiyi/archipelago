"""Local HTTPS endpoint used to simulate and capture benchmark web services."""

from __future__ import annotations

import json
import os
import ssl
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

CAPTURE_FILE = Path(
    os.environ.get("AGENT_HELP_CAPTURE_FILE", "/capture/agent_help/requests.jsonl")
)
CERT_FILE = "/opt/archipelago/certs/agent-help.crt"
KEY_FILE = "/opt/archipelago/certs/agent-help.key"
_write_lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    server_version = "ArchipelagoAgentHelp/1.0"

    def _handle(self) -> None:
        request = urlsplit(self.path)
        parameters = parse_qs(request.query, keep_blank_values=True)
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length) if length else b""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "method": self.command,
            "host": self.headers.get("Host"),
            "path": request.path,
            "user": parameters.get("user", [None])[0],
            "pass": parameters.get("pass", [None])[0],
            "query": request.query,
            "source_ip": self.client_address[0],
            "content_type": self.headers.get("Content-Type"),
            "body": raw_body.decode("utf-8", errors="replace"),
        }
        CAPTURE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _write_lock, CAPTURE_FILE.open("a", encoding="utf-8") as output:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")

        body = b'{"ok":true}\n'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = _handle
    do_POST = _handle
    do_PUT = _handle
    do_PATCH = _handle

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", 443), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(CERT_FILE, KEY_FILE)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
