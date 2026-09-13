import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('prompt_runner', Path(__file__).with_name('run_gemini36.py'))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class RunnerTest(unittest.TestCase):
    def test_plan_pairs_all_nine_vectors(self):
        jobs = runner.plan(runner.ROOT)
        self.assertEqual(len(jobs), 45)
        groups = [{(j.dataset_selector, j.goal) for j in jobs if j.category == v} for v in runner.VECTORS]
        self.assertEqual(len(groups[0]), 5)
        self.assertTrue(all(g == groups[0] for g in groups))

    def test_separate_denominators_and_pending_results(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            entries = [('txt','a',{'prompt_exposure':1,'attack_success':0},0),
                       ('txt','b',{'prompt_exposure':0},0),
                       ('txt','c',{'attack_success':1},1),
                       ('pdf','a',{},None)]
            jobs, results = [], {}
            for vector, task, grade, rc in entries:
                key = f'gemini36/{vector}/{task}'
                jobs.append(key)
                if rc is not None:
                    results[key] = {'returncode':rc}
                    directory = root/'gemini36'/vector/'tasks'/task
                    directory.mkdir(parents=True)
                    runner.parallel.write_json(directory/'grades.json', grade)
            runner.parallel.write_json(root/'manifest.json', {'jobs':jobs,'results':results})
            with contextlib.redirect_stdout(io.StringIO()):
                rows = {r['vector']:r for r in runner.summarize(root)}
            self.assertEqual(rows['txt']['exposure_rate'], .5)
            self.assertEqual(rows['txt']['asr'], .5)
            self.assertEqual(rows['txt']['exposure_evaluated'], 2)
            self.assertEqual(rows['txt']['attack_evaluated'], 2)
            self.assertEqual(rows['txt']['failed'], 1)
            self.assertEqual(rows['txt']['attack_missing'], 1)
            self.assertIsNone(rows['pdf']['exposure_rate'])
            self.assertIsNone(rows['pdf']['asr'])
            for suffix in ('md','csv','json'):
                self.assertTrue((root/f'vector_summary.{suffix}').is_file())


if __name__ == '__main__':
    unittest.main()
