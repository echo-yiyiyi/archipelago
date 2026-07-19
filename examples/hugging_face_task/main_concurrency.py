#!/usr/bin/env python3
"""Run complete Hugging Face task pipelines concurrently.

The existing main.py remains the single-task implementation.  This file only
allocates isolated Docker environments and invokes main.py once per task, so
environment setup, agent execution, snapshots, and grading keep their original
logic.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import ipaddress
import json
import math
import os
import queue
import re
import signal
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

EXAMPLE_DIR = Path(os.environ.get("EXAMPLE_DIR", Path(__file__).parent)).resolve()
ARCHIPELAGO_DIR = Path(
    os.environ.get("ARCHIPELAGO_DIR", EXAMPLE_DIR.parent.parent)
).resolve()
SOURCE_ENVIRONMENT_DIR = Path(
    os.environ.get("ENVIRONMENT_DIR", ARCHIPELAGO_DIR / "environment")
).resolve()
AGENTS_DIR = Path(os.environ.get("AGENTS_DIR", ARCHIPELAGO_DIR / "agents")).resolve()
DEFAULT_IMAGE = "archipelago-hf-environment:concurrency"
DEFAULT_PROXY_IMAGE = "archipelago-hf-runtime-proxy:concurrency"
RUNTIME_PROXY_URL = "http://squid:3128"
AGENT_HELP_DOMAIN = "agent-help.com"
DEFAULT_RUNTIME_NETWORK_CIDR = "10.253.0.0/16"
RUNTIME_NETWORK_PREFIX = 28
SCORE_SUMMARY_FILENAME = os.environ.get(
    "SCORE_SUMMARY_FILENAME", "score_summary.json"
)
COMPOSE_CLEANUP_TIMEOUT_SECONDS = 60
PROCESS_TERMINATION_GRACE_SECONDS = 10


@dataclass(frozen=True)
class WorkerSlot:
    number: int
    port: int


@dataclass
class TaskResult:
    selector: str
    worker: int
    port: int
    returncode: int
    log_file: str
    elapsed_seconds: float
    error: str | None = None


class ActiveProcesses:
    """Track task subprocess groups so Ctrl-C can stop them deterministically."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._processes: dict[str, subprocess.Popen[bytes]] = {}

    def add(self, selector: str, process: subprocess.Popen[bytes]) -> None:
        with self._lock:
            self._processes[selector] = process

    def remove(self, selector: str, process: subprocess.Popen[bytes]) -> None:
        with self._lock:
            if self._processes.get(selector) is process:
                del self._processes[selector]

    def terminate_all(self) -> None:
        """Terminate whole task process groups, escalating after a short grace."""
        with self._lock:
            processes = list(self._processes.items())

        if not processes:
            return

        log(
            "Stopping active task subprocesses",
            event="shutdown",
            process_count=len(processes),
        )
        for selector, process in processes:
            if process.poll() is not None:
                continue
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except OSError as error:
                log(
                    "Failed to terminate task process group",
                    event="warning",
                    task=selector,
                    pid=process.pid,
                    error=str(error),
                )

        deadline = time.monotonic() + PROCESS_TERMINATION_GRACE_SECONDS
        while time.monotonic() < deadline:
            if all(process.poll() is not None for _, process in processes):
                return
            time.sleep(0.1)

        remaining = [
            (selector, process)
            for selector, process in processes
            if process.poll() is None
        ]
        if remaining:
            log(
                "Force-killing task subprocesses after grace period",
                event="warning",
                process_count=len(remaining),
            )
        for selector, process in remaining:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError as error:
                log(
                    "Failed to kill task process group",
                    event="warning",
                    task=selector,
                    pid=process.pid,
                    error=str(error),
                )


