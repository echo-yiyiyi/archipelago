"""Freeze benchmark watchers and publish only validated final snapshots."""
import io
import shlex
import tarfile
import time
import zipfile
from pathlib import Path

import httpx

# Runs after coordinator.finish_actions(), before the archive is opened.
# SIGTERM does not call watcher.restore(): preserve the final observed state.
STOP_WATCHERS = r'''
import os, signal, time
from pathlib import Path
scripts = {'/.apps_data/dynamic_watcher/dynamic_watcher.py',
           '/.apps_data/dynamic_watcher/dynamic_script_watcher.py'}
matched = []
for proc in Path('/proc').iterdir():
    if not proc.name.isdigit(): continue
    try:
        args = proc.joinpath('cmdline').read_bytes().split(b'\0')
        if b'--worker' not in args or not any(os.fsencode(s) in args for s in scripts): continue
        os.kill(int(proc.name), signal.SIGTERM)
        matched.append(proc)
    except (FileNotFoundError, ProcessLookupError): pass
for proc in matched:
    deadline = time.monotonic() + 10
    while True:
        try:
            state = proc.joinpath('stat').read_text().rsplit(')', 1)[1].split()[0]
        except FileNotFoundError: break
        if state == 'Z': break
        if time.monotonic() >= deadline:
            raise RuntimeError('Watcher did not stop: ' + proc.name)
        time.sleep(.05)
print('Stopped benchmark watchers: ' + ','.join(p.name for p in matched))
'''


def tar_gz_to_zip(source):
    """Read every regular member before atomically publishing a grading ZIP."""
    source = Path(source)
    stem = source.name.removesuffix('.tar.gz')
    target = source.with_name(stem + '.zip')
    partial = target.with_name(target.name + '.partial')
    try:
        with tarfile.open(source, 'r:gz') as archive, zipfile.ZipFile(partial, 'w', zipfile.ZIP_DEFLATED) as dest:
            for member in archive:
                if member.isfile():
                    with archive.extractfile(member) as src, dest.open(member.name, 'w') as dst:
                        remaining = member.size
                        while remaining:
                            chunk = src.read(min(1024 * 1024, remaining))
                            if not chunk: raise tarfile.ReadError('incomplete member: ' + member.name)
                            dst.write(chunk)
                            remaining -= len(chunk)
        # Validate gzip CRC/trailer as tar readers may stop before gzip EOF.
        import gzip
        with gzip.open(source, 'rb') as stream:
            while stream.read(1024 * 1024): pass
        partial.replace(target)
        return target
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def save_final_snapshot(env_url, output_dir, attempts=3):
    output_dir = Path(output_dir)
    hook = {'name': 'stop-benchmark-watchers', 'command': 'python3 -c ' + shlex.quote(STOP_WATCHERS)}
    for attempt in range(1, attempts + 1):
        staging = output_dir / 'final_snapshot.download.tar.gz'
        staging_zip = output_dir / 'final_snapshot.download.zip'
        try:
            with httpx.stream('POST', f'{env_url}/data/snapshot',
                              json={'pre_snapshot_hooks': [hook]}, timeout=600.0) as response:
                response.raise_for_status()
                with staging.open('wb') as f:
                    for chunk in response.iter_bytes(chunk_size=65536): f.write(chunk)
            tar_gz_to_zip(staging)
            staging.replace(output_dir / 'final_snapshot.tar.gz')
            staging_zip.replace(output_dir / 'final_snapshot.zip')
            return output_dir / 'final_snapshot.zip'
        except (httpx.HTTPError, OSError, EOFError, tarfile.TarError, zipfile.BadZipFile):
            if staging.exists(): staging.replace(output_dir / f'final_snapshot.failed-{attempt}.tar.gz')
            staging_zip.unlink(missing_ok=True)
            if attempt == attempts: raise
            time.sleep(1)
    raise ValueError('attempts must be positive')
