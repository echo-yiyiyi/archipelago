import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parents[5]))
from benchmark.runner.security_check import check_record_prompt_exposure, check_attack_observation
from prepare import validate


class NoInstructionTest(unittest.TestCase):
    def test_retained_artifacts_match_and_credentials_survive(self):
        self.assertEqual(validate(),15)
        for vector in ('py','pyc','elf'):
            rows=json.loads((ROOT/vector/'selected_5_tasks_with_attack_config.json').read_text())
            credentials=next(r for r in rows if r['inject_goal']=='9_url_query_params')
            self.assertTrue(any(p.endswith('/username-password.txt') for p in credentials['populate_files']))

    def test_explicit_omission_does_not_fail_exposure_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            for vector in ('py','pyc','elf'):
                record={'inject_vector':vector,'omit_additional_instruction':True,'populate_files':['helper']}
                self.assertEqual(check_record_prompt_exposure({'messages':[]},record,base_dir=tmp),{})
                record.pop('omit_additional_instruction')
                with self.assertRaisesRegex(ValueError,'No prepared instruction'):
                    check_record_prompt_exposure({'messages':[]},record,base_dir=tmp)
            # Existing lure observation reports none when there is no lure.
            result=check_attack_observation({'messages':[]},attack_file='helper.py',add_user_prompt=False,lure_files=[])
            self.assertEqual(result['attack_observation'],0)


if __name__=='__main__':unittest.main()
