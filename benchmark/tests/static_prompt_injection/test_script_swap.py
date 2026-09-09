from collections import Counter
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmark.final_benchmark import generate_script_swap_tasks as generate


class ScriptSwapTests(unittest.TestCase):
    def setUp(self):
        self.tasks = generate.load_json_array(generate.DEFAULT_INPUT, "tasks")
        self.catalog = generate.load_json_array(generate.DEFAULT_GOALS, "goals")

    def assert_balanced(self, rows, field, values):
        counts = Counter(r[field] for r in rows)
        self.assertLessEqual(max(counts[v] for v in values) - min(counts[v] for v in values), 1)

    def test_sampling_counts_balance_and_no_stale_config(self):
        tasks = [dict(t, attack_config={"stale": True}, no_key_words=True, add_user_prompt=False)
                 for t in self.tasks]
        for ids in (generate.ARGS_GOALS, generate.NO_ARGS_GOALS):
            goals = generate.resolve_goal_ids(ids, self.catalog)
            for count in (1, 14, 15, 16, 30, 44, len(tasks) * len(goals)):
                rows = generate.sample_tasks(tasks, goals, count)
                self.assertEqual(len(rows), count)
                self.assertEqual(len({(r['task_id'], r['inject_goal']) for r in rows}), count)
                self.assert_balanced(rows, 'task_id', [t['task_id'] for t in tasks])
                self.assert_balanced(rows, 'inject_goal', goals)
                self.assert_balanced(rows, 'inject_vector', generate.VECTORS)
                for goal in goals:
                    self.assert_balanced([r for r in rows if r['inject_goal'] == goal], 'inject_vector', generate.VECTORS)
                for row in rows:
                    self.assertTrue(row['add_user_prompt'])
                    self.assertFalse(row['no_key_words'])
                    self.assertNotIn('attack_config', row)
            with self.assertRaises(ValueError):
                generate.sample_tasks(tasks, goals, len(tasks) * len(goals) + 1)
        args = generate.sample_tasks(tasks, generate.resolve_goal_ids(generate.ARGS_GOALS, self.catalog), 16)
        no_args = generate.sample_tasks(tasks, generate.resolve_goal_ids(generate.NO_ARGS_GOALS, self.catalog), 17, vector_offset=16)
        self.assert_balanced(args + no_args, 'inject_vector', generate.VECTORS)
        self.assertEqual(args, generate.sample_tasks(tasks, generate.resolve_goal_ids(generate.ARGS_GOALS, self.catalog), 16))

    def test_two_complete_bundles_and_generator_options(self):
        with tempfile.TemporaryDirectory() as directory:
            def fake_generator(command, **kwargs):
                self.assertIn('--add-user-prompt', command)
                rows = json.loads(Path(command[3]).read_text())
                final = Path(command[command.index('--output') + 1])
                for row in rows:
                    artifact = Path(row['harmful_task_id']) / ('helper.' + row['inject_vector'])
                    (final.parent / artifact).parent.mkdir(parents=True)
                    (final.parent / artifact).write_text('fixture')
                    row.update(attack_config={'add_user_prompt': True}, attack_file=str(artifact), populate_files=[str(artifact)])
                final.write_text(json.dumps(rows))
            with patch.object(generate.subprocess, 'run', side_effect=fake_generator) as run:
                generate.main(['15', '30', '--output-dir', directory])
                self.assertEqual(run.call_count, 2)
            for group, count, allowed in [('args', 15, generate.ARGS_GOALS), ('no_args', 30, generate.NO_ARGS_GOALS)]:
                rows = json.loads((Path(directory) / group / f'selected_{count}_tasks_with_attack_config.json').read_text())
                self.assertEqual(len(rows), count)
                self.assertTrue(all(int(r['inject_goal'].split('_')[0]) in allowed for r in rows))
                self.assertTrue(all(r['attack_config']['leakage_type'] == r['leakage_type'] for r in rows))

    def test_defaults_and_sample_only(self):
        args = generate.parse_args([])
        self.assertEqual((args.args_count, args.no_args_count), (15, 15))
        with tempfile.TemporaryDirectory() as directory, patch.object(generate.subprocess, 'run') as run:
            generate.main(['--sample-only', '--output-dir', directory])
            run.assert_not_called()
            self.assertEqual(len(list(Path(directory).glob('*/selected_15_tasks_with_inject_goals.json'))), 2)


if __name__ == '__main__':
    unittest.main()
