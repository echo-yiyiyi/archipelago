#!/usr/bin/env python3
"""Reuse the script-vector runner and model settings for no-instruction tasks."""
import importlib.util
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('script_vector_runner',ROOT.parents[1]/'run_models.py')
runner=importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
from prepare import validate

# Same model configurations, concurrency/step defaults, scheduler and ASR report.
runner.ROOT=ROOT.parent
runner.CATEGORIES=('no_txt',)
original_plan=runner.plan


def plan(root,configs):
    if root.resolve()!=ROOT.parent.resolve():
        raise ValueError('This paired launcher uses its sibling baseline; omit --input-root')
    validate()
    return original_plan(root,configs)


runner.plan=plan
if __name__=='__main__':
    if '--output-root' not in sys.argv and not any(a.startswith('--output-root=') for a in sys.argv):
        sys.argv.extend(['--output-root',str(runner.REPO/'benchmark/output/ablation/script_vevtor/no_txt')])
    raise SystemExit(runner.main())
