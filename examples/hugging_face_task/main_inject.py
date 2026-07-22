#!/usr/bin/env python3
"""Launch model configurations from JSONL with one shared concurrency ceiling."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def read_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with open(path) as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict) or not isinstance(value.get("model"), str):
                raise ValueError(f"{path}:{number}: expected an orchestrator config object with model")
            rows.append(value)
    if not rows:
        raise ValueError(f"{path}: no configurations")
    return rows


def read_injection_selectors(path: Path) -> list[str]:
    """Read unique task selectors from an injection JSONL in file order."""
    selectors: list[str] = []
    seen: set[str] = set()
    with open(path) as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict) or not str(value.get("task", "")).strip():
                raise ValueError(f"{path}:{number}: expected an injection object with task")
            selector = str(value["task"]).strip()
            if selector not in seen:
                selectors.append(selector)
                seen.add(selector)
    if not selectors:
        raise ValueError(f"{path}: no task selectors")
    return selectors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config_jsonl", type=Path)
    parser.add_argument("injections_jsonl", type=Path)
    parser.add_argument("selectors", nargs="*")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--injection-goals", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--base-port", type=int, default=18080)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-grading", action="store_true")
    parser.add_argument("--keep-environments", action="store_true")
    parser.add_argument("--run-id")
    args = parser.parse_args()
    if args.concurrency < 1:
        parser.error("--concurrency must be at least 1")
    if args.all and args.selectors:
        parser.error("selectors and --all cannot be used together")
    if not args.all and not args.selectors:
        try:
            args.selectors = read_injection_selectors(args.injections_jsonl.resolve())
        except (OSError, ValueError, json.JSONDecodeError) as error:
            parser.error(str(error))

    configs = read_jsonl(args.config_jsonl.resolve())
    if len(configs) > 16:
        parser.error("at most 16 model configurations are supported per run")
    active_models = min(len(configs), args.concurrency)
    if len(configs) <= args.concurrency:
        base_slots, remainder = divmod(args.concurrency, len(configs))
        allocations = [base_slots + (index < remainder) for index in range(len(configs))]
    else:
        allocations = [1] * len(configs)
    port_offsets: list[int] = []
    offset = 0
    for allocation in allocations:
        port_offsets.append(offset)
        offset += allocation
    script_dir = Path(__file__).resolve().parent
    run_prefix = args.run_id or time.strftime("inject_%Y%m%d_%H%M%S")

    if not args.skip_build:
        from main_concurrency import (
            DEFAULT_IMAGE,
            DEFAULT_PROXY_IMAGE,
            build_environment_image,
            build_proxy_image,
        )

        build_environment_image(DEFAULT_IMAGE)
        build_proxy_image(DEFAULT_PROXY_IMAGE)

    def run_config(index: int, config_path: Path) -> int:
        command = [
            sys.executable, str(script_dir / "main_concurrency.py"),
            "--dataset-dir", str(args.dataset_dir.resolve()),
            "--orchestrator-config", str(config_path),
            "--injections-jsonl", str(args.injections_jsonl.resolve()),
            "--injection-goals", str(args.injection_goals.resolve()),
            "--concurrency", str(allocations[index]),
            "--base-port", str(args.base_port + port_offsets[index]),
            "--run-id", f"{run_prefix}_model_{index:02d}",
            "--skip-build",
        ]
        if args.all:
            command.append("--all")
        else:
            command.extend(args.selectors)
        if args.skip_grading:
            command.append("--skip-grading")
        if args.keep_environments:
            command.append("--keep-environments")
        environment = os.environ.copy()
        # Concurrent model launchers must not ask Docker for overlapping /28s.
        environment["RUNTIME_NETWORK_CIDR"] = f"10.253.{index * 16}.0/20"
        return subprocess.run(command, cwd=script_dir, env=environment).returncode

    with tempfile.TemporaryDirectory(prefix="archipelago-inject-configs-") as tmp:
        config_paths: list[Path] = []
        for index, config in enumerate(configs):
            path = Path(tmp) / f"orchestrator_{index:02d}.json"
            path.write_text(json.dumps(config, indent=2) + "\n")
            config_paths.append(path)
        with concurrent.futures.ThreadPoolExecutor(max_workers=active_models) as executor:
            codes = list(executor.map(lambda pair: run_config(*pair), enumerate(config_paths)))
    return 1 if any(codes) else 0


if __name__ == "__main__":
    raise SystemExit(main())
