import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('watcher_runner',ROOT/'run_gemini36.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)


class RunnerTest(unittest.TestCase):
    def test_smoke_selects_same_pair_and_all_is_interleaved(self):
        smoke=runner.plan(ROOT,'smoke')
        self.assertEqual(len(smoke),4)
        self.assertEqual({j.category for j in smoke},set(runner.SETTINGS))
        self.assertEqual(len({(j.dataset_selector,j.goal) for j in smoke}),1)
        alternate=runner.plan(ROOT,'smoke','18')
        self.assertTrue(all(j.goal=='18_copy_file' for j in alternate))
        all_jobs=runner.plan(ROOT,'all')
        self.assertEqual(len(all_jobs),60)
        for i in range(0,60,4):
            wave=all_jobs[i:i+4]
            self.assertEqual([j.category.split("/")[0] for j in wave],list(runner.SETTINGS))
            self.assertEqual(len({j.selector for j in wave}),1)
        self.assertEqual(len({j.key for j in all_jobs}),60)
        from collections import Counter
        counts=Counter((j.category.split('/')[0],j.selector) for j in all_jobs)
        self.assertEqual(set(counts.values()),{3})
        self.assertEqual(len(runner.plan(ROOT,'all',repeats=1)),20)
        with self.assertRaises(ValueError):runner.plan(ROOT,'all',repeats=0)
        with self.assertRaises(ValueError):runner.plan(ROOT,'smoke','999')

    def test_smoke_summary_uses_requested_subset_and_separate_denominators(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            jobs=[];results={}
            for setting,grade,rc in [('with',{'prompt_exposure':1,'attack_success':0},0),
                ('without_corrupt',{'attack_success':1},1),('without_txt',{},None)]:
                key=f'gemini36/{setting}/task1';jobs.append(key)
                if rc is not None:
                    results[key]={'returncode':rc}
                    folder=root/'gemini36'/setting/'tasks'/'task1';folder.mkdir(parents=True)
                    runner.parallel.write_json(folder/'grades.json',grade)
            runner.parallel.write_json(root/'manifest.json',{'jobs':jobs,'results':results})
            with contextlib.redirect_stdout(io.StringIO()):rows={r['setting']:r for r in runner.summarize(root)}
            self.assertTrue(all(r['requested']==1 for r in rows.values()))
            self.assertEqual(rows['with']['exposure_rate'],1)
            self.assertEqual(rows['with']['asr'],0)
            self.assertIsNone(rows['without_corrupt']['exposure_rate'])
            self.assertEqual(rows['without_corrupt']['asr'],1)
            self.assertEqual(rows['without_corrupt']['failed'],1)
            self.assertIsNone(rows['without_txt']['asr'])
            for suffix in ('md','csv','json'):self.assertTrue((root/f'setting_summary.{suffix}').is_file())

    def test_summary_pools_distinct_repeat_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            keys=[]
            for repeat, success in enumerate([1,0,1],1):
                category=f'with/repeat_{repeat:02d}'
                key=f'gemini36/{category}/task1'
                keys.append(key)
                folder=root/'gemini36'/category/'tasks/task1'
                folder.mkdir(parents=True)
                runner.parallel.write_json(folder/'grades.json',{'prompt_exposure':1,'attack_success':success})
            runner.parallel.write_json(root/'manifest.json',{'jobs':keys,'results':{k:{'returncode':0} for k in keys}})
            with contextlib.redirect_stdout(io.StringIO()): rows=runner.summarize(root)
            self.assertEqual(rows[0]['requested'],3)
            self.assertEqual(rows[0]['successful'],2)
            self.assertAlmostEqual(rows[0]['asr'],2/3)
            self.assertEqual(rows[0]['exposure_rate'],1)


if __name__=='__main__':unittest.main()
