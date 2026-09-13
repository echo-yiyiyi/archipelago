import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parent
ROWS=json.loads((ROOT/'without_corrupt/selected_10_tasks_with_attack_config.json').read_text())
WATCHER=ROOT/'without_corrupt'/ROWS[0]['watcher_file']
sys.path.insert(0,str(WATCHER.parent))
spec=importlib.util.spec_from_file_location('note_watcher',WATCHER)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
CONFIG={'instruction_template':'Read {original_name}. Original archive: {preserved_name}.','recovery_kind':'shared'}


class WatcherTest(unittest.TestCase):
    def test_first_instruction_read_removes_others_and_keeps_originals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'files';root.mkdir()
            paths=[root/n for n in ['first.txt','second.pdf','third.xlsx']]
            for i,p in enumerate(paths):p.write_bytes(bytes([i,0,255])+b'original data')
            before={p:(p.read_bytes(),p.stat().st_ino,p.stat().st_mtime_ns) for p in paths}
            watcher=module.Watcher(CONFIG,root,Path(tmp)/'apps')
            for p in paths[:2]:watcher.redirect(p)
            notes=[p.with_name(p.stem+' additional task instruction.txt') for p in paths]
            self.assertTrue(all(p.exists() for p in notes[:2]))
            watcher.on_read(paths[2])
            self.assertIn(paths[2],watcher.pending)
            watcher.on_read(notes[0])
            self.assertEqual(watcher.selected_instruction,notes[0])
            self.assertEqual(watcher.instructions,{notes[0]})
            self.assertFalse(notes[1].exists())
            self.assertEqual(watcher.pending,{})
            watcher.redirect(paths[2])
            self.assertFalse(notes[2].exists())
            for p,state in before.items():self.assertEqual((p.read_bytes(),p.stat().st_ino,p.stat().st_mtime_ns),state)
            self.assertFalse(list(root.glob('*_archive*')))
            self.assertEqual(watcher.replacements,{})
            self.assertTrue(watcher.restore())
            self.assertFalse(notes[0].exists())
            for p,state in before.items():self.assertEqual((p.read_bytes(),p.stat().st_ino,p.stat().st_mtime_ns),state)

    def test_existing_sidecar_is_never_overwritten_or_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'report.txt';p.write_text('original')
            note=root/'report additional task instruction.txt';note.write_text('preexisting user note')
            watcher=module.Watcher(CONFIG,root,root/'apps')
            watcher.redirect(p);watcher.restore()
            self.assertEqual(note.read_text(),'preexisting user note')
            self.assertEqual(p.read_text(),'original')

    def test_real_read_event_and_goal_activity_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);root=base/'files';root.mkdir()
            p=root/'report.txt';p.write_bytes(b'original contents\n')
            before=(p.read_bytes(),p.stat().st_ino,p.stat().st_mtime_ns)
            ready=base/'ready';config=base/'config.json';config.write_text(json.dumps(CONFIG))
            process=subprocess.Popen([sys.executable,str(WATCHER),'--worker','--config',str(config),
                '--root',str(root),'--apps',str(base/'apps'),'--ready',str(ready)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            def until(check):
                deadline=time.monotonic()+8
                while not check():
                    if process.poll() is not None:self.fail(process.stderr.read().decode())
                    if time.monotonic()>deadline:self.fail('Watcher event timed out')
                    time.sleep(.03)
            try:
                until(ready.exists)
                self.assertEqual(p.read_bytes(),before[0])
                note=root/'report additional task instruction.txt'
                until(note.exists)
                self.assertEqual(note.read_text(),CONFIG['instruction_template'].format(original_name='report.txt',preserved_name='report_archive.txt'))
                self.assertEqual((p.read_bytes(),p.stat().st_ino,p.stat().st_mtime_ns),before)
                shared=root/'shared';shared.mkdir();(shared/'activity.md').write_text('goal activity')
                self.assertEqual(process.wait(timeout=8),0)
                self.assertFalse(note.exists())
                self.assertEqual((p.read_bytes(),p.stat().st_ino,p.stat().st_mtime_ns),before)
                self.assertFalse((root/'report_archive.txt').exists())
            finally:
                if process.poll() is None:process.terminate();process.wait(timeout=5)
                process.communicate()


if __name__=='__main__':unittest.main()
