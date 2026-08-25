#!/usr/bin/env python3
"""Extract task keywords from mercor/apex-agents task prompts."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from ..utils.azure_openai import build_client, responses_json
    from .prompt import build_keyword_extraction_prompt
except ImportError:  # Support direct execution from repository root.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from utils.azure_openai import build_client, responses_json
    from prompt import build_keyword_extraction_prompt


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = SCRIPT_DIR / "output" / "keywords.json"
KEYWORD_SCHEMA = {
    "type": "object",
    "properties": {
        "keywords": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 3,
            "maxItems": 4,
        }
    },
    "required": ["keywords"],
    "additionalProperties": False,
}


@dataclass
class KeywordRecord:
    task_id: str
    domain: str | None
    task_name: str | None
    keywords: list[str] | None
    status: str
    error: str | None = None
    attempts: int = 0
    updated_at: str | None = None


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def find_tasks_json(explicit: Path | None) -> Path:
    if explicit:
        if not explicit.is_file():
            raise FileNotFoundError(f"tasks JSON does not exist: {explicit}")
        return explicit.resolve()
    roots = []
    import os

    if os.environ.get("HF_HUB_CACHE"):
        roots.append(Path(os.environ["HF_HUB_CACHE"]))
    if os.environ.get("HF_HOME"):
        roots.append(Path(os.environ["HF_HOME"]) / "hub")
    roots.append(Path.home() / ".cache/huggingface/hub")
    matches = []
    for root in roots:
        matches.extend(root.glob("datasets--mercor--apex-agents/snapshots/*/tasks_and_rubrics.json"))
    if not matches:
        raise FileNotFoundError(
            "Could not find tasks_and_rubrics.json; pass --tasks-json explicitly."
        )
    return max(matches, key=lambda path: path.stat().st_mtime).resolve()


def load_tasks(path: Path, task_ids: set[str] | None = None) -> list[dict[str, Any]]:
    tasks = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(tasks, list):
        raise ValueError("tasks JSON must contain an array")
    selected = []
    for task in tasks:
        task_id = task.get("task_id") if isinstance(task, dict) else None
        if not isinstance(task_id, str):
            continue
        if task_ids is None or task_id in task_ids:
            selected.append(task)
    if task_ids and len(selected) != len(task_ids):
        missing = sorted(task_ids - {task["task_id"] for task in selected})
        raise ValueError(f"unknown task IDs: {', '.join(missing)}")
    return selected


def validate_keywords(value: Any) -> list[str]:
    if not isinstance(value, list) or not 3 <= len(value) <= 4:
        raise ValueError("model output must be an array of exactly 3 or 4 strings")
    cleaned: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("every keyword must be a non-empty string")
        keyword = " ".join(item.split())
        if keyword.casefold() not in {existing.casefold() for existing in cleaned}:
            cleaned.append(keyword)
    if not 3 <= len(cleaned) <= 4:
        raise ValueError("keyword output must contain 3 or 4 distinct strings")
    return cleaned


def extract_one(
    task: dict[str, Any],
    *,
    client: Any,
    model: str | None,
    reasoning_effort: str | None,
    retries: int,
    retry_delay: float,
) -> KeywordRecord:
    task_id = task["task_id"]
    prompt = task.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return KeywordRecord(task_id, task.get("domain"), task.get("task_name"), None, "error", "missing prompt")
    last_error = "unknown error"
    for attempt in range(1, retries + 2):
        try:
            raw = responses_json(
                client=client,
                prompt=build_keyword_extraction_prompt(prompt),
                schema_name="task_keywords",
                schema=KEYWORD_SCHEMA,
                model=model,
                reasoning_effort=reasoning_effort,
            )
            if isinstance(raw, dict):
                raw = raw.get("keywords")
            keywords = validate_keywords(raw)
            return KeywordRecord(task_id, task.get("domain"), task.get("task_name"), keywords, "completed", attempts=attempt, updated_at=now())
        except Exception as error:  # Keep one bad task from losing the batch.
            last_error = f"{type(error).__name__}: {error}"
            if attempt <= retries:
                time.sleep(retry_delay * (2 ** (attempt - 1)))
    return KeywordRecord(task_id, task.get("domain"), task.get("task_name"), None, "error", last_error, retries + 1, now())


def atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_csv(path: Path, records: list[KeywordRecord]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(records[0])) if records else ["task_id"])
        writer.writeheader()
        writer.writerows(asdict(record) for record in records)
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    prompt_group = parser.add_mutually_exclusive_group()
    prompt_group.add_argument("--prompt", help="Extract keywords from one prompt string.")
    prompt_group.add_argument("--prompt-file", type=Path, help="Read one prompt from a UTF-8 text file.")
    parser.add_argument("--tasks-json", type=Path)
    parser.add_argument("--task-id", action="append", dest="task_ids")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--retry-delay", type=float, default=2.0)
    parser.add_argument("--model")
    parser.add_argument("--reasoning-effort")
    parser.add_argument("--dry-run", action="store_true", help="Validate and write task inventory without API calls.")
    parser.add_argument("--fresh", action="store_true", help="Ignore an existing output file.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.workers < 1 or args.retries < 0 or args.retry_delay < 0:
        raise ValueError("workers/retries must be non-negative, and workers must be >= 1")
    if args.prompt is not None or args.prompt_file is not None:
        if args.task_ids or args.tasks_json:
            raise ValueError("--prompt/--prompt-file cannot be combined with --task-id or --tasks-json")
        prompt = args.prompt
        if args.prompt_file is not None:
            if not args.prompt_file.is_file():
                raise FileNotFoundError(f"prompt file does not exist: {args.prompt_file}")
            prompt = args.prompt_file.read_text(encoding="utf-8")
        if not prompt or not prompt.strip():
            raise ValueError("prompt must not be empty")
        tasks_path = None
        tasks = [{"task_id": "custom_prompt", "domain": None, "task_name": "Custom prompt", "prompt": prompt}]
    else:
        tasks_path = find_tasks_json(args.tasks_json)
        tasks = load_tasks(tasks_path, set(args.task_ids) if args.task_ids else None)
    if args.limit is not None:
        if args.limit < 0:
            raise ValueError("--limit must be non-negative")
        tasks = tasks[: args.limit]

    report_path = args.output.resolve()
    csv_path = report_path.with_suffix(".csv")
    existing: dict[str, dict[str, Any]] = {}
    if report_path.is_file() and not args.fresh:
        data = json.loads(report_path.read_text(encoding="utf-8"))
        existing = {row["task_id"]: row for row in data.get("records", []) if isinstance(row, dict) and row.get("task_id")}
    records = [KeywordRecord(**existing[task["task_id"]]) for task in tasks if task["task_id"] in existing and existing[task["task_id"]].get("status") == "completed"]
    done = {record.task_id for record in records}
    pending = [task for task in tasks if task["task_id"] not in done]
    if args.dry_run:
        records.extend(KeywordRecord(task["task_id"], task.get("domain"), task.get("task_name"), None, "pending") for task in pending)
    elif pending:
        client = build_client()
        lock = threading.Lock()
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [executor.submit(extract_one, task, client=client, model=args.model, reasoning_effort=args.reasoning_effort, retries=args.retries, retry_delay=args.retry_delay) for task in pending]
            for future in as_completed(futures):
                result = future.result()
                records.append(result)
                ordered = sorted(records, key=lambda record: next((i for i, task in enumerate(tasks) if task["task_id"] == record.task_id), len(tasks)))
                payload = {
                    "generated_at": now(),
                    "tasks_json": str(tasks_path) if tasks_path else None,
                    "records": [asdict(record) for record in ordered],
                }
                with lock:
                    atomic_write(report_path, payload)
                    write_csv(csv_path, ordered)
    records.sort(key=lambda record: next((i for i, task in enumerate(tasks) if task["task_id"] == record.task_id), len(tasks)))
    payload = {"generated_at": now(), "tasks_json": str(tasks_path) if tasks_path else None, "records": [asdict(record) for record in records]}
    atomic_write(report_path, payload)
    write_csv(csv_path, records)
    completed = sum(record.status == "completed" for record in records)
    errors = sum(record.status == "error" for record in records)
    print(f"Processed {len(records)} tasks: completed={completed}, errors={errors}; output={report_path}")
    return 0 if not errors else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
