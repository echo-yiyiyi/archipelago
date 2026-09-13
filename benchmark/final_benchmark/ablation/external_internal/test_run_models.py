import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('leakage_runner',Path(__file__).with_name('run_models.py'))
runner=importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class RunnerTest(unittest.TestCase):
    def test_full_plan_and_static_subset(self):
        with tempfile.TemporaryDirectory() as tmp:
            configs=runner.configs(list(runner.SOURCES),Path(tmp),True)
            jobs=runner.plan(runner.ROOT,['static','dynamic'],configs)
            self.assertEqual(len(jobs),180)
            self.assertEqual(len({j.key for j in jobs}),180)
            for model in configs:
                for mode in ('static','dynamic'):
                    for kind,n in runner.COUNTS.items():
                        subset=[j for j in jobs if j.model==model and j.category==f'{kind}/{mode}_prompt_injection']
                        self.assertEqual(len(subset),n)
                        self.assertEqual(len({j.dataset_selector for j in subset}),2)
            subset=runner.plan(runner.ROOT,['static'],{'deepseek':configs['deepseek']})
            self.assertEqual(len(subset),30)

    def test_independent_metric_denominators_and_groups(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            entries=[('internal','static', 'a',{'prompt_exposure':1,'attack_success':1},0),
                     ('internal','static', 'b',{'prompt_exposure':0,'attack_success':0},0),
                     ('internal','static', 'c',{'prompt_exposure':1},1),
                     ('external','dynamic','a',{},None)]
            jobs=[];results={}
            for kind,mode,task,grade,rc in entries:
                key=f'deepseek/{kind}/{mode}_prompt_injection/{task}'
                jobs.append(key)
                if rc is not None:
                    results[key]={'returncode':rc}
                    folder=root/'deepseek'/kind/f'{mode}_prompt_injection'/'tasks'/task
                    folder.mkdir(parents=True)
                    runner.parallel.write_json(folder/'grades.json',grade)
            runner.parallel.write_json(root/'manifest.json',{'jobs':jobs,'results':results})
            with contextlib.redirect_stdout(io.StringIO()):
                rows=runner.summarize(root)
            self.assertEqual(len(rows),2)
            internal=next(r for r in rows if r['leakage_type']=='internal')
            external=next(r for r in rows if r['leakage_type']=='external')
            self.assertEqual(internal['exposure_rate'],2/3)
            self.assertEqual(internal['asr'],.5)
            self.assertEqual(internal['attack_missing'],1)
            self.assertEqual(internal['failed'],1)
            self.assertIsNone(external['asr'])
            self.assertIsNone(external['exposure_rate'])
            self.assertEqual(external['finished'],0)


if __name__=='__main__':unittest.main()
