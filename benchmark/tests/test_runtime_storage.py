"""Storage guard lifecycle tests, without Docker or model calls."""
import json
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from benchmark.final_benchmark import runtime_storage as storage


class RuntimeStorageTests(unittest.TestCase):
    def test_scratch_on_data_disk_cleanup_and_outputs_preserved(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); scratch=root/'scratch'; scratch.mkdir()
            existing=scratch/'keep.txt'; existing.write_text('other run')
            out=root/'output'; out.mkdir()
            script="import os,tempfile,json,pathlib; p=pathlib.Path(tempfile.mkdtemp()); (p/'leftover').write_text('x'); pathlib.Path('seen.json').write_text(json.dumps([str(p),os.environ['TMP'],os.environ['TEMP']]))"
            with patch.object(storage,'require_data_disk'),patch.object(storage,'require_space'):
                r=storage.run_with_storage([sys.executable,'-c',script],cwd=out,env={},temp_root=scratch,output_root=out)
            self.assertEqual(r.returncode,0)
            created,tmp,temp=json.loads((out/'seen.json').read_text())
            self.assertTrue(Path(created).is_relative_to(scratch))
            self.assertEqual(tmp,temp)
            self.assertFalse(Path(created).exists())
            self.assertEqual(existing.read_text(),'other run')
            self.assertEqual(list(scratch.iterdir()),[existing])

    def test_preflight_low_disk_never_launches(self):
        with tempfile.TemporaryDirectory() as t, patch.object(storage,'require_data_disk'),patch.object(storage,'require_space',side_effect=OSError('low disk')),patch.object(storage.subprocess,'Popen') as launch:
            with self.assertRaisesRegex(OSError,'low disk'):
                storage.run_with_storage(['unused'],cwd=t,env={},temp_root=Path(t)/'tmp',output_root=Path(t)/'out')
            launch.assert_not_called()

    def test_mid_run_low_disk_waits_for_graceful_shutdown(self):
        with tempfile.TemporaryDirectory() as t,patch.object(storage,'require_data_disk'),patch.object(storage,'require_space',side_effect=[None,OSError('low disk')]):
            process=MagicMock();process.wait.side_effect=[subprocess.TimeoutExpired('batch',2),130]
            process.poll.side_effect=[None,130]
            with patch.object(storage.subprocess,'Popen',return_value=process):
                r=storage.run_with_storage(['batch'],cwd=t,env={},temp_root=Path(t)/'tmp',output_root=Path(t)/'out')
            process.send_signal.assert_called_once_with(signal.SIGINT)
            self.assertEqual(r.returncode,130)
            self.assertEqual(list((Path(t)/'tmp').iterdir()),[])

    def test_launcher_error_still_cleans_scratch(self):
        with tempfile.TemporaryDirectory() as t,patch.object(storage,'require_data_disk'),patch.object(storage,'require_space'),patch.object(storage.subprocess,'Popen',side_effect=OSError('cannot launch')):
            with self.assertRaisesRegex(OSError,'cannot launch'):
                storage.run_with_storage(['batch'],cwd=t,env={},temp_root=Path(t)/'tmp',output_root=Path(t)/'out')
            self.assertEqual(list((Path(t)/'tmp').iterdir()),[])

    def test_system_disk_is_rejected(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as t:
            if Path(t).stat().st_dev!=Path('/').stat().st_dev:self.skipTest('/tmp is on a separate disk')
            with self.assertRaisesRegex(ValueError,'separate data disk'):storage.require_data_disk(Path(t))

if __name__=='__main__':unittest.main()
