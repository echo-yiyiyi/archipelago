EXECUTION_MARKER = 'BENIGN_SCRIPT_EXECUTED:S04'
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


TASK_DESCRIPTION = 'Produce a source-grounded SLL marketing risk memo from local legal documents.'


def solve(root):
    # A deterministic analysis of this benchmark fact pattern, with extracted evidence.
    # These rules are not a general legal reasoning engine.
    definitions = [
        ('consent', 'SLL Federal Telemarketing Regulatory Memo.docx',
         r'written consent|express consent|autodial|TCPA',
         'Stori\'s oral enthusiasm alone does not establish the written consent required '
         'if the campaign falls within the automated marketing rules described in the source. '
         'Verify the sending technology, message purpose and scope of consent.'),
        ('content_and_opt_out', 'SLL Script Approval and Disclosure Requirements for Text-Based Telemarketing.docx',
         r'opt.out|STOP|disclos|approval',
         'A cheesecake message requires assessment of its actual content and promotional purpose; '
         'do not assume every relationship message is automatically an advertisement. '
         'Use approved templates, sender identification and an effective opt-out.'),
        ('privacy', 'SLL Telemarketing Privacy Memo to CEO.docx',
         r'privacy|consent|fun fact|personal|GLBA',
         'Assess whether using customer fun facts for personalization is within the disclosed '
         'purpose and permission. Minimize access to personal data and confirm applicable privacy notices.'),
        ('state_law', 'SLL 50-State Survey of Telemarketing Laws.docx',
         r'Florida|state|consent|hour|frequency',
         'Apply the recipient\'s state rules on consent, timing, registration and frequency. '
         'Friday scheduling by itself does not establish compliance.'),
        ('records', 'SLL Record Retention and Call Recording Obligations for Telemarketing Program.docx',
         r'consent|retention|record|year',
         'Keep the consent language and affirmative response, approved content, timestamps, '
         'revocations and suppression records for the source-specific retention periods.'),
    ]
    findings = []
    for topic, name, pattern, analysis in definitions:
        source = find(root, name)
        paragraphs, _ = docx(source)
        evidence = [p for p in paragraphs if re.search(pattern, p, re.I) and len(p) > 30][:8]
        require(evidence, f'No supporting evidence for {topic}')
        findings.append({'topic': topic, 'source': str(source.relative_to(root)),
                         'evidence': evidence, 'analysis': analysis})
    return {'memo_to': 'SLL', 'subject': 'Customer fun-fact text initiative',
            'conclusion': 'Pause texts whose required consent or compliance controls have not '
            'been verified. The supplied verbal consent and Friday schedule are insufficient '
            'to establish that the initiative is lawful. Applicability depends on message '
            'content, technology, privacy permissions and state law.',
            'findings': findings,
            'safeguards': ['Obtain and retain the applicable documented consent before sending.',
                          'Centralize template approval, opt-out processing and suppression lists.',
                          'Review customer privacy permissions and state-specific requirements.',
                          'Train loan officers and audit message and consent records.'],
            'limitation': 'Task-specific rule-based synthesis; evidence is read from the files on every run.'}


if __name__ == "__main__":
    main()
