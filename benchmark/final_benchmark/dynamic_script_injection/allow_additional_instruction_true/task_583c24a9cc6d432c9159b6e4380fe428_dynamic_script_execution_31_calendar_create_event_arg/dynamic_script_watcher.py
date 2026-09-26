"""Recovery protocol for runtime-argument experiments (runs outside the workspace)."""
import json
import os
from pathlib import Path
import shutil
import shlex
import socket
import time
import uuid

from dynamic_watcher import Watcher
from dynamic_document_formats import make_replacement


class ScriptWatcher(Watcher):
    def __init__(self, config, root, apps):
        super().__init__({'instruction_template': '', 'recovery_kind': 'shared'}, root, apps)
        self.kind = None  # Only an explicit successful recover request restores all files.
        self.config = config
        self.private = self.apps / 'dynamic_watcher'
        self.backups = self.private / 'backups'
        self.backups.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.selected = None
        self.frozen = False
        self.armed = {}
        self.history = []
        self.socket_path = config['recovery_socket']
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(self.socket_path)
        os.chmod(self.socket_path, 0o600)
        self.server.listen(4)
        self.server.setblocking(False)

    def save_state(self):
        state = {'files': {str(p): str(b) for p, b in self.replacements.items()},
                 'selected': str(self.selected) if self.selected else None,
                 'instruction_texts': self.history}
        target = self.private / 'recovery_state.json'
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(state, ensure_ascii=False))
        temporary.replace(target)

    def eligible(self, path):
        return not self.frozen and super().eligible(path)

    def redirect(self, path):
        if self.stopped or not self.eligible(path):
            return
        self.processed.add(path)
        backup = self.backups / uuid.uuid4().hex
        temporary = path.with_name('.' + uuid.uuid4().hex)
        script = self.root / 'recover_corrupted_file'
        try:
            if not self.replacements:
                if script.exists():
                    raise FileExistsError('recover_corrupted_file already exists')
                shutil.copy2(self.private / 'recover_corrupted_file', script)
                script.chmod(0o755)
            text = self.config['instruction_template'].replace(
                '{original_path_argument}', shlex.quote(str(path)))
            # Copy before replacing: backups may reside on another mount.
            shutil.copy2(path, backup)
            make_replacement(path, temporary, text.splitlines())
            temporary.replace(path)
            self.replacements[path] = backup
            self.armed[path] = time.monotonic() + 0.25
            self.history.append(text)
            self.save_state()
        except Exception:
            temporary.unlink(missing_ok=True)
            if backup.exists():
                shutil.copy2(backup, path)
                backup.unlink()
            raise

    def restore_one(self, path):
        backup = self.replacements[path]
        temporary = path.with_name('.' + uuid.uuid4().hex)
        shutil.copy2(backup, temporary)
        temporary.replace(path)
        backup.unlink()
        del self.replacements[path]

    def on_read(self, path):
        if path in self.replacements:
            if not self.frozen and time.monotonic() >= self.armed[path]:
                self.selected = path
                self.frozen = True
                self.pending.clear()
                for other in list(self.replacements):
                    if other != path:
                        self.restore_one(other)
                self.save_state()
            return
        super().on_read(path)

    def tick(self):
        try:
            connection, _ = self.server.accept()
        except BlockingIOError:
            return
        with connection:
            connection.settimeout(2)
            try:
                request = json.loads(connection.recv(4096))
                if set(request) != {'operation', 'file'} or request['operation'] not in {'restore', 'validate'}:
                    raise ValueError('unsupported recovery request')
                target = Path(request['file'])
                if not target.is_absolute(): target = self.root / target
                target = target.resolve()
                target.relative_to(self.root)
                if target not in self.replacements:
                    raise ValueError('the requested file is not awaiting recovery')
                if request['operation'] == 'validate':
                    connection.sendall(b'{"ok":true}')
                    return
                names = [str(p.relative_to(self.root)) for p in self.replacements]
                for path in list(self.replacements):
                    self.restore_one(path)
                self.frozen = True
                self.pending.clear()
                self.save_state()
                connection.sendall(json.dumps({'ok': True, 'files': names}).encode())
            except Exception as error:
                connection.sendall(json.dumps({'ok': False, 'error': str(error)}).encode())

    def watch(self, ready):
        try:
            super().watch(ready)
        finally:
            self.server.close()
            Path(self.socket_path).unlink(missing_ok=True)
