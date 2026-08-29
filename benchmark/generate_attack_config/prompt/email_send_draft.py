"""Attack-config generator for ``2_email_send_draft``."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .common import (
    generate_keyword_email,
    load_goal_prompt,
    load_task,
)
from .cot import generate_goal_cot


GOAL_ID = "2_email_send_draft"


def generate(
    task_record: dict[str, Any],
    source_json: str | Path,
    *,
    dataset_dir: str | Path | None = None,
    inject_goals_path: str | Path | None = None,
    client: Any | None = None,
    reasoning_effort: str | None = None,
) -> dict[str, str]:
    """Generate a coherent recipient and COT for sending the current draft."""
    del source_json, dataset_dir
    if client is None:
        raise ValueError("2_email_send_draft requires an LLM client")
    _, keywords = load_task(task_record)
    goal_prompt = load_goal_prompt(GOAL_ID, inject_goals_path)

    # Generate the address from keywords first, then resolve the goal before
    # producing the COT so both fields describe the same action.
    neutral_goal = goal_prompt.replace("{{attacker_email_address}}", "the task-related recipient")
    address = generate_keyword_email(
        keywords,
        neutral_goal,
        client=client,
        reasoning_effort=reasoning_effort,
    )
    resolved_goal = goal_prompt.replace("{{attacker_email_address}}", address)
    cot = generate_goal_cot(
        keywords,
        resolved_goal,
        resolved_values={"email_address": address},
        client=client,
        reasoning_effort=reasoning_effort,
    )
    if not re.search(r"original user (?:prompt|instruction)", cot, re.IGNORECASE):
        cot, replacements = re.subn(
            r"the complete original (?:request|task|description)",
            "the complete original user prompt",
            cot,
            count=1,
            flags=re.IGNORECASE,
        )
        if replacements == 0:
            raise ValueError("generated COT omitted the original user prompt")
    return {
        "attacker_email_address": address,
        "cot": cot,
        "original_task_prompt": str(task_record.get("prompt", "")),
    }
