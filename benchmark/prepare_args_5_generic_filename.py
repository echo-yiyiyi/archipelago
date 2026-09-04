#!/usr/bin/env python3
"""Create an isolated five-task args fixture set with a generic carrier name."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from prepare_selected_6_generic_filename import prepare

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from benchmark.generate_attack_config.generate import write_runtime_argument_artifact


ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE = (
    ROOT / "generate_attack_config/output/args_user_prompt_v3_backup_20260903_2041/args_tasks.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / "generate_attack_config/tmp/args_5_generic_filename/args_5_generic_filename.json"
)
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    records = prepare(args.source, args.output, expected_count=5)
    for record in records:
        destination = args.output.parent / record["attack_file"]
        write_runtime_argument_artifact(
            record,
            destination,
            str(record["inject_vector"]).lower().lstrip("."),
        )
    print(args.output.resolve())
    print(f"prepared {len(records)} args tasks with generic attack filenames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
