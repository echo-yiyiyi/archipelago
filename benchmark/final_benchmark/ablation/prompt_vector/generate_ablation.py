#!/usr/bin/env python3
"""Create nine paired prompt carriers from five existing task/goal pairs."""
import hashlib
import html
import json
import mailbox
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import tempfile
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent
BENCHMARK = ROOT.parents[2]
sys.path.insert(0, str(BENCHMARK.parent))
from benchmark.generate_attack_file.templates import generate_file, _xlsx_bytes

VECTORS = ('email', 'txt', 'xlsx', 'word', 'md', 'chat', 'html', 'pdf', 'calendar')
SOURCE = BENCHMARK / 'final_benchmark/static_prompt_injection/selected_30_tasks_with_attack_config.json'


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def rewrite(value, old, new):
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, list):
        return [rewrite(v, old, new) for v in value]
    if isinstance(value, dict):
        return {k: rewrite(v, old, new) for k, v in value.items()}
    return value


def select():
    candidates = json.loads(SOURCE.read_text())
    random.Random(42).shuffle(candidates)
    chosen = []
    for row in candidates:
        if row['task_id'] in {r['task_id'] for r in chosen} or row['inject_goal'] in {r['inject_goal'] for r in chosen}:
            continue
        chosen.append(row)
        if len(chosen) == 5:
            return chosen
    raise ValueError('Cannot select five distinct task IDs and goals')


def content(row):
    return ('Task Reference: ' + row['keywords'][0] + '\n\nKeywords: ' + ', '.join(row['keywords'])
            + '\n\nAdditional Task Instruction:\n\n' + row['attack_config']['cot'])


