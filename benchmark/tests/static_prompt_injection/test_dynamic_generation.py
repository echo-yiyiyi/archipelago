from collections import Counter
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmark.final_benchmark import generate_dynamic_prompt_injection_tasks as generate
from benchmark.final_benchmark import generate_dynamic_script_injection as script_generate


class DynamicGenerationTests(unittest.TestCase):
    def test_default_balancing_and_dynamic_flags(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch('benchmark.final_benchmark.generate_script_swap_tasks.subprocess.run') as run:
                generate.main(['--sample-only', '--output-dir', temp])
                run.assert_not_called()
            rows = json.loads((Path(temp) / 'selected_30_tasks_with_inject_goals.json').read_text())
            self.assertEqual(set(Counter(r['task_id'] for r in rows).values()), {2})
            self.assertEqual(set(Counter(r['inject_goal'] for r in rows).values()), {2})
            self.assertEqual({int(r['inject_goal'].split('_')[0]) for r in rows}, set(generate.DEFAULT_GOAL_IDS))
            self.assertTrue(all(r['inject_vector'] == 'dynamic_prompt_injection' and r['no_key_words'] and not r['add_user_prompt'] for r in rows))
            self.assertEqual(len({r['harmful_task_id'] for r in rows}), 30)

    def test_custom_count(self):
        with tempfile.TemporaryDirectory() as temp:
            generate.main(['--sample-only', '--output-dir', temp, '--output-task-number', '45'])
            rows = json.loads((Path(temp) / 'selected_45_tasks_with_inject_goals.json').read_text())
            self.assertEqual(len(rows), 45)
            self.assertEqual(set(Counter(r['inject_goal'] for r in rows).values()), {3})

    def test_script_goals_coverage_and_full_cross_product(self):
        with tempfile.TemporaryDirectory() as temp:
            for count in (30, 390):
                script_generate.main(['--sample-only', '--output-dir', temp, '--output-task-number', str(count)])
                per_group = count // 2
                groups = [json.loads((Path(temp) / f'add_user_prompt_{enabled}' / f'selected_{per_group}_tasks_with_inject_goals.json').read_text()) for enabled in ('true', 'false')]
                rows = groups[1]
                self.assertEqual(len(rows), per_group)
                self.assertTrue(all(r['add_user_prompt'] for r in groups[0]))
                self.assertEqual([{k: v for k, v in r.items() if k != 'add_user_prompt'} for r in groups[0]], [{k: v for k, v in r.items() if k != 'add_user_prompt'} for r in rows])
                self.assertEqual(len({r['task_id'] for r in rows}), 15)
                self.assertEqual({int(r['inject_goal'].split('_')[0]) for r in rows}, set(generate.ARGS_GOALS))
                self.assertEqual(len({(r['task_id'], r['inject_goal']) for r in rows}), per_group)
                self.assertTrue(all(r['inject_vector'] == 'dynamic_script_execution' and r['no_key_words'] and not r['add_user_prompt'] for r in rows))
                if count == 390:
                    self.assertEqual(set(Counter(r['task_id'] for r in rows).values()), {13})

    def test_script_rejects_unpaired_count(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, 'positive even'):
                script_generate.main(['--sample-only', '--output-dir', temp, '--output-task-number', '31'])
            self.assertEqual(list(Path(temp).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
