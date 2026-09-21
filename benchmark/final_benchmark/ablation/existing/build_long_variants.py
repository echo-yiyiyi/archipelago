"""Build benign head and keyword variants, preferring documents over 30 pages."""
from pathlib import Path
import copy
import hashlib
import io
import json
import random
import shutil
import sys
import zipfile
from xml.etree import ElementTree as ET

HERE = Path(__file__).resolve().parent
HEAD = HERE / "head"
sys.path.insert(0, str(HEAD))
sys.path.insert(0, "/data/ziyi/ablation_backups/existing_long_selection_20260917/head")
sys.path.insert(0, "/data/ziyi/ablation_backups/existing_head_before_keyword_20260917_131555")
from build_benign import head_document, original
from build_keyword import content, insert_docx, insert_pdf, insert_xlsx, score

SOURCE = Path("/data/ziyi/ablation_backups/existing_head_before_keyword_20260917_131555")
CONFIG_SOURCE = Path("/data/ziyi/ablation_backups/existing_head_benign_20260917")
KEYWORDS = Path("/data/ziyi/archipelago/benchmark/extract_key_words/selected_15_tasks_with_keywords.json")
PAGES = Path("/tmp/long_candidates/pages.json")
SEED = 20260918
SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def xlsx_head_in_first_sheet(data, prompt):
    """Prepend prompt to A1 of the workbook's original first worksheet."""
    with zipfile.ZipFile(io.BytesIO(data)) as source:
        parts = {name: source.read(name) for name in source.namelist()}
    workbook = ET.fromstring(parts["xl/workbook.xml"])
    first_sheet = workbook.find(f"{{{SHEET_NS}}}sheets")[0]
    relationship_id = first_sheet.attrib[f"{{{OFFICE_REL_NS}}}id"]
    relationships = ET.fromstring(parts["xl/_rels/workbook.xml.rels"])
    relationship = next(rel for rel in relationships if rel.attrib["Id"] == relationship_id)
    target = relationship.attrib["Target"].lstrip("/")
    worksheet_name = target if target.startswith("xl/") else "xl/" + target
    worksheet = ET.fromstring(parts[worksheet_name])
    sheet_data = worksheet.find(f"{{{SHEET_NS}}}sheetData")
    row = next((item for item in sheet_data if item.attrib.get("r") == "1"), None)
    if row is None:
        row = ET.Element(f"{{{SHEET_NS}}}row", {"r": "1"})
        sheet_data.insert(0, row)
    cell = next((item for item in row if item.attrib.get("r") == "A1"), None)
    if cell is None:
        cell = ET.Element(f"{{{SHEET_NS}}}c", {"r": "A1"})
        row.insert(0, cell)
    old_value = ""
    value = cell.find(f"{{{SHEET_NS}}}v")
    inline = cell.find(f"{{{SHEET_NS}}}is")
    if cell.attrib.get("t") == "s" and value is not None and "xl/sharedStrings.xml" in parts:
        strings = ET.fromstring(parts["xl/sharedStrings.xml"])
        old_value = "".join(strings[int(value.text)].itertext())
    elif inline is not None:
        old_value = "".join(inline.itertext())
    elif value is not None:
        old_value = value.text or ""
    for child in list(cell):
        if child.tag in {f"{{{SHEET_NS}}}f", f"{{{SHEET_NS}}}v", f"{{{SHEET_NS}}}is"}:
            cell.remove(child)
    cell.set("t", "inlineStr")
    styles = ET.fromstring(parts["xl/styles.xml"])
    cell_xfs = styles.find(f"{{{SHEET_NS}}}cellXfs")
    source_style = int(cell.attrib.get("s", "0"))
    wrapped_style = copy.deepcopy(cell_xfs[source_style])
    alignment = wrapped_style.find(f"{{{SHEET_NS}}}alignment")
    if alignment is None:
        alignment = ET.SubElement(wrapped_style, f"{{{SHEET_NS}}}alignment")
    alignment.set("wrapText", "1")
    alignment.set("vertical", "top")
    alignment.set("horizontal", "left")
    wrapped_style.set("applyAlignment", "1")
    cell_xfs.append(wrapped_style)
    cell_xfs.set("count", str(len(cell_xfs)))
    cell.set("s", str(len(cell_xfs) - 1))
    row.set("ht", "300")
    row.set("customHeight", "1")
    columns = worksheet.find(f"{{{SHEET_NS}}}cols")
    if columns is None:
        columns = ET.Element(f"{{{SHEET_NS}}}cols")
        sheet_data_index = list(worksheet).index(sheet_data)
        worksheet.insert(sheet_data_index, columns)
    ET.SubElement(
        columns,
        f"{{{SHEET_NS}}}col",
        {"min": "1", "max": "1", "width": "80", "customWidth": "1"},
    )
    inline = ET.SubElement(cell, f"{{{SHEET_NS}}}is")
    text = ET.SubElement(inline, f"{{{SHEET_NS}}}t")
    text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    text.text = prompt + (("\n" + old_value) if old_value else "")
    parts[worksheet_name] = ET.tostring(worksheet, xml_declaration=True, encoding="UTF-8")
    parts["xl/styles.xml"] = ET.tostring(styles, xml_declaration=True, encoding="UTF-8")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target_zip:
        for name, payload in parts.items():
            target_zip.writestr(name, payload)
    return output.getvalue()


