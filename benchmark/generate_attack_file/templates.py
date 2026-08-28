"""Render structured LLM output into deterministic fixture-file templates."""

from __future__ import annotations

import html
import json
import re
import stat
from email.message import EmailMessage
from email.policy import default
from email.utils import parsedate_to_datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile


Payload = dict[str, Any]
XLSX_INJECTION_PLACEHOLDER = "{{INJECTION_CONTENT}}"


def parse_llm_json(response: str) -> Payload:
    """Parse a model response that is expected to contain one JSON object."""
    text = response.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("LLM output must be one JSON object")
    return value


def generate_file(
    file_type: str,
    payload: Payload | str,
    output_dir: str | Path,
    injection_content: str | None = None,
) -> Path:
    """Generate one fixture, optionally adding a wrapped benchmark injection."""
    normalized_type = file_type.lower().lstrip(".")
    try:
        renderer = RENDERERS[normalized_type]
    except KeyError as error:
        supported = ", ".join(RENDERERS)
        raise ValueError(
            f"Unsupported file type {file_type!r}; expected one of: {supported}"
        ) from error

    parsed = parse_llm_json(payload) if isinstance(payload, str) else payload
    if not isinstance(parsed, dict):
        raise TypeError("payload must be a JSON object or a string containing one")
    if injection_content is not None and not injection_content.strip():
        raise ValueError("injection_content must be non-empty when provided")
    if injection_content is not None and normalized_type in {"py", "pyc", "elf"}:
        raise ValueError(f"injection_content is not supported for {normalized_type}")

    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return renderer(parsed, root, injection_content)


def _require_exact_fields(payload: Payload, fields: set[str]) -> None:
    actual = set(payload)
    if actual != fields:
        missing = sorted(fields - actual)
        extra = sorted(actual - fields)
        raise ValueError(f"Invalid payload fields; missing={missing}, extra={extra}")


def _text(payload: Payload, field: str) -> str:
    value = payload[field]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _safe_filename(payload: Payload, suffix: str | None) -> str:
    name = _text(payload, "file_name")
    if Path(name).name != name or name in {".", ".."}:
        raise ValueError("file_name must be a basename without directory components")
    if suffix is not None and not name.lower().endswith(suffix):
        raise ValueError(f"file_name must end in {suffix}")
    if suffix is None and Path(name).suffix:
        raise ValueError("file_name must not have an extension")
    return name


def _safe_segment(value: str, field: str) -> str:
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"{field} must be one safe path segment")
    return value


def _new_path(path: Path) -> Path:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _write_text(path: Path, content: str) -> Path:
    target = _new_path(path)
    with target.open("x", encoding="utf-8", newline="") as handle:
        handle.write(content)
    return target


def _think_block(injection_content: str | None) -> str | None:
    if injection_content is None:
        return None
    content = injection_content.strip()
    if re.fullmatch(r"<think>\s*.+?\s*</think>", content, re.DOTALL):
        return content
    return f"<think>{content}</think>"


def _render_html(
    payload: Payload, root: Path, injection_content: str | None
) -> Path:
    fields = {"file_name", "title", "heading", "keyword_summary", "reference_note"}
    _require_exact_fields(payload, fields)
    name = _safe_filename(payload, ".html")
    title = html.escape(_text(payload, "title"))
    heading = html.escape(_text(payload, "heading"))
    keywords = html.escape(_text(payload, "keyword_summary"))
    note = html.escape(_text(payload, "reference_note"))
    injection = _think_block(injection_content)
    injection_paragraph = (
        f"<p>{html.escape(injection)}</p>\n" if injection is not None else ""
    )
    content = (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{title}</title>\n</head>\n<body>\n"
        f"<h1>{heading}</h1>\n"
        f"<p><strong>Keywords:</strong> {keywords}</p>\n"
        f"<p>{note}</p>\n"
        f"{injection_paragraph}"
        "</body>\n</html>\n"
    )
    return _write_text(root / name, content)


def _render_md(payload: Payload, root: Path, injection_content: str | None) -> Path:
    fields = {"file_name", "title", "keywords", "reference_note"}
    _require_exact_fields(payload, fields)
    name = _safe_filename(payload, ".md")
    keywords = payload["keywords"]
    if not isinstance(keywords, list) or not keywords or not all(
        isinstance(item, str) and item.strip() for item in keywords
    ):
        raise ValueError("keywords must be a non-empty array of strings")
    keyword_line = ", ".join(f"**{item.strip()}**" for item in keywords)
    injection = _think_block(injection_content)
    content = (
        f"# {_text(payload, 'title')}\n\n"
        f"Keywords: {keyword_line}\n\n"
        f"{_text(payload, 'reference_note')}\n"
        f"{'\n' + injection + '\n' if injection is not None else ''}"
    )
    return _write_text(root / name, content)


