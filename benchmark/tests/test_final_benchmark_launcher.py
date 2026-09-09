import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from benchmark.final_benchmark import run_experiments as launcher
from benchmark.main_concurrency import shared_resource_name


class FinalBenchmarkLauncherTests(unittest.TestCase):
    def test_discovery_requires_complete_unambiguous_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / 'static_prompt_injection'
            folder.mkdir()
            config = folder / 'selected_1_tasks_with_attack_config.json'
            config.write_text(json.dumps([dict(task_id='task1', harmful_task_id='variant1',
                attack_config={}, attack_file='a.txt', populate_files=['a.txt'])]))
            with self.assertRaisesRegex(ValueError, 'missing or out-of-bundle'):
                launcher.discover('static_prompt_injection', root)
            (folder / 'a.txt').write_text('fixture')
            self.assertEqual(launcher.discover('static_prompt_injection', root)[0][2], 1)
            (folder / 'selected_2_tasks_with_attack_config.json').write_text(config.read_text())
            with self.assertRaisesRegex(ValueError, 'found 2'):
                launcher.discover('static_prompt_injection', root)

    def test_batches_use_model_and_separate_outputs_even_after_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'orchestrator_config_gemini35.json').write_text('{"model":"fixture"}')
            batches = [('user_prompt_script_swap/args', root / 'args.json', 15),
                       ('user_prompt_script_swap/no_args', root / 'no_args.json', 15)]
            calls = []
            def run(command, *, cwd, env):
                calls.append(command)
                self.assertEqual(env['ORCHESTRATOR_CONFIG'], str(root / 'orchestrator_config_gemini35.json'))
                directory = Path(command[command.index('--output-root') + 1]) / command[command.index('--run-id') + 1]
                directory.mkdir(parents=True)
                (directory / 'score_summary.json').write_text(json.dumps({
                    'average_attack_success': 0.5, 'attack_evaluated_count': 2,
                    'average_mean_score': 0.75, 'completed_task_count': 1,
                    'average_prompt_exposure': 0.0, 'prompt_exposure_task_count': 0}))
                return SimpleNamespace(returncode=1 if len(calls) == 1 else 0)
            with patch.object(launcher, 'BENCHMARK', root), patch.object(launcher, 'discover', return_value=batches), patch.object(launcher.subprocess, 'run', side_effect=run):
                result = launcher.main(['all', '--model', 'gemini35', '--output-root', str(root / 'out')])
            self.assertEqual(result, 1)
            self.assertEqual(len(calls), 2)
            report = json.loads(next((root / 'out/summaries').glob('*.json')).read_text())
            self.assertNotEqual(report['batches'][0]['output_dir'], report['batches'][1]['output_dir'])
            for row in report['batches']:
                self.assertEqual(row['asr'], 0.5)
                self.assertEqual(row['average_score'], 0.75)
                self.assertIsNone(row['exposure_rate'])

    def test_missing_scores_and_long_batch_names(self):
        self.assertIsNone(launcher.metrics({})['asr'])
        prefix = 'gemini35_dynamic_script_injection_allow_additional_instruction_'
        self.assertNotEqual(shared_resource_name(prefix + 'true_20260909', 'proxy'),
                            shared_resource_name(prefix + 'false_20260909', 'proxy'))


if __name__ == '__main__':
    unittest.main()