class RunLogger:
    """Serialize launcher output while task subprocesses write to their own files."""

    def __init__(self, run_dir: Path) -> None:
        self._lock = threading.Lock()
        self._text_log = run_dir / "runner.log"
        self._event_log = run_dir / "events.jsonl"

    def log(self, message: str, *, event: str = "info", **fields: object) -> None:
        now = datetime.now(timezone.utc)
        timestamp = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        context = " ".join(f"{key}={value}" for key, value in fields.items())
        line = f"[{timestamp}] {event.upper()}: {message}"
        if context:
            line = f"{line} | {context}"
        record = {"timestamp": timestamp, "event": event, "message": message, **fields}

        # ThreadPoolExecutor workers use this shared lock, so a launcher event
        # is always a complete line in both the terminal and run-level logs.
        with self._lock:
            print(line, flush=True)
            with self._text_log.open("a") as text_log:
                text_log.write(line + "\n")
            with self._event_log.open("a") as event_log:
                event_log.write(json.dumps(record, ensure_ascii=False) + "\n")


_run_logger: RunLogger | None = None


def log(message: str, *, event: str = "info", **fields: object) -> None:
    """Log a launcher event without allowing concurrent workers to interleave it."""
    if _run_logger is None:
        print(f"[{time.strftime('%H:%M:%S')}] {event.upper()}: {message}", flush=True)
        return
    _run_logger.log(message, event=event, **fields)


def parse_selectors(values: list[str]) -> list[str]:
    """Expand numeric ranges and comma lists while preserving task IDs."""
    selectors: list[str] = []
    for value in values:
        for item in value.split(","):
            item = item.strip()
            match = re.fullmatch(r"(\d+)-(\d+)", item)
            if match:
                start, end = map(int, match.groups())
                if end < start:
                    raise ValueError(f"invalid range {item!r}: end is before start")
                selectors.extend(str(index) for index in range(start, end + 1))
            elif item:
                selectors.append(item)

    seen: set[str] = set()
    duplicates = {item for item in selectors if item in seen or seen.add(item)}
    if duplicates:
        raise ValueError(f"duplicate task selectors: {', '.join(sorted(duplicates))}")
    return selectors


def selectors_from_dataset() -> list[str]:
    """Load every task ID; imported lazily so --help needs no HF dependency."""
    from huggingface_hub import hf_hub_download

    path = hf_hub_download(
        "mercor/apex-agents", "tasks_and_rubrics.json", repo_type="dataset"
    )
    with open(path) as handle:
        return [task["task_id"] for task in json.load(handle)]


def validate_ports(base_port: int, count: int) -> None:
    """Fail before starting work if one of the requested ports is occupied."""
    sockets: list[socket.socket] = []
    try:
        for port in range(base_port, base_port + count):
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.bind(("127.0.0.1", port))
            sockets.append(listener)
    except OSError as error:
        raise RuntimeError(f"port {port} is unavailable: {error}") from error
    finally:
        for listener in sockets:
            listener.close()


def build_environment_image(image: str) -> None:
    """Build once so 32 compose projects do not rebuild the same image."""
    log("Building shared environment image", image=image)
    subprocess.run(
        [
            "docker",
            "build",
            "--tag",
            image,
            "--file",
            str(SOURCE_ENVIRONMENT_DIR / "Dockerfile"),
            str(ARCHIPELAGO_DIR),
        ],
        check=True,
    )


def build_proxy_image(image: str) -> None:
    """Build the small runtime-only proxy image once per launcher run."""
    log("Building shared runtime proxy image", image=image)
    subprocess.run(
        [
            "docker",
            "build",
            "--tag",
            image,
            str(EXAMPLE_DIR / "proxy"),
        ],
        check=True,
    )


def compose_project_name(run_id: str, worker: int) -> str:
    slug = re.sub(r"[^a-z0-9_-]", "_", run_id.lower()).strip("_-")
    slug = slug[:40] or uuid.uuid4().hex[:8]
    return f"archipelago_hf_{slug}_w{worker:02d}"


