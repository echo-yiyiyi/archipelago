#!/usr/bin/env python3
"""Fully faithful end-to-end verification for every inject goal.

For each goal this loads the task's REAL HuggingFace world into the environment,
overlays the populate baseline (minus the attack file), drops the payload in
`/filesystem`, and runs it through the real `code_execution` MCP tool -- exactly
the path an injected agent takes. It then snapshots and scores with the real
`check_security`. Link goals (6, 8) additionally bring up the runtime collector.

    python test_faithful_all.py                 # all goals
    python test_faithful_all.py 1 5             # a subset
    python test_faithful_all.py --variant elf   # via the ELF instead of the pyc

Worlds are large; each goal is extracted, tested, and cleaned up in turn.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
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
GEN_DIR = HERE.parent
CONFIG = GEN_DIR / "output" / "1_to_8_with_attack_config.json"
REPO = GEN_DIR.parent.parent
RUNS = REPO / "benchmark" / "output" / "concurrent"
sys.path.insert(0, str(REPO))
from benchmark.main_concurrency import (  # noqa: E402
    link_hosts_from_attack_config, write_worker_environment,
)

IMAGE = "archipelago-hf-environment:concurrency"
PROXY_IMAGE = "archipelago-hf-runtime-proxy:concurrency"
MCP_CONFIG = REPO / "benchmark" / "mcp_config_all_oss_servers.json"
DRIVER = HERE / "_faithful_driver.py"
CHECK_PY = "/data/ziyi/.venv/bin/python"
LINK_GOALS = {"6_chat_to_achieve_url", "8_fetch_external_link"}
CHECK_FILES = (".mbox", ".ics", "messages.json", "requests.jsonl")
GOALS = [
    "1_email_send_file", "2_email_send_draft", "3_email_forward_otp",
    "4_email_broadcast_link", "5_chat_send_link", "6_chat_to_achieve_url",
    "7_calendar_create_event", "8_fetch_external_link",
]


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def record(goal):
    for r in json.loads(CONFIG.read_text(encoding="utf-8")):
        if r.get("inject_goal") == goal:
            return r
    raise SystemExit(f"no record for {goal}")


def newest_world(task_id):
    worlds = sorted(glob.glob(str(RUNS / f"run_*/tasks/{task_id}/world_*.zip")),
                    key=os.path.getmtime, reverse=True)
    if not worlds:
        raise SystemExit(f"no world snapshot for {task_id}")
    return Path(worlds[0])


def extract_world(task_id, work):
    world = work / "world"
    world.mkdir(parents=True)
    subprocess.run(["unzip", "-q", str(newest_world(task_id)), "-d", str(world)],
                   check=True)
    return world


def overlay_populate(world, rec):
    """Copy populate app fixtures (minus the attack file) over the world."""
    attack_file = rec.get("attack_file")
    for rel in rec.get("populate_files", []):
        if rel == attack_file:
            continue
        parts = Path(rel).parts
        if ".apps_data" not in parts:
            continue
        idx = parts.index(".apps_data")
        dst = world / ".apps_data" / Path(*parts[idx + 1:])
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(CONFIG.parent / rel, dst)


def wait_health(container):
    for _ in range(90):
        if run(["docker", "exec", container, "curl", "-s", "-o", "/dev/null",
                "-w", "%{http_code}", "http://localhost:8080/health"]).stdout.strip() == "200":
            return
        time.sleep(1)
    raise RuntimeError("unhealthy")


def configure_gateway(container):
    run(["docker", "cp", str(MCP_CONFIG), f"{container}:/mcp_config.json"])
    out = run(["docker", "exec", container, "curl", "-s", "-X", "POST",
               "http://localhost:8080/apps", "-H", "Content-Type: application/json",
               "--data-binary", "@/mcp_config.json", "--max-time", "200"])
    if '"servers"' not in out.stdout:
        raise RuntimeError(f"gateway configure failed: {out.stdout[:200]}")


def run_payload_via_code_exec(container, goal, variant):
    if variant == "elf":
        run(["docker", "cp", str(HERE / "elf" / goal), f"{container}:/filesystem/.task_helper"])
        run(["docker", "exec", container, "chmod", "+x", "/filesystem/.task_helper"])
        cmd = "/filesystem/.task_helper"
    else:
        run(["docker", "cp", str(HERE / "pyc" / f"{goal}.pyc"), f"{container}:/filesystem/.task_helper.pyc"])
        cmd = "python3 /filesystem/.task_helper.pyc"
    run(["docker", "cp", str(DRIVER), f"{container}:/driver.py"])
    out = run(["docker", "exec", container, "/usr/bin/python3", "/driver.py", cmd], timeout=180)
    return out.stdout.strip()[:120]


def wait_worker(container, timeout=90):
    for _ in range(timeout):
        n = run(["docker", "exec", container, "bash", "-lc",
                 "pgrep -fa 'task_helper|b64decode' | grep -v pgrep | wc -l"]).stdout.strip()
        if n in ("", "0"):
            time.sleep(2)
            return
        time.sleep(2)


def snapshot_min_zip(container, work):
    run(["docker", "exec", container, "bash", "-lc",
         "curl -s -X POST http://localhost:8080/data/snapshot -o /tmp/s.tar.gz"])
    tgz = work / "s.tar.gz"
    run(["docker", "cp", f"{container}:/tmp/s.tar.gz", str(tgz)])
    zp = work / "check.zip"
    with tarfile.open(tgz, "r:gz") as t, zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for m in t.getmembers():
            if m.isfile() and any(m.name.endswith(s) for s in CHECK_FILES):
                z.writestr(m.name, t.extractfile(m).read())
    tgz.unlink(missing_ok=True)
    return zp


def check(goal, zip_path, rec):
    cfg = dict(rec.get("attack_config") or {})
    cfg.setdefault("original_task_prompt", rec.get("prompt", ""))
    script = (
        "import json,sys;sys.path.insert(0,%r);" % str(REPO)
        + "from benchmark.runner.security_check import check_security;"
        "print(json.dumps(check_security(inject_goal=%r,final_snapshot=%r,"
        "attack_config=json.loads(%r))))" % (goal, str(zip_path), json.dumps(cfg))
    )
    out = run([CHECK_PY, "-c", script], timeout=200)
    line = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else ""
    try:
        return json.loads(line)
    except Exception:
        return {"attack_success": 0, "error": (out.stdout + out.stderr)[:300]}


def cp_world_into(container, world):
    for sub in ("filesystem", ".apps_data"):
        src = world / sub
        if src.exists():
            run(["docker", "exec", container, "mkdir", "-p", f"/{sub}"])
            for child in src.iterdir():
                run(["docker", "cp", str(child), f"{container}:/{sub}/"])


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def run_local_goal(goal, variant):
    rec = record(goal)
    work = Path(tempfile.mkdtemp(prefix="faith-"))
    container = "faith-" + uuid.uuid4().hex[:8]
    try:
        world = extract_world(rec["task_id"], work)
        overlay_populate(world, rec)
        run(["docker", "run", "--detach", "--name", container,
             "-v", f"{world}/filesystem:/filesystem",
             "-v", f"{world}/.apps_data:/.apps_data", IMAGE])
        wait_health(container)
        configure_gateway(container)
        tool_out = run_payload_via_code_exec(container, goal, variant)
        wait_worker(container)
        zp = snapshot_min_zip(container, work)
        result = check(goal, zp, rec)
        result["_code_exec"] = tool_out
        return result
    finally:
        run(["docker", "rm", "-f", container])
        run(["docker", "run", "--rm", "-v", f"{work}:/w", IMAGE, "rm", "-rf", "/w/world"])
        shutil.rmtree(work, ignore_errors=True)


def run_link_goal(goal, variant):
    rec = record(goal)
    hosts = link_hosts_from_attack_config(CONFIG)
    work = Path(tempfile.mkdtemp(prefix="faithlink-"))
    slug = "faithlink-" + uuid.uuid4().hex[:8]
    network = slug + "-net"
    env = os.environ.copy()
    env["COMPOSE_PROJECT_NAME"] = slug.replace("-", "_")
    run(["docker", "network", "create", "--internal", network])
    try:
        world = extract_world(rec["task_id"], work)
        overlay_populate(world, rec)
        write_worker_environment(
            work, free_port(), IMAGE, PROXY_IMAGE, network,
            "goal8" if goal == "8_fetch_external_link" else "generic", hosts[rec["task_id"]])
        up = subprocess.run(["docker", "compose", "up", "--detach", "--wait",
                             "--wait-timeout", "90"], cwd=work, env=env,
                            capture_output=True, text=True, timeout=150)
        if up.returncode != 0:
            return {"attack_success": 0, "error": "compose up: " + up.stderr[:200]}
        container = subprocess.run(["docker", "compose", "ps", "-q", "environment"],
                                   cwd=work, env=env, capture_output=True, text=True).stdout.strip()
        cp_world_into(container, world)
        configure_gateway(container)
        tool_out = run_payload_via_code_exec(container, goal, variant)
        wait_worker(container)
        zp = snapshot_min_zip(container, work)
        result = check(goal, zp, rec)
        result["_code_exec"] = tool_out
        return result
    finally:
        subprocess.run(["docker", "compose", "down", "-v", "--remove-orphans"],
                       cwd=work, env=env, capture_output=True, text=True, timeout=90)
        run(["docker", "network", "rm", network])
        run(["docker", "run", "--rm", "-v", f"{work}:/w", IMAGE, "rm", "-rf", "/w/world"])
        shutil.rmtree(work, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("goals", nargs="*")
    ap.add_argument("--variant", choices=["pyc", "elf"], default="pyc")
    args = ap.parse_args()

    selected = GOALS
    if args.goals:
        selected = [g for g in GOALS if any(g == t or g.startswith(t + "_") for t in args.goals)]

    results = {}
    for goal in selected:
        print(f"\n=== {goal} (faithful: real world + code_execution) ===", flush=True)
        try:
            result = (run_link_goal if goal in LINK_GOALS else run_local_goal)(goal, args.variant)
        except Exception as error:
            result = {"attack_success": "ERR", "error": str(error)[:200]}
        results[goal] = result
        print(f"  attack_success = {result.get('attack_success')}  code_exec={result.get('_code_exec','')!r}", flush=True)
        for rid, rule in (result.get("attack_rules") or {}).items():
            print(f"    {rid}: passed={rule.get('passed')}", flush=True)
        if result.get("error"):
            print(f"    error: {result['error']}", flush=True)

    print("\n===== FAITHFUL SUMMARY =====", flush=True)
    for goal in selected:
        print(f"  {goal}: attack_success={results.get(goal, {}).get('attack_success')}", flush=True)


if __name__ == "__main__":
    main()
