#!/usr/bin/env python3
"""Rerun the two Gemini keyword final-answer cases after fixing script help."""
import argparse
from dataclasses import replace
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[3]
sys.path.insert(0, str(REPO))
from benchmark import run_models_parallel as parallel
from benchmark.final_benchmark.ablation.key_words.run_models import summarize

TASK = 'task_4b3c2dfc4d164a25831e8787397766c3_elf_30_save_final_answer_arg'
ORIGINAL = REPO / 'benchmark/output/key_words/keyword_20260913_153249_49dde0/parallel_20260913_153249_67928685'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--base-port', type=int)
    args = parser.parse_args()
    args.models = ['gemini36']
    args.input_root = ROOT
    jobs = []
    provenance = []
    for setting in ('with', 'without'):
        selected = [j for j in parallel.plan_jobs(ROOT / setting, args.models, ['static_script_injection'])
                    if j.selector == TASK]
        assert len(selected) == 1
        original = ORIGINAL / 'gemini36' / setting / 'static_script_injection'
        job = replace(selected[0], category=setting + '/static_script_injection',
                      model_config=original / 'orchestrator_config.json')
        record = next(r for r in json.loads(job.source.read_text()) if r['harmful_task_id'] == TASK)
        artifact = job.source.parent / record['attack_file']
        jobs.append(job)
        provenance.append({'setting': setting, 'original_task': str(original / 'tasks' / TASK),
                           'artifact': str(artifact), 'artifact_sha256': hashlib.sha256(artifact.read_bytes()).hexdigest(),
                           'model_config': json.loads(job.model_config.read_text())})
    metadata = {'task': TASK, 'change': 'Help flags now print usage and exit without saving the flag as the final answer',
                'max_steps': 150, 'timer': False, 'runs': provenance}
    if args.dry_run:
        print(json.dumps(metadata, indent=2))
        return 0
    os.environ['HF_MAX_STEPS'] = '150'
    args.concurrency = 2
    args.timer = False
    args.skip_build = True
    args.output_root = REPO / 'benchmark/output/key_words' / (
        'final_answer_help_' + datetime.now().strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:6])
    args.output_root.mkdir(parents=True)
    (args.output_root / 'rerun_provenance.json').write_text(json.dumps(metadata, indent=2)+'\n')
    try:
        return parallel.execute(args, jobs)
    finally:
        for manifest in args.output_root.glob('parallel_*/manifest.json'):
            summarize(manifest)
            print('Summary:', manifest.parent / 'model_summary.md', flush=True)


if __name__ == '__main__':
    raise SystemExit(main())
