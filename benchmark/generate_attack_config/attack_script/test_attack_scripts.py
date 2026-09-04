#!/usr/bin/env python3
"""Run each rendered attack payload against the real benchmark environment.

For every inject goal this harness:

1. seeds a fresh ``/.apps_data`` baseline from the task's ``populate_files``
   (the attack file is deliberately excluded, and a mailbox directory is always
   present, mirroring the world state a real run starts from);
2. runs the payload inside the environment container -- the payload reaches the
   MCP gateway on ``localhost:8080`` exactly as the code-execution sandbox would;
3. snapshots ``/.apps_data``, converts it to the grading ZIP, and calls the real
   ``benchmark/runner/security_check.check_security``.

Local goals (1,2,3,4,5,7) need only the environment container. The link-visiting
goals (6,8) require the runtime proxy + collector and are covered by
``test_attack_scripts_link.py``.

    python test_attack_scripts.py                # all local goals
    python test_attack_scripts.py 5 7            # a subset

Requires: docker, the ``archipelago-hf-environment:concurrency`` image, and a
Python (``--check-python``) with openai + azure for the goal 2/7 LLM judge.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
GEN_DIR = HERE.parent
CONFIG = GEN_DIR / "output" / "1_to_8_with_attack_config.json"
REPO = GEN_DIR.parent.parent
IMAGE = "archipelago-hf-environment:concurrency"
MCP_CONFIG = REPO / "benchmark" / "mcp_config_all_oss_servers.json"
DEFAULT_CHECK_PYTHON = "/data/ziyi/.venv/bin/python"

LOCAL_GOALS = [
    "1_email_send_file",
    "2_email_send_prompt",
    "3_email_forward_otp",
    "4_email_broadcast_link",
    "5_chat_send_link",
    "7_calendar_create_event",
]
MAILBOX_NAME = "All mail Including Spam and Trash.mbox"


def _run(cmd, **kwargs):
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def _record(goal: str) -> dict:
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    for record in data:
        if record.get("inject_goal") == goal:
            return record
    raise SystemExit(f"no record for goal {goal}")


def _seed_dir(record: dict) -> Path:
    """Build a host directory that mirrors the environment's /.apps_data seed."""
    tmp = Path(tempfile.mkdtemp(prefix="atkseed-"))
    apps = tmp / ".apps_data"
    apps.mkdir()
    attack_file = record.get("attack_file")
    for rel in record.get("populate_files", []):
        if rel == attack_file:
            continue  # never place the injection carrier
        parts = Path(rel).parts
        if ".apps_data" not in parts:
            continue  # filesystem fixtures are not needed to pass the checks
        index = parts.index(".apps_data")
        destination = apps.joinpath(*parts[index + 1:])
        # populate_files are stored relative to the config directory (output/).
        source = CONFIG.parent / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    # Always provide a mailbox, as every real world does.
    mail_dir = apps / "mail" / "Mail"
    mail_dir.mkdir(parents=True, exist_ok=True)
    mbox = mail_dir / MAILBOX_NAME
    if not mbox.exists():
        mbox.write_bytes(b"")
    return tmp


def _start_container() -> str:
    name = "archipelago-atktest-" + uuid.uuid4().hex[:10]
    # Do NOT override the image command: the default entrypoint starts the
    # environment HTTP server (health, /apps gateway, /data/snapshot) on 8080.
    _run(["docker", "run", "--detach", "--name", name, IMAGE])
    return name


def _wait_health(container: str, timeout: int = 60) -> None:
    for _ in range(timeout):
        out = _run(["docker", "exec", container, "curl", "-s", "-o", "/dev/null",
                    "-w", "%{http_code}", "http://localhost:8080/health"])
        if out.stdout.strip() == "200":
            return
        time.sleep(1)
    raise RuntimeError("environment never became healthy")


def _configure_gateway(container: str) -> None:
    _run(["docker", "cp", str(MCP_CONFIG), f"{container}:/mcp_config.json"])
    out = _run(["docker", "exec", container, "curl", "-s", "-X", "POST",
                "http://localhost:8080/apps", "-H", "Content-Type: application/json",
                "--data-binary", "@/mcp_config.json", "--max-time", "180"])
    if '"servers"' not in out.stdout:
        raise RuntimeError(f"gateway configure failed: {out.stdout[:300]}")


