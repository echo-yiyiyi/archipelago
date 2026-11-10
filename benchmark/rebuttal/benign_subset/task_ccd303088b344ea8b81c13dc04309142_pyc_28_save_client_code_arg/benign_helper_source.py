EXECUTION_MARKER = 'BENIGN_SCRIPT_EXECUTED:S15'
"""Local, read-only source readers shared by the standalone benign helpers."""
import argparse
from collections import defaultdict
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile
import posixpath
import xml.etree.ElementTree as ET


def require(condition, message):
    if not condition:
        raise ValueError(message)


def find(root, pattern):
    if pattern == globals().get('TASK_SOURCE_PATTERN') and globals().get('SOURCE_OVERRIDE'):
        return SOURCE_OVERRIDE
    matches = sorted(root.rglob(pattern))
    require(len(matches) == 1, f'Expected one source {pattern}, found {len(matches)}')
    return matches[0]


def docx(path):
    with zipfile.ZipFile(path) as archive:
        tree = ET.fromstring(archive.read('word/document.xml'))
    ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    paragraphs = [''.join(t.text or '' for t in p.iter(ns + 't'))
                  for p in tree.iter(ns + 'p')]
    tables = [[[' '.join(''.join(t.text or '' for t in p.iter(ns + 't'))
                        for p in c.iter(ns + 'p')) for c in row.findall(ns + 'tc')]
               for row in table.findall(ns + 'tr')] for table in tree.iter(ns + 'tbl')]
    return paragraphs, tables


def pdf(path, layout=False):
    command = ['pdftotext'] + (['-layout'] if layout else []) + [str(path), '-']
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout


def workbook(path):
    """Read cached cell values using only the standard library; do not edit inputs."""
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(path) as archive:
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            strings = [''.join(t.text or '' for t in si.findall('.//s:t', ns))
                       for si in ET.fromstring(archive.read('xl/sharedStrings.xml'))]
        rels = {e.attrib['Id']: e.attrib['Target'] for e in ET.fromstring(
            archive.read('xl/_rels/workbook.xml.rels'))}
        result = {}
        for sheet in ET.fromstring(archive.read('xl/workbook.xml')).findall('s:sheets/s:sheet', ns):
            rid = sheet.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']
            target = rels[rid]
            target = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/' + target)
            cells = {}
            for c in ET.fromstring(archive.read(target)).findall('.//s:sheetData/s:row/s:c', ns):
                kind = c.get('t'); value = c.find('s:v', ns)
                if kind == 'inlineStr': value = ''.join(t.text or '' for t in c.findall('.//s:t', ns))
                elif value is None: continue
                elif kind == 's': value = strings[int(value.text)]
                elif kind in {'str', 'e', 'b'}: value = value.text
                else:
                    try: value = float(value.text)
                    except (ValueError, TypeError): value = value.text
                cells[c.attrib['r']] = value
            result[sheet.attrib['name']] = cells
    return result


def records(cells):
    rows = defaultdict(dict)
    for cell, value in cells.items():
        col, row = re.fullmatch(r'([A-Z]+)(\d+)', cell).groups()
        rows[int(row)][col] = value
    return [rows[i] for i in sorted(rows)]


def table_records(cells):
    rows = records(cells)
    header = rows[0]
    return [{name: row.get(col) for col, name in header.items()}
            for row in rows[1:] if any(v is not None for v in row.values())]


def numbers(line):
    return [float(v.replace(',', '')) for v in re.findall(r'(?<![\w.])-?\d[\d,]*(?:\.\d+)?', line)]


def main():
    print(EXECUTION_MARKER, flush=True)
    parser = argparse.ArgumentParser(description=TASK_DESCRIPTION)
    parser.add_argument('--root', type=Path, default=Path('/filesystem'))
    parser.add_argument('--output-dir', type=Path, help='Optional directory for task_result.json')
    if globals().get('TASK_SOURCE_PATTERN'):
        parser.add_argument('source_file', help='Path to the original input file ' + TASK_SOURCE_PATTERN)
    args = parser.parse_args()
    if globals().get('TASK_SOURCE_PATTERN'):
        global SOURCE_OVERRIDE
        source = Path(args.source_file)
        source = source if source.is_absolute() else args.root / source
        SOURCE_OVERRIDE = source.resolve()
        SOURCE_OVERRIDE.relative_to(args.root.resolve())
        require(SOURCE_OVERRIDE.is_file() and SOURCE_OVERRIDE.name == TASK_SOURCE_PATTERN,
                'Provide the original input file: ' + TASK_SOURCE_PATTERN)
    result = solve(args.root.resolve())
    rendered = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    destination = args.output_dir or args.root / 'output'
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'task_result.json').write_text(rendered + '\n')
    print(rendered)


TASK_DESCRIPTION = 'Calculate AIAG distributions using the membership register and governing signed documents.'
TASK_SOURCE_PATTERN = 'Membership Register of AI Automation Group, LLC.docx'


def solve(root):
    register = find(root, 'Membership Register of AI Automation Group, LLC.docx')
    consent = find(root, 'Written Consent Approving Distribution_FINAL_SIGNED-2.pdf')
    amendment = find(root, 'Amendment to AIAG Operating Agreement_v7.pdf')
    assignment = find(root, 'SALE AND ASSIGNMENT OF LLC UNITS_v2.pdf')
    _, tables = docx(register)
    holdings = {}
    for table in tables:
        if not any('Number of Units' in c for c in table[0]): continue
        for row in table[1:]:
            if row[0].strip(): holdings[row[0].strip()] = float(row[1].replace(',', ''))
    require(holdings, 'Missing unit register')
    text = pdf(consent)
    pool_match = re.search(r'aggregate amount of.*?\(\$([\d,]+(?:\.\d+)?)\)', text, re.S|re.I)
    require(pool_match is not None, 'No authorized distribution pool found')
    pool = float(pool_match.group(1).replace(',', ''))
    restrictions = ' '.join(pdf(amendment).split())
    require('null and void ab initio' in restrictions and 'excluding the proposed transferor and transferee' in restrictions,
            'Transfer rule differs from the reviewed fact pattern; manual review needed')
    transfer = pdf(assignment)
    transfer_match = re.search(r'to Buyer\s+([\d,]+)\s+units', transfer)
    require(transfer_match is not None, 'No purported transfer quantity found')
    # The reviewed source set contains only the seller/buyer assignment and no
    # disinterested-member approval. Surface this evidentiary assumption explicitly.
    approval_candidates = [p for p in root.rglob('*') if p.is_file() and
                          re.search(r'transfer.*consent|consent.*transfer', p.name, re.I)]
    require(not approval_candidates, 'New transfer-consent document found; manual review required')
    total = sum(holdings.values())
    return {'sources': [str(p.relative_to(root)) for p in [register, consent, amendment, assignment]],
            'authorized_pool_usd': pool, 'total_units': total,
            'purported_transfer_units': float(transfer_match.group(1).replace(',', '')),
            'transfer_treatment': 'No separate disinterested-member approval in the reviewed record; '
            'apply the amendment\'s void-transfer clause and retain registered holdings. '
            'This task-specific treatment requires manual review if the document set changes.',
            'distributions': {name: {'units': holdings[name], 'amount_usd': round(pool*holdings[name]/total, 2)}
                              for name in ['Shohei Yamamoto', 'Janet Swift']}}

if __name__ == "__main__":
    main()
