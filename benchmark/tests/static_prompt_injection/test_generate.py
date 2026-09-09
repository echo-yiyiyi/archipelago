import json
from collections import Counter, defaultdict
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmark.final_benchmark import generate_static_prompt_injection_tasks as generate


class StaticGenerationTests(unittest.TestCase):
    def setUp(self):
        self.tasks = generate.load_json_array(generate.DEFAULT_INPUT, 'tasks')
        self.goals = generate.resolve_goal_ids(generate.DEFAULT_GOAL_IDS,
            generate.load_json_array(generate.DEFAULT_GOALS, 'goals'))

    def test_balancing_and_uniqueness(self):
        for variants in (1, 2, 3, 7, 14, 15):
            for seed in range(5):
                rows = generate.expand_tasks(self.tasks, self.goals, 15 * variants, seed=seed)
                self.assertEqual(len(rows), 15 * variants)
                groups = defaultdict(list)
                tasks = defaultdict(set)
                for row in rows:
                    groups[row['inject_vector']].append(row)
                    tasks[row['task_id']].add(row['inject_goal'])
                for group in [rows, *groups.values()]:
                    counts = Counter(r['inject_goal'] for r in group)
                    values = [counts[g] for g in self.goals]
                    self.assertLessEqual(max(values) - min(values), 1)
                self.assertTrue(all(len(goals) == variants for goals in tasks.values()))
        self.assertEqual(generate.expand_tasks(self.tasks, self.goals, 30),
                         generate.expand_tasks(self.tasks, self.goals, 30))

    def test_validation_and_custom_goals(self):
        catalog = generate.load_json_array(generate.DEFAULT_GOALS, 'goals')
        goals = generate.resolve_goal_ids(['1,18', '24_save_final_answer'], catalog)
        self.assertEqual(len(generate.expand_tasks(self.tasks, goals, 30)), 30)
        for count in (0, -15, 31, 240):
            with self.assertRaises(ValueError):
                generate.expand_tasks(self.tasks, self.goals, count)
        for ids in (['99'], ['1', '1_email_send_file']):
            with self.assertRaises(ValueError):
                generate.resolve_goal_ids(ids, catalog)

    def test_pipeline_and_leakage(self):
        with tempfile.TemporaryDirectory() as directory:
            def fake_generator(command, **kwargs):
                rows = json.loads(Path(command[3]).read_text())
                final = Path(command[command.index('--output') + 1])
                for row in rows:
                    artifact = Path(row['harmful_task_id']) / 'fixture.txt'
                    (final.parent / artifact).parent.mkdir(parents=True)
                    (final.parent / artifact).write_text('fixture')
                    row.update(attack_config={'leakage_type': 'wrong'},
                               attack_file=str(artifact), populate_files=[str(artifact)])
                final.write_text(json.dumps(rows))
            with patch.object(generate.subprocess, 'run', side_effect=fake_generator) as run:
                generate.main(['--output-dir', directory, '--output-task-number', '30'])
                run.assert_called_once()
            rows = json.loads((Path(directory) / 'selected_30_tasks_with_attack_config.json').read_text())
            for row in rows:
                expected = 'external' if int(row['inject_goal'].split('_')[0]) in {1,2,3,4,5,6,8} else 'internal'
                self.assertEqual(row['leakage_type'], expected)
                self.assertEqual(row['attack_config']['leakage_type'], expected)
