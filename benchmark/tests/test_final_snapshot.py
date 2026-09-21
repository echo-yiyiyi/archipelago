import gzip
import io
import subprocess
import sys
import tarfile
import zipfile
from contextlib import contextmanager

import pytest
from benchmark.runner import final_snapshot as snapshot


def archive_bytes():
    raw=io.BytesIO()
    with tarfile.open(fileobj=raw,mode='w') as archive:
        entry=tarfile.TarInfo('filesystem/result.txt');entry.size=3
        archive.addfile(entry,io.BytesIO(b'yes'))
    return raw.getvalue()


def test_incomplete_member_never_publishes_zip(tmp_path):
    source=tmp_path/'final_snapshot.tar.gz'
    source.write_bytes(gzip.compress(archive_bytes()[:512]))
    with pytest.raises(tarfile.ReadError):snapshot.tar_gz_to_zip(source)
    assert not (tmp_path/'final_snapshot.zip').exists()
    assert not list(tmp_path.glob('*.partial'))


def test_snapshot_retries_validates_and_stops_watchers(tmp_path,monkeypatch):
    calls=[]
    payloads=[gzip.compress(archive_bytes()[:512]),gzip.compress(archive_bytes())]
    @contextmanager
    def stream(method,url,**kwargs):
        calls.append(kwargs)
        class Response:
            def raise_for_status(self):pass
            def iter_bytes(self,chunk_size):yield payloads[len(calls)-1]
        yield Response()
    monkeypatch.setattr(snapshot.httpx,'stream',stream)
    monkeypatch.setattr(snapshot.time,'sleep',lambda _:None)
    result=snapshot.save_final_snapshot('http://test',tmp_path)
    assert len(calls)==2
    assert calls[0]['json']['pre_snapshot_hooks'][0]['name']=='stop-benchmark-watchers'
    assert (tmp_path/'final_snapshot.failed-1.tar.gz').exists()
    with zipfile.ZipFile(result) as z:assert z.read('filesystem/result.txt')==b'yes'


def test_retry_exhaustion_preserves_existing_good_zip(tmp_path,monkeypatch):
    target=tmp_path/'final_snapshot.zip';target.write_bytes(b'previous')
    @contextmanager
    def stream(*args,**kwargs):
        class Response:
            def raise_for_status(self):pass
            def iter_bytes(self,chunk_size):yield gzip.compress(archive_bytes()[:512])
        yield Response()
    monkeypatch.setattr(snapshot.httpx,'stream',stream)
    monkeypatch.setattr(snapshot.time,'sleep',lambda _:None)
    with pytest.raises(tarfile.ReadError):snapshot.save_final_snapshot('http://test',tmp_path)
    assert target.read_bytes()==b'previous'
    assert len(list(tmp_path.glob('final_snapshot.failed-*')))==3


def test_hook_stops_only_benchmark_worker():
    worker=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)',
        '/.apps_data/dynamic_watcher/dynamic_watcher.py','--worker'])
    unrelated=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])
    try:
        subprocess.run([sys.executable,'-c',snapshot.STOP_WATCHERS],check=True,timeout=15)
        worker.wait(timeout=3)
        assert worker.returncode==-15
        assert unrelated.poll() is None
    finally:
        for p in [worker,unrelated]:
            if p.poll() is None:p.terminate()
            p.wait()
