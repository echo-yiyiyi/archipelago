#!/usr/bin/env python3
"""Remove only prepared instruction TXT files from existing script bundles."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parent
VECTORS=('py','pyc','elf')


def is_instruction(name):
    p=Path(name)
    return p.suffix.lower()=='.txt' and '.apps_data' not in p.parts and 'instruction' in p.name.lower()


def write(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')


def expected(vector):
    source=ROOT.parent/vector/'selected_5_tasks_with_attack_config.json'
    originals=json.loads(source.read_text())
    rows=deepcopy(originals)
    removed=[]
    for row in rows:
        names=[n for n in row['populate_files'] if is_instruction(n)]
        if len(names)!=1:raise ValueError(f'Expected one instruction file: {row["harmful_task_id"]}')
        removed.extend(names)
        row['populate_files']=[n for n in row['populate_files'] if n not in names]
        row['omit_additional_instruction']=True
    return originals,rows,removed


def validate():
    count=0
    for vector in VECTORS:
        originals,expected_rows,removed=expected(vector)
        folder=ROOT/vector
        rows=json.loads((folder/'selected_5_tasks_with_attack_config.json').read_text())
        assert rows==expected_rows
        assert len(rows)==5
        for row in rows:
            assert not row.get('add_user_prompt',False)
            assert not any(is_instruction(n) for n in row['populate_files'])
            for name in row['populate_files']:
                dest=(folder/name).resolve()
                assert dest.is_relative_to(folder.resolve()) and dest.is_file()
                assert dest.read_bytes()==(ROOT.parent/vector/name).read_bytes()
            actual={str(p.relative_to(folder)) for p in (folder/row['harmful_task_id']).rglob('*') if p.is_file()}
            assert actual==set(row['populate_files'])
        assert all(not (folder/name).exists() for name in removed)
        count+=len(rows)
    return count


def main():
    if '--validate' in sys.argv:
        print(f'Validated {validate()} no-instruction records');return
    # Preserve the user's existing copied directories before replacing them.
    occupied=[ROOT/v for v in VECTORS if (ROOT/v).exists() and any((ROOT/v).iterdir())]
    if occupied:
        backup=Path('/data/ziyi/ablation_backups')/('no_txt_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
        backup.mkdir(parents=True)
        for folder in occupied:shutil.move(str(folder),str(backup/folder.name))
        print('Backup:',backup)
    manifest={'source':str(ROOT.parent),'omitted':'additional instruction TXT only','vectors':{}}
    for vector in VECTORS:
        _,rows,removed=expected(vector)
        folder=ROOT/vector;folder.mkdir(parents=True,exist_ok=True)
        for row in rows:
            for name in row['populate_files']:
                dest=folder/name;dest.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(ROOT.parent/vector/name,dest)
        write(folder/'selected_5_tasks_with_attack_config.json',rows)
        write(folder/'selected_5_tasks_with_inject_goals.json',
              [{k:v for k,v in row.items() if k not in {'attack_config','attack_file','populate_files'}} for row in rows])
        source=ROOT.parent/vector/'selected_5_tasks_with_attack_config.json'
        manifest['vectors'][vector]={'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'removed':removed}
    write(ROOT/'selection_manifest.json',manifest)
    count=validate()
    write(ROOT/'validation_report.json',{'status':'passed','records':count,'checks':[
        'configs equal baseline except removed populate files and explicit omission flag',
        'all retained artifacts byte-identical to baseline','instruction files absent',
        'goal-required TXT fixtures retained'], 'evaluations_run':False})
    print(f'Validated {count} no-instruction records')


if __name__=='__main__':main()
