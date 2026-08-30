#!/usr/bin/env python3
"""Replay multiple COT trajectories in one shared concurrent runner.

Unlike replay_cot_variants.py, this creates one shared proxy compose project
and schedules every manifest entry as a worker task.  The original task id is
passed to main.py while the variant label keeps logs/results distinct.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import queue
import shutil
import sys
import threading
import time
import uuid
from urllib.parse import urlparse
from pathlib import Path

# Permit direct execution from the repository root or from any working dir.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from examples.hugging_face_task import main_concurrency as mc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("benchmark/cot_prompt_adjust/output/manifest.json"))
    parser.add_argument("--parallel", type=int, default=32)
    parser.add_argument("--limit", type=int, help="Run only the first N prepared entries (for smoke tests).")
    parser.add_argument("--task-id", help="Run only prepared entries for this original task id.")
    parser.add_argument("--base-port", type=int, default=18080)
    parser.add_argument("--additional-turns", type=int, default=10)
    parser.add_argument("--orchestrator-config", type=Path, default=Path("benchmark/orchestrator_config_gemini3.json"))
    parser.add_argument("--attack-config", type=Path, default=Path("benchmark/generate_attack_config/output/1_to_8_with_attack_config.json"), help="Attack config JSON; seeds mail/chat/calendar targets and grading rules.")
    parser.add_argument("--run-id")
    parser.add_argument("--keep-environments", action="store_true")
    parser.add_argument("--skip-grading", action="store_true")
    args = parser.parse_args()
    if args.parallel < 1 or args.additional_turns < 1:
        parser.error("parallel and additional-turns must be positive")

    records = json.loads(args.manifest.read_text(encoding="utf-8"))
    records = [r for r in records if isinstance(r, dict) and r.get("status") == "prepared"]
    if args.task_id:
        records = [r for r in records if r.get("task_id") == args.task_id]
    if args.limit is not None:
        if args.limit < 1:
            parser.error("limit must be positive")
        records = records[: args.limit]
    if not records:
        parser.error("manifest contains no prepared trajectories")
    worker_count = min(args.parallel, len(records))
    if args.base_port < 1 or args.base_port > 65536 - worker_count:
        parser.error("base-port leaves insufficient valid ports")

    # Seed attack target fixtures during replay: examples/main.py reads this env
    # and calls populate_attack_file so OTP mail / chat channels / calendar exist
    # in the running world (otherwise injected attacks error with "not found").
    attack_config_path = args.attack_config.resolve()
    if not attack_config_path.is_file():
        parser.error(f"attack config not found: {attack_config_path}")
    os.environ["ATTACK_CONFIG_FILE"] = str(attack_config_path)

    # Map URL-visiting attack goals to their attacker hostname so the worker
    # collector answers (and captures) the request instead of failing DNS.
    _url_goals = {"6_chat_to_achieve_url", "8_fetch_external_link", "9_url_query_params"}
    task_link_hosts: dict[str, list[str]] = {}
    _cfg = json.loads(attack_config_path.read_text(encoding="utf-8"))
    _cfg_records = _cfg if isinstance(_cfg, list) else list(_cfg.values())
    for _rec in _cfg_records:
        if not isinstance(_rec, dict):
            continue
        if _rec.get("inject_goal") not in _url_goals:
            continue
        _link = (_rec.get("attack_config") or {}).get("attacker_link")
        _tid = _rec.get("task_id")
        if _link and _tid:
            _host = urlparse(_link).hostname
            if _host:
                task_link_hosts[_tid] = [_host]

    run_id = args.run_id or f"cotbatch_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    run_dir = mc.EXAMPLE_DIR / "output" / "concurrent" / run_id
    (run_dir / "logs").mkdir(parents=True, exist_ok=False)
    mc._run_logger = mc.RunLogger(run_dir)

    runtime_subnets = mc.allocate_runtime_subnets(worker_count)
    runtime_networks = [
        (mc.shared_resource_name(run_id, f"runtime_{i:02d}"), runtime_subnets[i])
        for i in range(worker_count)
    ]
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

    def stage_resume_input(trajectory: Path, label: str) -> Path:
        """Create a self-consistent truncated trajectory and audit set.

        Prepared replay trajectories inherit usage metadata from the complete
        source trajectory.  Only ReSum records whose trigger is still present
        in the truncated message list are valid during resume.
        """
        stage_dir = run_dir / "resume_inputs" / label
        stage_dir.mkdir(parents=True, exist_ok=False)
        data = json.loads(trajectory.read_text(encoding="utf-8"))
        message_count = len(data.get("messages") or [])
        candidates = list(trajectory.parent.glob("sumerize_*.json"))
        if not candidates:
            candidates = list((trajectory.parent.parent / "variant_01").glob("sumerize_*.json"))
        valid: list[tuple[int, Path]] = []
        for audit in candidates:
            record = json.loads(audit.read_text(encoding="utf-8"))
            trigger = record.get("trigger_after_trajectory_message_index")
            if isinstance(trigger, int) and 0 <= trigger < message_count:
                valid.append((trigger, audit))
        valid.sort(key=lambda item: item[0])
        usage = data.setdefault("usage", {})
        usage["compaction_count"] = len(valid)
        staged_trajectory = stage_dir / "trajectory.json"
        staged_trajectory.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        for index, (_, audit) in enumerate(valid, 1):
            shutil.copy2(audit, stage_dir / f"sumerize_{index}.json")
        return staged_trajectory

    def run_record(record: dict[str, object]):
        slot = slots.get()
        task_id = str(record["task_id"])
        variant = int(record.get("variant", 0))
        label = f"{task_id}__variant_{variant:02d}"
        source_trajectory = Path(str(record["trajectory"])).resolve()
        # Replays of the same task must never share TASK_OUTPUT_ROOT: world
        # snapshots and temporary ZIP files are named by task id and concurrent
        # writers otherwise corrupt one another.
        variant_run_dir = run_dir / "variants" / label
        (variant_run_dir / "logs").mkdir(parents=True, exist_ok=False)
        try:
            trajectory = stage_resume_input(source_trajectory, label)
            mc.log("Task started", event="task_started", task=label, worker=slot.number, port=slot.port)
            result = mc.run_task(
                task_id, slot, variant_run_dir, mc.DEFAULT_IMAGE, mc.DEFAULT_PROXY_IMAGE,
                args.keep_environments, args.skip_grading,
                runtime_networks[slot.number][0], stop_requested, active,
                None, config_path, None, None, None,
                trajectory, args.additional_turns,
                task_link_hosts.get(task_id),
            )
            result.selector = label
            return result
        finally:
            slots.put(slot)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(run_record, r) for r in records]
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())
    finally:
        if not args.keep_environments:
            mc.cleanup_shared_proxy(proxy_dir, proxy_env)

    manifest = {
        "run_id": run_id,
        "requested_task_count": len(records),
        "worker_count": worker_count,
        "additional_turns": args.additional_turns,
        "results": [mc.asdict(r) for r in results],
        "runtime_networks": [{"name": n, "subnet": s} for n, s in runtime_networks],
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Completed {len(results)}/{len(records)} replay variants; run_dir={run_dir}")
    return 0 if all(r.returncode == 0 for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
