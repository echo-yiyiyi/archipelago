#!/usr/bin/env python3
"""Copy with, disabling only first-instruction sibling cleanup."""
import ast
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT/'with'
OUTPUT=ROOT/'without_restore_other_txt'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')


def patch(source):
    tree=ast.parse(source)
    watcher=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Watcher')
    method=next(n for n in watcher.body if isinstance(n,ast.FunctionDef) and n.name=='tick')
    lines=source.splitlines(keepends=True)
    lines[method.lineno-1:method.end_lineno]=[
        '    def tick(self):\n',
        '        # Keep sibling corrupted files and instruction TXT after first selection.\n',
        '        # Goal-category activity still calls the unchanged restore() method.\n',
        '        return\n']
    result=''.join(lines)
    ast.parse(result)
    return result


def validate():
    config_name='selected_10_tasks_with_attack_config.json'
    assert (OUTPUT/config_name).read_bytes()==(SOURCE/config_name).read_bytes()
    sampled='selected_10_tasks_with_inject_goals.json'
    assert (OUTPUT/sampled).read_bytes()==(SOURCE/sampled).read_bytes()
    rows=json.loads((OUTPUT/config_name).read_text())
    assert len(rows)==len({r['task_id'] for r in rows})==len({r['inject_goal'] for r in rows})==10
    for row in rows:
        for name in {row['attack_file'],row['watcher_file'],row['watcher_config'],*row['populate_files']}:
            path=(OUTPUT/name).resolve()
            assert path.is_relative_to(OUTPUT.resolve()) and path.is_file()
            if name==row['watcher_file']:
                assert path.read_text()==patch((SOURCE/name).read_text())
            else:
                assert path.read_bytes()==(SOURCE/name).read_bytes()
    return len(rows)


def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    if any(OUTPUT.iterdir()):raise FileExistsError(f'Refusing to overwrite {OUTPUT}')
    rows=json.loads((SOURCE/'selected_10_tasks_with_attack_config.json').read_text())
    manifest={'source':'../with','variant':'without_restore_other_txt','changed_watcher_methods':['tick'],
        'source_config_sha256':sha(SOURCE/'selected_10_tasks_with_attack_config.json'),'tasks':[]}
    with tempfile.TemporaryDirectory(prefix='.without-restore-other-',dir=ROOT) as temporary:
        stage=Path(temporary)
        for row in rows:
            for name in {row['attack_file'],row['watcher_file'],row['watcher_config'],*row['populate_files']}:
                source=(SOURCE/name).resolve();dest=(stage/name).resolve()
                if not source.is_relative_to(SOURCE.resolve()) or not dest.is_relative_to(stage):raise ValueError(name)
                dest.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(source,dest)
                if name==row['watcher_file']:dest.write_text(patch(source.read_text()))
            manifest['tasks'].append({'task_id':row['task_id'],'inject_goal':row['inject_goal'],
                'harmful_task_id':row['harmful_task_id'],'watcher_sha256':sha(stage/row['watcher_file'])})
        for name in ('selected_10_tasks_with_attack_config.json','selected_10_tasks_with_inject_goals.json'):
            shutil.copy2(SOURCE/name,stage/name)
        write(stage/'selection_manifest.json',manifest)
        if any(OUTPUT.iterdir()):raise FileExistsError('Destination changed during generation')
        for entry in stage.iterdir():entry.rename(OUTPUT/entry.name)
    count=validate()
    write(OUTPUT/'validation_report.json',{'status':'passed','records':count,'checks':[
        '10 task IDs and goal IDs aligned with with','task JSON files byte-identical',
        'only watcher tick method changed','all other artifacts and templates byte-identical'],
        'evaluations_run':False})
    print(f'Validated {count} without_restore_other_txt records')


if __name__=='__main__':main()
