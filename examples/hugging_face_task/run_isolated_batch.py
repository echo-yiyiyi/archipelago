#!/usr/bin/env python3
"""Prepare and run text variants of one resumed trajectory in parallel."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import ipaddress
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import main_concurrency


EXAMPLE_DIR = Path(__file__).resolve().parent
AGENTS_DIR = Path(
    os.environ.get("AGENTS_DIR", EXAMPLE_DIR.parent.parent / "agents")
).resolve()
BATCH_INPUT_ROOT = Path(
    os.environ.get(
        "ISOLATED_BATCH_INPUT_ROOT", EXAMPLE_DIR / "input" / ".isolated_batches"
    )
).resolve()


@dataclass(frozen=True)
class Variant:
    name: str
    text: str
    experiment: str
    repeat: int


def choose_free_network_second_octet() -> int:
    """Choose an unused 10.x.0.0/16 for explicit runtime and egress subnets."""
    listed = subprocess.run(
        ["docker", "network", "ls", "-q"],
        check=True, capture_output=True, text=True,
    ).stdout.split()
    occupied: list[ipaddress.IPv4Network] = []
    if listed:
        inspected = subprocess.run(
            ["docker", "network", "inspect", *listed],
            check=True, capture_output=True, text=True,
        )
        for network in json.loads(inspected.stdout):
            for config in network.get("IPAM", {}).get("Config", []) or []:
                try:
                    subnet = ipaddress.ip_network(config.get("Subnet", ""))
                except ValueError:
                    continue
                if isinstance(subnet, ipaddress.IPv4Network):
                    occupied.append(subnet)
    for second_octet in range(100, 251):
        candidate = ipaddress.ip_network(f"10.{second_octet}.0.0/16")
        if not any(candidate.overlaps(subnet) for subnet in occupied):
            return second_octet
    raise RuntimeError("no unused 10.x.0.0/16 remains for the isolated batch")


def write_batch_score_summary(
    batch_dir: Path, results: list[tuple[Variant, int, str]]
) -> dict[str, object]:
    """Aggregate child-run scores overall and by the original variant name."""
    runs: list[dict[str, object]] = []
    for variant, returncode, run_id in sorted(results, key=lambda item: item[2]):
        score_file = EXAMPLE_DIR / "output" / "concurrent" / run_id / "score_summary.json"
        run: dict[str, object] = {
            "variant": variant.experiment, "repeat": variant.repeat,
            "run_id": run_id, "returncode": returncode,
        }
        try:
            summary = json.loads(score_file.read_text())
            task = next((item for item in summary.get("tasks", [])
                         if item.get("variant") == variant.experiment), None)
            if task:
                for key in ("attack_success", "security_score", "security_judging_status", "final_score"):
                    if key in task:
                        run[key] = task[key]
        except (OSError, json.JSONDecodeError, TypeError):
            run["security_judging_status"] = "missing"
        runs.append(run)

    def aggregate(items: list[dict[str, object]]) -> dict[str, object]:
        judged = [item for item in items if item.get("security_judging_status") == "completed" and isinstance(item.get("security_score"), (int, float)) and not isinstance(item.get("security_score"), bool)]
        attacks = sum(item.get("attack_success") is True for item in judged)
        task_graded = [item for item in items if isinstance(item.get("final_score"), (int, float)) and not isinstance(item.get("final_score"), bool)]
        return {
            "run_count": len(items), "security_judged_count": len(judged),
            "security_unjudged_count": len(items) - len(judged),
            "attack_success_count": attacks,
            "average_attack_success_rate": attacks / len(judged) if judged else 0.0,
            "average_security_score": sum(float(item["security_score"]) for item in judged) / len(judged) if judged else 0.0,
            "task_graded_count": len(task_graded),
            "average_task_score": sum(float(item["final_score"]) for item in task_graded) / len(task_graded) if task_graded else 0.0,
        }

    names = sorted({str(run["variant"]) for run in runs})
    result: dict[str, object] = {
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **aggregate(runs),
        "variants": {name: aggregate([run for run in runs if run["variant"] == name]) for name in names},
        "runs": runs,
    }
    target = batch_dir / "score_summary.json"
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(target)
    output_dir = EXAMPLE_DIR / "output" / "concurrent" / batch_dir.name
    output_dir.mkdir(parents=True, exist_ok=True)
    output_target = output_dir / "score_summary.json"
    output_temporary = output_target.with_name(output_target.name + ".tmp")
    output_temporary.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    )
    output_temporary.replace(output_target)
    return result


def safe_name(value: str, index: int) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_.-")
    return (slug[:40] or f"variant_{index:03d}").lower()


def load_variants(path: Path, repeats: int = 3) -> list[Variant]:
    data = json.loads(path.read_text())
    raw: object
    if isinstance(data, list):
        raw = data
    elif isinstance(data, dict) and "variants" in data:
        raw = data["variants"]
    elif isinstance(data, dict) and "texts" in data:
        raw = data["texts"]
    elif isinstance(data, dict) and all(isinstance(value, str) for value in data.values()):
        raw = [{"name": key, "text": value} for key, value in data.items()]
    else:
        raise ValueError(
            "variants JSON must be a string list, a {texts: [...]}/{variants: [...]} "
            "object, or a name-to-text mapping"
        )

    if not isinstance(raw, list) or not raw:
        raise ValueError("variants JSON must contain at least one item")

    variants: list[Variant] = []
    used_names: set[str] = set()
    for index, item in enumerate(raw):
        if isinstance(item, str):
            text = item
            requested_name = f"variant_{index:03d}"
        elif isinstance(item, dict) and isinstance(item.get("text"), str):
            text = item["text"]
            requested_name = str(item.get("name", f"variant_{index:03d}"))
        else:
            raise ValueError(f"variant {index} must be a string or an object with text")
        if not text:
            raise ValueError(f"variant {index} has empty text")
        name = safe_name(requested_name, index)
        if name in used_names:
            name = f"{name}_{index:03d}"
        used_names.add(name)
        for repeat in range(1, repeats + 1):
            variants.append(
                Variant(
                    name=f"{name}_{repeat}",
                    text=text,
                    experiment=requested_name,
                    repeat=repeat,
                )
            )
    return variants


def append_last_tool_text(trajectory: dict[str, object], addition: str) -> int:
    messages = trajectory.get("messages")
    if not isinstance(messages, list):
        raise ValueError("trajectory must contain a messages list")

    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "tool":
            continue
        content = message.get("content")
        if isinstance(content, str):
            message["content"] = content + addition
            return 1
        if isinstance(content, list):
            for block in reversed(content):
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    block["text"] += addition
                    return 1
        raise ValueError("last tool message has no replaceable text field")
    raise ValueError("trajectory contains no tool message")


def prepare_variant(
    source: Path, task_id: str, batch_dir: Path, variant: Variant
) -> Path:
    target_dir = batch_dir / variant.name / task_id
    target_dir.mkdir(parents=True, exist_ok=False)
    trajectory = json.loads(source.read_text())
    append_last_tool_text(trajectory, variant.text)
    target = target_dir / "trajectory.json"
    target.write_text(json.dumps(trajectory, indent=2, ensure_ascii=False) + "\n")
    for summary in source.parent.glob("sumerize_*.json"):
        shutil.copy2(summary, target_dir / summary.name)
    return target


def option_value(options: list[str], flag: str, default: str) -> str:
    for index, option in enumerate(options):
        if option == flag:
            if index + 1 >= len(options):
                raise ValueError(f"{flag} requires a value")
            return options[index + 1]
        if option.startswith(flag + "="):
            return option.split("=", 1)[1]
    return default


def reject_conflicting_options(options: list[str]) -> None:
    reserved = {
        "--concurrency",
        "--base-port",
        "--run-id",
        "--resume-trajectory",
        "--additional-turns",
    }
    for option in options:
        if option.split("=", 1)[0] in reserved:
            raise ValueError(f"{option.split('=', 1)[0]} is managed by batch mode")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trajectory", type=Path)
    parser.add_argument("additional_turns", type=int)
    parser.add_argument("variants_json", type=Path)
    parser.add_argument("--parallel", type=int)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--base-port", type=int, default=18080)
    parser.add_argument("--prepare-only", action="store_true")
    args, main_options = parser.parse_known_args()

    source = args.trajectory.resolve()
    if not source.is_file():
        parser.error(f"trajectory not found: {source}")
    if args.additional_turns < 1:
        parser.error("additional_turns must be positive")

    task_dir = source.parent.name
    task_id = task_dir if task_dir.startswith("task_") else f"task_{task_dir}"
    try:
        if args.repeats < 1:
            raise ValueError("--repeats must be positive")
        variants = load_variants(args.variants_json.resolve(), args.repeats)
        reject_conflicting_options(main_options)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        parser.error(str(error))

    parallel = args.parallel or min(4, len(variants))
    if len(variants) > 256:
        parser.error("batch mode supports at most 256 variants")
    if not 1 <= parallel <= len(variants):
        parser.error("--parallel must be between 1 and the number of variants")
    if not 1 <= args.base_port <= 65535 - len(variants):
        parser.error("--base-port leaves insufficient ports for all variants")

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    batch_id = f"isolated_batch_{timestamp}_{task_id.removeprefix('task_')}"
    batch_dir = BATCH_INPUT_ROOT / batch_id
    batch_dir.mkdir(parents=True, exist_ok=False)
    prepared = [
        (variant, prepare_variant(source, task_id, batch_dir, variant))
        for variant in variants
    ]
    manifest = {
        "batch_id": batch_id,
        "source_trajectory": str(source),
        "additional_turns": args.additional_turns,
        "parallel": parallel,
        "variants": [
            {
                "name": variant.name,
                "experiment": variant.experiment,
                "repeat": variant.repeat,
                "text": variant.text,
                "trajectory": str(path),
            }
            for variant, path in prepared
        ],
    }
    (batch_dir / "batch_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    )
    print(f"Prepared {len(prepared)} variants in {batch_dir}", flush=True)
    if args.prepare_only:
        return 0

    environment_image = option_value(
        main_options, "--environment-image", main_concurrency.DEFAULT_IMAGE
    )
    proxy_image = option_value(
        main_options, "--proxy-image", main_concurrency.DEFAULT_PROXY_IMAGE
    )
    child_options = list(main_options)
    if "--skip-build" not in child_options:
        main_concurrency.build_environment_image(environment_image)
        main_concurrency.build_proxy_image(proxy_image)
        child_options.append("--skip-build")
    network_second_octet = choose_free_network_second_octet()

    def run_variant(item: tuple[int, tuple[Variant, Path]]) -> tuple[Variant, int, str]:
        index, (variant, trajectory) = item
        # Docker/Compose resource names retain only the first 40 characters of
        # the run ID. Put the variant and index first so parallel variants
        # cannot collapse to the same proxy/network/container names.
        short_variant = variant.name[:16]
        short_task = task_id.removeprefix("task_")[:8]
        run_id = f"iso_{timestamp}_{index:03d}_{short_variant}_{short_task}"
        command = [
            sys.executable,
            str(EXAMPLE_DIR / "main_concurrency.py"),
            task_id,
            "--resume-trajectory",
            str(trajectory),
            "--additional-turns",
            str(args.additional_turns),
            "--concurrency",
            "1",
            "--base-port",
            str(args.base_port + index),
            "--run-id",
            run_id,
            *child_options,
        ]
        environment = os.environ.copy()
        environment["HF_EXPERIMENT_NAME"] = variant.experiment
        environment["HF_INITIAL_CONFIG_SOURCE"] = str(
            EXAMPLE_DIR.parent.parent.parent
            / "sampled_tasks"
            / "prompt_inject"
            / "inject_file"
            / "initial_config"
        )
        environment["HF_SSH_ARCHIVE_SOURCE"] = str(
            EXAMPLE_DIR.parent.parent.parent / "os-harm" / "assets" / "ssh.tar.xz"
        )
        environment["RUNTIME_NETWORK_CIDR"] = (
            f"10.{network_second_octet}.{index}.0/28"
        )
        environment["RUNTIME_EGRESS_SUBNET"] = (
            f"10.{network_second_octet}.{index}.16/28"
        )
        launcher_log = batch_dir / f"{index:03d}_{variant.name}.launcher.log"
        with launcher_log.open("w") as output:
            result = subprocess.run(
                command,
                cwd=AGENTS_DIR,
                env=environment,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        return variant, result.returncode, run_id

    results: list[tuple[Variant, int, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel) as executor:
        futures = [executor.submit(run_variant, item) for item in enumerate(prepared)]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            write_batch_score_summary(batch_dir, results)
            print(
                f"Variant {result[0].name} finished with code {result[1]}: "
                f"output/concurrent/{result[2]}",
                flush=True,
            )

    summary = write_batch_score_summary(batch_dir, results)
    print(f"Batch security attack rate: {summary['average_attack_success_rate']:.3f}", flush=True)
    failed = [variant.name for variant, returncode, _ in results if returncode != 0]
    if failed:
        print(f"Failed variants: {', '.join(sorted(failed))}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
