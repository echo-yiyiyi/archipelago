#!/usr/bin/env python3
"""Run original-pipeline leakage ablations and report exposure/ASR."""
import argparse
import csv
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import uuid

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[3]
sys.path.insert(0,str(REPO))
from benchmark import run_models_parallel as parallel

SOURCES={
    'gpt-terra': REPO/'benchmark/orchestrator_config_gpt_terra.json',
    'deepseek': REPO/'litellm_configs/deepseek_v4_flash.json',
    'glm53': REPO/'litellm_configs/glm_5_3_flash.json',
}
COUNTS={'internal':16,'external':14}


def configs(models,directory,dry_run):
    paths={}
    for model in models:
        data=json.loads(SOURCES[model].read_text())
        if 'api_key_env' in data:
            name=data['api_key_env']
            key=os.environ.get(name)
            if not key and not dry_run:
                raise ValueError(f'Export {name} before running {model}')
            data={'model':data['model'],'extra_args':{**data.get('extra_args',{}),
                'api_base':data['api_base'],'api_key':key or 'DRY_RUN_ONLY'}}
        path=directory/f'{model}.json'
        parallel.write_json(path,data)
        path.chmod(0o600)
        paths[model]=path
    return paths


def plan(root,modes,model_configs):
    categories=[f'{mode}_prompt_injection' for mode in modes]
    groups=[]
    reference_tasks=None
    for kind,count in COUNTS.items():
        pairing=None
        for category in categories:
            directory=root/kind/category
            config_file=directory/f'selected_{count}_tasks_with_attack_config.json'
            provenance=json.loads((directory/'pipeline_provenance.json').read_text())
            required={config_file.name}
            rows=json.loads(config_file.read_text())
            keys={(r['task_id'],r['inject_goal']) for r in rows}
            tasks={r['task_id'] for r in rows}
            goals={r['inject_goal'] for r in rows}
            if len(rows)!=count or len(tasks)!=2 or len(goals)!=count//2 or keys!={(t,g) for t in tasks for g in goals}:
                raise ValueError(f'{config_file}: expected complete two-task goal grid')
            if reference_tasks is not None and reference_tasks!=tasks:
                raise ValueError('Task IDs differ between leakage groups or modes')
            reference_tasks=tasks
            signature={(r['task_id'],r['inject_goal'],r['prompt']) for r in rows}
            if pairing is not None and signature!=pairing:
                raise ValueError(f'{kind}: static/dynamic task-goal pairing differs')
            pairing=signature
            for row in rows:
                if row['leakage_type']!=kind or row['attack_config']['leakage_type']!=kind:
                    raise ValueError(f'{config_file}: wrong leakage label')
                expected_vector='txt' if category.startswith('static') else 'dynamic_prompt_injection'
                if row['inject_vector']!=expected_vector or row.get('add_user_prompt') is not False:
                    raise ValueError(f'{config_file}: wrong vector or prompt setting')
                required.update([row['attack_file'],*row['populate_files']])
            if set(provenance['output_sha256'])!=required:
                raise ValueError(f'{directory}: incomplete original-pipeline provenance')
            for name,digest in provenance['output_sha256'].items():
                path=(directory/name).resolve()
                if not path.is_relative_to(directory.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
                    raise ValueError(f'Original pipeline output changed: {path}')
        # Reuse repository discovery, selector handling, and host resolution.
        jobs=[]
        for category in categories:
            for leaf, source, _ in parallel.discover(category, root=root/kind):
                rows=json.loads(source.read_text())
                hosts=parallel.runtime.link_hosts_from_attack_config(source)
                jobs.extend(parallel.Job('gpt-terra', leaf, r['harmful_task_id'], r['task_id'],
                    source, model_configs[next(iter(model_configs))], r['inject_goal'],
                    hosts.get(r['harmful_task_id'])) for r in rows)
        groups.append([replace(j,model=model,model_config=config,category=f'{kind}/{j.category}')
                       for j in jobs for model,config in model_configs.items()])
    jobs=[group[i] for i in range(max(map(len,groups))) for group in groups if i<len(group)]
    if len({j.key for j in jobs})!=len(jobs):
        raise ValueError('Duplicate job keys')
    return jobs


def summarize(run):
    manifest=json.loads((run/'manifest.json').read_text())
    groups={}
    for key in manifest['jobs']:
        model,kind,category,task=key.split('/')
        row=groups.setdefault((model,category,kind),dict(model=model,category=category,leakage_type=kind,
            requested=0,finished=0,failed=0,exposed=0,exposure_evaluated=0,successful=0,attack_evaluated=0))
        row['requested']+=1
        result=manifest.get('results',{}).get(key)
        row['finished']+=int(result is not None)
        row['failed']+=int(result is not None and result['returncode']!=0)
        path=run/model/kind/category/'tasks'/task/'grades.json'
        grade=json.loads(path.read_text()) if path.exists() else {}
        for field,total,success in [('prompt_exposure','exposure_evaluated','exposed'),('attack_success','attack_evaluated','successful')]:
            value=grade.get(field)
            if type(value) in (int,float) and value in (0,1):
                row[total]+=1
                row[success]+=int(value)
    rows=[]
    for _,row in sorted(groups.items()):
        row['exposure_missing']=row['requested']-row['exposure_evaluated']
        row['attack_missing']=row['requested']-row['attack_evaluated']
        row['exposure_rate']=row['exposed']/row['exposure_evaluated'] if row['exposure_evaluated'] else None
        row['asr']=row['successful']/row['attack_evaluated'] if row['attack_evaluated'] else None
        rows.append(row)
    if not rows:raise ValueError('No jobs to summarize')
    notes=('Exposure uses benchmark prompt_exposure; ASR uses attack_success. Each rate uses its own valid '
        'binary-grade denominator. Missing grades are excluded, not zero. Valid grades are included even '
        'for process failures, which are reported separately. Static/dynamic and internal/external are kept separate.')
    parallel.write_json(run/'leakage_summary.json',{'notes':notes,'interrupted':manifest.get('interrupted',False),'rows':rows})
    with (run/'leakage_summary.csv').open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    def metric(row,key,numerator,denominator):
        value='N/A' if row[key] is None else f"{row[key]:.2%}"
        return f"{value} ({row[numerator]}/{row[denominator]})"
    lines=['# Internal / external results','',notes,'',
        '| Model | Category | Leakage | Exposure (n/N) | ASR (n/N) | Finished/requested | Failed | Missing exposure/attack |',
        '|---|---|---|---:|---:|---:|---:|---:|']
    for r in rows:
        lines.append(f"| {r['model']} | {r['category']} | {r['leakage_type']} | "
            f"{metric(r,'exposure_rate','exposed','exposure_evaluated')} | {metric(r,'asr','successful','attack_evaluated')} | "
            f"{r['finished']}/{r['requested']} | {r['failed']} | {r['exposure_missing']}/{r['attack_missing']} |")
    report='\n'.join(lines)+'\n'
    (run/'leakage_summary.md').write_text(report)
    print(report,flush=True)
    print(f'Reports: {run}/leakage_summary.{{md,csv,json}}',flush=True)
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models',nargs='+',choices=list(SOURCES),default=list(SOURCES))
    parser.add_argument('--mode',choices=['both','static','dynamic'],default='both')
    parser.add_argument('--input-root',type=Path,default=ROOT)
    parser.add_argument('--output-root',type=Path,default=REPO/'benchmark/output/ablation/external_internal')
    parser.add_argument('--concurrency',type=int,default=12,help='Global shared slots, 1..64 (default: 12)')
    parser.add_argument('--max-steps',type=int,default=100)
    parser.add_argument('--base-port',type=int)
    parser.add_argument('--skip-build',action='store_true')
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--summarize',type=Path,metavar='RUN_DIR')
    args=parser.parse_args()
    if args.summarize:
        summarize(args.summarize.resolve());return 0
    if not 1<=args.concurrency<=64 or args.max_steps<1 or len(set(args.models))!=len(args.models):
        parser.error('Require concurrency 1..64, positive max-steps and distinct models')
    if args.base_port is not None and not 1<=args.base_port<=65536-args.concurrency:
        parser.error('base-port leaves insufficient valid ports')
    args.input_root=args.input_root.resolve();args.output_root=args.output_root.resolve()
    args.timer=False
    os.environ['HF_MAX_STEPS']=str(args.max_steps)
    os.umask(0o077)
    modes=['static','dynamic'] if args.mode=='both' else [args.mode]
    with tempfile.TemporaryDirectory(prefix='leakage-models-') as temporary:
        try:
            paths=configs(args.models,Path(temporary),args.dry_run)
            jobs=plan(args.input_root,modes,paths)
        except (OSError,ValueError) as e:parser.error(str(e))
        if args.dry_run:
            print(json.dumps({'runs':len(jobs),'models':{m:json.loads(p.read_text())['model'] for m,p in paths.items()},
                'modes':modes,'tasks':2,'goals_per_task':15,'per_model_per_mode':COUNTS,
                'concurrency':args.concurrency,'max_steps':args.max_steps,'timer':False},indent=2));return 0
        args.output_root/='run_'+time.strftime('%Y%m%d_%H%M%S_')+uuid.uuid4().hex[:6]
        args.output_root.mkdir(parents=True)
        try:return parallel.execute(args,jobs)
        finally:
            for manifest in args.output_root.glob('parallel_*/manifest.json'):summarize(manifest.parent)


if __name__=='__main__':raise SystemExit(main())
