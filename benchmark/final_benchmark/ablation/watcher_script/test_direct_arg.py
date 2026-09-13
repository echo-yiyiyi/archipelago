import ast
import importlib.util
import json
from pathlib import Path
import shlex
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_direct_arg import SOURCE, OUTPUT, embedded_source, instruction


class DirectArgumentTests(unittest.TestCase):
    def test_only_instruction_templates_change(self):
        rows = json.loads((SOURCE / 'selected_10_tasks_with_attack_config.json').read_text())
        self.assertEqual(len(rows), 10)
        configs = {Path(row['watcher_config']) for row in rows}
        for source in SOURCE.rglob('*'):
            if not source.is_file():
                continue
            relative = source.relative_to(SOURCE)
            target = OUTPUT / relative
            if relative in configs:
                original = json.loads(source.read_text())
                changed = json.loads(target.read_text())
                self.assertNotEqual(original.pop('instruction_template'),
                                    changed.pop('instruction_template'))
                self.assertEqual(original, changed)
            else:
                self.assertEqual(source.read_bytes(), target.read_bytes())

    def test_actual_redirect_and_wrapper_argument_count(self):
        rows = json.loads((OUTPUT / 'selected_10_tasks_with_attack_config.json').read_text())
        for row in rows:
            with self.subTest(goal=row['inject_goal']), tempfile.TemporaryDirectory() as temp:
                bundle = OUTPUT / row['harmful_task_id']
                sys.path.insert(0, str(bundle))
                try:
                    spec = importlib.util.spec_from_file_location('direct_watcher', bundle / 'dynamic_script_watcher.py')
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                finally:
                    sys.path.pop(0)
                root = Path(temp)
                original = root / "task's file.txt"
                original.write_text('original task content')
                watcher = module.ScriptWatcher.__new__(module.ScriptWatcher)
                watcher.stopped = False
                watcher.eligible = lambda path: True
                watcher.processed = set()
                watcher.backups = root / 'backups'
                watcher.backups.mkdir()
                watcher.root = root
                watcher.private = bundle
                watcher.replacements = {}
                watcher.armed = {}
                watcher.history = []
                watcher.save_state = lambda: None
                watcher.config = json.loads((OUTPUT / row['watcher_config']).read_text())
                watcher.redirect(original)
                rendered = original.read_text()
                self.assertIn('Two non-empty arguments are required', rendered)
                self.assertEqual(rendered, instruction(row, bundle / 'recover_corrupted_file').replace(
                    '{original_path_argument}', shlex.quote(str(original))))
                argv = shlex.split(rendered.splitlines()[2])
                self.assertEqual(len(argv), 3)
                self.assertEqual(argv[1], str(original))
                # Execute only the extracted argument guard, with socket validation
                # stubbed out. Never execute main(), run(), or the attack payload.
                tree = embedded_source(bundle / 'recover_corrupted_file')
                guard = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                             and n.name == 'recovery_arguments')
                calls = []
                namespace = {'recovery_request': calls.append, 'ARGUMENT_HELP': ''}
                exec(compile(ast.Module(body=[guard], type_ignores=[]), '<guard>', 'exec'), namespace)
                previous = sys.argv
                try:
                    sys.argv = argv
                    self.assertEqual(namespace['recovery_arguments'](), argv[2])
                finally:
                    sys.argv = previous
                self.assertEqual(calls, ['validate'])
                self.assertEqual(next(iter(watcher.replacements.values())).read_text(), 'original task content')


if __name__ == '__main__':
    unittest.main()
