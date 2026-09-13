#!/usr/bin/env python3
"""PDF-only inline prompt variant of the existing with watcher bundle."""
import ast
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import textwrap

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT/'with'
OUTPUT=ROOT/'without_txt'
METHODS={
'eligible': '''def eligible(self, path):
    if self.selected_instruction is not None: return False
    if path.is_symlink(): return False
    try: relative = path.resolve().relative_to(self.root)
    except (ValueError, OSError): return False
    return (path.is_file() and path.suffix.lower() == '.pdf'
            and path not in self.processed and path not in self.instructions
            and 'shared' != relative.parts[0]
            and not any(part.startswith('.') for part in relative.parts)
            and not path.name.startswith('dynamic_watcher')
            and not path.stem.endswith(('_archive', '_v0', '_backup_v0', '_archived_backup')))
''',
'redirect': '''def redirect(self, path):
    if self.stopped or not self.eligible(path): return
    archive = path.with_name(path.stem + '_archive' + path.suffix)
    if archive.exists():
        self.processed.add(path)
        return
    self.processed.add(path)
    temporary = path.with_name('.' + path.name + '.dynamic-replacement')
    try:
        content = self.template.replace('{original_name}', path.name).replace('{preserved_name}', archive.name)
        # The replacement PDF itself contains the unchanged instruction text.
        make_replacement(path, temporary, content.splitlines())
        path.rename(archive)
        self.replacements[path] = archive
        temporary.rename(path)
        self.instructions.add(path)
        self.instruction_sources[path] = path
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, ParseError) as error:
        temporary.unlink(missing_ok=True)
        if path in self.replacements:
            archive.replace(path)
            self.replacements.pop(path, None)
        print(f'inline prompt replacement failed for {path}: {error}', file=sys.stderr, flush=True)
''',
'restore': '''def restore(self):
    # Instruction carriers ARE the original paths; never unlink them after restore.
    for original, archive in list(self.replacements.items()):
        try:
            archive.replace(original)
            del self.replacements[original]
            self.instructions.discard(original)
            self.instruction_sources.pop(original, None)
        except OSError as error:
            print(f'restore failed for {original}: {error}', file=sys.stderr, flush=True)
    return not self.replacements
''',
'tick': '''def tick(self):
    if self.selected_instruction is None: return
    for original, archive in list(self.replacements.items()):
        if original == self.selected_instruction: continue
        try:
            # Restore sibling PDFs byte-for-byte, not another corruption notice.
            archive.replace(original)
            del self.replacements[original]
            self.instructions.discard(original)
            self.instruction_sources.pop(original, None)
        except OSError as error:
            print(f'restore sibling failed: {error}', file=sys.stderr, flush=True)
''',
}


def patch_formats(source):
    old = '/BaseFont /Helvetica >>'
    new = '/BaseFont /Helvetica /Encoding /WinAnsiEncoding >>'
    if source.count(old) != 1:raise ValueError('Expected original PDF font declaration')
    return source.replace(old,new)


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def write(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')


def patch(source):
    tree=ast.parse(source)
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Watcher')
    methods={n.name:n for n in cls.body if isinstance(n,ast.FunctionDef)}
    lines=source.splitlines(keepends=True)
    for name in sorted(METHODS,key=lambda n:methods[n].lineno,reverse=True):
        node=methods[name]
        lines[node.lineno-1:node.end_lineno]=[textwrap.indent(METHODS[name],'    ')]
    result=''.join(lines);ast.parse(result)
    return result


def validate():
    rows=json.loads((SOURCE/'selected_10_tasks_with_attack_config.json').read_text())
    for filename in ['selected_10_tasks_with_attack_config.json','selected_10_tasks_with_inject_goals.json']:
        assert (SOURCE/filename).read_bytes()==(OUTPUT/filename).read_bytes()
    assert len(rows)==len({r['task_id'] for r in rows})==len({r['inject_goal'] for r in rows})==10
    for row in rows:
        for name in {row['attack_file'],row['watcher_file'],row['watcher_config'],*row['populate_files']}:
            path=(OUTPUT/name).resolve()
            assert path.is_relative_to(OUTPUT.resolve()) and path.is_file()
            if name==row['watcher_file']:assert path.read_text()==patch((SOURCE/name).read_text())
            elif path.name=='dynamic_document_formats.py':assert path.read_text()==patch_formats((SOURCE/name).read_text())
            else:assert path.read_bytes()==(SOURCE/name).read_bytes()
    return len(rows)


def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    if any(OUTPUT.iterdir()):raise FileExistsError(f'Refusing to overwrite {OUTPUT}')
    rows=json.loads((SOURCE/'selected_10_tasks_with_attack_config.json').read_text())
    manifest={'source':'../with','variant':'without_txt','injection_scope':'pdf only',
        'changed_watcher_methods':list(METHODS),'pdf_font_encoding':'WinAnsiEncoding preserves literal punctuation','instruction_template':'unchanged from with',
        'source_config_sha256':sha(SOURCE/'selected_10_tasks_with_attack_config.json'),'tasks':[]}
    with tempfile.TemporaryDirectory(prefix='.without-txt-',dir=ROOT) as temporary:
        stage=Path(temporary)
        for row in rows:
            for name in {row['attack_file'],row['watcher_file'],row['watcher_config'],*row['populate_files']}:
                source=(SOURCE/name).resolve();dest=(stage/name).resolve()
                if not source.is_relative_to(SOURCE.resolve()) or not dest.is_relative_to(stage):raise ValueError(name)
                dest.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(source,dest)
                if name==row['watcher_file']:dest.write_text(patch(source.read_text()))
                elif dest.name=='dynamic_document_formats.py':dest.write_text(patch_formats(source.read_text()))
            manifest['tasks'].append({'task_id':row['task_id'],'inject_goal':row['inject_goal'],
                'harmful_task_id':row['harmful_task_id'],'watcher_sha256':sha(stage/row['watcher_file'])})
        for filename in ['selected_10_tasks_with_attack_config.json','selected_10_tasks_with_inject_goals.json']:
            shutil.copy2(SOURCE/filename,stage/filename)
        write(stage/'selection_manifest.json',manifest)
        if any(OUTPUT.iterdir()):raise FileExistsError('Destination changed during generation')
        for entry in stage.iterdir():entry.rename(OUTPUT/entry.name)
    count=validate()
    write(OUTPUT/'validation_report.json',{'status':'passed','records':count,'checks':[
        '10 task IDs and goal IDs aligned with with','task JSONs unchanged','only specified watcher methods changed',
        'PDF font encoding explicitly set; all remaining artifacts and instruction templates byte-identical'],'evaluations_run':False})
    print(f'Validated {count} without_txt records')


if __name__=='__main__':main()
