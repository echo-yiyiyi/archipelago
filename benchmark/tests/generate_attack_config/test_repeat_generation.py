import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmark.generate_attack_config import generate
from benchmark.generate_attack_file.templates import generate_file


class RepeatGenerationTests(unittest.TestCase):
    def test_same_filename_can_be_generated_twice_and_failure_preserves_old(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / 'tasks.json'
            args = lambda: argparse.Namespace(input_json=root / 'input.json', output=output)
            def render(options):
                directory = options.output.parent / 'task_example'
                # Exercise the same overwrite-protected renderer as the error.
                artifact = generate_file('pyc', {'file_name': 'helper.pyc'}, directory)
                artifact.write_bytes(b'new bytecode')
                options.output.write_text(json.dumps([{'attack_file': 'task_example/helper.pyc', 'populate_files': ['task_example/helper.pyc']}]))
                return 0
            (root / 'unrelated.txt').write_text('keep')
            with patch.object(generate, 'parse_args', side_effect=args), patch.object(generate, '_generate', side_effect=render):
                self.assertEqual(generate.main(), 0)
                self.assertEqual(generate.main(), 0)
            before = output.read_bytes()
            (root / 'task_example/helper.pyc').write_bytes(b'previous')
            def fail(options):
                render(options)
                raise RuntimeError('simulated API failure')
            with patch.object(generate, 'parse_args', side_effect=args), patch.object(generate, '_generate', side_effect=fail):
                with self.assertRaisesRegex(RuntimeError, 'simulated API failure'):
                    generate.main()
            self.assertEqual(output.read_bytes(), before)
            self.assertEqual((root / 'task_example/helper.pyc').read_bytes(), b'previous')
            self.assertEqual((root / 'unrelated.txt').read_text(), 'keep')

    def test_publish_failure_rolls_back(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stage = root / 'stage'
            stage.mkdir()
            (root / 'task').mkdir()
            (root / 'task/old').write_text('old')
            (stage / 'task').mkdir()
            (stage / 'task/new').write_text('new')
            (root / 'tasks.json').write_text('old json')
            (stage / 'tasks.json').write_text('[]')
            replace = Path.replace
            def fail(source, target):
                if source == stage / 'tasks.json':
                    raise OSError('publish failure')
                return replace(source, target)
            with patch.object(Path, 'replace', fail), self.assertRaisesRegex(OSError, 'publish failure'):
                generate._publish_bundle(stage / 'tasks.json', root / 'tasks.json')
            self.assertEqual((root / 'tasks.json').read_text(), 'old json')
            self.assertEqual((root / 'task/old').read_text(), 'old')
            self.assertFalse((root / 'task/new').exists())

    def test_real_dynamic_bundle_is_repeatable_without_model_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, output = root / 'input.json', root / 'tasks.json'
            source.write_text(json.dumps([{'task_id': 'task_example', 'harmful_task_id': 'task_example_dynamic',
                                          'inject_goal': '22_save_client_code', 'inject_vector': 'dynamic_prompt_injection',
                                          'prompt': 'Review the task', 'no_key_words': True}]))
            with patch('sys.argv', ['generate', str(source), '--output', str(output)]), patch(
                'benchmark.utils.azure_openai.build_client', return_value=object()
            ):
                generate.main()
                generate.main()
            row = json.loads(output.read_text())[0]
            self.assertFalse(row['add_user_prompt'])
            self.assertTrue(row['no_key_words'])
            self.assertTrue((root / row['watcher_file']).is_file())
            self.assertTrue((root / row['watcher_config']).is_file())


if __name__ == '__main__':
    unittest.main()
