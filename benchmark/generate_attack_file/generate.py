"""End-to-end GPT-5.4 fixture generator.

This script makes a live API request only when executed directly. The local
fake-response test does not import or call this module.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

try:
    from .api import generate_payload
    from .templates import generate_file
except ImportError:  # Support direct execution from the repository root.
    from api import generate_payload
    from templates import generate_file


def generate_from_task_record(
    task_record: dict[str, Any],
    output_dir: str | Path,
    *,
    client: Any | None = None,
    reasoning_effort: str | None = None,
) -> Path:
    """Generate the fixture selected by a task record and its attack config.

    Task JSON uses ``keywords`` (with ``task_keywords`` accepted for older
    records), while the fixture renderer consumes the structured payload
    returned by ``generate_payload``.  The attack-config COT is inserted into
    formats that support embedded injection content.
    """
    if not isinstance(task_record, dict):
        raise TypeError("task_record must be a JSON object")
    file_type = task_record.get("inject_vector")
    if not isinstance(file_type, str) or not file_type.strip():
        raise ValueError("task_record must contain a non-empty inject_vector")
    file_type = file_type.strip().lower().lstrip(".")
    from ..generate_attack_config.prompt.common import uses_generic_identifiers, GENERIC_TASK_CONTEXT
    keywords = ([GENERIC_TASK_CONTEXT] if uses_generic_identifiers(task_record)
                else task_record.get("keywords", task_record.get("task_keywords")))
    if not isinstance(keywords, list) or not keywords or not all(
        isinstance(keyword, str) and keyword.strip() for keyword in keywords
    ):
        raise ValueError("task_record must contain a non-empty keywords array")

    attack_config = task_record.get("attack_config") or {}
    if not isinstance(attack_config, dict):
        raise ValueError("attack_config must be a JSON object when provided")
    injection_content = attack_config.get("cot")
    if injection_content is not None and not isinstance(injection_content, str):
        raise ValueError("attack_config.cot must be a string when provided")
    if file_type in {"py", "pyc", "elf"}:
        injection_content = None

    payload = generate_payload(
        file_type,
        keywords,
        client=client,
        reasoning_effort=reasoning_effort,
    )
    return generate_file(
        file_type,
        payload,
        output_dir,
        injection_content=injection_content,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate one fixture using GPT-5.4 structured output."
    )
    parser.add_argument(
        "file_type",
        choices=("html", "md", "xlsx", "txt", "chat", "email", "calendar", "py", "pyc", "elf"),
    )
    parser.add_argument(
        "keywords",
        nargs="+",
        help="Task keywords passed to GPT-5.4.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "output",
    )
    parser.add_argument(
        "--injection-content",
        default=None,
        help="Optional inner text wrapped in <think> by the template layer.",
    )
    parser.add_argument(
        "--reasoning-effort",
        default=None,
        help="Optional fixed reasoning effort; omit to let GPT-5.4 choose.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = generate_payload(
        args.file_type,
        args.keywords,
        reasoning_effort=args.reasoning_effort,
    )
    path = generate_file(
        args.file_type,
        payload,
        args.output_dir,
        injection_content=args.injection_content,
    )
    print(path)


if __name__ == "__main__":
    main()