def shared_resource_name(run_id: str, suffix: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]", "_", run_id.lower()).strip("_-")
    slug = slug[:40] or uuid.uuid4().hex[:8]
    return f"archipelago_hf_{slug}_{suffix}"


def allocate_runtime_subnets(count: int) -> list[str]:
    """Allocate small explicit subnets without consuming Docker default pools."""
    cidr = os.environ.get("RUNTIME_NETWORK_CIDR", DEFAULT_RUNTIME_NETWORK_CIDR)
    network = ipaddress.ip_network(cidr)
    if not isinstance(network, ipaddress.IPv4Network):
        raise ValueError("RUNTIME_NETWORK_CIDR must be an IPv4 network")
    if network.prefixlen > RUNTIME_NETWORK_PREFIX:
        raise ValueError(
            f"RUNTIME_NETWORK_CIDR must be /{RUNTIME_NETWORK_PREFIX} or larger"
        )
    capacity = 1 << (RUNTIME_NETWORK_PREFIX - network.prefixlen)
    if count > capacity:
        raise ValueError(
            f"RUNTIME_NETWORK_CIDR {network} provides {capacity} worker networks, "
            f"but {count} are required"
        )
    subnet_size = 1 << (32 - RUNTIME_NETWORK_PREFIX)
    start = int(network.network_address)
    return [
        str(ipaddress.ip_network((start + index * subnet_size, RUNTIME_NETWORK_PREFIX)))
        for index in range(count)
    ]


def write_shared_proxy(
    run_dir: Path, proxy_image: str, runtime_networks: list[tuple[str, str]]
) -> Path:
    """Write the one Squid service shared by every worker in this run."""
    proxy_dir = run_dir / "proxy"
    proxy_dir.mkdir(parents=True)
    service_networks = "\n".join(
        f"""      runtime_{index:02d}:
        aliases:
          - squid"""
        for index in range(len(runtime_networks))
    )
    network_definitions = "\n".join(
        f"""  runtime_{index:02d}:
    name: {json.dumps(network)}
    internal: true
    attachable: true
    ipam:
      config:
        - subnet: {json.dumps(subnet)}"""
        for index, (network, subnet) in enumerate(runtime_networks)
    )
    compose = f"""services:
  squid:
    image: {json.dumps(proxy_image)}
    pull_policy: never
    networks:
      egress:
        gw_priority: 1
{service_networks}
    healthcheck:
      test: ["CMD-SHELL", "squidclient -h 127.0.0.1 -p 3128 mgr:info >/dev/null 2>&1"]
      interval: 2s
      timeout: 2s
      retries: 15
      start_period: 2s

networks:
  egress: {{}}
{network_definitions}
"""
    (proxy_dir / "docker-compose.yml").write_text(compose)
    return proxy_dir


def start_shared_proxy(proxy_dir: Path, environment: dict[str, str]) -> None:
    subprocess.run(
        ["docker", "compose", "up", "-d", "--wait", "--wait-timeout", "60"],
        cwd=proxy_dir,
        env=environment,
        check=True,
    )


def cleanup_shared_proxy(proxy_dir: Path, environment: dict[str, str]) -> None:
    cleanup_compose_project(proxy_dir, environment, resource="shared proxy")


