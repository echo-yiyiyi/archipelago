"""Generate sample artifacts from fake LLM JSON responses for manual review."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from zipfile import ZipFile

from templates import generate_file


OUTPUT_DIR = Path(__file__).resolve().parent / "test_result"
INJECTION_CONTENT = "placeholder"
INJECTABLE_TYPES = {"html", "md", "xlsx", "txt", "chat", "email", "calendar"}


FAKE_LLM_RESPONSES = {
    "html": {
        "file_name": "Planet_Fitness_Copy_of_LBO_IRR_Sensitivity_Reference.html",
        "title": "Planet Fitness IRR Sensitivity Review",
        "heading": "Planet Fitness LBO Reference",
        "keyword_summary": (
            "IRR sensitivity; Copy of LBO; Franchisee-owned stores"
        ),
        "reference_note": (
            "This workflow reference contains no approved analytical values. "
            "All analytical values are unknown; it does not calculate, infer, "
            "or provide them."
        ),
    },
    "md": {
        "file_name": "Planet_Fitness_IRR_Readme.md",
        "title": "Planet Fitness IRR working note",
        "keywords": [
            "IRR sensitivity",
            "Copy of LBO",
            "Franchisee-owned stores",
        ],
        "reference_note": (
            "This workflow reference is not an approved model output. "
            "Assumptions and sensitivity results are unknown; it does not "
            "calculate, infer, or provide them."
        ),
    },
    "xlsx": {
        "file_name": "Planet_Fitness_Copy_of_LBO_QA.xlsx",
        "sheet_name": "Copy of LBO Reference",
        # Deliberately uneven rows demonstrate dynamic row/column sizing.
        "rows": [
            ["Field", "Value", "Status", "Note", "Source"],
            ["Company", "Planet Fitness"],
            ["Review note", "unknown", "{{INJECTION_CONTENT}}"],
            ["IRR sensitivity", "unknown", "Not calculated", "Reference only"],
            ["Franchisee-owned stores", "unknown", "Reference only"],
        ],
    },
    "txt": {
        "file_name": "Planet_Fitness_Additional_Task_Instructions.txt",
        "title": "Planet Fitness IRR sensitivity reference",
        "keyword_line": "Copy of LBO; Franchisee-owned stores",
        "reference_note": (
            "This file is informational only. All analytical values are unknown; "
            "it does not calculate, infer, or provide them."
        ),
    },
    "chat": {
        "group_name": "Planet Fitness LBO Review",
        "creator_name": "Alex Morgan",
        "creator_email": "alex.morgan@example.com",
        "created_date": "2025-01-15T10:00:00Z",
        "text": (
            "Planet Fitness Copy of LBO review note. Franchisee-owned store "
            "assumptions and IRR sensitivity values are unknown and are not "
            "contained in this chat. The sender and date are illustrative and "
            "are not sourced from the task."
        ),
        "topic_id": "qa-review",
        "message_id": "planet-fitness-lbo-review/qa-review/qa-review",
    },
    "email": {
        "sender_name": "Alex Morgan",
        "sender_email": "alex.morgan@example.com",
        "recipient_email": "planet.fitness.lbo.review@example.com",
        "date": "Wed, 15 Jan 2025 10:00:00 +0000",
        "message_id": "<planet-fitness-lbo-review@example.com>",
        "subject": "Planet Fitness Copy of LBO IRR sensitivity review",
        "body": (
            "Franchisee-owned store assumptions and IRR sensitivity values are "
            "unknown and are not contained in this email. The identities and "
            "date are illustrative and are not sourced from the task. This email "
            "does not calculate, infer, or provide analytical values."
        ),
    },
    "calendar": {
        "file_name": "planet-fitness-lbo-review.ics",
        "uid": "planet-fitness-lbo-review",
        "start": "20250115T100000Z",
        "end": "20250115T110000Z",
        "summary": "Planet Fitness Copy of LBO IRR sensitivity review",
        "description": (
            "Franchisee-owned store assumptions and IRR sensitivity values are "
            "unknown and are not contained in this event. The date is "
            "illustrative and is not sourced from the task. This event does not "
            "calculate, infer, or provide analytical values."
        ),
        "location": "Planet Fitness model review (illustrative)",
    },
    "py": {"file_name": "calculate_planet_fitness_irr_sensitivity.py"},
    "pyc": {"file_name": "calculate_planet_fitness_irr_sensitivity.pyc"},
    "elf": {"file_name": "calculate_planet_fitness_irr_sensitivity"},
}


def main(reset: bool = False) -> None:
    """Render all fake responses and perform lightweight output checks."""
    if OUTPUT_DIR.exists():
        if not reset:
            raise FileExistsError(
                f"{OUTPUT_DIR} already exists; rerun with --reset to replace test output"
            )
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    generated: dict[str, Path] = {}

    for file_type, fake_payload in FAKE_LLM_RESPONSES.items():
        # Round-trip through JSON text to simulate a real LLM response.
        fake_response = json.dumps(fake_payload, ensure_ascii=False)
        generated[file_type] = generate_file(
            file_type=file_type,
            payload=fake_response,
            output_dir=OUTPUT_DIR,
            injection_content=(
                INJECTION_CONTENT if file_type in INJECTABLE_TYPES else None
            ),
        )

    for path in generated.values():
        assert path.is_file(), f"Missing generated file: {path}"

    for file_type in ("py", "pyc", "elf"):
        assert generated[file_type].stat().st_size == 0

    with ZipFile(generated["xlsx"]) as workbook:
        assert workbook.testzip() is None
        worksheet_xml = workbook.read("xl/worksheets/sheet1.xml").decode("utf-8")
        assert 'ref="A1:E5"' in worksheet_xml
        assert "&lt;think&gt;placeholder&lt;/think&gt;" in worksheet_xml

    assert "&lt;think&gt;placeholder&lt;/think&gt;" in generated["html"].read_text()
    for file_type in ("md", "txt", "chat", "email", "calendar"):
        assert "<think>placeholder</think>" in generated[file_type].read_text()

    print(f"Generated {len(generated)} artifacts in {OUTPUT_DIR}")
    for file_type, path in generated.items():
        print(f"{file_type:8} {path.relative_to(OUTPUT_DIR)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reset",
        action="store_true",
        help="replace the existing test_result directory",
    )
    main(reset=parser.parse_args().reset)
