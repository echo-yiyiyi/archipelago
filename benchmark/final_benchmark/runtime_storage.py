"""Run one batch with isolated scratch space and a graceful low-space stop."""
from __future__ import annotations
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile

GIB = 1024 ** 3


def require_space(paths):
    for path, minimum in paths:
        free = shutil.disk_usage(path).free / GIB
        if free < minimum:
            raise OSError(f'{path}: {free:.1f} GiB free, need at least {minimum:g} GiB')


def require_data_disk(path):
    if path.stat().st_dev == Path('/').stat().st_dev:
        raise ValueError('Temporary files must use a separate data disk, not the system filesystem')


def run_with_storage(command, *, cwd, env, temp_root, output_root,
                     min_free_gb=30, min_system_free_gb=10):
    temp_root = Path(temp_root).resolve()
    output_root = Path(output_root).resolve()
    temp_root.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)
    require_data_disk(temp_root)
    paths = [(temp_root, min_free_gb), (output_root, min_free_gb),
             (Path('/'), min_system_free_gb)]
    require_space(paths)
    # Only this batch's new directory is removed. Existing scratch/results stay intact.
    with tempfile.TemporaryDirectory(prefix='final-batch-', dir=temp_root) as scratch:
        child_env = {**env, 'TMPDIR': scratch, 'TMP': scratch, 'TEMP': scratch}
        print(f'Batch temporary directory: {scratch}', flush=True)
        stopped = False
        process = None

        def stop(signum=None, frame=None):
            nonlocal stopped
            if not stopped:
                stopped = True
                if process is not None and process.poll() is None:
                    try:
                        # main_concurrency handles SIGINT by stopping tasks and cleaning Docker.
                        process.send_signal(signal.SIGINT)
                    except ProcessLookupError:
                        pass

        old = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
        try:
            process = subprocess.Popen(command, cwd=cwd, env=child_env, start_new_session=True)
            if stopped:
                process.send_signal(signal.SIGINT)
            while True:
                try:
                    code = process.wait(timeout=2)
                    break
                except subprocess.TimeoutExpired:
                    if not stopped:
                        try:
                            require_space(paths)
                        except OSError as error:
                            print(f'Stopping batch before disk space is exhausted: {error}', flush=True)
                            stop()
            return subprocess.CompletedProcess(command, 130 if stopped else code)
        finally:
            if process is not None and process.poll() is None:
                stop()
                process.wait()  # Do not delete scratch while task cleanup is still running.
            for sig, handler in old.items():
                signal.signal(sig, handler)