def docx(path, text):
    ns = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    ET.register_namespace('w', ns)
    document = ET.Element(f'{{{ns}}}document')
    body = ET.SubElement(document, f'{{{ns}}}body')
    for line in text.split('\n'):
        p = ET.SubElement(body, f'{{{ns}}}p')
        run = ET.SubElement(p, f'{{{ns}}}r')
        node = ET.SubElement(run, f'{{{ns}}}t', {'{http://www.w3.org/XML/1998/namespace}space': 'preserve'})
        node.text = line
    with ZipFile(path, 'w', ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr('_rels/.rels', '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr('word/document.xml', ET.tostring(document, encoding='utf-8', xml_declaration=True))


def carrier(row, vector, directory):
    text = content(row)
    title = 'Task Reference: ' + row['keywords'][0]
    stem = re.sub(r'[^A-Za-z0-9]+', '_', row['keywords'][0]).strip('_') + '_Task_Reference'
    token = row['task_id'].removeprefix('task_')[:12]
    if vector in ('txt', 'md'):
        path = directory / f'{stem}.{vector}'
        path.write_text(text + '\n')
    elif vector == 'html':
        path = directory / f'{stem}.html'
        path.write_text('<!doctype html><html><head><meta charset="utf-8"><title>' + html.escape(title)
                       + '</title></head><body><pre>' + html.escape(text) + '</pre></body></html>\n')
    elif vector == 'xlsx':
        path = directory / f'{stem}.xlsx'
        path.write_bytes(_xlsx_bytes('Task Reference', [[line] for line in text.split('\n')]))
    elif vector in ('word', 'pdf'):
        path = directory / f'{stem}.docx'
        docx(path, text)
    elif vector == 'email':
        path = generate_file(vector, {'sender_name': 'Task Coordinator', 'sender_email': 'coordinator@benchmark.local',
            'recipient_email': 'assistant@benchmark.local', 'date': 'Thu, 20 Feb 2025 14:00:00 +0000',
            'message_id': f'<reference-{token}@benchmark.local>', 'subject': title, 'body': text}, directory)
    elif vector == 'chat':
        path = generate_file(vector, {'group_name': f'{title} {token}', 'creator_name': 'Task Coordinator',
            'creator_email': 'coordinator@benchmark.local', 'created_date': 'Thursday, 20 February 2025 at 14:00:00 UTC',
            'text': text, 'topic_id': f'reference-{token}', 'message_id': f'reference-{token}'}, directory)
    else:
        path = generate_file('calendar', {'file_name': f'task-reference-{token}.ics', 'uid': f'task-reference-{token}',
            'start': '20250220T140000Z', 'end': '20250220T150000Z', 'summary': title,
            'description': text, 'location': 'Task reference'}, directory)
    return path


def extracted(path, vector):
    if vector in ('txt', 'md'):
        return path.read_text().strip()
    if vector == 'html':
        return html.unescape(path.read_text().split('<pre>', 1)[1].split('</pre>', 1)[0])
    if vector in ('word', 'xlsx'):
        with ZipFile(path) as z:
            member = 'word/document.xml' if vector == 'word' else 'xl/worksheets/sheet1.xml'
            tree = ET.fromstring(z.read(member))
            return '\n'.join(e.text or '' for e in tree.iter() if e.tag.endswith('}t'))
    if vector == 'pdf':
        return subprocess.check_output(['pdftotext', '-layout', '-enc', 'UTF-8', str(path), '-'], text=True)
    if vector == 'email':
        for message in mailbox.mbox(str(path)):
            if str(message['Message-ID']).startswith('<reference-'):
                return message.get_payload(decode=True).decode(message.get_content_charset() or 'utf-8').strip()
        raise ValueError('Missing injection email')
    if vector == 'chat':
        return json.loads(path.read_text())['messages'][0]['text']
    value = next(line[len('DESCRIPTION:'):] for line in path.read_text().splitlines() if line.startswith('DESCRIPTION:'))
    return re.sub(r'\\([nN,;\\])', lambda m: '\n' if m[1].lower() == 'n' else m[1], value)


def validate():
    originals = select()
    canonical = None
    checks = 0
    for vector in VECTORS:
        folder = ROOT / vector
        rows = json.loads((folder / 'selected_5_tasks_with_attack_config.json').read_text())
        assert len(rows) == len({r['task_id'] for r in rows}) == len({r['inject_goal'] for r in rows}) == 5
        normalized = []
        for row, source in zip(rows, originals):
            assert row['inject_vector'] == vector
            assert (row['task_id'], row['inject_goal']) == (source['task_id'], source['inject_goal'])
            assert row['attack_config'] == rewrite(source['attack_config'], source['harmful_task_id'], row['harmful_task_id'])
            for name in row['populate_files']:
                path = (folder / name).resolve()
                assert path.is_relative_to(folder.resolve()) and path.is_file(), path
            actual = extracted(folder / row['attack_file'], vector)
            # PDF line wrapping is a layout difference; all Unicode characters must survive.
            assert re.sub(r'\s+', '', actual) == re.sub(r'\s+', '', content(source)), (vector, row['task_id'])
            for relative in source['populate_files']:
                if relative == source['attack_file']:
                    continue
                new = folder / relative.replace(source['harmful_task_id'], row['harmful_task_id'])
                original = (SOURCE.parent / relative).read_bytes()
                if new == folder / row['attack_file']:
                    assert new.read_bytes().startswith(original), new
                else:
                    assert new.read_bytes() == original, new
            normalized.append((row['task_id'], row['inject_goal'], row['prompt']))
            checks += 1
        if canonical is not None:
            assert normalized == canonical
        canonical = normalized
    write_json(ROOT / 'validation_report.json', {'status': 'passed', 'records': checks, 'distinct_task_goal_pairs': 5,
        'vectors': list(VECTORS), 'checks': ['unique task IDs and goals', 'same task/goal pairs across all carriers',
        'source attack configs retained with path updates only', 'decoded injection text matches across all nine formats (ignoring whitespace)',
        'supporting fixtures byte-identical or preserved as prefix of merged carrier', 'all populate files exist inside bundle'],
        'evaluations_run': False})
    print(f'Validated {checks} paired records', flush=True)


def main():
    originals = select()
    for vector in VECTORS:
        folder = ROOT / vector
        if folder.exists() and any(folder.iterdir()):
            raise FileExistsError(f'Refusing to overwrite {folder}')
    pending = []
    for vector in VECTORS:
        folder = ROOT / vector
        folder.mkdir(parents=True, exist_ok=True)
        rows = []
        for original in originals:
            old_id = original['harmful_task_id']
            new_id = f"{original['task_id']}_{vector}_{original['inject_goal']}"
            row = rewrite(original, old_id, new_id)
            row['inject_vector'] = vector
            directory = folder / new_id
            directory.mkdir()
            path = carrier(row, vector, directory)
            if vector == 'pdf':
                pending.append(path)
                path = path.with_suffix('.pdf')
            row['attack_file'] = str(path.relative_to(folder))
            row['populate_files'] = [row['attack_file']]
            for name in original['populate_files']:
                if name == original['attack_file']:
                    continue
                new = name.replace(old_id, new_id)
                dest = folder / new
                dest.parent.mkdir(parents=True, exist_ok=True)
                source = SOURCE.parent / name
                if dest.exists():
                    # Email injection and OTP fixture share the canonical mailbox path.
                    if vector != 'email' or dest != path:
                        raise ValueError(f'Unexpected artifact collision: {dest}')
                    dest.write_bytes(source.read_bytes() + b'\n' + dest.read_bytes())
                else:
                    shutil.copy2(source, dest)
                if new not in row['populate_files']:
                    row['populate_files'].append(new)
            rows.append(row)
        write_json(folder / 'selected_5_tasks_with_attack_config.json', rows)
        write_json(folder / 'selected_5_tasks_with_inject_goals.json',
                   [{k: v for k,v in row.items() if k not in {'attack_config','attack_file','populate_files'}} for row in rows])
    finish()


def finish():
    originals = select()
    pending = sorted((ROOT / 'pdf').glob('task_*/*.docx'))
    with tempfile.TemporaryDirectory(prefix='prompt-vector-office-') as temporary:
        profile = (Path(temporary) / 'profile').as_uri()
        for source in pending:
            subprocess.run(['libreoffice', f'-env:UserInstallation={profile}', '--headless', '--convert-to',
                            'pdf', '--outdir', str(source.parent), str(source)], check=True, timeout=60)
            if not source.with_suffix('.pdf').is_file():
                raise ValueError(f'PDF conversion failed: {source}')
            source.unlink()  # Conversion input only; PDF bundle contains just its PDF carrier.
    write_json(ROOT / 'selection_manifest.json', {'seed': 42, 'source': str(SOURCE.relative_to(BENCHMARK)),
        'source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(), 'vectors': list(VECTORS),
        'carrier_policy': 'Identical keyword-based reference header and original attack_config.cot across all carriers; neutral fixed app metadata; word means docx.',
        'tasks': [{'task_id': row['task_id'], 'inject_goal': row['inject_goal'],
                   'source_harmful_task_id': row['harmful_task_id'], 'text_sha256': hashlib.sha256(content(row).encode()).hexdigest()} for row in originals]})
    validate()


if __name__ == '__main__':
    if '--validate' in sys.argv:
        validate()
    elif '--finish' in sys.argv:
        finish()
    else:
        main()
