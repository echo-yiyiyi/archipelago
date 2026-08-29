"""Docker integration test for every generated attack/populate fixture.

Run explicitly with pytest:

    RUN_DOCKER_INTEGRATION=1 pytest -q \
      benchmark/tests/runner/test_generated_fixture_mcp_docker.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
CONFIG = REPO / "benchmark/generate_attack_config/output/1_to_8_with_attack_config.json"
PROBE = REPO / "benchmark/tests/runner/generated_fixture_mcp_probe.py"
CHAT_SERVER_SOURCE = REPO / "mcp_servers/chat/mcp_servers/chat_server"
IMAGE = os.environ.get("BENCHMARK_ENVIRONMENT_IMAGE", "archipelago-hf-environment:concurrency")


@unittest.skipUnless(os.environ.get("RUN_DOCKER_INTEGRATION") == "1", "Docker integration test")
class GeneratedFixtureMcpDockerTests(unittest.TestCase):
    def _exec_probe(self, container: str, kind: str, paths: list[str]) -> dict:
        server = {
            "filesystem": "filesystem",
            "filesystem_marker": "filesystem",
            "code_modify": "code",
            "spreadsheets": "spreadsheets",
            "mail": "mail",
            "calendar": "calendar",
            "chat": "chat",
        }[kind]
        module = {
            "filesystem": "filesystem_server",
            "code": "code_execution_server",
            "spreadsheets": "sheets_server",
            "mail": "mail_server",
            "calendar": "calendar_server",
            "chat": "chat_server",
        }[server]
        result = subprocess.run(
            [
                "docker", "exec",
                "--workdir", f"/app/mcp_servers/{server}/mcp_servers/{module}",
                container,
                f"/app/mcp_servers/{server}/.venv/bin/python",
                "/fixture_probe.py",
                kind,
                json.dumps(paths),
            ],
            text=True,
            capture_output=True,
            timeout=180,
        )
        self.assertEqual(result.returncode, 0, f"{kind} failed:\n{result.stdout}\n{result.stderr}")
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertTrue(payload["ok"])
        return payload

    @staticmethod
    def _clear(directory: Path) -> None:
        for child in directory.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()

    def test_all_attack_and_populate_files_are_mcp_usable(self) -> None:
        records = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(len(records), 8)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            filesystem = root / "filesystem"
            apps_data = root / ".apps_data"
            filesystem.mkdir()
            apps_data.mkdir()
            container = "archipelago-fixture-probe-" + uuid.uuid4().hex[:10]
            subprocess.run(
                [
                    "docker", "run", "--detach", "--name", container,
                    "--volume", f"{filesystem}:/filesystem",
                    "--volume", f"{apps_data}:/.apps_data",
                    "--volume", f"{PROBE}:/fixture_probe.py:ro",
                    # Always exercise the current checkout's unmodified Chat
                    # MCP implementation, even when the cached image predates it.
                    "--volume", f"{CHAT_SERVER_SOURCE}:/app/mcp_servers/chat/mcp_servers/chat_server:ro",
                    IMAGE, "sleep", "infinity",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            tested_sources: set[str] = set()
            try:
                for record in records:
                    self._clear(filesystem)
                    self._clear(apps_data)
                    values = [record.get("attack_file"), *record.get("populate_files", [])]
                    source_values = list(dict.fromkeys(value for value in values if isinstance(value, str)))
                    self.assertTrue(source_values, record["inject_goal"])
                    virtual_files: list[str] = []
                    app_suffixes: list[str] = []
                    for value in source_values:
                        source = CONFIG.parent / value
                        self.assertTrue(source.is_file(), source)
                        tested_sources.add(value)
                        parts = Path(value).parts
                        if ".apps_data" in parts:
                            index = parts.index(".apps_data")
                            suffix = Path(*parts[index + 1 :])
                            destination = apps_data / suffix
                            app_suffixes.append(suffix.as_posix())
                        else:
                            destination = filesystem / source.name
                            virtual_files.append("/" + source.name)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, destination)

                    text_files = [path for path in virtual_files if Path(path).suffix.lower() in {".html", ".md", ".txt"}]
                    sheet_files = [path for path in virtual_files if Path(path).suffix.lower() == ".xlsx"]
                    if text_files:
                        self._exec_probe(container, "filesystem", text_files)
                        self._exec_probe(container, "code_modify", text_files)
                        self._exec_probe(container, "filesystem_marker", text_files)
                    if sheet_files:
                        self._exec_probe(container, "spreadsheets", sheet_files)
                    if any(path.lower().endswith(".mbox") for path in app_suffixes):
                        self._exec_probe(container, "mail", [])
                    if any(path.lower().endswith(".ics") for path in app_suffixes):
                        self._exec_probe(container, "calendar", [])
                    if any(path.endswith("messages.json") for path in app_suffixes):
                        self._exec_probe(container, "chat", [])
            finally:
                subprocess.run(
                    ["docker", "rm", "--force", container],
                    check=False,
                    capture_output=True,
                    text=True,
                )

        expected_sources = {
            value
            for record in records
            for value in [record.get("attack_file"), *record.get("populate_files", [])]
            if isinstance(value, str)
        }
        self.assertEqual(tested_sources, expected_sources)


if __name__ == "__main__":
    unittest.main()
