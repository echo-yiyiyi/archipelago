#!/usr/bin/env python3
"""Run four paired watcher settings with Gemini 3.6 Flash."""
import argparse
import csv
import json
import os
from pathlib import Path
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[3]
sys.path.insert(0,str(REPO))
from benchmark import run_models_parallel as parallel

SETTINGS=('with','without_corrupt','without_restore_other_txt','without_txt')
VECTOR='dynamic_prompt_injection'
OUTPUT_ROOT=REPO/'benchmark/output/ablation/watcher_prompt'
MODEL_CONFIG=REPO/'benchmark/orchestrator_config_gemini36.json'


def plan(root,suite,goal=None):
    if json.loads(MODEL_CONFIG.read_text()).get('model')!='vertex_ai/gemini-3.6-flash':
        raise ValueError('gemini36 config no longer selects Gemini 3.6 Flash')
    baseline=None
    batches=[]
    for setting in SETTINGS:
        directory=root/setting
        source=directory/'selected_10_tasks_with_attack_config.json'
        rows=json.loads(source.read_text())
        records={r['harmful_task_id']:r for r in rows}
        if len(rows)!=10 or len(records)!=10 or len({r['inject_goal'] for r in rows})!=10:
            raise ValueError(f'{source}: expected 10 distinct goal records')
        if baseline is not None and records!=baseline:
            raise ValueError(f'{setting}: task records differ from with')
        baseline=records
        for row in rows:
            if row['inject_vector']!=VECTOR or row.get('add_user_prompt') is not False:
                raise ValueError(f'{source}: invalid dynamic injection flags')
            for name in {row['attack_file'],row['watcher_file'],row['watcher_config'],*row['populate_files']}:
                artifact=(directory/name).resolve()
                if not artifact.is_relative_to(directory.resolve()) or not artifact.is_file():
                    raise ValueError(f'Missing/out-of-bundle artifact: {artifact}')
        batches.append((setting,source,records,parallel.runtime.link_hosts_from_attack_config(source)))
    ordered=sorted(baseline.values(),key=lambda r:int(r['inject_goal'].split('_')[0]))
    if suite=='smoke':
        goal=goal or ordered[0]['inject_goal']
        ordered=[r for r in ordered if r['inject_goal']==goal or r['inject_goal'].split('_')[0]==goal]
        if len(ordered)!=1:raise ValueError(f'Unknown or ambiguous goal: {goal}')
    elif goal is not None:
        raise ValueError('--goal is only supported for smoke runs')
    jobs=[]
    for chosen in ordered:
        for setting,source,records,hosts in batches:
            row=records[chosen['harmful_task_id']]
            jobs.append(parallel.Job('gemini36',setting,row['harmful_task_id'],row['task_id'],
                source,MODEL_CONFIG,row['inject_goal'],hosts.get(row['harmful_task_id'])))
    if len({j.key for j in jobs})!=len(jobs):raise ValueError('Duplicate jobs')
    return jobs

