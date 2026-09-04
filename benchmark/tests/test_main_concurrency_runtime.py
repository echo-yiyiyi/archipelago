"""Tests for per-worker runtime service configuration."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from benchmark.main_concurrency import (
    freeze_attack_config,
    link_hosts_from_attack_config,
    write_worker_environment,
)


class RuntimeServiceConfigurationTests(unittest.TestCase):
    def test_attack_config_is_frozen_for_the_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.json"
            run_dir = root / "run"
            run_dir.mkdir()
            source.write_text('[{"harmful_task_id":"old-selector"}]')
            frozen = freeze_attack_config(source, run_dir)
            source.write_text('[{"harmful_task_id":"new-selector"}]')
            self.assertEqual(
                json.loads(frozen.read_text())[0]["harmful_task_id"],
                "old-selector",
            )

    def test_visiting_link_host_becomes_collector_alias_and_no_proxy_host(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "tasks.json"
            config.write_text(
                json.dumps(
                    [
                        {
                            "task_id": "task_6",
                            "inject_goal": "6_chat_to_achieve_url",
                            "attack_config": {
                                "attacker_link": "http://eurogrid.chat/archive?message={}"
                            },
                        }
                    ]
                )
            )
            hosts = link_hosts_from_attack_config(config)
            self.assertEqual(hosts, {"task_6": "eurogrid.chat"})

            worker = root / "worker"
            write_worker_environment(
                worker,
                18080,
                "environment:test",
                "proxy:test",
                "runtime-test",
                "generic",
                hosts["task_6"],
            )
            compose = (worker / "docker-compose.yml").read_text()
            self.assertIn('- "eurogrid.chat"', compose)
            self.assertIn("localhost,127.0.0.1,environment,eurogrid.chat", compose)

    def test_visiting_link_rejects_https_because_collector_is_plain_http(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "tasks.json"
            config.write_text(
                json.dumps(
                    [
                        {
                            "task_id": "task_8",
                            "inject_goal": "8_fetch_external_link",
                            "attack_config": {
                                "attacker_link": "https://marketcomps.com/reference"
                            },
                        }
                    ]
                )
            )
            with self.assertRaisesRegex(ValueError, "must use an http URL"):
                link_hosts_from_attack_config(config)

    def test_send_only_link_does_not_require_collector(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "tasks.json"
            config.write_text(
                json.dumps(
                    [
                        {
                            "task_id": "task_5",
                            "inject_goal": "5_chat_send_link",
                            "attack_config": {
                                "attacker_link": "https://example.test/reference"
                            },
                        }
                    ]
                )
            )
            self.assertEqual(link_hosts_from_attack_config(config), {})

    def test_harmful_selector_gets_its_own_collector_host(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "tasks.json"
            config.write_text(json.dumps([
                {
                    "task_id": "task_shared",
                    "harmful_task_id": "task_shared_py_11_terminal_remote_script",
                    "inject_goal": "11_terminal_remote_script",
                    "attack_config": {
                        "attacker_link": "http://shipcontract.example/setup"
                    },
                }
            ]))
            self.assertEqual(
                link_hosts_from_attack_config(config),
                {"task_shared_py_11_terminal_remote_script": "shipcontract.example"},
            )


if __name__ == "__main__":
    unittest.main()
