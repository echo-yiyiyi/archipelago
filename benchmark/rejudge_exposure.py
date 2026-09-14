"""Re-evaluate zero-exposure grades in a completed batch without rerunning agents.

Usage: python -m benchmark.rejudge_exposure BATCH_DIR [--dry-run]
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile

from benchmark.runner.security_check import check_record_prompt_exposure


def read_json(path):
    return json.loads(path.read_text())


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, suffix='.tmp', delete=False) as f:
        json.dump(value, f, indent=2, ensure_ascii=False)
        f.write('\n')
        temporary = Path(f.name)
    temporary.replace(path)


def candidates(batch, *, retry_reviewed=False):
    for path in sorted(batch.rglob('grades.json')):
        if '_exposure_rejudge' in path.relative_to(batch).parts or path.parent.parent.name != 'tasks':
            continue
        grade = read_json(path)
        if type(grade.get('prompt_exposure')) not in (int, float) or grade['prompt_exposure'] != 0:
            continue
        judge = grade.get('prompt_exposure_llm_judge') or {}
        if not retry_reviewed and 'exposure' in judge and not grade.get('prompt_exposure_error'):
            continue
        yield path


def resolve_record(task_dir, base_dir=None):
    config_path = task_dir.parent.parent / 'attack_config.json'
    config = read_json(config_path)
    records = config if isinstance(config, list) else [config]
    # Match the complete selector, never a prefix shared by several variants.
    matches = [r for r in records if r.get('harmful_task_id') == task_dir.name]
    if not matches:
        matches = [r for r in records if r.get('task_id') == task_dir.name]
    if len(matches) != 1:
        raise ValueError(f'Expected one config record for {task_dir.name}, found {len(matches)}')
    record = deepcopy(matches[0])
    # Prefer the deployed instruction TXT over possibly edited source files.
    for key in ('populate_files', 'attack_files'):
        files = []
        for name in record.get(key, []):
            path = Path(name)
            if path.suffix == '.txt' and 'instruction' in path.name.lower() and '.apps_data' not in path.parts:
                deployed = list((task_dir / '_attack_task_files' / 'filesystem').rglob(path.name))
                if len(deployed) == 1:
                    name = str(deployed[0].resolve())
            files.append(name)
        if key in record:
            record[key] = files
    return record, base_dir or config_path.parent


def rejudge_one(path, *, batch, backup, base_dir=None):
    item = {'task': str(path.parent.relative_to(batch))}
    try:
        grade = read_json(path)
        record, reference_dir = resolve_record(path.parent, base_dir)
        trajectory = read_json(path.parent / 'trajectory.json')
        snapshot = path.parent / 'final_snapshot.zip'
        result = check_record_prompt_exposure(
            trajectory, record, base_dir=reference_dir,
            final_snapshot=snapshot if snapshot.exists() else None,
        )
        if not result:
            return {**item, 'status': 'skipped', 'reason': 'Exposure is not applicable'}
        saved = backup / path.relative_to(batch)
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, saved)
        updated = {k: v for k, v in grade.items() if not k.startswith('prompt_exposure')}
        updated.update(result)
        write_json(path, updated)
        return {**item, 'status': 'error' if result.get('prompt_exposure_error') else 'updated',
                **result}
    except Exception as error:
        return {**item, 'status': 'error', 'error': f'{type(error).__name__}: {error}'}


def refresh_summaries(batch, paths, backup):
    from benchmark.main_concurrency import SCORE_SUMMARY_FILENAME, update_score_summary

    for run in sorted({p.parent.parent.parent for p in paths}):
        summary = run / SCORE_SUMMARY_FILENAME
        if summary.exists():
            saved = backup / summary.relative_to(batch)
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(summary, saved)
        update_score_summary(run)
    # The external/internal runner owns these additional CSV/JSON/Markdown views.
    leakage_roots = {ancestor for path in paths for ancestor in path.parents
                     if ancestor.is_relative_to(batch) and (ancestor / 'leakage_summary.json').exists()}
    if leakage_roots:
        from benchmark.final_benchmark.ablation.external_internal.run_models import summarize
        for root in sorted(leakage_roots):
            for extension in ('json', 'csv', 'md'):
                summary = root / f'leakage_summary.{extension}'
                if summary.exists():
                    saved = backup / summary.relative_to(batch)
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(summary, saved)
            summarize(root)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('batch_dir', type=Path)
    parser.add_argument('--dry-run', action='store_true', help='List eligible tasks without calls or writes')
    parser.add_argument('--base-dir', type=Path, help='Original config base directory if instruction source files are needed')
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--retry-reviewed', action='store_true', help='Also rejudge prior successful LLM negative judgments')
    args = parser.parse_args(argv)
    batch = args.batch_dir.resolve()
    if not batch.is_dir() or args.workers < 1:
        parser.error('batch_dir must exist and workers must be positive')
    paths = list(candidates(batch, retry_reviewed=args.retry_reviewed))
    print(f'{len(paths)} zero-exposure tasks eligible', flush=True)
    if args.dry_run:
        for path in paths:
            print(path.parent.relative_to(batch))
        return 0
    if not paths:
        return 0
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    backup = batch / '_exposure_rejudge' / stamp
    report = {'batch_dir': str(batch), 'backup_dir': str(backup), 'tasks': []}
    def run(path):
        return rejudge_one(path, batch=batch, backup=backup,
                           base_dir=args.base_dir.resolve() if args.base_dir else None)
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        for item in executor.map(run, paths):
            report['tasks'].append(item)
            write_json(backup / 'report.json', report)
            print(f"{item['status']}: {item['task']}", flush=True)
    refresh_summaries(batch, paths, backup)
    print(f'Report and original files: {backup}', flush=True)
    return int(any(item['status'] == 'error' for item in report['tasks']))


if __name__ == '__main__':
    raise SystemExit(main())
