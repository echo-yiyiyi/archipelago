import json
from collections import Counter

import pytest

from benchmark.final_benchmark.ablation.key_words import run_models as runner


def test_plan_interleaves_models_settings_and_preserves_pairing():
    jobs = runner.plan(runner.ROOT, ['with', 'without'], runner.MODELS)
    assert len(jobs) == len({j.key for j in jobs}) == 120
    assert {j.model for j in jobs[:6]} == set(runner.MODELS)
    assert {j.category.split('/')[0] for j in jobs[:6]} == {'with', 'without'}
    for model in runner.MODELS:
        assert len([j for j in jobs if j.model == model]) == 40
        for setting in ('with', 'without'):
            rows = json.loads(next(j.source for j in jobs if j.model == model and j.category == setting + '/static_script_injection').read_text())
            assert Counter(r['inject_vector'] for r in rows) == {'py': 3, 'pyc': 3, 'elf': 4}


def manifest_fixture(root):
    batches = []
    specs = [('static_prompt_injection', 2, .5, 4, .25, 1, .8),
             ('static_script_injection', 8, .25, 2, 1., 3, .4)]
    for category, na, attack, ne, exposure, ns, score in specs:
        directory = root / 'gemini36' / 'without' / category
        directory.mkdir(parents=True)
        (directory / 'score_summary.json').write_text(json.dumps({
            'attack_evaluated_count': na, 'average_attack_success': attack,
            'prompt_exposure_task_count': ne, 'average_prompt_exposure': exposure,
            'completed_task_count': ns, 'average_mean_score': score}))
        batches.append({'model': 'gemini36', 'category': 'without/' + category,
                        'requested_task_count': 10, 'finished_task_count': 10, 'failed_task_count': 2})
    path = root / 'manifest.json'
    path.write_text(json.dumps({'batches': batches, 'interrupted': False}))
    return path


def test_combined_metrics_use_separate_denominators_and_report_missing(tmp_path):
    rows = runner.summarize(manifest_fixture(tmp_path))
    combined = next(r for r in rows if r['category'] == 'combined')
    assert combined['asr'] == pytest.approx(.3)
    assert combined['exposure_rate'] == pytest.approx(.5)
    assert combined['score'] == pytest.approx(.5)
    assert combined['missing_attack_count'] == 10
    assert combined['missing_exposure_count'] == 14
    assert combined['missing_score_count'] == 16
    assert combined['failed_task_count'] == 4
    assert (tmp_path / 'model_summary.csv').is_file()
    assert (tmp_path / 'model_summary.md').is_file()


def test_missing_summary_is_unknown_not_zero(tmp_path):
    path = manifest_fixture(tmp_path)
    for score in tmp_path.rglob('score_summary.json'):
        score.unlink()
    for row in runner.summarize(path):
        assert row['asr'] is row['score'] is row['exposure_rate'] is None
        assert row['missing_score_count'] == row['requested_task_count']


def test_missing_deepseek_key_stops_before_any_execution(monkeypatch):
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    def unexpected(*args):
        pytest.fail('should not start any models without the required key')
    monkeypatch.setattr(runner.parallel, 'execute', unexpected)
    with pytest.raises(SystemExit) as result:
        runner.main(['--settings', 'without'])
    assert result.value.code == 2


def test_failed_run_still_writes_summary(tmp_path, monkeypatch):
    def fake_execute(args, jobs):
        assert len(jobs) == 20
        directory = args.output_root / 'parallel_test'
        directory.mkdir()
        manifest_fixture(directory)
        return 1
    monkeypatch.setattr(runner.parallel, 'execute', fake_execute)
    assert runner.main(['--settings', 'without', '--models', 'gemini36', '--output-root', str(tmp_path)]) == 1
    assert len(list(tmp_path.rglob('model_summary.md'))) == 1


def test_terra_uses_openai_responses_like_astra_and_requires_openai_key(monkeypatch):
    from pathlib import Path
    root = runner.REPO / 'benchmark'
    sol = json.loads((root / 'orchestrator_config_gpt_terra_high.json').read_text())
    astra = json.loads((root / 'orchestrator_config_gpt_astra_low.json').read_text())
    assert sol['model'] == 'openai/responses/gpt-5.6-terra'
    assert 'azure_key_vault' not in sol
    assert sol['extra_args']['api_base'] == astra['extra_args']['api_base']
    assert sol['extra_args']['allowed_openai_params'] == astra['extra_args']['allowed_openai_params']
    assert sol['extra_args']['reasoning']['effort'] == 'high'
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    with pytest.raises(SystemExit) as result:
        runner.main(['--settings', 'without', '--models', 'gpt_terra_high'])
    assert result.value.code == 2
