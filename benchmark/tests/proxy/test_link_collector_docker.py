"""Docker integration test for every generated URL that must be visited."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from urllib.parse import quote, urlparse

from benchmark.main_concurrency import link_hosts_from_attack_config, write_worker_environment


REPO = Path(__file__).resolve().parents[3]
CONFIG = REPO / "benchmark/generate_attack_config/output/1_to_8_with_attack_config.json"
ENVIRONMENT_IMAGE = os.environ.get(
    "BENCHMARK_ENVIRONMENT_IMAGE", "archipelago-hf-environment:concurrency"
)
PROXY_IMAGE = os.environ.get(
    "BENCHMARK_PROXY_IMAGE", "archipelago-hf-runtime-proxy:concurrency"
)


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@unittest.skipUnless(os.environ.get("RUN_DOCKER_INTEGRATION") == "1", "Docker integration test")
class LinkCollectorDockerTests(unittest.TestCase):
    def test_every_visiting_link_resolves_returns_and_is_captured(self) -> None:
        records = json.loads(CONFIG.read_text(encoding="utf-8"))
        hosts = link_hosts_from_attack_config(CONFIG)
        visiting = [
            record
            for record in records
            if record.get("inject_goal")
            in {"6_chat_to_achieve_url", "8_fetch_external_link"}
        ]
        self.assertEqual(len(visiting), 2)

        for record in visiting:
            task_id = record["task_id"]
            goal = record["inject_goal"]
            configured_link = record["attack_config"]["attacker_link"]
            requested_link = configured_link.replace("{}", quote("docker probe", safe=""))
            parsed = urlparse(requested_link)
            run_slug = "archipelago-link-probe-" + uuid.uuid4().hex[:10]
            network = run_slug + "-runtime"
            project = run_slug.replace("-", "_")
            with tempfile.TemporaryDirectory() as temporary:
                worker = Path(temporary) / "worker"
                subprocess.run(
                    ["docker", "network", "create", "--internal", network],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                environment = os.environ.copy()
                environment["COMPOSE_PROJECT_NAME"] = project
                try:
                    write_worker_environment(
                        worker,
                        _free_port(),
                        ENVIRONMENT_IMAGE,
                        PROXY_IMAGE,
                        network,
                        "goal8" if goal == "8_fetch_external_link" else "generic",
                        hosts[task_id],
                    )
                    subprocess.run(
                        [
                            "docker", "compose", "up", "--detach", "--wait",
                            "--wait-timeout", "90",
                        ],
                        cwd=worker,
                        env=environment,
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                    response = subprocess.run(
                        [
                            "docker", "compose", "exec", "-T", "environment",
                            "curl", "--fail", "--silent", "--show-error", requested_link,
                        ],
                        cwd=worker,
                        env=environment,
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    ).stdout
                    expected_response = (
                        "cannot provide the requested information"
                        if goal == "8_fetch_external_link"
                        else "Request received successfully"
                    )
                    self.assertIn(expected_response, response)

                    capture = subprocess.run(
                        [
                            "docker", "compose", "exec", "-T", "environment",
                            "cat", "/.apps_data/http_capture/requests.jsonl",
                        ],
                        cwd=worker,
                        env=environment,
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    ).stdout
                    requests = [json.loads(line) for line in capture.splitlines() if line]
                    self.assertTrue(
                        any(
                            request.get("host") == parsed.netloc
                            and request.get("path") == parsed.path
                            and request.get("query") == parsed.query
                            for request in requests
                        ),
                        requests,
                    )
                finally:
                    subprocess.run(
                        ["docker", "compose", "down", "--volumes", "--remove-orphans"],
                        cwd=worker,
                        env=environment,
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                    subprocess.run(
                        ["docker", "network", "rm", network],
                        check=False,
                        capture_output=True,
                        text=True,
                    )


if __name__ == "__main__":
    unittest.main()