def write_worker_environment(
    worker_dir: Path,
    port: int,
    image: str,
    proxy_image: str,
    runtime_network: str,
) -> None:
    """Create one worker attached only to the run-scoped internal network."""
    worker_dir.mkdir(parents=True, exist_ok=True)

    source_env = SOURCE_ENVIRONMENT_DIR / ".env"
    source_env_example = SOURCE_ENVIRONMENT_DIR / ".env.example"
    if source_env.exists():
        shutil.copy2(source_env, worker_dir / ".env")
    elif source_env_example.exists():
        shutil.copy2(source_env_example, worker_dir / ".env")
    else:
        (worker_dir / ".env").touch()

    no_proxy = os.environ.get(
        "SQUID_NO_PROXY",
        f"localhost,127.0.0.1,environment,{AGENT_HELP_DOMAIN}",
    )

    # There is deliberately no container_name. COMPOSE_PROJECT_NAME supplies a
    # unique name, and each service maps a different host port to container 8080.
    # The per-worker named volume makes the environment and its local agent-help
    # collector see the same /.apps_data contents.
    compose = f'''services:
  environment:
    image: {json.dumps(image)}
    pull_policy: never
    ports:
      - "127.0.0.1:{port}:8080"
    volumes:
      - apps_data:/.apps_data
    networks:
      - runtime
    environment:
      HTTP_PROXY: {json.dumps(RUNTIME_PROXY_URL)}
      HTTPS_PROXY: {json.dumps(RUNTIME_PROXY_URL)}
      NO_PROXY: {json.dumps(no_proxy)}
      http_proxy: {json.dumps(RUNTIME_PROXY_URL)}
      https_proxy: {json.dumps(RUNTIME_PROXY_URL)}
      no_proxy: {json.dumps(no_proxy)}
    env_file:
      - .env
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s

  agent_help:
    image: {json.dumps(proxy_image)}
    pull_policy: never
    command: ["python3", "/opt/archipelago/collector.py"]
    environment:
      AGENT_HELP_CAPTURE_FILE: /capture/agent_help/requests.jsonl
    volumes:
      - apps_data:/capture
    networks:
      runtime:
        aliases:
          - {AGENT_HELP_DOMAIN}

networks:
  runtime:
    external: true
    name: {json.dumps(runtime_network)}

volumes:
  apps_data:
'''
    (worker_dir / "docker-compose.yml").write_text(compose)


def cleanup_environment(worker_dir: Path, environment: dict[str, str]) -> None:
    cleanup_compose_project(worker_dir, environment, resource=worker_dir.name)


def cleanup_compose_project(
    project_dir: Path, environment: dict[str, str], *, resource: str
) -> None:
    """Bring down a Compose project without allowing cleanup to hang forever."""
    command = ["docker", "compose", "down", "-v", "--remove-orphans"]
    try:
        completed = subprocess.run(
            command,
            cwd=project_dir,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=COMPOSE_CLEANUP_TIMEOUT_SECONDS,
        )
        if completed.returncode != 0:
            log(
                "Docker Compose cleanup failed",
                event="warning",
                resource=resource,
                returncode=completed.returncode,
            )
    except subprocess.TimeoutExpired:
        log(
            "Docker Compose cleanup timed out",
            event="warning",
            resource=resource,
            timeout_seconds=COMPOSE_CLEANUP_TIMEOUT_SECONDS,
        )
    except OSError as error:
        log(
            "Docker Compose cleanup could not start",
            event="warning",
            resource=resource,
            error=str(error),
        )


