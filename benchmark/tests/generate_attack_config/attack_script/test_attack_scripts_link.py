#!/usr/bin/env python3
"""Run the link-visiting payloads (goals 6 and 8) against the real runtime.

These goals only pass when an outbound HTTP request reaches the run-scoped
collector, so this harness brings up the same Compose worker the benchmark uses
(environment + link_collector on an internal network) via
``benchmark.main_concurrency.write_worker_environment``. It then seeds the chat
baseline, runs the payload inside the environment container, snapshots, and calls
the real ``check_security``.

    python test_attack_scripts_link.py           # goals 6 and 8
    python test_attack_scripts_link.py 6

Requires docker + docker compose, the environment and runtime-proxy images.
"""

from __future__ import annotations

import argparse
import json
import os
import re
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

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
SCRIPT_DIR = REPO / "benchmark" / "generate_attack_config" / "attack_script"
GEN_DIR = SCRIPT_DIR.parent
CONFIG = GEN_DIR / "output" / "1_to_8_with_attack_config.json"
sys.path.insert(0, str(REPO))

from benchmark.main_concurrency import (  # noqa: E402
    link_hosts_from_attack_config,
    write_worker_environment,
)

IMAGE = "archipelago-hf-environment:concurrency"
PROXY_IMAGE = "archipelago-hf-runtime-proxy:concurrency"
MCP_CONFIG = REPO / "benchmark" / "mcp_config_all_oss_servers.json"
DEFAULT_CHECK_PYTHON = "/data/ziyi/.venv/bin/python"
LINK_GOALS = ["6_chat_to_achieve_url", "8_fetch_external_link"]


def _run(cmd, **kwargs):
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def _wait_worker(container: str, timeout: int = 60) -> None:
    for _ in range(timeout):
        out = _run(["docker", "exec", container, "bash", "-lc",
                    "pgrep -fa 'payload|b64decode' | grep -v pgrep | wc -l"])
        if out.stdout.strip() in ("", "0"):
            time.sleep(1)
            return
        time.sleep(1)


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _record(goal: str) -> dict:
    for record in json.loads(CONFIG.read_text(encoding="utf-8")):
        if record.get("inject_goal") == goal:
            return record
    raise SystemExit(f"no record for goal {goal}")


def _compose(worker: Path, env: dict, *args, timeout=180):
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=worker, env=env, capture_output=True, text=True, timeout=timeout,
    )


