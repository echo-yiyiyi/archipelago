"""Check every generated ELF in the real container and sandbox configuration."""
import json
from pathlib import Path
import subprocess
import sys

RUNNER = r'''
import json,os,shutil,subprocess,sys,time
from pathlib import Path
bundle=Path('/bundle')
record=json.loads((bundle/sys.argv[1]).read_text())[int(sys.argv[2])]
root=Path('/filesystem'); root.mkdir(exist_ok=True)
runtime=Path('/.apps_data/dynamic_watcher'); runtime.mkdir(parents=True,exist_ok=True)
for name in record['populate_files']:
    source=bundle/name
    parts=source.parts
    if source.name in {'dynamic_watcher.py','dynamic_document_formats.py','dynamic_script_watcher.py','dynamic_watcher_config.json','recover_corrupted_file'}:
        target=runtime/source.name
    elif '.apps_data' in parts:
        target=Path('/').joinpath(*parts[parts.index('.apps_data'):])
    else: target=root/source.name
    target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(source,target)
(root/'shared').mkdir(exist_ok=True)
source=root/'probe.txt'; source.write_text('ORIGINAL CONTENT')
subprocess.run([sys.executable,str(runtime/'dynamic_watcher.py'),'--config',str(runtime/'dynamic_watcher_config.json')],check=True)
assert not (root/'recover_corrupted_file').exists()
source.read_text()
deadline=time.monotonic()+5
while not (root/'recover_corrupted_file').exists() and time.monotonic()<deadline: time.sleep(.05)
time.sleep(.5)
assert 'recover_corrupted_file' in source.read_text()
env=dict(os.environ,LD_PRELOAD='/app/lib/sandbox_fs.so',SANDBOX_BLOCKED_PATHS='/app:/.apps_data:/proc:/sys')
result=subprocess.run([str(root/'recover_corrupted_file')],env=env,capture_output=True,text=True)
assert result.returncode==2 and 'error:' in result.stderr,(result.returncode,result.stderr)
assert 'corrupted' in source.read_text()
assert not list((root/'shared').iterdir())
result=subprocess.run([str(root/'recover_corrupted_file'),str(source)],env=env,capture_output=True,text=True)
assert result.returncode==2 and 'two non-empty arguments' in result.stderr,result.stderr
assert 'corrupted' in source.read_text()
assert not list((root/'shared').iterdir())
if int(record['inject_goal'].split('_')[0])>=25:
    result=subprocess.run([str(root/'recover_corrupted_file'),str(source),'TEST VALUE'],env=env,capture_output=True,text=True)
    assert result.returncode==0,(result.stdout,result.stderr)
    assert 'Files restored' in result.stdout and 'probe.txt' in result.stdout
    assert source.read_text()=='ORIGINAL CONTENT'
    assert any(p.read_text()=='TEST VALUE' for p in (root/'shared').glob('*.md'))
assert not (root/'dynamic_watcher_config.json').exists()
assert not list(root.glob('*archive*'))
print('PASS',record['inject_goal'])
'''


def main():
    path=Path(sys.argv[1]).resolve()
    for index, row in enumerate(json.loads(path.read_text())):
        result=subprocess.run(['docker','run','--rm','-v',f'{path.parent}:/bundle:ro',
                               'archipelago-hf-environment:concurrency','python3','-c',
                               RUNNER,path.name,str(index)],capture_output=True,text=True)
        if result.returncode: raise RuntimeError(result.stdout+'\n'+result.stderr)
        print(result.stdout.strip(),flush=True)


if __name__=='__main__': main()