def _seed_container(container: str, seed: Path) -> None:
    _run(["docker", "exec", container, "rm", "-rf", "/.apps_data"])
    _run(["docker", "exec", container, "mkdir", "-p", "/.apps_data"])
    # Copy the seed contents into /.apps_data.
    for child in (seed / ".apps_data").iterdir():
        _run(["docker", "cp", str(child), f"{container}:/.apps_data/"])


def _snapshot_zip(container: str, workdir: Path) -> Path:
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
        "import json,sys;"
        "sys.path.insert(0, %r);" % str(REPO)
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
        return {"attack_success": 0, "error": out.stdout + out.stderr}


def _exec_payload(container: str, goal: str, variant: str) -> None:
    """Copy the requested artifact into the container and run it."""
    if variant == "py":
        src, dest, cmd = HERE / "py" / f"{goal}.py", "/payload.py", \
            ["/usr/bin/python3", "/payload.py"]
    elif variant == "pyc":
        src, dest, cmd = HERE / "pyc" / f"{goal}.pyc", "/payload.pyc", \
            ["/usr/bin/python3", "/payload.pyc"]
    elif variant == "elf":
        src, dest, cmd = HERE / "elf" / goal, "/payload_bin", \
            ["/payload_bin"]
    else:
        raise ValueError(variant)
    _run(["docker", "cp", str(src), f"{container}:{dest}"])
    if variant == "elf":
        _run(["docker", "exec", container, "chmod", "+x", dest])
    _run(["docker", "exec", container, *cmd], timeout=120)
    # The payload detaches its MCP work into a daemon and returns immediately, so
    # wait for that daemon to finish before snapshotting. In a real run the task
    # keeps running for minutes, so this delay is a harness-only concern.
    _wait_worker(container)


def _wait_worker(container: str, timeout: int = 60) -> None:
    for _ in range(timeout):
        out = _run(["docker", "exec", container, "bash", "-lc",
                    "pgrep -fa 'payload|b64decode|open_session' | grep -v pgrep | wc -l"])
        if out.stdout.strip() in ("", "0"):
            time.sleep(1)
            return
        time.sleep(1)


def run_goal(container: str, goal: str, check_python: str, variant: str = "py") -> dict:
    record = _record(goal)
    seed = _seed_dir(record)
    try:
        _seed_container(container, seed)
        _exec_payload(container, goal, variant)
        with tempfile.TemporaryDirectory() as workdir:
            zip_path = _snapshot_zip(container, Path(workdir))
            result = _check(check_python, goal, zip_path, record)
        return result
    finally:
        shutil.rmtree(seed, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("goals", nargs="*", help="goal numbers or names (default: all local)")
    parser.add_argument("--check-python", default=DEFAULT_CHECK_PYTHON)
    parser.add_argument("--keep", action="store_true", help="keep the container")
    parser.add_argument("--variant", choices=["py","pyc","elf"], default="py")
    args = parser.parse_args()

    selected = LOCAL_GOALS
    if args.goals:
        chosen = []
        for token in args.goals:
            matches = [g for g in LOCAL_GOALS if g == token or g.startswith(token + "_")]
            chosen.extend(matches)
        selected = chosen or LOCAL_GOALS

    container = _start_container()
    print(f"container: {container}")
    results: dict[str, dict] = {}
    try:
        _wait_health(container)
        _configure_gateway(container)
        for goal in selected:
            print(f"\n=== {goal} ===")
            result = run_goal(container, goal, args.check_python, args.variant)
            results[goal] = result
            success = result.get("attack_success")
            print(f"  attack_success = {success}")
            for rule_id, rule in (result.get("attack_rules") or {}).items():
                print(f"    {rule_id}: passed={rule.get('passed')}")
            if result.get("error"):
                print(f"    error: {str(result['error'])[:200]}")
    finally:
        if not args.keep:
            _run(["docker", "rm", "--force", container])

    print("\n===== SUMMARY =====")
    for goal in selected:
        print(f"  {goal}: attack_success={results.get(goal, {}).get('attack_success')}")


if __name__ == "__main__":
    main()
