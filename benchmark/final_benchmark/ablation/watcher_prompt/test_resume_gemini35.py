"""Offline regression tests for completion selection and merged statistics."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import resume_gemini35_all as resume


class ResumeTests(unittest.TestCase):
    def test_interrupted_retry_keeps_completed_and_counts_each_task_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            keys = ['gemini35/with/a', 'gemini35/with/b', 'gemini35/with/c']
            manifest = {'models': ['gemini35'], 'jobs': keys, 'results': {}}
            (root / 'manifest.json').write_text(json.dumps(manifest))
            batch = root / 'gemini35/with'
            batch.mkdir(parents=True)
            for name in ('attack_config.json', 'orchestrator_config.json'):
                (batch / name).write_text('{}')

            def grade(run, key, attack):
                directory = resume.task_dir(run, key)
                directory.mkdir(parents=True, exist_ok=True)
                (directory / 'grades.json').write_text(json.dumps({
                    'attack_success': attack, 'prompt_exposure': 1,
                    'scoring_results': {'final_score': 0.5}}))

            grade(root, keys[0], 0)
            partial = resume.task_dir(root, keys[1])
            partial.mkdir(parents=True)
            (partial / 'grades.json').write_text('{')
            retry = root / 'resume_attempts/attempt_1/parallel_1'
            grade(retry, keys[0], 1)  # Duplicate must not override retained original.
            grade(retry, keys[1], 1)
            selected = resume.collect(root, manifest)
            self.assertEqual(selected, {keys[0]: root, keys[1]: retry})
            with contextlib.redirect_stdout(io.StringIO()):
                output = resume.merge(root, manifest, selected)
            row = resume.read(output / 'setting_summary.json')['rows'][0]
            self.assertEqual((row['requested'], row['attack_evaluated'], row['successful']), (3, 2, 1))
            self.assertEqual(row['asr'], 0.5)
            self.assertEqual(row['attack_missing'], 1)
            # A later retry adds only the last missing task.
            retry2 = root / 'resume_attempts/attempt_2/parallel_2'
            grade(retry2, keys[2], 0)
            with contextlib.redirect_stdout(io.StringIO()):
                resume.merge(root, manifest, resume.collect(root, manifest))
            row = resume.read(output / 'setting_summary.json')['rows'][0]
            self.assertEqual((row['attack_evaluated'], row['successful']), (3, 1))
            self.assertFalse(resume.read(output / 'manifest.json')['interrupted'])

    def test_repeats_are_independent_when_resuming(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            keys=[f'gemini35/with/repeat_{i:02d}/same_task' for i in range(1,4)]
            manifest={'models':['gemini35'],'jobs':keys,'results':{}}
            for key in keys:
                batch=resume.task_dir(root,key).parent.parent
                batch.mkdir(parents=True,exist_ok=True)
                for name in ('attack_config.json','orchestrator_config.json'):
                    (batch/name).write_text('{}')
            for key,attack in zip(keys[:2],[0,1]):
                directory=resume.task_dir(root,key)
                directory.mkdir(parents=True)
                (directory/'grades.json').write_text(json.dumps({
                    'attack_success':attack,'prompt_exposure':1,
                    'scoring_results':{'final_score':0.5}}))
            selected=resume.collect(root,manifest)
            self.assertEqual(set(selected),set(keys[:2]))
            with contextlib.redirect_stdout(io.StringIO()):
                output=resume.merge(root,manifest,selected)
            row=resume.read(output/'setting_summary.json')['rows'][0]
            self.assertEqual((row['requested'],row['attack_evaluated'],row['successful']),(3,2,1))
            self.assertEqual(row['attack_missing'],1)

    def test_incomplete_or_invalid_grades_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for score in (None, True, float('nan')):
                (directory / 'grades.json').write_text(json.dumps({
                    'attack_success': 0, 'prompt_exposure': 0,
                    'scoring_results': {'final_score': score}}))
                self.assertFalse(resume.complete(directory))
            (directory / 'grades.json').write_text(json.dumps({
                'attack_success': 0, 'prompt_exposure': 0,
                'scoring_results': {'final_score': 0}}))
            self.assertTrue(resume.complete(directory))


if __name__ == '__main__':
    unittest.main()
