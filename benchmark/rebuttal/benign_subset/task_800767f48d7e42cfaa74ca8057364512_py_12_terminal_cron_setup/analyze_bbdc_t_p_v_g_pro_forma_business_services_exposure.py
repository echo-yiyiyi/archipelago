EXECUTION_MARKER = 'BENIGN_SCRIPT_EXECUTED:S10'
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


TASK_DESCRIPTION = 'Calculate BBDC/TPVG pro forma business-services exposure from the September 2025 10-Qs.'


def solve(root):
    bbdc_path = find(root, 'BBDC_10Q_09.30.2025.pdf')
    tpvg_path = find(root, 'TPVG_10Q_09.30.2025.pdf')
    b = pdf(bbdc_path, True)
    t = pdf(tpvg_path, True)
    # The first balance-sheet line is the current-period value; the second is the prior period.
    btotal_line = next(l for l in b.splitlines() if re.search('Total investments at fair value', l, re.I))
    ttotal_line = next(l for l in t.splitlines() if 'Investments at fair value (amortized cost' in l)
    btotal = numbers(btotal_line)[0]
    ttotal = numbers(ttotal_line.split('respectively)')[-1])[0]
    # Restrict investment schedules to September, before the December comparative schedule.
    bstart = b.index('Unaudited Consolidated Schedule of Investments')
    bprior = re.search(r'Consolidated Schedule of Investments\s+December 31, 2024', b[bstart:])
    require(bprior is not None, 'Cannot locate prior-period BBDC schedule boundary')
    bcurrent = b[bstart:bstart + bprior.start()]
    lines = bcurrent.splitlines()
    subtotals = []
    for i, line in enumerate(lines):
        if 'Subtotal Services: Business' not in line: continue
        tail = line.split(')*')[-1].strip()
        if not tail:
            tail = next((s.strip() for s in lines[i+1:i+4] if s.strip()), '')
        require(tail, 'Empty BBDC business subtotal')
        vals = numbers(tail)
        subtotals.append(vals[-1] if vals else 0.0)
    require(len(subtotals) == 4, f'Expected four BBDC business subtotals, got {len(subtotals)}')
    # TPVG schedule is immediately followed by its December comparative schedule.
    start_match = re.search(r'CONSOLIDATED SCHEDULE OF INVESTMENTS\s*(?:\([^\n]*\)\s*)?(?:As of\s+)?September 30, 2025', t, re.I)
    require(start_match is not None, 'Cannot locate current-period TPVG schedule')
    tstart = start_match.start()
    prior = re.search(r'Consolidated Schedule of Investments\s*(?:\([^\n]*\)\s*)?(?:As of\s+)?December 31, 2024', t[tstart:], re.I)
    require(prior is not None, 'Cannot locate prior-period TPVG schedule boundary')
    current = t[tstart:tstart + prior.start()]
    tsub = [numbers(line.split('*', 1)[-1])[-1] for line in current.splitlines()
            if 'Total Business Products and Services -' in line]
    require(len(tsub) == 3, f'Expected three TPVG business subtotals, got {len(tsub)}')
    muon = []
    lines = current.splitlines()
    for i, line in enumerate(lines):
        if 'Muon Space, Inc.' not in line: continue
        if 'Preferred Stock' in line:
            muon.append(numbers(line)[-1])
        elif 'Growth Capital Loan' in line:
            # Sum the two loan fair values via their printed issuer subtotal.
            block = lines[i+1:i+7]
            candidates = [numbers(l) for l in block if re.fullmatch(r'[\s\d,]+', l) and len(numbers(l)) == 3]
            require(len(candidates) == 1, 'Ambiguous Muon loan subtotal')
            muon.append(candidates[0][-1])
    require(len(muon) == 2, 'Expected Muon loan and warrant holdings')
    numerator = sum(subtotals) + sum(tsub) - sum(muon)
    denominator = btotal + ttotal
    return {'sources': [str(p.relative_to(root)) for p in [bbdc_path, tpvg_path]],
            'units': 'USD thousands', 'bbdc_business_subtotals': subtotals,
            'tpvg_business_subtotals': tsub, 'muon_excluded': muon,
            'business_services_fair_value': numerator, 'total_fair_value': denominator,
            'exposure_percent': round(numerator / denominator * 100, 2)}


if __name__ == "__main__":
    main()