def _seed_chat(worker: Path, env: dict, record: dict) -> None:
    """Copy the chat baseline (populate minus attack file) into /.apps_data."""
    attack_file = record.get("attack_file")
    tmp = Path(tempfile.mkdtemp(prefix="atklinkseed-"))
    try:
        for rel in record.get("populate_files", []):
            if rel == attack_file:
                continue
            parts = Path(rel).parts
            if ".apps_data" not in parts:
                continue
            index = parts.index(".apps_data")
            destination = tmp.joinpath(*parts[index + 1:])
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(CONFIG.parent / rel, destination)
        container = _compose(worker, env, "ps", "-q", "environment").stdout.strip()
        for child in tmp.iterdir():
            _run(["docker", "cp", str(child), f"{container}:/.apps_data/"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _configure_gateway(worker: Path, env: dict) -> None:
    container = _compose(worker, env, "ps", "-q", "environment").stdout.strip()
    _run(["docker", "cp", str(MCP_CONFIG), f"{container}:/mcp_config.json"])
    out = _run(["docker", "exec", container, "curl", "-s", "-X", "POST",
                "http://localhost:8080/apps", "-H", "Content-Type: application/json",
                "--data-binary", "@/mcp_config.json", "--max-time", "180"])
    if '"servers"' not in out.stdout:
        raise RuntimeError(f"gateway configure failed: {out.stdout[:300]}")


def _snapshot_zip(worker: Path, env: dict, workdir: Path) -> Path:
    container = _compose(worker, env, "ps", "-q", "environment").stdout.strip()
    _run(["docker", "exec", container, "bash", "-lc",
          "curl -s -X POST http://localhost:8080/data/snapshot -o /tmp/snap.tar.gz"])
    tgz = workdir / "snap.tar.gz"
    _run(["docker", "cp", f"{container}:/tmp/snap.tar.gz", str(tgz)])
    zip_path = workdir / "snap.zip"
    with tarfile.open(tgz, "r:gz") as tar, \
            zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for member in tar.getmembers():
            if member.isfile():
                handle = tar.extractfile(member)
                if handle is not None:
                    zf.writestr(member.name, handle.read())
    return zip_path


def _check(check_python: str, goal: str, zip_path: Path, record: dict) -> dict:
    config = dict(record.get("attack_config") or {})
    config.setdefault("original_task_prompt", record.get("prompt", ""))
    script = (
        "import json,sys;sys.path.insert(0, %r);" % str(REPO)
        + "from benchmark.runner.security_check import check_security;"
        "print(json.dumps(check_security(inject_goal=%r," % goal
        + "final_snapshot=%r,attack_config=json.loads(%r))))"
        % (str(zip_path), json.dumps(config))
    )
    out = _run([check_python, "-c", script], timeout=180)
    line = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else ""
    try:
        return json.loads(line)
    except Exception:
        return {"attack_success": 0, "error": (out.stdout + out.stderr)[:400]}


def run_goal(goal: str, check_python: str, variant: str = "py", runtime_args: list[str] | None = None, execution: str = "direct") -> dict:
    record = _record(goal)
    hosts = link_hosts_from_attack_config(CONFIG)
    task_id = record["task_id"]
    slug = "atklink-" + uuid.uuid4().hex[:10]
    network = slug + "-runtime"
    env = os.environ.copy()
    env["COMPOSE_PROJECT_NAME"] = slug.replace("-", "_")
    worker = Path(tempfile.mkdtemp(prefix="atklinkwork-"))
    _run(["docker", "network", "create", "--internal", network])
    try:
        write_worker_environment(
            worker, _free_port(), IMAGE, PROXY_IMAGE, network,
            "goal8" if goal == "8_fetch_external_link" else "generic",
            hosts[task_id],
        )
        up = _compose(worker, env, "up", "--detach", "--wait",
                      "--wait-timeout", "90", timeout=150)
        if up.returncode != 0:
            return {"attack_success": 0, "error": "compose up failed: " + up.stderr[:300]}
        _configure_gateway(worker, env)
        if goal == "6_chat_to_achieve_url":
            _seed_chat(worker, env, record)
        container = _compose(worker, env, "ps", "-q", "environment").stdout.strip()
        configured = CONFIG.parent / str(record.get("attack_file", ""))
        extra = runtime_args or []
        if not extra and goal == "6_chat_to_achieve_url":
            rule = ((record.get("attack_config") or {}).get("judge") or {}).get("rule_2", "")
            match = re.search(r":\s*(\[.*\])\s*$", rule)
            extra = [" ".join(json.loads(match.group(1)))] if match else [rule]
        if variant == "pyc":
            source = configured if configured.is_file() else SCRIPT_DIR / "no_args" / "pyc" / f"{goal}.pyc"
            destination = "/filesystem/.task_helper.pyc"
            command = ["python", destination, *extra]
        elif variant == "elf":
            source = configured if configured.is_file() else SCRIPT_DIR / "no_args" / "elf" / goal
            destination = "/filesystem/.task_helper"
            command = [destination, *extra]
        else:
            source = configured if configured.is_file() else SCRIPT_DIR / "no_args" / "py" / f"{goal}.py"
            destination = "/filesystem/.task_helper.py"
            command = ["python", destination, *extra]
        _run(["docker", "cp", str(source), f"{container}:{destination}"])
        if variant == "elf":
            _run(["docker", "exec", container, "chmod", "+x", destination])
        if execution == "code-exec":
            driver = HERE / "_faithful_driver.py"
            _run(["docker", "cp", str(driver), f"{container}:/args_faithful_driver.py"])
            code = "ARGS_HELPER_DEBUG=/tmp/args_helper_debug.log " + shlex.join(command)
            tool = _run(["docker", "exec", container, "/usr/bin/python3",
                         "/args_faithful_driver.py", code], timeout=180)
            print("  code_exec=" + (tool.stdout or tool.stderr).strip()[:180], flush=True)
            time.sleep(8)
            trace = _run(["docker", "exec", container, "sh", "-c",
                          "test ! -f /tmp/args_helper_debug.log || cat /tmp/args_helper_debug.log"])
            if trace.stdout:
                print("  helper_trace=" + trace.stdout.strip(), flush=True)
        else:
            _run(["docker", "exec", container, *command], timeout=120)
            _wait_worker(container)
        capture = _run(["docker", "exec", container, "sh", "-c",
                        "test ! -f /.apps_data/http_capture/requests.jsonl || cat /.apps_data/http_capture/requests.jsonl"])
        if capture.stdout:
            print("  captured_requests=" + capture.stdout.strip(), flush=True)
        with tempfile.TemporaryDirectory() as workdir:
            zip_path = _snapshot_zip(worker, env, Path(workdir))
            return _check(check_python, goal, zip_path, record)
    finally:
        _compose(worker, env, "down", "--volumes", "--remove-orphans", timeout=90)
        _run(["docker", "network", "rm", network])
        shutil.rmtree(worker, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("goals", nargs="*", help="6, 8, or full names (default: both)")
    parser.add_argument("--check-python", default=DEFAULT_CHECK_PYTHON)
    parser.add_argument("--variant", choices=["py","pyc","elf"], default="py")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--runtime-arg", action="append", default=[])
    parser.add_argument("--execution", choices=["direct", "code-exec"], default="direct")
    args = parser.parse_args()
    global CONFIG
    if args.config:
        CONFIG = args.config.resolve()

    selected = LINK_GOALS
    if args.goals:
        chosen = []
        for token in args.goals:
            chosen.extend(g for g in LINK_GOALS if g == token or g.startswith(token + "_"))
        selected = chosen or LINK_GOALS

    results: dict[str, dict] = {}
    for goal in selected:
        print(f"\n=== {goal} ===")
        result = run_goal(goal, args.check_python, args.variant, args.runtime_arg, args.execution)
        results[goal] = result
        print(f"  attack_success = {result.get('attack_success')}")
        for rule_id, rule in (result.get("attack_rules") or {}).items():
            print(f"    {rule_id}: passed={rule.get('passed')}")
        if result.get("error"):
            print(f"    error: {str(result['error'])[:200]}")

    print("\n===== SUMMARY =====")
    for goal in selected:
        print(f"  {goal}: attack_success={results.get(goal, {}).get('attack_success')}")


if __name__ == "__main__":
    main()
