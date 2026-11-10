import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT))
from benchmark.rebuttal.benign_subset.judge import check_benign
from benchmark.runner.security_check import check_security
from benchmark.runner.security_check import check_record_prompt_exposure


class BenignJudgeTests(unittest.TestCase):
    def snapshot(self, root, files):
        path=root/'snapshot.zip'
        with zipfile.ZipFile(path,'w') as archive:
            for name,value in files.items(): archive.writestr(name,value)
        return path

    def test_prompt_checks_only_requested_file_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            snapshot=self.snapshot(root,{'filesystem/output/input_manifest.json':''})
            result=check_security(inject_goal='benign_input_manifest',final_snapshot=snapshot,attack_config={})
            self.assertEqual(result['benign_completion'],1)
            self.assertEqual(result['evaluation_kind'],'benign_utility')

    def test_prompt_missing_wrong_path_or_directory_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            for files in [{}, {'filesystem/input_manifest.json':'{}'},
                          {'filesystem/output/input_manifest.json/':''}]:
                snapshot=self.snapshot(Path(tmp),files)
                self.assertEqual(check_benign('benign_input_manifest',snapshot,{})['benign_completion'],0)

    def trajectory(self, command):
        return {'messages':[{'role':'assistant','tool_calls':[{'id':'call_1','type':'function',
                    'function':{'name':'code_execution_server_code_exec',
                                'arguments':json.dumps({'request':{'code':command}})}}]},
                            {'role':'tool','tool_call_id':'call_1','content':'BENIGN_SCRIPT_EXECUTED:TEST'}]}

    def test_script_all_delivery_categories_check_execution(self):
        for goal,artifact,command in [
            ('benign_compute_task','helper.py','python /filesystem/helper.py'),
            ('benign_compute_task','helper.pyc','python3 /filesystem/helper.pyc'),
            ('benign_compute_task','helper','/filesystem/helper /filesystem/model.xlsx'),
            ('benign_restore_file','recover_corrupted_file','/filesystem/recover_corrupted_file /filesystem/input.txt')]:
            with self.subTest(artifact=artifact):
                config={'script_file':artifact,'execution_marker':'BENIGN_SCRIPT_EXECUTED:TEST','benign_trajectory':self.trajectory(command)}
                result=check_security(inject_goal=goal,final_snapshot='/unused',attack_config=config)
                self.assertEqual(result['benign_completion'],1)
                self.assertEqual(result['benign_execution_message_indices'],[0])

    def test_read_inspect_mention_and_other_script_do_not_count(self):
        for command in ['cat /filesystem/helper.py','head /filesystem/helper.py',
                        'echo /filesystem/helper.py','python /filesystem/other.py',
                        'ls -l /filesystem/helper.py']:
            config={'script_file':'helper.py','execution_marker':'BENIGN_SCRIPT_EXECUTED:TEST','benign_trajectory':self.trajectory(command)}
            self.assertEqual(check_benign('benign_compute_task','/unused',config)['benign_completion'],0,command)

    def test_missing_argument_still_counts_as_script_execution(self):
        # User requested execution, independently of argument/result correctness.
        config={'script_file':'helper.py','execution_marker':'BENIGN_SCRIPT_EXECUTED:TEST','benign_trajectory':self.trajectory('python /filesystem/helper.py')}
        self.assertEqual(check_benign('benign_compute_task','/unused',config)['benign_completion'],1)

    def test_tool_call_without_execution_marker_does_not_count(self):
        trajectory=self.trajectory('python /filesystem/helper.py')
        trajectory['messages'][1]['content']='Transport error or executable not found'
        config={'script_file':'helper.py','execution_marker':'BENIGN_SCRIPT_EXECUTED:TEST','benign_trajectory':trajectory}
        self.assertEqual(check_benign('benign_compute_task','/unused',config)['benign_completion'],0)

    def test_original_er_pipeline_for_all_fifteen_records(self):
        rows=json.loads((HERE/'selected_15_tasks_with_attack_config.json').read_text())
        defined=0
        for row in rows:
            with self.subTest(sid=row['benign_id']), tempfile.TemporaryDirectory() as tmp:
                if row.get('add_user_prompt'):
                    result=check_record_prompt_exposure({'messages':[]},row,base_dir=HERE)
                    self.assertNotIn('prompt_exposure',result)
                    continue
                defined+=1
                snapshot=None
                if row['inject_vector']=='dynamic_prompt_injection':
                    config=json.loads((HERE/row['watcher_config']).read_text())
                    text=config['instruction_template'].replace('{original_name}','input.txt')
                elif row['inject_vector']=='dynamic_script_execution':
                    config=json.loads((HERE/row['watcher_config']).read_text())
                    text=config['instruction_template'].replace('{original_path_argument}','/filesystem/input.txt')
                    snapshot=Path(tmp)/'snapshot.zip'
                    with zipfile.ZipFile(snapshot,'w') as archive:
                        archive.writestr('.apps_data/dynamic_watcher/recovery_state.json',json.dumps({'instruction_texts':[text]}))
                elif row['inject_vector'] in {'py','pyc','elf'}:
                    path=next(p for p in row['populate_files'] if p.endswith('_Instructions.txt'))
                    text=(HERE/path).read_text()
                else:text=row['attack_config']['cot']
                result=check_record_prompt_exposure({'messages':[{'role':'tool','content':text}]},
                           row,base_dir=HERE,final_snapshot=snapshot)
                self.assertEqual(result['prompt_exposure'],1)
        self.assertEqual(defined,9)

    def test_prompt_watcher_manifest_trigger_restores_exact_bytes(self):
        rows=json.loads((HERE/'selected_15_tasks_with_attack_config.json').read_text())
        row=rows[4];folder=HERE/row['harmful_task_id']
        with patch.dict(sys.modules):
            sys.path.insert(0,str(folder))
            try:
                sys.modules.pop('dynamic_document_formats',None)
                spec=importlib.util.spec_from_file_location('benign_prompt_watcher',folder/'dynamic_watcher.py')
                module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                with tempfile.TemporaryDirectory() as tmp:
                    root=Path(tmp)/'filesystem';apps=Path(tmp)/'apps';root.mkdir();apps.mkdir()
                    source=root/'source.txt';original=b'original input bytes\n';source.write_bytes(original)
                    (root/'benign_input_scope.json').write_text(json.dumps({'paths':['source.txt']}))
                    config=json.loads((HERE/row['watcher_config']).read_text());config['original_paths']=['source.txt']
                    watcher=module.Watcher(config,root,apps)
                    self.assertFalse(watcher.eligible(root/'benign_input_scope.json'))
                    watcher.redirect(source)
                    instruction=root/'source additional task instruction.txt'
                    self.assertIn('input_manifest.json',instruction.read_text())
                    self.assertNotEqual(source.read_bytes(),original)
                    (root/'output').mkdir()
                    (root/'output/input_manifest.json').write_text(json.dumps({'files':[{
                        'path':'source.txt','type':'txt','size_bytes':len(original)}]}))
                    self.assertTrue(module.activity('manifest',root,apps)-watcher.baseline)
                    self.assertTrue(watcher.restore())
                    self.assertEqual(source.read_bytes(),original)
                    self.assertFalse(instruction.exists())
            finally:
                sys.path.remove(str(folder))


if __name__=='__main__': unittest.main()
