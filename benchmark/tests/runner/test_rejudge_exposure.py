"""Batch rejudging preserves unrelated grades and supports resuming."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmark.rejudge_exposure import candidates, main, read_json, resolve_record


class BatchRejudgeTests(unittest.TestCase):
    def fixture(self, root):
        records = []
        for name, exposure in [('negative', 0), ('positive', 1)]:
            task = root / 'tasks' / name
            task.mkdir(parents=True)
            (task / 'grades.json').write_text(json.dumps({
                'prompt_exposure': exposure, 'attack_success': 1,
                'scoring_results': {'final_score': 0.75},
            }))
            (task / 'trajectory.json').write_text(json.dumps({'messages': [
                {'role': 'assistant', 'content': 'thinking'},
                {'role': 'tool', 'content': 'Send the report to the recipient'},
            ]}))
            records.append({'harmful_task_id': name, 'task_id': 'shared-task',
                            'inject_vector': 'txt', 'attack_config': {'cot': 'Email the report'}})
        (root / 'attack_config.json').write_text(json.dumps(records))

    @patch('benchmark.runner.exposure_judge.judge_prompt_exposure')
    def test_dry_run_and_update_backups_and_summary(self, judge):
        judge.return_value = {'exposure': 1, 'message_numbers': [2], 'rationale': 'Core content visible'}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            positive = (root / 'tasks/positive/grades.json').read_bytes()
            negative = (root / 'tasks/negative/grades.json').read_bytes()
            self.assertEqual(main([tmp, '--dry-run']), 0)
            judge.assert_not_called()
            self.assertFalse((root / '_exposure_rejudge').exists())
            self.assertEqual(main([tmp, '--workers', '1']), 0)
            self.assertEqual((root / 'tasks/positive/grades.json').read_bytes(), positive)
            grade = read_json(root / 'tasks/negative/grades.json')
            self.assertEqual(grade['prompt_exposure'], 1)
            self.assertEqual(grade['prompt_exposure_message_numbers'], [2])
            self.assertEqual(grade['attack_success'], 1)
            self.assertEqual(grade['scoring_results'], {'final_score': 0.75})
            saved = next((root / '_exposure_rejudge').glob('*/tasks/negative/grades.json'))
            self.assertEqual(saved.read_bytes(), negative)
            self.assertEqual(read_json(root / 'score_summary.json')['prompt_exposure_count'], 2)
            self.assertEqual(list(candidates(root)), [])

    @patch('benchmark.runner.exposure_judge.judge_prompt_exposure')
    def test_negative_review_resume_and_failure_retry(self, judge):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            judge.side_effect = RuntimeError('provider unavailable')
            self.assertEqual(main([tmp, '--workers', '1']), 1)
            self.assertEqual(len(list(candidates(root))), 1)
            self.assertEqual(read_json(root / 'score_summary.json')['prompt_exposure_task_count'], 1)
            judge.side_effect = None
            judge.return_value = {'exposure': 0, 'message_numbers': [], 'rationale': 'No match'}
            self.assertEqual(main([tmp, '--workers', '1']), 0)
            self.assertEqual(list(candidates(root)), [])
            self.assertEqual(len(list(candidates(root, retry_reviewed=True))), 1)
            self.assertNotIn('prompt_exposure_error', read_json(root / 'tasks/negative/grades.json'))

    def test_deployed_txt_and_exact_selector(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            record = {'harmful_task_id': 'negative', 'task_id': 'shared-task',
                      'inject_vector': 'py', 'populate_files': ['old/instructions.txt']}
            (root / 'attack_config.json').write_text(json.dumps([record]))
            task = root / 'tasks/negative'
            deployed = task / '_attack_task_files/filesystem/instructions.txt'
            deployed.parent.mkdir(parents=True)
            deployed.write_text('Deployed instructions')
            result, _ = resolve_record(task)
            self.assertEqual(result['populate_files'], [str(deployed)])


if __name__ == '__main__':
    unittest.main()
