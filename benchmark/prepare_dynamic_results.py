"""Audit completed repetitions and prepare missing model/setting cells."""
import json
from pathlib import Path
import shutil
import re

ROOT = Path(__file__).resolve().parent
MODELS = ['sol', 'glm53', 'deepseekv4', 'opus5', 'gemini', 'kimik3']
SETTINGS = ['prompt', 'script_allow', 'script_no_allow']
OUT = ROOT / 'generate_attack_config/output/dynamic_missing'
OUT.mkdir(parents=True, exist_ok=True)
sources = {}
for setting in SETTINGS:
    bundle = ROOT / 'generate_attack_config/output' / ('dynamic_prompt_8_tasks' if setting == 'prompt' else 'dynamic_script_11_tasks')
    sources[setting] = (bundle, json.loads((bundle / 'tasks_with_attack_config.json').read_text()))
cells = {(m, s): [] for m in MODELS for s in SETTINGS}
excluded = []
totals = {}


def exhausted_max_steps(run: Path, task_id: str) -> bool:
    """Return whether a task failed specifically by exhausting its step budget."""
    for log_file in (run / 'logs').glob(f'worker-*_{task_id}.log'):
        try:
            if re.search(r'Not finalized after \d+ steps', log_file.read_text(errors='replace')):
                return True
        except OSError:
            continue
    return False


for run in sorted((ROOT / 'output/concurrent').glob('tasks_*')):
    # Latest prompt wording starts with 223915. The earlier Kimi script
    # no-allow run is retained as explicitly requested.
    if run.name < 'tasks_20260905_215210' or run.name.startswith('tasks_20260905_215227'):
        continue
    model = run.name.rsplit('_', 1)[-1]
    if model not in MODELS or not (run / 'attack_config.json').exists():
        continue
    records = json.loads((run / 'attack_config.json').read_text())
    if not isinstance(records, list) or not records: continue
    vector = records[0].get('inject_vector')
    if vector not in ('dynamic_prompt_injection', 'dynamic_script_execution'): continue
    manifest = json.loads((run / 'manifest.json').read_text()) if (run / 'manifest.json').exists() else {}
    if not manifest:
        excluded.append(run.name + ': no final manifest')
        continue
    setting = 'prompt' if vector == 'dynamic_prompt_injection' else ('script_allow' if manifest.get('user_allow_additional_instruction', False) else 'script_no_allow')
    good = {x['selector'] for x in manifest['results'] if x.get('returncode') == 0}
    summary = json.loads((run / 'score_summary.json').read_text()) if (run / 'score_summary.json').exists() else {}
    rows = [x for x in summary.get('tasks', []) if x.get('task_id') in good and x.get('attack_success') in (0, 1)]
    # Some historical score summaries were later regenerated with fewer rows.
    # Recover per-task outcomes from the original cumulative completion events.
    known = {x['task_id'] for x in rows}
    previous_success = previous_exposure = previous_evaluated = 0
    for line in (run / 'runner.log').read_text().splitlines():
        if 'TASK_FINISHED:' not in line and 'TASK_FAILED:' not in line: continue
        fields = dict(re.findall(r'(\w+)=([^ ]+)', line))
        if 'attack_evaluated_count' not in fields: continue
        evaluated = int(fields['attack_evaluated_count'])
        success = int(fields['attack_success_count'])
        exposure = int(fields['prompt_exposure_count'])
        task = fields.get('task')
        if evaluated == previous_evaluated + 1 and task in good and task not in known:
            hit_max_steps = exhausted_max_steps(run, task)
            rows.append({'task_id': task, 'attack_success': success-previous_success,
                         'prompt_exposure': exposure-previous_exposure,
                         'final_score': 0.0 if hit_max_steps else None,
                         'score_source': 'max_steps_exhausted' if hit_max_steps else None,
                         'recovered_from_runner_log': True})
            known.add(task)
        previous_evaluated, previous_success, previous_exposure = evaluated, success, exposure
    if previous_evaluated == len(good) and good:
        for task in good - known:
            rows.append({'task_id': task, 'attack_success': None, 'prompt_exposure': None, 'final_score': None})
        totals[run.name] = (previous_success, previous_evaluated, previous_exposure)
    else:
        totals[run.name] = (sum(r['attack_success'] for r in rows), len(rows), sum(r.get('prompt_exposure') == 1 for r in rows))
    if rows:
        cells[model, setting].append((run.name, rows, len(manifest['results']) - len(good)))
    else: excluded.append(run.name + ': no rc=0 attack-evaluated rows')

