#!/usr/bin/env python3
"""Select one existing dynamic task per goal, preserving complete bundles."""
import hashlib
import json
from pathlib import Path
import random
import shutil
import tempfile

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT.parents[1]/'dynamic_prompt_injection/selected_30_tasks_with_attack_config.json'
OUTPUT=ROOT/'with'
SEED=42


def write(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def select(rows):
    goals=sorted({r['inject_goal'] for r in rows},key=lambda g:int(g.split('_')[0]))
    if len(goals)!=15:raise ValueError(f'Expected 15 source goals before subset filtering, found {len(goals)}')
    candidates={goal:[r for r in rows if r['inject_goal']==goal] for goal in goals}
    rng=random.Random(SEED)
    for group in candidates.values():rng.shuffle(group)
    # Prefer distinct source task IDs using maximum bipartite matching.
    assigned={}
    def assign(goal,seen):
        for row in candidates[goal]:
            task=row['task_id']
            if task in seen:continue
            seen.add(task)
            previous=assigned.get(task)
            if previous is None or assign(previous['inject_goal'],seen):
                assigned[task]=row
                return True
        return False
    for goal in goals:assign(goal,set())
    matched={r['inject_goal']:r for r in assigned.values()}
    selected = [matched.get(goal,candidates[goal][0]) for goal in goals]
    frozen = json.loads((ROOT/'subset_manifest.json').read_text())['retained']
    keep = {r['harmful_task_id'] for r in frozen}
    selected = [r for r in selected if r['harmful_task_id'] in keep]
    assert {r['harmful_task_id'] for r in selected} == keep
    return selected


def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    if any(OUTPUT.iterdir()):raise FileExistsError(f'Refusing to overwrite nonempty output: {OUTPUT}')
    source_rows=json.loads(SOURCE.read_text())
    selected=select(source_rows)
    assert len(selected)==len({r['inject_goal'] for r in selected})==10
    sampled_source=SOURCE.with_name('selected_30_tasks_with_inject_goals.json')
    sampled={r['harmful_task_id']:r for r in json.loads(sampled_source.read_text())}
    manifest={'seed':SEED,'source':str(SOURCE),'source_sha256':sha(SOURCE),
        'selection':'One record per goal, maximizing distinct source task IDs',
        'task_count':len({r['task_id'] for r in selected}),'goal_count':10,'tasks':[]}
    with tempfile.TemporaryDirectory(prefix='.select-with-',dir=ROOT) as temporary:
        stage=Path(temporary)
        for row in selected:
            assert row['inject_vector']=='dynamic_prompt_injection'
            identifier=row['harmful_task_id']
            if Path(identifier).name!=identifier or identifier in {'.','..'}:raise ValueError('Unsafe task ID')
            files=set([row['attack_file'],row['watcher_file'],row['watcher_config'],*row['populate_files']])
            hashes={}
            for relative in files:
                source=(SOURCE.parent/relative).resolve()
                target=(stage/relative).resolve()
                if not source.is_relative_to(SOURCE.parent.resolve()) or not target.is_relative_to(stage):
                    raise ValueError(f'Out-of-bundle path: {relative}')
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(source,target)
                assert sha(source)==sha(target)
                hashes[relative]=sha(source)
            payload=json.loads((stage/row['watcher_config']).read_text())
            assert payload['inject_goal']==row['inject_goal']
            assert payload['attack_config']==row['attack_config']
            manifest['tasks'].append({'task_id':row['task_id'],'inject_goal':row['inject_goal'],
                'harmful_task_id':identifier,'artifact_sha256':hashes})
        write(stage/'selected_10_tasks_with_attack_config.json',selected)
        write(stage/'selected_10_tasks_with_inject_goals.json',[sampled[r['harmful_task_id']] for r in selected])
        write(stage/'selection_manifest.json',manifest)
        write(stage/'validation_report.json',{'status':'passed','records':10,'distinct_goals':10,
            'distinct_task_ids':manifest['task_count'],'checks':['records unchanged from source',
                'one task per goal','all referenced artifacts byte-identical to source','watcher configs consistent'],
            'evaluations_run':False})
        assert json.loads((stage/'selected_10_tasks_with_attack_config.json').read_text())==selected
        if any(OUTPUT.iterdir()):raise FileExistsError('Destination changed during selection')
        for entry in stage.iterdir():entry.rename(OUTPUT/entry.name)
    print(f"Copied 10 goals, {manifest['task_count']} distinct task IDs, to {OUTPUT}")


if __name__=='__main__':main()
