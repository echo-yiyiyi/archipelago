"""Format-preserving replacement writers adapted from watch_aiag_text_files.py."""
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

def write_plain(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def wrap_lines(lines: list[str], width: int = 88) -> list[str]:
    wrapped: list[str] = []
    for line in lines:
        if not line:
            wrapped.append("")
            continue
        words = line.split()
        current = ""
        for word in words:
            candidate = word if not current else f"{current} {word}"
            if len(candidate) <= width:
                current = candidate
            else:
                if current:
                    wrapped.append(current)
                current = word
        wrapped.append(current)
    return wrapped


def write_pdf(path: Path, lines: list[str]) -> None:
    commands = ["BT", "/F1 10 Tf", "50 750 Td", "13 TL"]
    for index, line in enumerate(wrap_lines(lines)):
        if index:
            commands.append("T*")
        commands.append(f"({pdf_escape(line)}) Tj")
    commands.append("ET")
    stream = "\n".join(commands).encode("ascii", errors="replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode())
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode()
    )
    path.write_bytes(output)


def qname(namespace: str, local: str) -> str:
    return f"{{{namespace}}}{local}"


def clone_zip_with_replacement(source: Path, target: Path, member: str, data: bytes) -> None:
    with zipfile.ZipFile(source, "r") as zin, zipfile.ZipFile(target, "w") as zout:
        for item in zin.infolist():
            if item.filename == member:
                zout.writestr(item, data)
            else:
                zout.writestr(item, zin.read(item.filename))


def write_docx(source: Path, target: Path, lines: list[str]) -> None:
    member = "word/document.xml"
    with zipfile.ZipFile(source) as archive:
        root = ET.fromstring(archive.read(member))
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = root.find(qname(ns, "body"))
    if body is None:
        raise ValueError("DOCX has no document body")
    section = body.find(qname(ns, "sectPr"))
    for child in list(body):
        body.remove(child)
    for line in lines:
        paragraph = ET.SubElement(body, qname(ns, "p"))
        run = ET.SubElement(paragraph, qname(ns, "r"))
        text = ET.SubElement(run, qname(ns, "t"))
        text.text = line
    if section is not None:
        body.append(section)
    clone_zip_with_replacement(source, target, member, ET.tostring(root, encoding="utf-8", xml_declaration=True))


def write_xlsx(source: Path, target: Path, lines: list[str]) -> None:
    member = "xl/worksheets/sheet1.xml"
    with zipfile.ZipFile(source) as archive:
        if member not in archive.namelist():
            member = sorted(name for name in archive.namelist() if name.startswith("xl/worksheets/sheet"))[0]
        root = ET.fromstring(archive.read(member))
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    sheet_data = root.find(qname(ns, "sheetData"))
    if sheet_data is None:
        raise ValueError("XLSX has no sheet data")
    sheet_data.clear()
    for index, line in enumerate(lines, 1):
        row = ET.SubElement(sheet_data, qname(ns, "row"), {"r": str(index)})
        cell = ET.SubElement(row, qname(ns, "c"), {"r": f"A{index}", "t": "inlineStr"})
        inline = ET.SubElement(cell, qname(ns, "is"))
        text = ET.SubElement(inline, qname(ns, "t"))
        text.text = line
    clone_zip_with_replacement(source, target, member, ET.tostring(root, encoding="utf-8", xml_declaration=True))


def write_pptx(source: Path, target: Path, lines: list[str]) -> None:
    member = "ppt/slides/slide1.xml"
    with zipfile.ZipFile(source) as archive:
        if member not in archive.namelist():
            member = sorted(name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml"))[0]
        root = ET.fromstring(archive.read(member))
    drawing_ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
    text_nodes = root.findall(f".//{qname(drawing_ns, 't')}")
    message = "\n".join(lines)
    if not text_nodes:
        raise ValueError("PPTX first slide has no text container")
    text_nodes[0].text = message
    for node in text_nodes[1:]:
        node.text = ""
    clone_zip_with_replacement(source, target, member, ET.tostring(root, encoding="utf-8", xml_declaration=True))


def make_replacement(source: Path, target: Path, lines: list[str]) -> None:
    suffix = source.suffix.lower()
    if suffix == ".pdf":
        write_pdf(target, lines)
    elif suffix == ".docx":
        write_docx(source, target, lines)
    elif suffix == ".xlsx":
        write_xlsx(source, target, lines)
    elif suffix == ".pptx":
        write_pptx(source, target, lines)
    else:
        write_plain(target, lines)
