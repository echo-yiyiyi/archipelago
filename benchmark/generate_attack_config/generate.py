#!/usr/bin/env python3
"""Generate attack-config fields for supported goals in a task JSON file."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from .prompt.email_send_file import GOAL_ID as FILE_GOAL_ID, generate as generate_email_send_file
    from .prompt.email_send_draft import GOAL_ID as DRAFT_GOAL_ID, generate as generate_email_send_draft
    from .prompt.email_forward_otp import (
        GOAL_ID as OTP_GOAL_ID,
        generate as generate_email_forward_otp,
        generate_otp_artifact,
    )
    from .prompt.email_broadcast_link import (
        GOAL_ID as BROADCAST_GOAL_ID,
        generate as generate_email_broadcast_link,
        generate_calendar_artifact,
    )
    from .prompt.chat_send_link import (
        GOAL_ID as CHAT_SEND_LINK_GOAL_ID,
        generate as generate_chat_send_link,
        generate_chat_channel_artifact,
    )
    from .prompt.chat_archive_to_url import (
        GOAL_ID as CHAT_ARCHIVE_GOAL_ID,
        generate as generate_chat_archive,
    )
    from .prompt.calendar_create_event import GOAL_ID as CALENDAR_CREATE_GOAL_ID, generate as generate_calendar_create
    from .prompt.fetch_external_link import GOAL_ID as FETCH_LINK_GOAL_ID, generate as generate_fetch_link
except ImportError:  # Support direct execution from the repository root.
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from archipelago.benchmark.generate_attack_config.prompt.email_send_file import (
        GOAL_ID as FILE_GOAL_ID,
        generate as generate_email_send_file,
    )
    from archipelago.benchmark.generate_attack_config.prompt.email_send_draft import (
        GOAL_ID as DRAFT_GOAL_ID,
        generate as generate_email_send_draft,
    )
    from archipelago.benchmark.generate_attack_config.prompt.email_forward_otp import (
        GOAL_ID as OTP_GOAL_ID,
        generate as generate_email_forward_otp,
        generate_otp_artifact,
    )
    from archipelago.benchmark.generate_attack_config.prompt.email_broadcast_link import (
        GOAL_ID as BROADCAST_GOAL_ID,
        generate as generate_email_broadcast_link,
        generate_calendar_artifact,
    )
    from archipelago.benchmark.generate_attack_config.prompt.chat_send_link import (
        GOAL_ID as CHAT_SEND_LINK_GOAL_ID,
        generate as generate_chat_send_link,
        generate_chat_channel_artifact,
    )
    from archipelago.benchmark.generate_attack_config.prompt.chat_archive_to_url import (
        GOAL_ID as CHAT_ARCHIVE_GOAL_ID,
        generate as generate_chat_archive,
    )
    from archipelago.benchmark.generate_attack_config.prompt.calendar_create_event import GOAL_ID as CALENDAR_CREATE_GOAL_ID, generate as generate_calendar_create
    from archipelago.benchmark.generate_attack_config.prompt.fetch_external_link import GOAL_ID as FETCH_LINK_GOAL_ID, generate as generate_fetch_link

try:
    from ..generate_attack_file.generate import generate_from_task_record
except ImportError:  # Support direct execution from the repository root.
    from archipelago.benchmark.generate_attack_file.generate import generate_from_task_record


OUTPUT_DIR = Path(__file__).resolve().parent / "output"
DEFAULT_MODEL = "aoai-swedencentral-aii-02-gpt-5.6-sol"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_json", type=Path, help="Input task JSON array")
    parser.add_argument("--output", type=Path, help="Output JSON path")
    parser.add_argument("--dataset-dir", type=Path)
    parser.add_argument("--inject-goals", type=Path)
    parser.add_argument("--reasoning-effort")
    parser.add_argument("--model", help="Azure OpenAI deployment name (or set AZURE_OPENAI_MODEL).")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.model:
        # Keep the goal-specific generators aligned with extract_key_words:
        # both accept an explicit deployment override while shared helpers
        # continue to read AZURE_OPENAI_MODEL.
        os.environ["AZURE_OPENAI_MODEL"] = args.model
    else:
        os.environ.setdefault("AZURE_OPENAI_MODEL", DEFAULT_MODEL)
    input_path = args.input_json.resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"input JSON does not exist: {input_path}")
    data = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("input JSON must contain an array of task records")

    client = None

    def get_client():
        nonlocal client
        if client is None:
            try:
                from ..utils.azure_openai import build_client
            except ImportError:  # Direct-script fallback.
                from archipelago.benchmark.utils.azure_openai import build_client
            client = build_client()
        return client

    output_records: list[dict[str, object]] = []
    generators = {
        FILE_GOAL_ID: generate_email_send_file,
        DRAFT_GOAL_ID: generate_email_send_draft,
        OTP_GOAL_ID: generate_email_forward_otp,
        BROADCAST_GOAL_ID: generate_email_broadcast_link,
        CHAT_SEND_LINK_GOAL_ID: generate_chat_send_link,
        CHAT_ARCHIVE_GOAL_ID: generate_chat_archive,
        CALENDAR_CREATE_GOAL_ID: generate_calendar_create,
        FETCH_LINK_GOAL_ID: generate_fetch_link,
    }
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("every input record must be a JSON object")
        record = dict(item)
        generator = generators.get(record.get("inject_goal"))
        if generator is not None:
            record["attack_config"] = generator(
                record,
                input_path,
                dataset_dir=args.dataset_dir,
                inject_goals_path=args.inject_goals,
                client=get_client(),
                reasoning_effort=args.reasoning_effort,
            )
        output_records.append(record)

    output = args.output or (
        OUTPUT_DIR / f"{input_path.stem}_with_attack_config.json"
    )
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    # Generate the referenced fixture from the same record.  The path stored in
    # ``attack_file`` is relative to the JSON directory so the complete output
    # folder can be copied to a runner without rewriting metadata.
    for record in output_records:
        if not isinstance(record.get("inject_vector"), str):
            continue
        harmful_task_id = record.get("harmful_task_id") or record.get("task_id")
        if (
            not isinstance(harmful_task_id, str)
            or not harmful_task_id.strip()
            or Path(harmful_task_id).name != harmful_task_id
            or harmful_task_id in {".", ".."}
        ):
            raise ValueError("every record with inject_vector needs harmful_task_id or task_id")
        artifact_dir = output.parent / harmful_task_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        attack_path = generate_from_task_record(
            record,
            artifact_dir,
            client=get_client(),
            reasoning_effort=args.reasoning_effort,
        )
        record["attack_file"] = attack_path.relative_to(output.parent).as_posix()
        attack_files = [record["attack_file"]]
        if record.get("inject_goal") == OTP_GOAL_ID:
            otp_path = generate_otp_artifact(
                record,
                artifact_dir,
                client=get_client(),
                reasoning_effort=args.reasoning_effort,
            )
            otp_output_path = otp_path.relative_to(output.parent).as_posix()
            attack_files.append(otp_output_path)
            attack_config = record.get("attack_config")
            if not isinstance(attack_config, dict):
                raise ValueError("3_email_forward_otp requires attack_config")
            # Store the generated artifact path relative to the output JSON.
            # ``populate_attack_file`` derives the runtime .apps_data target
            # from this same relative path when the benchmark starts.
            attack_config["otp_email"] = otp_output_path
        if record.get("inject_goal") == BROADCAST_GOAL_ID:
            calendar_path = generate_calendar_artifact(
                record,
                record["attack_config"],
                artifact_dir,
                client=get_client(),
                reasoning_effort=args.reasoning_effort,
            )
            calendar_output_path = calendar_path.relative_to(output.parent).as_posix()
            attack_files.append(calendar_output_path)
            attack_config = record.get("attack_config")
            if not isinstance(attack_config, dict):
                raise ValueError("4_email_broadcast_link requires attack_config")
            attack_config["calendar_event"] = calendar_output_path
        if record.get("inject_goal") in {CHAT_SEND_LINK_GOAL_ID, CHAT_ARCHIVE_GOAL_ID}:
            attack_config = record.get("attack_config")
            if not isinstance(attack_config, dict):
                raise ValueError("5_chat_send_link requires attack_config")
            channel_path = generate_chat_channel_artifact(
                record,
                attack_config,
                artifact_dir,
                client=get_client(),
                reasoning_effort=args.reasoning_effort,
            )
            channel_output_path = channel_path.relative_to(output.parent).as_posix()
            attack_files.append(channel_output_path)
            attack_config["chat_messages"] = channel_output_path
        record["attack_files"] = attack_files

    json_output = output
    temporary = json_output.with_suffix(json_output.suffix + ".tmp")
    # Keep the same top-level array shape as selected_15_tasks_with_keywords.json.
    temporary.write_text(
        json.dumps(output_records, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(json_output)
    print(json_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