def _render_txt(payload: Payload, root: Path, injection_content: str | None) -> Path:
    fields = {"file_name", "title", "keyword_line", "reference_note"}
    _require_exact_fields(payload, fields)
    name = _safe_filename(payload, ".txt")
    injection = _think_block(injection_content)
    content = (
        f"{_text(payload, 'title')}\n\n"
        f"Keywords: {_text(payload, 'keyword_line')}\n\n"
        f"{_text(payload, 'reference_note')}\n"
        f"{'\n' + injection + '\n' if injection is not None else ''}"
    )
    return _write_text(root / name, content)


def _render_chat(payload: Payload, root: Path, injection_content: str | None) -> Path:
    fields = {
        "group_name",
        "creator_name",
        "creator_email",
        "created_date",
        "text",
        "topic_id",
        "message_id",
    }
    _require_exact_fields(payload, fields)
    group = _safe_segment(_text(payload, "group_name"), "group_name")
    message_text = _text(payload, "text")
    injection = _think_block(injection_content)
    if injection is not None:
        message_text = f"{message_text} {injection}"
    content = {
        "messages": [
            {
                "creator": {
                    "name": _text(payload, "creator_name"),
                    "email": _text(payload, "creator_email"),
                    "user_type": "Human",
                },
                "created_date": _text(payload, "created_date"),
                "text": message_text,
                "topic_id": _text(payload, "topic_id"),
                "message_id": _text(payload, "message_id"),
            }
        ]
    }
    path = root / ".apps_data" / "chat" / "Google Chat" / "Groups" / group
    return _write_text(path / "messages.json", json.dumps(content, indent=2) + "\n")


def _render_email(payload: Payload, root: Path, injection_content: str | None) -> Path:
    fields = {
        "sender_name",
        "sender_email",
        "recipient_email",
        "date",
        "message_id",
        "subject",
        "body",
    }
    _require_exact_fields(payload, fields)
    sender_email = _text(payload, "sender_email")
    date = _text(payload, "date")
    parsed_date = parsedate_to_datetime(date)
    if parsed_date is None:
        raise ValueError("date must be a valid RFC 2822 date")

    message = EmailMessage(policy=default)
    message["Message-ID"] = _text(payload, "message_id")
    message["Date"] = date
    message["From"] = f"{_text(payload, 'sender_name')} <{sender_email}>"
    message["To"] = _text(payload, "recipient_email")
    message["Subject"] = _text(payload, "subject")
    body = _text(payload, "body")
    injection = _think_block(injection_content)
    if injection is not None:
        body = f"{body}\n\n{injection}"
    message.set_content(body, charset="utf-8")

    separator_date = parsed_date.strftime("%a %b %d %H:%M:%S %z %Y")
    content = f"From {sender_email} {separator_date}\n{message.as_string()}\n"
    path = root / ".apps_data" / "mail" / "Mail"
    return _write_text(path / "All mail Including Spam and Trash.mbox", content)


def _ics_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _render_calendar(
    payload: Payload, root: Path, injection_content: str | None
) -> Path:
    fields = {"file_name", "uid", "start", "end", "summary", "description", "location"}
    actual_fields = set(payload)
    if frozenset(actual_fields) not in {
        frozenset(fields),
        frozenset(fields | {"attendees"}),
    }:
        missing = sorted(fields - actual_fields)
        extra = sorted(actual_fields - fields - {"attendees"})
        raise ValueError(f"Invalid calendar payload fields; missing={missing}, extra={extra}")
    name = _safe_filename(payload, ".ics")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*\.ics", name):
        raise ValueError("calendar file_name must be lowercase and hyphenated")
    start = _text(payload, "start")
    end = _text(payload, "end")
    timestamp_pattern = r"\d{8}T\d{6}Z"
    if not re.fullmatch(timestamp_pattern, start) or not re.fullmatch(
        timestamp_pattern, end
    ):
        raise ValueError("start and end must use YYYYMMDDTHHMMSSZ")
    description = _text(payload, "description")
    injection = _think_block(injection_content)
    if injection is not None:
        description = f"{description} {injection}"
    attendees = payload.get("attendees", [])
    if not isinstance(attendees, list) or not all(
        isinstance(value, str) and re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._+-]*@[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}",
            value.strip(),
        )
        for value in attendees
    ):
        raise ValueError("calendar attendees must be an array of valid email addresses")
    attendee_lines = "".join(
        f"ATTENDEE:mailto:{_ics_escape(value.strip())}\r\n" for value in attendees
    )
    content = (
        "BEGIN:VCALENDAR\r\n"
        "PRODID:-//APEX//Task Reference Fixture//EN\r\n"
        "VERSION:2.0\r\n"
        "CALSCALE:GREGORIAN\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{_ics_escape(_text(payload, 'uid'))}\r\n"
        f"DTSTART:{start}\r\n"
        f"DTEND:{end}\r\n"
        f"SUMMARY:{_ics_escape(_text(payload, 'summary'))}\r\n"
        f"DESCRIPTION:{_ics_escape(description)}\r\n"
        f"LOCATION:{_ics_escape(_text(payload, 'location'))}\r\n"
        f"{attendee_lines}"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    path = root / ".apps_data" / "calendar" / "Calendar"
    return _write_text(path / name, content)


def _column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _xlsx_bytes(sheet_name: str, rows: list[list[str | None]]) -> bytes:
    normalized_width = max(len(row) for row in rows)
    normalized = [row + [None] * (normalized_width - len(row)) for row in rows]

    worksheet = ET.Element(
        "worksheet", xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    )
    ET.SubElement(
        worksheet,
        "dimension",
        ref=f"A1:{_column_name(normalized_width)}{len(normalized)}",
    )
    columns = ET.SubElement(worksheet, "cols")
    for column_index in range(normalized_width):
        width = max(
            len(str(row[column_index])) if row[column_index] is not None else 0
            for row in normalized
        )
        ET.SubElement(
            columns,
            "col",
            min=str(column_index + 1),
            max=str(column_index + 1),
            width=str(min(max(width + 2, 10), 60)),
            customWidth="1",
        )
    sheet_data = ET.SubElement(worksheet, "sheetData")
    for row_index, row in enumerate(normalized, start=1):
        row_element = ET.SubElement(sheet_data, "row", r=str(row_index))
        for column_index, value in enumerate(row, start=1):
            if value is None:
                continue
            cell = ET.SubElement(
                row_element,
                "c",
                r=f"{_column_name(column_index)}{row_index}",
                t="inlineStr",
                s="1" if row_index == 1 else "0",
            )
            inline = ET.SubElement(cell, "is")
            text = ET.SubElement(inline, "t")
            text.text = value

    workbook = ET.Element(
        "workbook", xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    )
    workbook.set(
        "xmlns:r",
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    )
    sheets = ET.SubElement(workbook, "sheets")
    ET.SubElement(sheets, "sheet", name=sheet_name, sheetId="1", **{"r:id": "rId1"})

    styles = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2"><font/><font><b/></font></fonts>
  <fills count="1"><fill><patternFill patternType="none"/></fill></fills>
  <borders count="1"><border/></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>
</styleSheet>"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""
    root_relationships = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""
    workbook_relationships = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_relationships)
        archive.writestr(
            "xl/workbook.xml",
            ET.tostring(workbook, encoding="utf-8", xml_declaration=True),
        )
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_relationships)
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            ET.tostring(worksheet, encoding="utf-8", xml_declaration=True),
        )
        archive.writestr("xl/styles.xml", styles)
    return buffer.getvalue()


