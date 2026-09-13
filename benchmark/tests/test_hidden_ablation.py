import json
from pathlib import Path

from benchmark.final_benchmark.ablation.hideen import run_hidden


def test_hidden_plan_pairs_conditions_and_models():
    jobs = run_hidden.plan(Path(run_hidden.__file__).parent, ['with', 'without'])
    assert len(jobs) == len({j.key for j in jobs}) == 40
    assert len({(j.model, j.category.split('/')[0]) for j in jobs[:4]}) == 4
    for model in ['gpt', 'gemini36']:
        groups = [{(j.category.split('/')[1], j.selector) for j in jobs
                   if j.model == model and j.category.startswith(condition + '/')}
                  for condition in ['with', 'without']]
        assert groups[0] == groups[1]
        assert len(groups[0]) == 10


def test_summary_uses_independent_denominators_and_weights_tasks(tmp_path):
    values = [
        ('with/static_prompt_injection/a', {'prompt_exposure': 1, 'attack_success': 0,
                                           'scoring_results': {'final_score': 1.0}}),
        ('with/static_prompt_injection/b', {'prompt_exposure': 0, 'attack_success': 1}),
        ('with/static_script_injection/c', {'prompt_exposure': 1, 'attack_success': 1,
                                           'scoring_results': {'final_score': 0.0}}),
        ('without/static_script_injection/d', None),
    ]
    manifest = {'jobs': [], 'results': {}}
    for suffix, grade in values:
        key = 'gpt/' + suffix
        manifest['jobs'].append(key)
        if grade is not None:
            model, condition, category, task = key.split('/')
            path = tmp_path/model/condition/category/'tasks'/task/'grades.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(grade))
            manifest['results'][key] = {'returncode': int(task == 'b')}
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    rows = run_hidden.summarize(tmp_path)
    row = next(r for r in rows if r['condition'] == 'with' and r['category'] == 'all')
    assert row['exposure_rate'] == row['asr'] == 2/3
    assert row['exposure_rate_n'] == row['asr_n'] == 3
    assert row['score'] == 0.5 and row['score_n'] == 2
    assert row['failed'] == 1 and row['finished'] == 3
    missing = next(r for r in rows if r['condition'] == 'without' and r['category'] == 'all')
    assert missing['score'] is missing['asr'] is missing['exposure_rate'] is None
    assert missing['finished'] == missing['score_n'] == 0
    assert all((tmp_path/f'comparison.{ext}').is_file() for ext in ['md', 'csv', 'json'])
