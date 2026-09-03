#!/usr/bin/env python3
"""End-to-end verification of the six selected generated attack artifacts.

This intentionally omits only the model/agent loop.  For every selected record it
loads the same world ZIP used by a benchmark run, starts the real environment and
MCP gateway, executes the exact configured py/pyc/ELF through the code-execution
MCP tool, snapshots the environment, and invokes the production security check.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlparse


HERE = Path(__file__).resolve().parent
GEN_DIR = HERE.parent
REPO = GEN_DIR.parent.parent
DEFAULT_CONFIG = GEN_DIR / "output" / "selected_6_with_attack_config.json"
RUNS = REPO / "benchmark" / "output" / "concurrent"
MCP_CONFIG = REPO / "benchmark" / "mcp_config_all_oss_servers.json"
DRIVER = HERE / "_faithful_driver.py"
IMAGE = "archipelago-hf-environment:concurrency"
PROXY_IMAGE = "archipelago-hf-runtime-proxy:concurrency"
DEFAULT_CHECK_PYTHON = "/data/ziyi/.venv/bin/python"
LINK_GOALS = {
    "6_chat_to_achieve_url",
    "8_fetch_external_link",
    "9_url_query_params",
    "11_terminal_remote_script",
    "12_terminal_cron_setup",
}

sys.path.insert(0, str(REPO))
from benchmark.main_concurrency import collector_settings, write_worker_environment  # noqa: E402


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, **kwargs)


def records(config: Path) -> list[dict]:
    data = json.loads(config.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("selected task config must contain a JSON array")
    result = [item for item in data if isinstance(item, dict)]
    for item in result:
        for field in ("task_id", "harmful_task_id", "inject_goal", "attack_file"):
            if not isinstance(item.get(field), str) or not item[field]:
                raise ValueError(f"selected task is missing {field}: {item!r}")
    return result


def select_records(all_records: list[dict], selectors: list[str]) -> list[dict]:
    if not selectors:
        return all_records
    selected: list[dict] = []
    for index, item in enumerate(all_records, 1):
        values = {
            str(index),
            item["task_id"],
            item["harmful_task_id"],
            item["inject_goal"],
            Path(item["attack_file"]).name,
        }
        if any(selector in values for selector in selectors):
            selected.append(item)
    missing = [selector for selector in selectors if not any(
        selector in {
            str(index), item["task_id"], item["harmful_task_id"],
            item["inject_goal"], Path(item["attack_file"]).name,
        }
        for index, item in enumerate(all_records, 1)
    )]
    if missing:
        raise ValueError("unknown selector(s): " + ", ".join(missing))
    return selected


def newest_world(item: dict) -> Path:
    selectors = [item["harmful_task_id"], item["task_id"]]
    candidates: list[str] = []
    for selector in selectors:
        candidates.extend(glob.glob(str(RUNS / "*" / "tasks" / selector / "world_*.zip")))
    if not candidates:
        raise FileNotFoundError(
            f"no downloaded world snapshot for {item['harmful_task_id']}; run the task once first"
        )
    return Path(max(set(candidates), key=os.path.getmtime))


def extract_world(item: dict, work: Path) -> Path:
    destination = work / "world"
    destination.mkdir(parents=True)
    with zipfile.ZipFile(newest_world(item)) as archive:
        archive.extractall(destination)
    (destination / "filesystem").mkdir(exist_ok=True)
    (destination / ".apps_data").mkdir(exist_ok=True)
    return destination


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def wait_health(container: str, timeout: int = 90) -> None:
    for _ in range(timeout):
        response = run([
            "docker", "exec", container, "curl", "-s", "-o", "/dev/null",
            "-w", "%{http_code}", "http://localhost:8080/health",
        ])
        if response.stdout.strip() == "200":
            return
        time.sleep(1)
    raise RuntimeError("environment did not become healthy")


def configure_gateway(container: str) -> None:
    copied = run(["docker", "cp", str(MCP_CONFIG), f"{container}:/mcp_config.json"])
    if copied.returncode:
        raise RuntimeError(copied.stderr.strip())
    response = run([
        "docker", "exec", container, "curl", "-s", "-X", "POST",
        "http://localhost:8080/apps", "-H", "Content-Type: application/json",
        "--data-binary", "@/mcp_config.json", "--max-time", "200",
    ], timeout=210)
    if response.returncode or '"servers"' not in response.stdout:
        raise RuntimeError("gateway configuration failed: " + (response.stdout + response.stderr)[:400])


def compose(worker: Path, environment: dict[str, str], *arguments: str,
            timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return run(["docker", "compose", *arguments], cwd=worker, env=environment, timeout=timeout)


def copy_world(container: str, world: Path) -> None:
    for subsystem in ("filesystem", ".apps_data"):
        run(["docker", "exec", container, "mkdir", "-p", f"/{subsystem}"], check=True)
        for child in (world / subsystem).iterdir():
            run(["docker", "cp", str(child), f"{container}:/{subsystem}/"], check=True)


def execute_artifact(container: str, config: Path, item: dict) -> str:
    source = config.parent / item["attack_file"]
    if not source.is_file():
        raise FileNotFoundError(f"configured attack artifact does not exist: {source}")
    destination = "/filesystem/" + source.name
    run(["docker", "exec", container, "rm", "-f", "/tmp/helper_done"])
    copied = run(["docker", "cp", str(source), f"{container}:{destination}"])
    if copied.returncode:
        raise RuntimeError(copied.stderr.strip())
    vector = str(item.get("inject_vector", "")).lower()
    if vector == "elf":
        run(["docker", "exec", container, "chmod", "+x", destination], check=True)
        command = destination
    elif vector in {"py", "pyc"}:
        command = "python " + shlex.quote(destination)
    else:
        raise ValueError(f"unsupported inject_vector={vector!r}")
    run(["docker", "cp", str(DRIVER), f"{container}:/selected6_e2e_driver.py"], check=True)
    response = run([
        "docker", "exec", container, "/usr/bin/python3",
        "/selected6_e2e_driver.py", command,
    ], timeout=190)
    output = (response.stdout or response.stderr).strip()
    if response.returncode:
        raise RuntimeError(f"code-execution driver failed: {output[:500]}")
    return output[:500]


def wait_payload(container: str, timeout: int = 90) -> None:
    for _ in range(timeout):
        marker = run(["docker", "exec", container, "test", "-f", "/tmp/helper_done"])
        if marker.returncode == 0:
            return
        response = run([
            "docker", "exec", container, "sh", "-c",
            "pgrep -fa 'task_helper|selected6|b64decode|open_session' | grep -v pgrep | wc -l",
        ])
        if response.stdout.strip() in {"", "0"}:
            time.sleep(1)
        time.sleep(1)
    raise TimeoutError("payload background process did not finish within 90 seconds")


def snapshot_zip(container: str, work: Path) -> Path:
    response = run([
        "docker", "exec", container, "curl", "-fsS", "-X", "POST",
        "http://localhost:8080/data/snapshot", "-o", "/tmp/selected6-snapshot.tar.gz",
    ], timeout=120)
    if response.returncode:
        raise RuntimeError("snapshot failed: " + response.stderr[:400])
    archive = work / "snapshot.tar.gz"
    run([
        "docker", "cp", f"{container}:/tmp/selected6-snapshot.tar.gz", str(archive)
    ], check=True)
    result = work / "final_snapshot.zip"
    with tarfile.open(archive, "r:gz") as source, zipfile.ZipFile(
        result, "w", zipfile.ZIP_DEFLATED
    ) as destination:
        for member in source.getmembers():
            if not member.isfile():
                continue
            handle = source.extractfile(member)
            if handle is not None:
                destination.writestr(member.name, handle.read())
    return result


def security_check(check_python: str, item: dict, snapshot: Path) -> dict:
    attack_config = dict(item.get("attack_config") or {})
    attack_config.setdefault("original_task_prompt", item.get("prompt", ""))
    code = (
        "import json,sys;sys.path.insert(0,%r);" % str(REPO)
        + "from benchmark.runner.security_check import check_security;"
        + "print(json.dumps(check_security(inject_goal=%r,final_snapshot=%r,"
        "attack_config=json.loads(%r))))"
        % (item["inject_goal"], str(snapshot), json.dumps(attack_config))
    )
    response = run([check_python, "-c", code], timeout=240)
    output = response.stdout.strip().splitlines()
    if response.returncode or not output:
        return {"attack_success": 0, "attack_rules": {},
                "error": (response.stdout + response.stderr).strip()[:1000]}
    try:
        return json.loads(output[-1])
    except json.JSONDecodeError:
        return {"attack_success": 0, "attack_rules": {},
                "error": (response.stdout + response.stderr).strip()[:1000]}


def run_local(config: Path, item: dict, check_python: str) -> tuple[dict, str]:
    work = Path(tempfile.mkdtemp(prefix="selected6-e2e-"))
    container = "selected6-e2e-" + uuid.uuid4().hex[:10]
    try:
        world = extract_world(item, work)
        started = run([
            "docker", "run", "--detach", "--name", container,
            "-v", f"{world / 'filesystem'}:/filesystem",
            "-v", f"{world / '.apps_data'}:/.apps_data", IMAGE,
        ])
        if started.returncode:
            raise RuntimeError(started.stderr.strip())
        wait_health(container)
        configure_gateway(container)
        output = execute_artifact(container, config, item)
        wait_payload(container)
        snapshot = snapshot_zip(container, work)
        return security_check(check_python, item, snapshot), output
    finally:
        run(["docker", "rm", "-f", container])
        shutil.rmtree(work, ignore_errors=True)


def run_link(config: Path, item: dict, check_python: str) -> tuple[dict, str]:
    work = Path(tempfile.mkdtemp(prefix="selected6-e2e-link-"))
    worker = work / "environment"
    slug = "selected6-e2e-" + uuid.uuid4().hex[:10]
    network = slug + "-network"
    environment = os.environ.copy()
    environment["COMPOSE_PROJECT_NAME"] = slug.replace("-", "_")
    host = urlparse(str((item.get("attack_config") or {}).get("attacker_link", ""))).hostname
    if not host:
        raise ValueError("URL-visiting task has no attacker_link hostname")
    mode, script_body = collector_settings(item["inject_goal"])
    created = run(["docker", "network", "create", "--internal", network])
    if created.returncode:
        raise RuntimeError(created.stderr.strip())
    try:
        world = extract_world(item, work)
        write_worker_environment(
            worker, free_port(), IMAGE, PROXY_IMAGE, network, mode, host, script_body
        )
        started = compose(worker, environment, "up", "--detach", "--wait", "--wait-timeout", "90")
        if started.returncode:
            raise RuntimeError("compose up failed: " + started.stderr[:500])
        container = compose(worker, environment, "ps", "-q", "environment").stdout.strip()
        if not container:
            raise RuntimeError("compose did not return the environment container")
        copy_world(container, world)
        wait_health(container)
        configure_gateway(container)
        output = execute_artifact(container, config, item)
        wait_payload(container)
        snapshot = snapshot_zip(container, work)
        return security_check(check_python, item, snapshot), output
    finally:
        compose(worker, environment, "down", "--volumes", "--remove-orphans", timeout=90)
        run(["docker", "network", "rm", network])
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("selectors", nargs="*", help="index, harmful_task_id, goal, or artifact name")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--check-python", default=DEFAULT_CHECK_PYTHON)
    arguments = parser.parse_args()
    config = arguments.config.expanduser().resolve()
    selected = select_records(records(config), arguments.selectors)
    failures = 0
    for item in selected:
        selector = item["harmful_task_id"]
        print(f"\n=== {selector} ===", flush=True)
        try:
            runner = run_link if item["inject_goal"] in LINK_GOALS else run_local
            result, tool_output = runner(config, item, arguments.check_python)
        except Exception as error:
            result, tool_output = {
                "attack_success": 0,
                "attack_rules": {},
                "error": f"{type(error).__name__}: {error}",
            }, ""
        success = int(result.get("attack_success") == 1)
        failures += 1 - success
        print(f"code_execution: {tool_output!r}", flush=True)
        print(f"attack_success: {result.get('attack_success')}", flush=True)
        for rule_id, rule in (result.get("attack_rules") or {}).items():
            print(
                f"  {rule_id}: passed={rule.get('passed')} - {rule.get('description', '')}",
                flush=True,
            )
        if result.get("error"):
            print(f"error: {result['error']}", flush=True)
    print(f"\nselected6 e2e: {len(selected) - failures}/{len(selected)} passed", flush=True)
    return int(failures != 0)


if __name__ == "__main__":
    raise SystemExit(main())
