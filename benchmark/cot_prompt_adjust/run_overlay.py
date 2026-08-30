#!/usr/bin/env python3
"""Run the 8 goals with the injection delivered as a standalone
`Additional_Task_Instructions.txt` world-overlay file (the ~100%-ASR vector),
using the un-varied original inner COT, on the current model.

Mirrors run_inject.py but resumes a minimal [system, user] seed and passes a
per-task --world-overlay instead of a mid-trajectory poisoned tool message.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import queue
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from examples.hugging_face_task import main_concurrency as mc


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, default=Path("benchmark/cot_prompt_adjust/overlay_inject/manifest_overlay.json"))
    p.add_argument("--parallel", type=int, default=8)
    p.add_argument("--base-port", type=int, default=18400)
    p.add_argument("--additional-turns", type=int, default=10)
    p.add_argument("--orchestrator-config", type=Path, default=Path("benchmark/orchestrator_config_gemini3.json"))
    p.add_argument("--attack-config", type=Path, default=Path("benchmark/generate_attack_config/output/1_to_8_with_attack_config.json"))
    p.add_argument("--run-id")
    p.add_argument("--keep-environments", action="store_true")
    p.add_argument("--skip-grading", action="store_true")
    args = p.parse_args()

    records = [r for r in json.loads(args.manifest.read_text(encoding="utf-8")) if isinstance(r, dict)]
    if not records:
        p.error("empty manifest")
    worker_count = min(args.parallel, len(records))

    attack_config_path = args.attack_config.resolve()
    os.environ["ATTACK_CONFIG_FILE"] = str(attack_config_path)
    cfg = json.loads(attack_config_path.read_text(encoding="utf-8"))
    cfg_recs = cfg if isinstance(cfg, list) else list(cfg.values())
    url_goals = {"6_chat_to_achieve_url", "8_fetch_external_link", "9_url_query_params"}
    task_link_hosts: dict[str, list[str]] = {}
    for rec in cfg_recs:
        if isinstance(rec, dict) and rec.get("inject_goal") in url_goals:
            link = (rec.get("attack_config") or {}).get("attacker_link")
            host = urlparse(link).hostname if link else None
            if host and rec.get("task_id"):
                task_link_hosts[rec["task_id"]] = [host]

    run_id = args.run_id or f"cotoverlay_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    run_dir = mc.EXAMPLE_DIR / "output" / "concurrent" / run_id
    (run_dir / "logs").mkdir(parents=True, exist_ok=False)
    mc._run_logger = mc.RunLogger(run_dir)

    runtime_subnets = mc.allocate_runtime_subnets(worker_count)
    runtime_networks = [(mc.shared_resource_name(run_id, f"runtime_{i:02d}"), runtime_subnets[i]) for i in range(worker_count)]
    proxy_dir = mc.write_shared_proxy(run_dir, mc.DEFAULT_PROXY_IMAGE, runtime_networks)
    proxy_env = os.environ.copy()
    proxy_env["COMPOSE_PROJECT_NAME"] = mc.shared_resource_name(run_id, "proxy")
    try:
        mc.start_shared_proxy(proxy_dir, proxy_env)
    except Exception:
        mc.cleanup_shared_proxy(proxy_dir, proxy_env)
        raise

    slots: queue.Queue[mc.WorkerSlot] = queue.Queue()
    for i in range(worker_count):
        slots.put(mc.WorkerSlot(i, args.base_port + i))
    stop_requested = threading.Event()
    active = mc.ActiveProcesses()
    config_path = args.orchestrator_config.resolve()
    results = []

    def run_record(record: dict):
        slot = slots.get()
        task_id = str(record["task_id"])
        label = f"{task_id}__overlay"
        variant_run_dir = run_dir / "variants" / label
        (variant_run_dir / "logs").mkdir(parents=True, exist_ok=False)
        try:
            mc.log("Task started", event="task_started", task=label, worker=slot.number, port=slot.port)
            result = mc.run_task(
                task_id, slot, variant_run_dir, mc.DEFAULT_IMAGE, mc.DEFAULT_PROXY_IMAGE,
                args.keep_environments, args.skip_grading,
                runtime_networks[slot.number][0], stop_requested, active,
                None, config_path, Path(record["world_overlay"]), None, None,
                Path(record["seed"]), args.additional_turns,
                task_link_hosts.get(task_id),
            )
            result.selector = label
            return result
        finally:
            slots.put(slot)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as ex:
            futures = [ex.submit(run_record, r) for r in records]
            for f in concurrent.futures.as_completed(futures):
                results.append(f.result())
    finally:
        if not args.keep_environments:
            mc.cleanup_shared_proxy(proxy_dir, proxy_env)

    (run_dir / "manifest.json").write_text(json.dumps({
        "run_id": run_id, "requested_task_count": len(records),
        "results": [mc.asdict(r) for r in results],
    }, indent=2) + "\n")
    print(f"Completed {len(results)}/{len(records)} overlay runs; run_dir={run_dir}")
    return 0 if all(r.returncode == 0 for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
