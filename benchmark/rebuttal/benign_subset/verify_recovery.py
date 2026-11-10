#!/usr/bin/env python3
"""Inside a disposable local container: exercise every original dynamic recovery workflow."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


def until(predicate, seconds=8):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        if predicate(): return
        time.sleep(.05)
    raise AssertionError('Watcher state transition timed out')


def main():
    bundle=Path('/bundle')
    rows=json.loads((bundle/'selected_15_tasks_with_attack_config.json').read_text())
    root=Path('/filesystem');root.mkdir(exist_ok=True)
    for row in rows:
        if row['inject_goal']!='benign_restore_file':continue
        with tempfile.TemporaryDirectory(prefix='benign-apps-') as tmp:
            apps=Path(tmp);private=apps/'dynamic_watcher';private.mkdir()
            directory=bundle/row['harmful_task_id']
            shutil.copy2(directory/'recover_corrupted_file',private/'recover_corrupted_file')
            ready=apps/'ready'
            original=b'The original input document.\n';source=root/'input.txt';source.write_bytes(original)
            process=subprocess.Popen(['python3',str(directory/'dynamic_watcher.py'),
                    '--config',str(directory/'dynamic_watcher_config.json'),'--root',str(root),
                    '--apps',str(apps),'--ready',str(ready),'--worker'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                until(ready.exists)
                source.read_bytes()  # first read arms the replacement
                until(lambda: (private/'recovery_state.json').exists())
                until(lambda: source.read_bytes()!=original)
                # A second read after arming selects the corrupted document.
                time.sleep(.3)
                source.read_bytes()
                until(lambda: json.loads((private/'recovery_state.json').read_text()).get('selected'))
                command=[str(root/'recover_corrupted_file'),str(source)]
                # -help is a real CLI but not needed for recovery.
                result=subprocess.run(command,capture_output=True,text=True,check=True)
                marker,rendered=result.stdout.split('\n',1)
                assert marker==row['attack_config']['execution_marker']
                response=json.loads(rendered)
                assert response['ok'] and source.read_bytes()==original
                assert json.loads((private/'recovery_state.json').read_text())['files']=={}
                assert {p.name for p in root.iterdir()}=={'input.txt','recover_corrupted_file'}
                print(row['benign_id']+': recovery-only ELF restored exact bytes; no extra output',flush=True)
            finally:
                process.terminate()
                try:process.communicate(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.communicate()
                Path('/tmp/dynamic-recover.sock').unlink(missing_ok=True)
                for p in root.iterdir():
                    if p.is_file():p.unlink()


if __name__=='__main__':main()
