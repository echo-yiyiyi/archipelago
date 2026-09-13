"""Check ASR denominators and format pooling without launching evaluations."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('vector_runner', Path(__file__).with_name('run_models.py'))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class SummaryTest(unittest.TestCase):
    def test_missing_evaluations_and_failed_process_are_distinct(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            jobs, results = [], {}
            # py: success + failure; pyc: missing + success with process error; elf: pending.
            for vector, task, value, rc in [('py','a',1,0), ('py','b',0,0),
                    ('pyc','a',None,1), ('pyc','b',1,1), ('elf','a',None,None)]:
                key = f'kimi/static_script_injection/{vector}/{task}'
                jobs.append(key)
                if rc is not None:
                    results[key] = {'returncode': rc}
                if value is not None:
                    folder = root/'kimi'/'static_script_injection'/vector/'tasks'/task
                    folder.mkdir(parents=True)
                    runner.write(folder/'grades.json', {'attack_success': value})
            runner.write(root/'manifest.json', {'jobs': jobs, 'results': results})
            rows = {r['vector']: r for r in runner.summarize(root)}
            self.assertEqual(rows['py']['asr'], 0.5)
            self.assertEqual(rows['pyc']['evaluated'], 1)
            self.assertEqual(rows['pyc']['failed'], 2)
            self.assertIsNone(rows['elf']['asr'])
            self.assertEqual(rows['all']['asr'], 2/3)
            self.assertEqual(rows['all']['missing'], 2)
            self.assertEqual(rows['all']['requested'], 5)

    def test_plan_has_five_paired_tasks_per_model_category_vector(self):
        with tempfile.TemporaryDirectory() as temporary:
            configs = runner.configs(list(runner.SOURCES), Path(temporary), True)
            jobs = runner.plan(runner.ROOT, configs)
            self.assertEqual(len(jobs), 135)
            self.assertEqual(len({j.key for j in jobs}), 135)
            for model in configs:
                for category in runner.CATEGORIES:
                    pairs = [{(j.dataset_selector, j.goal) for j in jobs
                              if j.model == model and j.category == f'{category}/{v}'}
                             for v in runner.VECTORS]
                    self.assertEqual(len(pairs[0]), 5)
                    self.assertEqual(pairs[0], pairs[1])
                    self.assertEqual(pairs[0], pairs[2])


if __name__ == '__main__':
    unittest.main()
