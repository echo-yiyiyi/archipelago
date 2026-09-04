#!/usr/bin/env python3
"""Create an isolated selected-six fixture set with generic carrier names."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE = (
    ROOT / "generate_attack_config/output/selected_6_with_attack_config.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / "generate_attack_config/tmp/selected_6_generic_filename/selected_6_generic_filename.json"
)
GENERIC_NAMES = {
    "py": "calculate_final_result.py",
    "pyc": "calculate_final_result.pyc",
    "elf": "calculate_final_result",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def prepare(
    source: Path,
    output: Path,
    expected_count: int = 6,
    carrier_root: Path | None = None,
) -> list[dict]:
    source = source.resolve()
    output = output.resolve()
    records = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(records, list) or len(records) != expected_count:
        raise ValueError(f"source must contain exactly {expected_count} task records")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)

    prepared: list[dict] = []
    for original in records:
        record = json.loads(json.dumps(original))
        vector = str(record.get("inject_vector", "")).lower().lstrip(".")
        generic_name = GENERIC_NAMES.get(vector)
        if generic_name is None:
            raise ValueError(f"unsupported selected-six inject_vector: {vector!r}")

        harmful_task_id = record.get("harmful_task_id")
        attack_file = record.get("attack_file")
        populate_files = record.get("populate_files")
        if not isinstance(harmful_task_id, str) or not harmful_task_id:
            raise ValueError("record is missing harmful_task_id")
        if Path(harmful_task_id).name != harmful_task_id:
            raise ValueError(f"unsafe harmful_task_id: {harmful_task_id!r}")
        if not isinstance(attack_file, str) or not attack_file:
            raise ValueError(f"{harmful_task_id} is missing attack_file")
        if not isinstance(populate_files, list) or attack_file not in populate_files:
            raise ValueError(f"{harmful_task_id} has inconsistent populate_files")

        task_dir = output.parent / harmful_task_id
        if task_dir.exists():
            shutil.rmtree(task_dir)
        task_dir.mkdir(parents=True)
        path_map: dict[str, str] = {}
        for relative in populate_files:
            if not isinstance(relative, str):
                raise ValueError(f"{harmful_task_id} has a non-string populate path")
            if relative == attack_file and carrier_root is not None:
                suffix = ".py" if vector == "py" else ".pyc" if vector == "pyc" else ""
                source_file = carrier_root / vector / f"{record['inject_goal']}{suffix}"
            else:
                source_file = source.parent / relative
            if not source_file.is_file():
                raise FileNotFoundError(source_file)
            if relative == attack_file:
                destination = task_dir / generic_name
            else:
                destination = output.parent / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, destination)
            path_map[relative] = destination.relative_to(output.parent).as_posix()

        record["attack_file"] = path_map[attack_file]
        record["populate_files"] = [path_map[path] for path in populate_files]
        attack_config = record.get("attack_config")
        if isinstance(attack_config, dict):
            for key, value in list(attack_config.items()):
                if isinstance(value, str) and value in path_map:
                    attack_config[key] = path_map[value]
        prepared.append(record)

    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(prepared, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    return prepared


def main() -> int:
    args = parse_args()
    records = prepare(args.source, args.output)
    print(args.output.resolve())
    print(f"prepared {len(records)} tasks with generic attack filenames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
