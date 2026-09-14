#!/usr/bin/env python3
"""Rerun the corrected keyword-free client-code TXT case on one original model."""
import argparse
from dataclasses import replace
from datetime import datetime
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

TASK = 'task_fe573b8ce38d4a9f9642fbe7b8f11358_txt_22_save_client_code'
ORIGINAL = {
    model: 'keyword_20260913_153249_49dde0/parallel_20260913_153249_67928685'
    for model in ('gemini36', 'gpt_terra_high', 'deepseekv4')
}
ORIGINAL['glm53'] = 'keyword_20260913_184212_a7a34e/parallel_20260913_184212_5fd0a167'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=ORIGINAL, required=True)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--base-port', type=int)
    args = parser.parse_args()
    args.models = [args.model]
    args.input_root = ROOT / 'without'
    jobs = [j for j in parallel.plan_jobs(args.input_root, args.models, ['static_prompt_injection'])
            if j.selector == TASK]
    if len(jobs) != 1:
        parser.error('Expected exactly one matching task')
    row = next(r for r in json.loads(jobs[0].source.read_text()) if r['harmful_task_id'] == TASK)
    deployed = (jobs[0].source.parent / row['attack_file']).read_text()
    if row['attack_config']['cot'] not in deployed or 'Prerequisite:' in deployed:
        parser.error('Deployed TXT must contain the exact Before-version reference')
    original = (REPO / 'benchmark/output/key_words' / ORIGINAL[args.model] /
                args.model / 'without/static_prompt_injection')
    jobs = [replace(jobs[0], category='without/static_prompt_injection',
                    model_config=original / 'orchestrator_config.json')]
    if args.dry_run:
        print(json.dumps({'job': jobs[0].key, 'original': str(original),
                          'model_config': json.loads(jobs[0].model_config.read_text()),
                          'reference_matches_txt': True, 'max_steps': 150, 'timer': False}, indent=2))
        return 0
    # Credentials remain process-local and are never copied into run configs.
    if args.model == 'glm53':
        if not os.environ.get('ZAI_API_KEY'):
            parser.error('ZAI_API_KEY is required')
        os.environ['OPENAI_API_KEY'] = os.environ['ZAI_API_KEY']
    if args.model == 'deepseekv4' and not os.environ.get('DEEPSEEK_API_KEY'):
        parser.error('DEEPSEEK_API_KEY is required')
    if args.model == 'gpt_terra_high' and not os.environ.get('OPENAI_API_KEY'):
        from dotenv import dotenv_values
        key = dotenv_values(REPO / 'agents/.env').get('OPENAI_API_KEY')
        if not key:
            parser.error('OPENAI_API_KEY is required')
        os.environ['OPENAI_API_KEY'] = key
    os.environ['HF_MAX_STEPS'] = '150'
    args.concurrency = 1
    args.timer = False
    args.skip_build = True
    args.output_root = REPO / 'benchmark/output/key_words' / (
        'client_code_before_' + datetime.now().strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:6])
    args.output_root.mkdir(parents=True)
    (args.output_root / 'rerun_provenance.json').write_text(json.dumps({
        'original_batch': str(original), 'task': TASK, 'model': args.model,
        'change': 'Replace stale Prerequisite instruction with exact configured Before text',
        'instruction_text': deployed, 'max_steps': 150, 'timer': False,
    }, ensure_ascii=False, indent=2) + '\n')
    try:
        return parallel.execute(args, jobs)
    finally:
        for manifest in args.output_root.glob('parallel_*/manifest.json'):
            summarize(manifest)
            print('Summary:', manifest.parent / 'model_summary.md', flush=True)


if __name__ == '__main__':
    raise SystemExit(main())
