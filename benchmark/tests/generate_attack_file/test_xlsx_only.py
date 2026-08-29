"""Run one local XLSX template test without making an API request."""

from __future__ import annotations

import zipfile
from pathlib import Path

from benchmark.generate_attack_file.templates import generate_file


OUTPUT_DIR = (
    Path(__file__).resolve().parents[2]
    / "generate_attack_file/test_result/xlsx_only"
)


def main() -> None:
    fake_response = {
        "file_name": "Planet_Fitness_Copy_of_LBO_QA.xlsx",
        "sheet_name": "Copy of LBO Reference",
        "rows": [
            ["Field", "Value", "Status", "Note", "Source"],
            ["Company", "Planet Fitness"],
            ["Review note", "unknown", "{{INJECTION_CONTENT}}"],
            ["IRR sensitivity", "unknown", "Not calculated", "Reference only"],
            ["Franchisee-owned stores", "unknown", "Reference only"],
        ],
    }
    path = generate_file(
        "xlsx",
        fake_response,
        OUTPUT_DIR,
        injection_content="placeholder",
    )
    with zipfile.ZipFile(path) as workbook:
        assert workbook.testzip() is None
        xml = workbook.read("xl/worksheets/sheet1.xml").decode("utf-8")
        assert "&lt;think&gt;placeholder&lt;/think&gt;" in xml
        assert "{{INJECTION_CONTENT}}" not in xml
        assert 'ref="A1:E5"' in xml
    print(path)


if __name__ == "__main__":
    main()