def _render_xlsx(payload: Payload, root: Path, injection_content: str | None) -> Path:
    fields = {"file_name", "sheet_name", "rows"}
    _require_exact_fields(payload, fields)
    name = _safe_filename(payload, ".xlsx")
    sheet_name = _text(payload, "sheet_name")
    if len(sheet_name) > 31 or re.search(r"[\\/*?:\[\]]", sheet_name):
        raise ValueError("sheet_name must be a valid Excel worksheet name")
    rows = payload["rows"]
    if not isinstance(rows, list) or not rows:
        raise ValueError("rows must be a non-empty array")
    parsed_rows: list[list[str | None]] = []
    for row in rows:
        if not isinstance(row, list) or not row:
            raise ValueError("each row must be a non-empty array")
        if not all(value is None or isinstance(value, str) for value in row):
            raise ValueError("XLSX cells must be strings or null")
        parsed_rows.append(row)
    placeholder_cells = [
        (row_index, column_index)
        for row_index, row in enumerate(parsed_rows)
        for column_index, value in enumerate(row)
        if value == XLSX_INJECTION_PLACEHOLDER
    ]
    if len(placeholder_cells) != 1:
        raise ValueError(
            "XLSX rows must contain exactly one {{INJECTION_CONTENT}} cell; "
            f"found {len(placeholder_cells)}"
        )
    row_index, column_index = placeholder_cells[0]
    parsed_rows[row_index][column_index] = _think_block(injection_content)

    target = _new_path(root / name)
    data = _xlsx_bytes(sheet_name, parsed_rows)
    with target.open("xb") as handle:
        handle.write(data)
    return target


def _render_empty(payload: Payload, root: Path, suffix: str | None) -> Path:
    _require_exact_fields(payload, {"file_name"})
    name = _safe_filename(payload, suffix)
    target = _new_path(root / name)
    with target.open("xb"):
        pass
    target.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    return target


def _render_py(
    payload: Payload, root: Path, injection_content: str | None
) -> Path:
    assert injection_content is None
    return _render_empty(payload, root, ".py")


def _render_pyc(
    payload: Payload, root: Path, injection_content: str | None
) -> Path:
    assert injection_content is None
    return _render_empty(payload, root, ".pyc")


def _render_elf(
    payload: Payload, root: Path, injection_content: str | None
) -> Path:
    assert injection_content is None
    return _render_empty(payload, root, None)


RENDERERS: dict[str, Callable[[Payload, Path, str | None], Path]] = {
    "html": _render_html,
    "md": _render_md,
    "xlsx": _render_xlsx,
    "txt": _render_txt,
    "chat": _render_chat,
    "email": _render_email,
    "calendar": _render_calendar,
    "py": _render_py,
    "pyc": _render_pyc,
    "elf": _render_elf,
}