def summarize(run):
    manifest = json.loads((run / 'manifest.json').read_text())
    groups = {}
    for key in manifest['jobs']:
        model, setting, task = key.split('/')
        row = groups.setdefault(setting, dict(model=model, setting=setting, requested=0, finished=0,
            failed=0, exposed=0, exposure_evaluated=0, successful=0, attack_evaluated=0))
        result = manifest.get('results', {}).get(key)
        row['requested'] += 1
        row['finished'] += int(result is not None)
        row['failed'] += int(result is not None and result['returncode'] != 0)
        grade_path = run / model / setting / 'tasks' / task / 'grades.json'
        grade = json.loads(grade_path.read_text()) if grade_path.exists() else {}
        for field, count, success in [('prompt_exposure', 'exposure_evaluated', 'exposed'),
                                      ('attack_success', 'attack_evaluated', 'successful')]:
            value = grade.get(field)
            if type(value) in (int, float) and value in (0, 1):
                row[count] += 1
                row[success] += int(value)
    rows = []
    for setting in SETTINGS:
        if setting not in groups:
            continue
        row = groups[setting]
        row['exposure_missing'] = row['requested'] - row['exposure_evaluated']
        row['attack_missing'] = row['requested'] - row['attack_evaluated']
        row['exposure_rate'] = row['exposed'] / row['exposure_evaluated'] if row['exposure_evaluated'] else None
        row['asr'] = row['successful'] / row['attack_evaluated'] if row['attack_evaluated'] else None
        rows.append(row)
    if not rows:
        raise ValueError('No watcher setting jobs in manifest')
    notes = ('Exposure rate uses the benchmark prompt_exposure grade; ASR uses attack_success. '
             'Each rate has its own denominator of valid binary grades. Missing grades are excluded, not zero. '
             'Valid grades are included even for process failures, which are reported separately.')
    parallel.write_json(run / 'setting_summary.json', {'notes': notes, 'interrupted': manifest.get('interrupted', False), 'rows': rows})
    with (run / 'setting_summary.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    lines = ['# Gemini 3.6 Flash — watcher setting results', '', notes, '',
        '| Setting | Exposure rate (exposed/evaluated) | ASR (successful/evaluated) | Finished/requested | Process failed | Missing exposure/attack |',
        '|---|---:|---:|---:|---:|---:|']
    def metric(row, name, numerator, denominator):
        value = 'N/A' if row[name] is None else f"{row[name]:.2%}"
        return f"{value} ({row[numerator]}/{row[denominator]})"
    for r in rows:
        lines.append(f"| {r['setting']} | {metric(r, 'exposure_rate', 'exposed', 'exposure_evaluated')} | "
            f"{metric(r, 'asr', 'successful', 'attack_evaluated')} | {r['finished']}/{r['requested']} | "
            f"{r['failed']} | {r['exposure_missing']}/{r['attack_missing']} |")
    report = '\n'.join(lines) + '\n'
    (run / 'setting_summary.md').write_text(report)
    print(report, flush=True)
    print(f'Reports: {run}/setting_summary.{{md,csv,json}}', flush=True)
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite',choices=['smoke','all'],required=True)
    parser.add_argument('--goal',help='Smoke goal number or full ID; default: lowest retained goal number')
    parser.add_argument('--input-root',type=Path,default=ROOT)
    parser.add_argument('--output-root',type=Path,default=OUTPUT_ROOT)
    parser.add_argument('--concurrency',type=int,help='Shared slots; default smoke=number of settings, all=12')
    parser.add_argument('--max-steps',type=int,default=100)
    parser.add_argument('--base-port',type=int)
    parser.add_argument('--skip-build',action='store_true')
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--summarize',type=Path,metavar='RUN_DIR')
    args=parser.parse_args()
    if args.summarize:
        summarize(args.summarize.resolve());return 0
    if args.concurrency is None:args.concurrency=len(SETTINGS) if args.suite=='smoke' else 12
    if not 1<=args.concurrency<=64 or args.max_steps<1:
        parser.error('Require concurrency 1..64 and positive max-steps')
    if args.base_port is not None and not 1<=args.base_port<=65536-args.concurrency:
        parser.error('base-port leaves insufficient valid ports')
    args.input_root=args.input_root.resolve();args.output_root=args.output_root.resolve()
    args.models=['gemini36'];args.timer=False
    os.environ['HF_MAX_STEPS']=str(args.max_steps)
    os.umask(0o077)
    try:jobs=plan(args.input_root,args.suite,args.goal)
    except (OSError,ValueError) as error:parser.error(str(error))
    if args.dry_run:
        print(json.dumps({'model':json.loads(MODEL_CONFIG.read_text())['model'],'suite':args.suite,
            'runs':len(jobs),'settings':SETTINGS,'tasks_per_setting':len(jobs)//len(SETTINGS),
            'concurrency':min(args.concurrency,len(jobs)),'max_steps':args.max_steps,'timer':False,
            'selected_pairs':[{'task_id':j.dataset_selector,'goal':j.goal} for j in jobs if j.category=='with']},indent=2));return 0
    args.output_root/=args.suite+'_'+time.strftime('%Y%m%d_%H%M%S_')+uuid.uuid4().hex[:6]
    args.output_root.mkdir(parents=True)
    try:return parallel.execute(args,jobs)
    finally:
        for manifest in args.output_root.glob('parallel_*/manifest.json'):summarize(manifest.parent)


if __name__=='__main__':raise SystemExit(main())
