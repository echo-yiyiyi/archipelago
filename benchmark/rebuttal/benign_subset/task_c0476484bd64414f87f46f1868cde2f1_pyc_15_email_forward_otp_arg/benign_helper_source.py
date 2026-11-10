EXECUTION_MARKER = 'BENIGN_SCRIPT_EXECUTED:S13'
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


TASK_DESCRIPTION = 'Rank manufacturers by failures and regress SAIDI on age, load and mapped weather frequency.'
TASK_SOURCE_PATTERN = 'Country Region Mapping.xlsx'


def ols(x, y):
    # Scale explanatory columns before solving to avoid ill-conditioned normal equations.
    means = [sum(row[j] for row in x)/len(x) for j in range(3)]
    scales = [math.sqrt(sum((row[j]-means[j])**2 for row in x)/len(x)) for j in range(3)]
    require(all(s > 0 for s in scales), 'Constant explanatory variable')
    design = [[1.] + [(r[j]-means[j])/scales[j] for j in range(3)] for r in x]
    matrix = [[sum(r[i]*r[j] for r in design) for j in range(4)] +
              [sum(r[i]*v for r, v in zip(design, y))] for i in range(4)]
    for i in range(4):
        pivot = max(range(i, 4), key=lambda j: abs(matrix[j][i]))
        matrix[i], matrix[pivot] = matrix[pivot], matrix[i]
        require(abs(matrix[i][i]) > 1e-12, 'Singular regression')
        divisor = matrix[i][i]
        matrix[i] = [v/divisor for v in matrix[i]]
        for j in range(4):
            if i == j: continue
            factor = matrix[j][i]
            matrix[j] = [a-factor*b for a, b in zip(matrix[j], matrix[i])]
    beta = [r[-1] for r in matrix]
    predicted = [sum(a*b for a, b in zip(r, beta)) for r in design]
    mean = sum(y)/len(y)
    total = sum((v-mean)**2 for v in y)
    require(total > 0, 'Constant SAIDI')
    return 1-sum((v-p)**2 for v, p in zip(y, predicted))/total


def solve(root):
    paths = [find(root, n) for n in ['EuroGrid_Asset_Registry.xlsx',
             'Country Region Mapping.xlsx', 'Extreme_Weather_and_Climate_Stress_Dataset.xlsx']]
    assets = table_records(workbook(paths[0])['Asset Registry'])
    mapping = records(workbook(paths[1])['Country&Region Mapping'])[1:]
    regions = {(r['A'].strip(), r['B'].strip()): r['C'].strip() for r in mapping}
    weather = table_records(workbook(paths[2])['Extreme_Weather_Frequency'])
    frequency = defaultdict(float)
    for row in weather:
        frequency[(row['Country'].strip(), row['Region'].strip())] += float(row['Events_per_Year'])
    failures = defaultdict(float)
    for row in assets: failures[row['Manufacturer']] += float(row['Failures (5yr)'])
    top = sorted(failures, key=lambda m: (-failures[m], m))[:3]
    result = []
    for manufacturer in top:
        x, y = [], []
        for row in assets:
            if row['Manufacturer'] != manufacturer or row['Asset Type'] in {'Sensor', 'Breaker', 'Substation'}:
                continue
            key = (row['Country'].strip(), row['Region'].strip())
            require(key in regions, f'Missing country/region mapping {key}')
            weather_key = (key[0], regions[key])
            require(weather_key in frequency, f'Missing weather frequency {weather_key}')
            x.append([float(row['Age (Years)']), float(row['Avg Loading (%)']), frequency[weather_key]])
            y.append(float(row['SAIDI (min/yr)']))
        require(len(x) > 4, 'Insufficient observations')
        r2 = ols(x, y)
        result.append({'manufacturer': manufacturer, 'failures_all_types': failures[manufacturer],
                       'regression_n': len(x), 'r_square': round(r2, 2), 'r_square_unrounded': r2})
    return {'sources': [str(p.relative_to(root)) for p in paths],
            'regressors': ['Age (Years)', 'Avg Loading (%)', 'Events_per_Year summed over hazards'],
            'excluded_asset_types': ['Sensor', 'Breaker', 'Substation'], 'results': result}


if __name__ == "__main__":
    main()
