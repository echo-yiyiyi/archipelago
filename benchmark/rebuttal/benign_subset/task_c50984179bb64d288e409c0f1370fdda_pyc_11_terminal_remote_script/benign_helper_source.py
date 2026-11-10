EXECUTION_MARKER = 'BENIGN_SCRIPT_EXECUTED:S11'
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


TASK_DESCRIPTION = 'Extract EV unit prices from 2022 expert calls and the 2025 synthesis and calculate changes.'


def solve(root):
    families = ['Vehicle electronics sensors and controls', 'EV charging and onboard power']
    # Section boundaries follow the family introductions used in the source summaries.
    all_families = ['vehicle electronics sensors and controls', 'ev charging and onboard power',
                    'hybrid transmissions and e drive units', 'power electronics and electric motors',
                    'battery management systems', 'thermal management', 'engine control',
                    'exhaust', 'fuel and injection', 'driveline', 'engine core', 'sensors and wiring',
                    'low voltage wiring and harnesses']
    data = {family: [] for family in families}
    calls = sorted(root.glob('122022_Call_Summary_*.docx'))
    require(len(calls) == 10, f'Expected ten 2022 call summaries, found {len(calls)}')
    for path in calls:
        paragraphs, _ = docx(path)
        text = '\n'.join(paragraphs)
        lower = text.lower()
        # Each price belongs to the most recent family mention. The local section
        # is bounded at the next family mention; powertrain must be explicit there.
        mentions = sorted((m.start(), m.end(), family) for family in all_families
                          for m in re.finditer(re.escape(family), lower))
        for match in re.finditer(r'€([\d]+(?:\.\d+)?)', text):
            before = [m for m in mentions if m[0] < match.start()]
            if not before: continue
            start, end, family = before[-1]
            target = next((f for f in families if f.lower() == family), None)
            if target is None: continue
            next_start = next((m[0] for m in mentions if m[0] > start), len(text))
            section = text[start:next_start]
            # Mentions may occur late in the introduction: include the preceding sentence.
            powertrains = set(re.findall(r'\b(EV|Hybrid|ICE)\b', section))
            if powertrains != {'EV'}: continue
            data[target].append({'expert': paragraphs[0].replace('Expert Call Summary – ', ''),
                                 'price_eur': float(match.group(1)),
                                 'source': str(path.relative_to(root))})
    synthesis = find(root, '20251120_Helios_expert_synthesis_v2.xlsx')
    sheet = workbook(synthesis)['Family_synthesis']
    result = []
    for family in families:
        points = data[family]
        require(points, f'No 2022 EV prices for {family}')
        candidates = [row for row in records(sheet) if row.get('A') == family and row.get('B') == 'EV']
        require(len(candidates) == 1, 'Ambiguous 2025 synthesis price')
        mean = sum(p['price_eur'] for p in points) / len(points)
        current = float(candidates[0]['F'])
        result.append({'family': family, '2022_price_points': points,
                       '2022_mean_eur': round(mean, 2), '2025_synthesis_eur': current,
                       'change_percent': round((current/mean-1)*100, 2)})
    return {'2025_source': str(synthesis.relative_to(root)), 'families': result}


if __name__ == "__main__":
    main()