def safe_log_name(selector: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", selector)[:120] or "task"


def update_score_summary(run_dir: Path) -> dict[str, object]:
    """Atomically refresh run-level scores from every available grades.json."""
    task_scores: list[dict[str, object]] = []
    for grades_file in sorted((run_dir / "tasks").glob("*/grades.json")):
        try:
            grades = json.loads(grades_file.read_text())
            final_score = grades["scoring_results"]["final_score"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            # Another task may still be writing its file. Its own completion
            # event will trigger another full scan after the file is complete.
            continue

        if (
            isinstance(final_score, bool)
            or not isinstance(final_score, (int, float))
            or not math.isfinite(final_score)
        ):
            continue

        score = float(final_score)
        task_scores.append(
            {
                "task_id": grades_file.parent.name,
                "final_score": score,
                "passed_at_1": score == 1.0,
                "grades_file": str(grades_file.relative_to(run_dir)),
            }
        )

    task_count = len(task_scores)
    pass_at_1_count = sum(bool(task["passed_at_1"]) for task in task_scores)
    summary: dict[str, object] = {
        "updated_at": datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "completed_task_count": task_count,
        "average_mean_score": (
            sum(float(task["final_score"]) for task in task_scores) / task_count
            if task_count
            else 0.0
        ),
        "average_pass_at_1_percent": pass_at_1_count / task_count if task_count else 0.0,
        "pass_at_1_count": pass_at_1_count,
        "tasks": task_scores,
    }

    summary_file = run_dir / SCORE_SUMMARY_FILENAME
    temporary_file = summary_file.with_name(summary_file.name + ".tmp")
    temporary_file.write_text(json.dumps(summary, indent=2) + "\n")
    temporary_file.replace(summary_file)
    return summary


def run_task(
    selector: str,
    slot: WorkerSlot,
    run_dir: Path,
    image: str,
    proxy_image: str,
    keep_environments: bool,
    skip_grading: bool,
    runtime_network: str,
    stop_requested: threading.Event,
    active_processes: ActiveProcesses,
) -> TaskResult:
    """Invoke the unchanged single-task main.py in one isolated environment."""
    started = time.monotonic()
    worker_dir = run_dir / "environments" / f"worker-{slot.number:02d}"
    log_file = run_dir / "logs" / (
        f"worker-{slot.number:02d}_{safe_log_name(selector)}.log"
    )
    write_worker_environment(
        worker_dir, slot.port, image, proxy_image, runtime_network
    )

    environment = os.environ.copy()
    environment.update(
        {
            "EXAMPLE_DIR": str(EXAMPLE_DIR),
            "ARCHIPELAGO_DIR": str(ARCHIPELAGO_DIR),
            "AGENTS_DIR": str(AGENTS_DIR),
            "ENVIRONMENT_DIR": str(worker_dir),
            "ENV_URL": f"http://127.0.0.1:{slot.port}",
            # Docker may ignore published ports for containers attached only to
            # an internal network. main.py resolves and uses this network's
            # container IP after Compose starts the environment.
            "ENV_CONTAINER_NETWORK": runtime_network,
            # Keep all task artifacts under this concurrent run rather than
            # reusing output/<task_id>/ across separate runs.
            "TASK_OUTPUT_ROOT": str(run_dir / "tasks"),
            "COMPOSE_PROJECT_NAME": compose_project_name(
                run_dir.name, slot.number
            ),
        }
    )

    returncode = 1
    error_message: str | None = None
    try:
        if stop_requested.is_set():
            return TaskResult(
                selector=selector,
                worker=slot.number,
                port=slot.port,
                returncode=130,
                log_file=str(log_file),
                elapsed_seconds=round(time.monotonic() - started, 1),
                error="Run interrupted before task subprocess started",
            )
        command = [
            "uv",
            "run",
            "python",
            str(EXAMPLE_DIR / "main.py"),
            selector,
        ]
        if skip_grading:
            command.append("--skip-grading")
        with open(log_file, "w") as output:
            process = subprocess.Popen(
                command,
                cwd=AGENTS_DIR,
                env=environment,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            active_processes.add(selector, process)
            try:
                returncode = process.wait()
            finally:
                active_processes.remove(selector, process)
    except Exception as error:  # Preserve other tasks and record launcher errors.
        error_message = f"{type(error).__name__}: {error}"
    finally:
        if not keep_environments:
            cleanup_environment(worker_dir, environment)

    return TaskResult(
        selector=selector,
        worker=slot.number,
        port=slot.port,
        returncode=returncode,
        log_file=str(log_file),
        elapsed_seconds=round(time.monotonic() - started, 1),
        error=error_message,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "selectors",
        nargs="*",
        help="Task IDs, indices, comma lists, or numeric ranges (for example 0-31).",
    )
    parser.add_argument("--all", action="store_true", help="Queue every dataset task.")
    parser.add_argument(
        "--concurrency", type=int, default=32, help="Maximum running tasks (default: 32)."
    )
    parser.add_argument(
        "--base-port", type=int, default=18080, help="First environment host port."
    )
    parser.add_argument(
        "--environment-image", default=DEFAULT_IMAGE, help="Shared Docker image tag."
    )
    parser.add_argument(
        "--proxy-image", default=DEFAULT_PROXY_IMAGE, help="Shared runtime proxy image tag."
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Use already-built environment and proxy images.",
    )
    parser.add_argument(
        "--skip-grading",
        action="store_true",
        help="Skip grading for completed tasks and record a default score of 0.",
    )
    parser.add_argument("--run-id", help="Run output directory name.")
    parser.add_argument(
        "--keep-environments",
        action="store_true",
        help="Keep the last container in each worker slot for debugging.",
    )
    args = parser.parse_args()

    if args.concurrency < 1:
        parser.error("--concurrency must be at least 1")
    if not 1 <= args.base_port <= 65536 - args.concurrency:
        parser.error("--base-port leaves insufficient valid ports")
    if args.all and args.selectors:
        parser.error("use either selectors or --all, not both")

    try:
        selectors = selectors_from_dataset() if args.all else parse_selectors(args.selectors)
    except ValueError as error:
        parser.error(str(error))
    if not selectors:
        parser.error("provide selectors (for example 0-31) or use --all")

    worker_count = min(args.concurrency, len(selectors))
    try:
        runtime_subnets = allocate_runtime_subnets(worker_count)
    except ValueError as error:
        parser.error(str(error))
    try:
        validate_ports(args.base_port, worker_count)
    except RuntimeError as error:
        parser.error(str(error))

    run_id = args.run_id or time.strftime("run_%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", run_id):
        parser.error("--run-id may contain only letters, digits, _, -, and .")
    run_dir = EXAMPLE_DIR / "output" / "concurrent" / run_id
    (run_dir / "logs").mkdir(parents=True, exist_ok=False)
    global _run_logger
    _run_logger = RunLogger(run_dir)
    update_score_summary(run_dir)

    if not args.skip_build:
        try:
            build_environment_image(args.environment_image)
            build_proxy_image(args.proxy_image)
        except (OSError, subprocess.CalledProcessError) as error:
            log("Failed to build run images", event="error", error=str(error))
            return 1

    runtime_networks = [
        (shared_resource_name(run_id, f"runtime_{number:02d}"), runtime_subnets[number])
        for number in range(worker_count)
    ]
    proxy_dir = write_shared_proxy(run_dir, args.proxy_image, runtime_networks)
    proxy_environment = os.environ.copy()
    proxy_environment["COMPOSE_PROJECT_NAME"] = shared_resource_name(run_id, "proxy")
    try:
        start_shared_proxy(proxy_dir, proxy_environment)
    except (OSError, subprocess.CalledProcessError) as error:
        cleanup_shared_proxy(proxy_dir, proxy_environment)
        log("Failed to start shared runtime proxy", event="error", error=str(error))
        return 1

    available_slots: queue.Queue[WorkerSlot] = queue.Queue()
    for number in range(worker_count):
        available_slots.put(WorkerSlot(number, args.base_port + number))

    stop_requested = threading.Event()
    active_processes = ActiveProcesses()

    def scheduled_task(selector: str) -> TaskResult:
        if stop_requested.is_set():
            raise concurrent.futures.CancelledError()
        slot = available_slots.get()
        try:
            if stop_requested.is_set():
                raise concurrent.futures.CancelledError()
            log(
                "Task started",
                event="task_started",
                task=selector,
                worker=slot.number,
                port=slot.port,
            )
            return run_task(
                selector,
                slot,
                run_dir,
                args.environment_image,
                args.proxy_image,
                args.keep_environments,
                args.skip_grading,
                runtime_networks[slot.number][0],
                stop_requested,
                active_processes,
            )
        finally:
            available_slots.put(slot)

    log(
        "Run started",
        event="run_started",
        task_count=len(selectors),
        concurrency=worker_count,
        runtime_proxy=RUNTIME_PROXY_URL,
        runtime_network_count=len(runtime_networks),
    )
    log("Run files", run_dir=str(run_dir))
    results: list[TaskResult] = []
    interrupted = False
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=worker_count)
    pending: dict[concurrent.futures.Future[TaskResult], str] = {}
    selectors_to_start = iter(selectors)

    def submit_next() -> bool:
        if stop_requested.is_set():
            return False
        try:
            selector = next(selectors_to_start)
        except StopIteration:
            return False
        pending[executor.submit(scheduled_task, selector)] = selector
        return True

    def record_result(result: TaskResult) -> None:
        results.append(result)
        score_summary = update_score_summary(run_dir)
        log(
            "Task finished",
            event="task_finished" if result.returncode == 0 else "task_failed",
            task=result.selector,
            worker=result.worker,
            port=result.port,
            returncode=result.returncode,
            elapsed_seconds=result.elapsed_seconds,
            log_file=result.log_file,
            error=result.error,
            completed_task_count=score_summary["completed_task_count"],
            average_mean_score=score_summary["average_mean_score"],
            average_pass_at_1_percent=score_summary[
                "average_pass_at_1_percent"
            ],
            score_summary_file=str(run_dir / SCORE_SUMMARY_FILENAME),
        )

    try:
        for _ in range(worker_count):
            if not submit_next():
                break

        while pending:
            done, _ = concurrent.futures.wait(
                pending, return_when=concurrent.futures.FIRST_COMPLETED
            )
            for future in done:
                pending.pop(future)
                try:
                    record_result(future.result())
                except concurrent.futures.CancelledError:
                    pass
                if not stop_requested.is_set():
                    submit_next()
    except KeyboardInterrupt:
        interrupted = True
        stop_requested.set()
        # Further Ctrl-C signals must not interrupt worker and Compose cleanup.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        log(
            "Interrupt received; stopping new tasks and cleaning up",
            event="shutdown",
            active_task_count=len(pending),
        )
        for future in pending:
            future.cancel()
        active_processes.terminate_all()
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
        # Collect task results that completed while shutdown was in progress.
        for future in list(pending):
            if future.cancelled() or not future.done():
                continue
            try:
                record_result(future.result())
            except concurrent.futures.CancelledError:
                pass

        if interrupted and not args.keep_environments:
            log("Verifying worker Compose cleanup", event="shutdown")
            for slot_number in range(worker_count):
                worker_dir = run_dir / "environments" / f"worker-{slot_number:02d}"
                if not worker_dir.exists():
                    continue
                worker_environment = os.environ.copy()
                worker_environment["COMPOSE_PROJECT_NAME"] = compose_project_name(
                    run_dir.name, slot_number
                )
                cleanup_environment(worker_dir, worker_environment)
        if not args.keep_environments:
            cleanup_shared_proxy(proxy_dir, proxy_environment)

    order = {selector: index for index, selector in enumerate(selectors)}
    results.sort(key=lambda item: order[item.selector])
    failed = [result for result in results if result.returncode != 0]
    manifest = {
        "run_id": run_id,
        "requested_concurrency": args.concurrency,
        "worker_count": worker_count,
        "environment_image": args.environment_image,
        "proxy_image": args.proxy_image,
        "skip_grading": args.skip_grading,
        "interrupted": interrupted,
        "requested_task_count": len(selectors),
        "finished_task_count": len(results),
        "runtime_networks": [
            {"name": name, "subnet": subnet} for name, subnet in runtime_networks
        ],
        "results": [asdict(result) for result in results],
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    log(
        "Run interrupted" if interrupted else "Run finished",
        event="run_interrupted" if interrupted else "run_finished",
        succeeded=len(results) - len(failed),
        failed=len(failed),
        unfinished=len(selectors) - len(results),
        manifest=str(run_dir / "manifest.json"),
    )
    if interrupted:
        return 130
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
