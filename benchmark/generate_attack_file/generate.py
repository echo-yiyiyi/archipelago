"""End-to-end GPT-5.4 fixture generator.

This script makes a live API request only when executed directly. The local
fake-response test does not import or call this module.
"""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    from .api import generate_payload
    from .templates import generate_file
except ImportError:  # Support direct execution from the repository root.
    from api import generate_payload
    from templates import generate_file


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
