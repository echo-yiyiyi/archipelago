#!/usr/bin/env bash
# Run the audited missing cells only; total workers <=64 (currently 41).
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
python3 - "$ROOT" "${1:-}" <<'PY'
import fcntl, ipaddress, json, os, pathlib, signal, socket, subprocess, sys, time
root = pathlib.Path(sys.argv[1])
dry = sys.argv[2] == '--dry-run'
if sys.argv[2] not in ('', '--dry-run'): raise SystemExit('Usage: bash benchmark/run_missing_dynamic_tasks.sh [--dry-run]')
jobs = json.loads((root/'benchmark/generate_attack_config/output/dynamic_missing/jobs.json').read_text())
if sum(j['count'] for j in jobs) > 64: raise SystemExit('Plan exceeds 64 workers; regenerate scheduling before running.')
# Hold the lock through completion to prevent two copies of this launcher racing.
lock = open('/tmp/archipelago-missing-dynamic.lock', 'a')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
if not dry:
    for model, key in [('glm53','ZAI_API_KEY'), ('deepseekv4','DEEPSEEK_API_KEY')]:
        if any(j['model']==model for j in jobs) and not os.environ.get(key):
            raise SystemExit('Missing '+key+'; no jobs launched.')
ids = subprocess.check_output(['docker','network','ls','-q'], text=True).split()
nets = json.loads(subprocess.check_output(['docker','network','inspect',*ids], text=True)) if ids else []
used = [ipaddress.ip_network(c['Subnet'], strict=False) for n in nets for c in (n.get('IPAM',{}).get('Config') or []) if c.get('Subnet')]
commands = []
reserved_ports = set()
for job in jobs:
    for octet in range(10,254):
        net = ipaddress.ip_network(f'10.{octet}.0.0/16')
        if not any(net.version==n.version and net.overlaps(n) for n in used): break
    else: raise SystemExit('No free Docker subnet; no jobs launched.')
    used.append(net)
    for base in range(18080,64000,100):
        ports = set(range(base,base+job['count']))
        if ports & reserved_ports: continue
        sockets=[]
        try:
            for port in ports:
                s=socket.socket(); sockets.append(s); s.bind(('0.0.0.0',port))
        except OSError: continue
        finally:
            for s in sockets: s.close()
        break
    else: raise SystemExit('No free host ports; no jobs launched.')
    reserved_ports.update(ports)
    cmd=['bash',str(root/'benchmark/run_tasks_models.sh'),'--task-json',job['json'],'--models',job['model'],'--concurrency',str(job['count']),'--base-port',str(base),'--cidr-start',str(octet)]
    if job['setting']=='script_allow': cmd+=['--user-allow-addtional-instruction']
    if job['model']=='gemini': cmd+=['--max-steps','100']
    commands.append(cmd)
    print(job['model'],job['setting'],job['count'],'workers',net,'ports',base,flush=True)
for cmd in commands: subprocess.run(cmd+['--dry-run'],check=True)
if dry: raise SystemExit(0)
children=[]
def stop(signum, frame):
    for p in children:
        if p.poll() is None: os.killpg(p.pid,signal.SIGINT)
    raise KeyboardInterrupt
signal.signal(signal.SIGINT,stop); signal.signal(signal.SIGTERM,stop)
try:
    for cmd in commands: children.append(subprocess.Popen(cmd,start_new_session=True))
    statuses=[p.wait() for p in children]
except KeyboardInterrupt:
    print('Stop requested; waiting for child cleanup.',flush=True)
    for p in children:
        try: p.wait(timeout=120)
        except subprocess.TimeoutExpired: print('Cleanup still running for PID',p.pid,flush=True)
    raise SystemExit(130)
raise SystemExit(int(any(statuses)))
PY