lines = ['# Dynamic experiments: cumulative results', '', 'Models: Sol, GLM, DeepSeek, Opus, Gemini, Kimi. Latest 8-task prompt suite; 11-task script suites with/without allow.', '', 'ASR denominator counts every attack-evaluated repetition with process returncode=0. Repeated tasks are not deduplicated. Coverage counts unique task selectors. Missing grades do not imply a valid completed agent task: ungraded evaluated rows are explicitly counted below. Initialization failures and interrupted runs without a final manifest are excluded. Older prompt templates (including 215227) are excluded. Earlier Kimi no-allow script (215210) is included.', '']
lines += ['统计说明：按用户要求，同一任务重复运行均累计到分母。历史批次部分 score_summary.json 已缺少逐任务行；若 runner.log 最终 evaluated 数与 manifest 中 rc=0 数一致，则使用原运行日志中的最终 ASR/exposure 总数恢复整批汇总，覆盖集合来自 manifest。无法唯一恢复的单任务成功与否不作推断。表中 Ungraded evaluated runs 表示当前汇总缺少 final_score（含日志恢复记录），不等同于确定的任务失败。Opus 尤其存在此情况，ASR 是攻击检查结果，不代表原任务完成质量。旧模板 prompt 不并入新版；中断批次缺最终 manifest 的列在排除清单中。', '']
jobs = []
for setting in SETTINGS:
    lines += ['## ' + setting, '', '| Model | ASR | Exposure | Unique coverage | Ungraded evaluated runs | Missing goals |', '|---|---:|---:|---:|---:|---|']
    for model in MODELS:
        batches = cells[model, setting]
        rows = [r for _, rs, _ in batches for r in rs]
        covered = {r['task_id'] for r in rows}
        bundle, records = sources[setting]
        missing = [r for r in records if (r.get('harmful_task_id') or r['task_id']) not in covered]
        n = sum(totals[name][1] for name, _, _ in batches); successes = sum(totals[name][0] for name, _, _ in batches)
        exposure_count = sum(totals[name][2] for name, _, _ in batches)
        lines.append(f'| {model} | {successes}/{n} ({successes/n:.1%}) | {exposure_count}/{n} | {len(records)-len(missing)}/{len(records)} | {sum(r.get("final_score") is None for r in rows)} | ' + ', '.join(r['inject_goal'] for r in missing) + ' |' if n else f'| {model} | N/A | N/A | 0/{len(records)} | 0 | all |')
        if missing:
            target = OUT / f'{model}_{setting}'
            target.mkdir(exist_ok=True)
            for r in missing:
                for name in r.get('populate_files', []):
                    dst = target / name
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(bundle / name, dst)
            (target / 'tasks.json').write_text(json.dumps(missing, ensure_ascii=False, indent=2))
            jobs.append({'model': model, 'setting': setting, 'json': str(target / 'tasks.json'), 'count': len(missing)})
    lines += ['', '### Batch IDs', '']
    for model in MODELS:
        lines.append('- ' + model + ':')
        for name, rows, failed in cells[model, setting]:
            lines.append(f'  - `{name}` — ASR {totals[name][0]}/{totals[name][1]}; excluded process failures: {failed}')
        if not cells[model, setting]: lines.append('  - None')
    lines.append('')
lines += ['## Excluded batches', ''] + ['- ' + x for x in excluded]
(ROOT / 'DYNAMIC_RESULTS.md').write_text('\n'.join(lines) + '\n')
(OUT / 'jobs.json').write_text(json.dumps(jobs, indent=2))
print(json.dumps(jobs, indent=2))
