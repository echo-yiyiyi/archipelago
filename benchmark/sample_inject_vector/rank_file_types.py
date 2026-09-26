#!/usr/bin/env python3
"""Rank all seven candidate source file types for each selected task."""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

try:
    from ..utils.azure_openai import build_client, responses_json
    from .file_type_prompt import build_file_type_ranking_prompt
except ImportError:  # Support direct execution from the repository root.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from file_type_prompt import build_file_type_ranking_prompt
    from utils.azure_openai import build_client, responses_json


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = (
    SCRIPT_DIR.parent
    / "extract_key_words"
    / "output"
    / "selected_15_keywords_extraction.json"
)
DEFAULT_OUTPUT = SCRIPT_DIR / "output" / "selected_15_tasks_with_file_type_ranking.json"
DEFAULT_MODEL = "aoai-swedencentral-aii-02-gpt-5.4"
ALLOWED_FILE_TYPES = ("md", "xlsx", "html", "txt", "chat", "email", "calendar")
FILE_TYPE_SCHEMA = {
    "type": "object",
    "properties": {
        "file_types": {
            "type": "array",
            "items": {"type": "string", "enum": list(ALLOWED_FILE_TYPES)},
            "minItems": len(ALLOWED_FILE_TYPES),
            "maxItems": len(ALLOWED_FILE_TYPES),
        }
    },
    "required": ["file_types"],
    "additionalProperties": False,
}


def load_tasks(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"input JSON does not exist: {path}")
    tasks = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(tasks, list):
        raise ValueError("input JSON must contain a top-level array")
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("every task must be a JSON object")
        if not isinstance(task.get("task_id"), str) or not task["task_id"]:
            raise ValueError("every task must have a non-empty string task_id")
        keywords = task.get("keywords")
        if (
            not isinstance(keywords, list)
            or not keywords
            or any(
                not isinstance(keyword, str) or not keyword.strip()
                for keyword in keywords
            )
        ):
            raise ValueError(f"task {task['task_id']} has no usable keywords")
    if len({task["task_id"] for task in tasks}) != len(tasks):
        raise ValueError("task_id values must be unique")
    return tasks


def validate_file_types(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) != len(ALLOWED_FILE_TYPES):
        raise ValueError("file_types must contain exactly seven values")
    if any(item not in ALLOWED_FILE_TYPES for item in value):
        raise ValueError("file_types contains an unsupported value")
    if len(set(value)) != len(ALLOWED_FILE_TYPES):
        raise ValueError("file_types must contain all seven values exactly once")
    return value


def rank_one(
    task: dict[str, Any],
    *,
    client: Any,
    model: str,
    reasoning_effort: str | None,
    retries: int,
    retry_delay: float,
) -> list[str]:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            payload = responses_json(
                client=client,
                prompt=build_file_type_ranking_prompt(task["keywords"]),
                schema_name="task_file_type_ranking",
                schema=FILE_TYPE_SCHEMA,
                model=model,
                reasoning_effort=reasoning_effort,
            )
            if not isinstance(payload, dict):
                raise ValueError("model output must be a JSON object")
            return validate_file_types(payload.get("file_types"))
        except Exception as error:
            last_error = error
            if attempt < retries:
                time.sleep(retry_delay * (2**attempt))
    assert last_error is not None
    raise last_error


def build_output(
    tasks: list[dict[str, Any]], rankings: dict[str, list[str]]
) -> list[dict[str, Any]]:
    return [
        {**task, "file_type_ranking": rankings.get(task["task_id"])}
        for task in tasks
    ]


def load_existing_rankings(path: Path) -> dict[str, list[str]]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return {}
    rankings = {}
    for row in data:
        if not isinstance(row, dict) or not isinstance(row.get("task_id"), str):
            continue
        try:
            rankings[row["task_id"]] = validate_file_types(
                row.get("file_type_ranking")
            )
        except ValueError:
            continue
    return rankings


def atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--reasoning-effort")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--retry-delay", type=float, default=2.0)
    parser.add_argument("--fresh", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.workers < 1:
        raise ValueError("workers must be at least 1")
    if args.retries < 0 or args.retry_delay < 0:
        raise ValueError("retries and retry-delay must be non-negative")

    tasks = load_tasks(args.input.resolve())
    output_path = args.output.resolve()
    rankings = {} if args.fresh else load_existing_rankings(output_path)
    task_ids = {task["task_id"] for task in tasks}
    rankings = {
        task_id: ranking
        for task_id, ranking in rankings.items()
        if task_id in task_ids
    }
    pending = [task for task in tasks if task["task_id"] not in rankings]
    errors: dict[str, str] = {}

    if pending:
        client = build_client()
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(
                    rank_one,
                    task,
                    client=client,
                    model=args.model,
                    reasoning_effort=args.reasoning_effort,
                    retries=args.retries,
                    retry_delay=args.retry_delay,
                ): task
                for task in pending
            }
            for future in as_completed(futures):
                task = futures[future]
                try:
                    rankings[task["task_id"]] = future.result()
                except Exception as error:
                    errors[task["task_id"]] = f"{type(error).__name__}: {error}"
                atomic_write(output_path, build_output(tasks, rankings))

    atomic_write(output_path, build_output(tasks, rankings))
    print(
        f"Processed {len(tasks)} tasks: completed={len(rankings)}, "
        f"errors={len(errors)}; output={output_path}"
    )
    for task_id, error in errors.items():
        print(f"ERROR {task_id}: {error}", file=sys.stderr)
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