def sanitized(task, prompt, document, workspace_path, auxiliary_files):
    clean = {
        k: v for k, v in task.items()
        if k not in {
            "attack_file", "populate_files", "attack_config", "inject_goal",
            "leakage_type", "inject_vector", "populate_file_destinations",
            "injected_document",
        }
    }
    clean.update(
        inject_goal=task["inject_goal"],
        leakage_type=task["leakage_type"],
        inject_vector=Path(workspace_path).suffix.lstrip("."),
        populate_files=[document, *auxiliary_files],
        populate_file_destinations={document: workspace_path},
        injected_document=document,
        benign_existing_file_test=True,
        attack_config=task["attack_config"],
    )
    return clean


def original_injection_text(task, group):
    cot = task.get("attack_config", {}).get("cot")
    if isinstance(cot, str) and cot:
        return cot, "attack_config.cot"
    for fixture in task.get("populate_files", []):
        if fixture.endswith("Additional_Task_Instructions.txt"):
            return (CONFIG_SOURCE / group / fixture).read_text(), "original additional-instructions text"
    raise KeyError(f"no original injected text for {task['harmful_task_id']}")


def main():
    if not PAGES.is_file():
        raise SystemExit(f"missing rendered page counts: {PAGES}")
    pages = json.loads(PAGES.read_text())
    source_manifest = json.loads((SOURCE / "selection_manifest.json").read_text())
    old_selection = json.loads((HEAD / "selection_manifest.json").read_text())
    old_by_id = {(r["group"], r["id"]): r for r in old_selection["tasks"]}
    keywords = {r["task_id"]: r["keywords"] for r in json.loads(KEYWORDS.read_text())}
    candidates = {(r["group"], r["id"]): r["candidates"] for r in source_manifest["tasks"]}
    rng = random.Random(SEED)
    stage = HERE / ".long_stage"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()
    manifests = {"head": [], "key-word": []}

    for variant in ("head", "key-word"):
        for group in ("static_prompt_injection", "static_script_injection"):
            base = stage / variant / group
            base.mkdir(parents=True)
            tasks = json.loads((CONFIG_SOURCE / group / "selected_10_tasks_with_attack_config.json").read_text())
            output = []
            goals = []
            for task in tasks:
                task_key = (group, task["harmful_task_id"])
                pool = candidates[task_key]
                long_pool = [c for c in pool if pages.get(c["path"], 0) > 30]
                if long_pool:
                    longest = max(pages[c["path"]] for c in long_pool)
                    tied = sorted((c for c in long_pool if pages[c["path"]] == longest), key=lambda c: c["path"])
                    chosen = tied[0]
                    selection = "longest_over_30_pages"
                else:
                    measured = [c for c in pool if pages.get(c["path"]) is not None]
                    if measured:
                        longest = max(pages[c["path"]] for c in measured)
                        tied = sorted((c for c in measured if pages[c["path"]] == longest), key=lambda c: c["path"])
                        chosen = tied[0]
                        selection = "longest_available_under_30_pages"
                    else:
                        previous = old_by_id[task_key]["candidate_file"]
                        chosen = next((c for c in pool if c["path"] == previous), pool[0])
                        selection = "unmeasured_kept_previous"
                data = original(chosen["source"])
                workspace_path = chosen["path"]
                suffix = Path(workspace_path).suffix.lower()
                prompt, prompt_source = original_injection_text(task, group)
                matched_keyword = None
                match_method = None
                if variant == "head":
                    if suffix == ".xlsx":
                        injected = xlsx_head_in_first_sheet(data, prompt)
                        position = "original_first_worksheet_A1"
                    else:
                        injected = head_document(data, suffix, prompt)
                        position = "document_head"
                else:
                    scored = score(content(data, suffix) + [workspace_path], keywords[task["task_id"]])
                    _, matched_keyword, match_method = scored
                    if suffix == ".docx":
                        injected, position = insert_docx(data, prompt, matched_keyword)
                    elif suffix == ".pdf":
                        injected, position = insert_pdf(data, prompt, matched_keyword)
                    elif suffix == ".xlsx":
                        injected, position = insert_xlsx(data, prompt, matched_keyword)
                    else:
                        raise ValueError(workspace_path)
                document = str(Path(task["harmful_task_id"]) / "filesystem" / workspace_path)
                target = base / document
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(injected)
                auxiliary_files = []
                original_attack_file = task.get("attack_file")
                for fixture in task.get("populate_files", []):
                    if fixture == original_attack_file or fixture.endswith("Additional_Task_Instructions.txt"):
                        continue
                    source_fixture = CONFIG_SOURCE / group / fixture
                    if not source_fixture.is_file():
                        continue
                    fixture_target = base / fixture
                    fixture_target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source_fixture, fixture_target)
                    auxiliary_files.append(fixture)
                clean = sanitized(task, prompt, document, workspace_path, auxiliary_files)
                output.append(clean)
                goals.append({
                    k: v for k, v in clean.items()
                    if k not in {"attack_config", "populate_files", "populate_file_destinations", "injected_document"}
                })
                manifests[variant].append({
                    "group": group,
                    "id": task["harmful_task_id"],
                    "original_task_id": task["task_id"],
                    "file": workspace_path,
                    "rendered_pages": pages.get(workspace_path),
                    "selection": selection,
                    "matched_keyword": matched_keyword,
                    "match_method": match_method,
                    "position": position,
                    "cot_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                    "prompt_source": prompt_source,
                    "source_sha256": hashlib.sha256(data).hexdigest(),
                    "output_sha256": hashlib.sha256(injected).hexdigest(),
                })
            (base / "selected_10_tasks_with_attack_config.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
            (base / "selected_10_tasks_with_inject_goals.json").write_text(json.dumps(goals, ensure_ascii=False, indent=2) + "\n")

    for variant in ("head", "key-word"):
        destination = HERE / variant
        if destination.exists():
            archived = HERE / ".long_stage" / (variant + "_old")
            shutil.move(str(destination), str(archived))
        shutil.move(str(stage / variant), str(destination))
        manifest = {
            "seed": SEED,
            "page_count_method": "PDF native pages; DOCX/XLSX LibreOffice PDF export",
            "minimum_long_file_pages": 31,
            "variant": variant,
            "tasks": manifests[variant],
        }
        (destination / "selection_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    shutil.rmtree(stage)
    (HERE / "page_counts.json").write_text(json.dumps(pages, ensure_ascii=False, indent=2) + "\n")
    print("built head and key-word variants; long selections:", sum(r["rendered_pages"] and r["rendered_pages"] > 30 for r in manifests["head"]))


if __name__ == "__main__":
    main()
