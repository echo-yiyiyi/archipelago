import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('script_runner', ROOT/'run_gemini36.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
runner = module.runner


class ScriptRunnerTest(unittest.TestCase):
    def test_paired_plans(self):
        for suite, count in [('smoke', 2), ('all', 20)]:
            jobs = runner.plan(ROOT, suite)
            self.assertEqual(len(jobs), count)
            for i in range(0, count, 2):
                left, right = jobs[i:i+2]
                self.assertEqual((left.category, right.category), ('with', 'direct_arg'))
                self.assertEqual((left.dataset_selector, left.goal),
                                 (right.dataset_selector, right.goal))
        self.assertEqual({j.goal for j in runner.plan(ROOT, 'smoke', '16')},
                         {'16_email_broadcast_link_arg'})
        with self.assertRaises(ValueError):
            runner.plan(ROOT, 'smoke', '17')  # Removed in the frozen subset.


if __name__ == '__main__':
    unittest.main()
