#!/usr/bin/env python3
"""Prepare a 2 x 15 goal grid and invoke the unmodified benchmark pipeline."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
BENCHMARK = ROOT.parents[2]
REPO = BENCHMARK.parent
sys.path.insert(0,str(REPO))
from benchmark.final_benchmark.generate_static_prompt_injection_tasks import leakage_type

SOURCE = BENCHMARK/'final_benchmark/static_prompt_injection/selected_30_tasks_with_attack_config.json'
TASKS = ('task_800767f48d7e42cfaa74ca8057364512','task_f525769ab6a748e6855e03c95e4b4bd7')


def write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def paths(mode,kind,count):
    folder=ROOT/kind/f'{mode}_prompt_injection'
    return folder,folder/f'selected_{count}_tasks_with_inject_goals.json',folder/f'selected_{count}_tasks_with_attack_config.json'


def prepare(mode):
    source=json.loads(SOURCE.read_text())
    goals=sorted({r['inject_goal'] for r in source},key=lambda g:int(g.split('_')[0]))
    assert len(goals)==15
    base={task:next(r for r in source if r['task_id']==task) for task in TASKS}
    groups={'internal':[],'external':[]}
    vector='txt' if mode=='static' else 'dynamic_prompt_injection'
    for goal in goals:
        kind=leakage_type(goal)
        for task in TASKS:
            row={k:v for k,v in base[task].items() if k not in {
                'inject_goal','inject_vector','harmful_task_id','attack_config','attack_file',
                'attack_files','populate_files','watcher_file','watcher_config'}}
            row.update(inject_goal=goal,inject_vector=vector,leakage_type=kind,
                       harmful_task_id=f'{task}_{vector}_{goal}',add_user_prompt=False,no_key_words=mode=='dynamic')
            groups[kind].append(row)
    for kind,rows in groups.items():
        folder,sampled,_=paths(mode,kind,len(rows))
        folder.mkdir(parents=True,exist_ok=True)
        write(sampled,rows)
    name='selection_manifest.json' if mode=='static' else 'dynamic_selection_manifest.json'
    write(ROOT/name,{'source':str(SOURCE.relative_to(BENCHMARK)),'source_sha256':digest(SOURCE),
        'task_ids':list(TASKS),'domains':{t:base[t]['domain'] for t in TASKS},'inject_vector':vector,
        'goal_ids':goals,'record_count':30,'counts':{k:len(v) for k,v in groups.items()},
        'pipeline':'benchmark.generate_attack_config.generate','postprocessing':False})
    return groups


def snapshot(folder,final):
    files={final.name: digest(final)}
    for row in json.loads(final.read_text()):
        for name in {row['attack_file'],*row['populate_files']}:
            files[name]=digest(folder/name)
    return files


def validate(mode):
    pairs=set()
    prompts={}
    for kind,count in [('internal',16),('external',14)]:
        folder,sampled,final=paths(mode,kind,count)
        expected={r['harmful_task_id']:r for r in json.loads(sampled.read_text())}
        rows=json.loads(final.read_text())
        assert len(rows)==count and {r['harmful_task_id'] for r in rows}==set(expected)
        provenance=json.loads((folder/'pipeline_provenance.json').read_text())
        assert snapshot(folder,final)==provenance['output_sha256'], 'Pipeline output modified'
        for row in rows:
            original=expected[row['harmful_task_id']]
            for field in ('task_id','inject_goal','inject_vector','prompt','keywords','add_user_prompt','no_key_words','leakage_type'):
                assert row[field]==original[field],field
            assert row['attack_config']['leakage_type']==leakage_type(row['inject_goal'])==kind
            prompts.setdefault(row['task_id'],row['prompt'])
            assert prompts[row['task_id']]==row['prompt']
            for name in {row['attack_file'],*row['populate_files']}:
                artifact=(folder/name).resolve()
                assert artifact.is_relative_to(folder.resolve()) and artifact.is_file(),artifact
            if mode=='static':
                assert row['attack_file'].endswith('.txt')
                assert row['attack_config']['cot'].strip() in (folder/row['attack_file']).read_text()
            else:
                config=json.loads((folder/row['watcher_config']).read_text())
                assert config['attack_config']==row['attack_config']
                assert config['inject_goal']==row['inject_goal']
                assert '{original_name}' in config['instruction_template']
            pairs.add((row['task_id'],row['inject_goal']))
    manifest=json.loads((ROOT/('selection_manifest.json' if mode=='static' else 'dynamic_selection_manifest.json')).read_text())
    assert pairs=={(t,g) for t in TASKS for g in manifest['goal_ids']}
    write(ROOT/('validation_report.json' if mode=='static' else 'dynamic_validation_report.json'),
        {'status':'passed','records':30,'task_count':2,'goals_per_task':15,'internal':16,'external':14,
         'pipeline':'benchmark.generate_attack_config.generate','postprocessing':False,
         'checks':['complete 2 x 15 task/goal grid','fixed task prompts and vector','leakage labels',
                   'artifact references','pipeline JSON and artifacts match generation-time SHA256 hashes'],
         'evaluations_run':False})
    print(f'Validated 30 {mode} records; original pipeline output hashes unchanged',flush=True)


def main(mode='static'):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--validate-only',action='store_true')
    args=parser.parse_args()
    if args.validate_only:
        validate(mode)
        return
    groups=prepare(mode)
    if args.prepare_only:return
    for kind,rows in groups.items():
        folder,sampled,final=paths(mode,kind,len(rows))
        provenance=folder/'pipeline_provenance.json'
        if final.exists():
            if not provenance.exists() or snapshot(folder,final)!=json.loads(provenance.read_text())['output_sha256']:
                raise ValueError(f'Existing result lacks unchanged pipeline provenance: {final}')
            print(f'Reusing original pipeline bundle: {final}',flush=True)
            continue
        command=[sys.executable,'-m','benchmark.generate_attack_config.generate',str(sampled),'--output',str(final)]
        subprocess.run(command,cwd=REPO,check=True)
        # Record output checksums only; do not rewrite any generated JSON or artifact.
        write(provenance,{'command':command,'input_sha256':digest(sampled),'output_sha256':snapshot(folder,final)})
    validate(mode)


if __name__=='__main__':main()
