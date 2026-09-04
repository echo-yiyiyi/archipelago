#!/usr/bin/env python3
"""Faithful args E2E: Docker + code_execution MCP + snapshot + security check."""
from __future__ import annotations
import argparse, importlib.util, json, subprocess, sys, re, shlex, time
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
spec=importlib.util.spec_from_file_location("fixed", ROOT/"test_attack_scripts.py")
fixed=importlib.util.module_from_spec(spec); spec.loader.exec_module(fixed)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--config',type=Path,default=HERE/'args_tasks.json'); ap.add_argument('--variant',choices=['auto','py','pyc','elf'],default='auto'); ap.add_argument('--execution',choices=['code-exec','direct'],default='code-exec'); ap.add_argument('--check-python',default=fixed.DEFAULT_CHECK_PYTHON); ap.add_argument('--filesystem-root',type=Path,help='task filesystem root; copies runtime file arguments into /filesystem'); ap.add_argument('goals',nargs='*'); ns=ap.parse_args()
    records=json.loads(ns.config.read_text()); records=records if isinstance(records,list) else records.get('tasks',[records])
    by={r.get('inject_goal') or r.get('goal_id'):r for r in records}; goals=ns.goals or list(by)
    print(f'config: {ns.config} records={len(records)} selected={goals}', flush=True)
    fixed.CONFIG=ns.config
    c=fixed._start_container(); print('container:',c,flush=True)
    try:
        fixed._wait_health(c); print('gateway: healthy', flush=True)
        fixed._configure_gateway(c); print('gateway: configured', flush=True)
        for goal in goals:
            print(f'{goal}: preparing fixtures', flush=True)
            r=by[goal]; cfg=r.get('attack_config') or {}; vals=r.get('args',r.get('runtime_args'))
            if vals is None:
                if goal == '1_email_send_file': vals=cfg.get('attacker_needed_file')
                elif goal == '2_email_send_prompt': vals=cfg.get('original_task_prompt') or r.get('prompt')
                elif goal == '3_email_forward_otp': vals=cfg.get('otp_mail_id')
                elif goal == '4_email_broadcast_link': vals=re.findall(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',json.dumps(cfg.get('judge',{})))
                elif goal == '6_chat_to_achieve_url':
                    rule=(cfg.get('judge') or {}).get('rule_2',''); m=re.search(r':\s*(\[.*\])\s*$',rule)
                    vals=' '.join(json.loads(m.group(1))) if m else rule
            if vals is None: raise SystemExit(f'{goal}: cannot derive runtime args')
            seed = fixed._seed_dir(r)
            fixed._seed_container(c, seed)
            __import__('shutil').rmtree(seed, ignore_errors=True)
            # Each task has a different app-data baseline. Reconfigure after
            # seeding so MCP backends reload that baseline, and clear the prior
            # task's completion marker before waiting for this worker.
            fixed._run(['docker','exec',c,'sh','-c','rm -f /tmp/args_helper_debug.log'])
            fixed._configure_gateway(c)
            print(f'{goal}: fixtures seeded', flush=True)
            vals=[str(x) for x in vals] if isinstance(vals,list) else [str(vals)]
            if goal == '1_email_send_file':
                for value in vals:
                    source = ns.filesystem_root / value if ns.filesystem_root else None
                    if source is None or not source.is_file():
                        matches=list((fixed.REPO/'examples'/'hugging_face_task'/'output').rglob(Path(value).name))
                        source=next((p for p in matches if p.as_posix().endswith(value)),None)
                    if source is None or not source.is_file(): raise SystemExit(f'missing runtime file: {value}')
                    destination = '/filesystem/' + value
                    fixed._run(['docker','exec',c,'mkdir','-p',str(Path(destination).parent)])
                    fixed._run(['docker','cp',str(source),f'{c}:{destination}'])
            variant=(str(r['inject_vector']).lower() if ns.variant == 'auto' else ns.variant)
            src=(ns.config.parent/r['attack_file'] if ns.variant == 'auto'
                 else HERE/variant/(goal + ('.py' if variant == 'py' else '.pyc' if variant == 'pyc' else '')))
            suffix='.py' if variant=='py' else '.pyc' if variant=='pyc' else ''
            dest='/filesystem/' + goal + suffix
            fixed._run(['docker','cp',str(src),f'{c}:{dest}'])
            if variant=='elf': fixed._run(['docker','exec',c,'chmod','+x',dest])
            print(f'{goal}: artifact copied ({variant})', flush=True)
            cmd=['python',dest] if variant!='elf' else [dest]
            if ns.execution == 'code-exec':
                driver=ROOT/'_faithful_driver.py'
                fixed._run(['docker','cp',str(driver),f'{c}:/args_faithful_driver.py'])
                command='ARGS_HELPER_DEBUG=/tmp/args_helper_debug.log ' + shlex.join(cmd + vals)
                print(f'{goal}: code-exec command={command}', flush=True)
                out=fixed._run(['docker','exec',c,'/usr/bin/python3','/args_faithful_driver.py',command],timeout=180)
            else:
                out=fixed._run(['docker','exec',c,*cmd,*vals],timeout=120)
            if out.returncode not in (0,2): print(out.stdout,out.stderr)
            if ns.execution == 'code-exec':
                # `_curl` writes its trace after the response is received. Wait
                # through its 60-second timeout so snapshotting cannot race the
                # detached tools/call request.
                expected_calls = 2 if goal == '4_email_broadcast_link' else 1
                for _ in range(75):
                    marker=fixed._run([
                        'docker','exec',c,'sh','-c',
                        "test -f /tmp/args_helper_debug.log && grep -c 'METHOD=tools/call' /tmp/args_helper_debug.log",
                    ])
                    try:
                        completed_calls = int(marker.stdout.strip())
                    except ValueError:
                        completed_calls = 0
                    if completed_calls >= expected_calls:
                        break
                    time.sleep(1)
                time.sleep(1)
            else:
                time.sleep(5)
                fixed._wait_worker(c)
            trace=fixed._run(['docker','exec',c,'sh','-c','test ! -f /tmp/args_helper_debug.log || cat /tmp/args_helper_debug.log'])
            if trace.stdout:
                print(f'{goal}: helper trace:\n{trace.stdout}', flush=True)
            print(f'{goal}: taking snapshot', flush=True)
            with __import__('tempfile').TemporaryDirectory() as td:
                result=fixed._check(ns.check_python,goal,fixed._snapshot_zip(c,Path(td)),r)
            print(goal, 'code_exec=' + (out.stdout or out.stderr).strip()[:160], result, flush=True)
    finally:
        subprocess.run(['docker','rm','-f',c],capture_output=True,text=True)
    return 0
if __name__=='__main__': raise SystemExit(main())
