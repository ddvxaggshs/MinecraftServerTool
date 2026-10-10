"""Recoverable mod-only Git publication, preserving the world and its index entries."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid
from .mod_files import digest, mod_path, read_mod, scan_mods
from .paths import DATA_DIR, LOCK_REF
from .world_git import WorldGit


class ModSync:
    def __init__(self, cfg, storage=DATA_DIR):
        self.root = Path(cfg['server_dir']).resolve()
        self.g = WorldGit(str(self.root), cfg['git_remote'], cfg['git_branch'])
        key = hashlib.sha256(str(self.root).casefold().encode()).hexdigest()[:24]
        self.storage = Path(storage) / 'mod-transactions' / key
        self.journal = self.storage / 'pending.json'
        self.host = cfg.get('host_name', 'Host')

    @property
    def pending(self):
        return self.journal.exists()

    def save(self, data):
        self.storage.mkdir(parents=True, exist_ok=True)
        temp = self.journal.with_suffix('.tmp')
        temp.write_text(json.dumps(data, indent=2), encoding='utf-8')
        temp.replace(self.journal)

    def load(self):
        data = json.loads(self.journal.read_text(encoding='utf-8'))
        if data['root'] != str(self.root) or data['remote'] != self.g.remote or data['branch'] != self.g.branch:
            raise RuntimeError('Pending mod operation belongs to different repository settings')
        if not data['id'].isalnum():
            raise ValueError('Invalid mod transaction')
        for edit in data['edits']:
            mod_path(self.root, edit['path'])
        return data

    def check_repo(self):
        self.g.check_branch()
        if Path(self.g.command('rev-parse', '--show-toplevel')).resolve() != self.root:
            raise RuntimeError('Server directory must be the Git repository root')
        if self.g.command('ls-files', '-u'):
            raise RuntimeError('Resolve existing Git merge conflicts first')

    def prepare(self, action, filename=None, source=None):
        if self.pending:
            raise RuntimeError('Retry or cancel the pending mod synchronization first')
        self.check_repo()
        remote, lock = self.g.remote_refs()
        if lock:
            raise RuntimeError('Another hosting or mod operation owns the server lock. Wait until it finishes.')
        base = self.g.command('rev-parse', 'HEAD')
        if base != remote:
            raise RuntimeError('Local and GitHub history differ. Synchronize the server first; no mod or world was changed.')
        edits = {}
        if action == 'add':
            source = Path(source)
            info = read_mod(source)
            if source.suffix.lower() != '.jar' or info['error'] or info['loader'] != 'Fabric':
                raise ValueError('Choose a valid Fabric mod JAR')
            if info['environment'] == 'client':
                raise ValueError('This mod is client-only and cannot be added to the server')
            if source.stat().st_size >= 95 * 1024 * 1024:
                raise ValueError('Mod exceeds the 95 MiB upload limit')
            if any(m['mod_id'] == info['mod_id'] for m in scan_mods(self.root)):
                raise ValueError('This mod ID is already installed (possibly disabled). Remove the old version first.')
            path = mod_path(self.root, 'mods/' + source.name)
            if path.exists():
                raise ValueError('A file with that name already exists')
            edits['mods/' + source.name] = source
        elif action in ('enable', 'disable', 'remove'):
            relative = 'mods/' + filename
            path = mod_path(self.root, relative)
            if not path.is_file():
                raise ValueError('Mod no longer exists; refresh the list')
            edits[relative] = None
            if action != 'remove':
                enabled = path.name.lower().endswith('.jar')
                if (action == 'enable') == enabled:
                    raise ValueError('Mod already has that state')
                new = relative[:-9] if action == 'enable' else relative + '.disabled'
                if mod_path(self.root, new).exists():
                    raise ValueError('Destination already exists; no file was overwritten')
                edits[new] = path
        else:
            raise ValueError('Unknown mod action')
        identity = uuid.uuid4().hex
        folder = self.storage / identity
        folder.mkdir(parents=True)
        data = dict(id=identity, root=str(self.root), remote=self.g.remote, branch=self.g.branch,
                    base=base, commit=None, action=action, edits=[])
        # Keep snapshots in data/, outside the server repo. Stage nothing yet.
        for index, (relative, source) in enumerate(edits.items()):
            path = mod_path(self.root, relative)
            before = digest(path) if path.exists() else None
            after = digest(source) if source else None
            if before:
                shutil.copy2(path, folder / f'{index}.before')
                if digest(folder / f'{index}.before') != before:
                    raise RuntimeError('Mod changed while taking its backup')
            if after:
                shutil.copy2(source, folder / f'{index}.after')
                if digest(folder / f'{index}.after') != after:
                    raise RuntimeError('Selected JAR changed while copying')
            data['edits'].append(dict(path=relative, before=before, after=after))
        data['lock'] = self.g.command('commit-tree', base + '^{tree}', '-p', base,
            input=f'MC Relay mod lock | host={self.host} | operation={identity}\n')
        self.save(data)  # Intent exists before a lock push could be interrupted.
        return self.retry()

    def inspect_remote(self, data):
        remote, lock = self.g.remote_refs()
        published = False
        if data['commit']:
            self.g.fetch()
            published = self.g.command('merge-base', data['commit'], remote) == data['commit']
        return remote, lock, published

    def write_files(self, data, side):
        folder = self.storage / data['id']
        # Validate all files before changing any. Repeated calls recover partial operations.
        for edit in data['edits']:
            path = mod_path(self.root, edit['path'])
            actual = digest(path) if path.exists() else None
            if actual not in (edit['before'], edit['after']):
                raise RuntimeError('Mod changed outside Relay; keep it safe and resolve manually: ' + edit['path'])
        for index, edit in enumerate(data['edits']):
            path = mod_path(self.root, edit['path'])
            temp = path.with_name('.relay-' + data['id'] + '.tmp')
            # Clean a partial copy left by an interrupted previous attempt.
            temp.unlink(missing_ok=True)
            wanted = edit[side]
            actual = digest(path) if path.exists() else None
            if actual == wanted:
                continue
            if wanted:
                source = folder / f'{index}.{side}'
                if digest(source) != wanted:
                    raise RuntimeError('Mod snapshot checksum mismatch')
                path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(source, temp)
                    temp.replace(path)
                finally:
                    temp.unlink(missing_ok=True)
            else:
                path.unlink(missing_ok=True)

    def make_commit(self, data):
        # An isolated index starts at the published tree; unrelated staged/dirty
        # world files cannot enter this commit, even if the real index contains them.
        # Git for Windows may reject deeply nested alternate-index paths even
        # when Python can open them. Keep this disposable file in the OS temp dir.
        index = Path(tempfile.gettempdir()) / ('relay-mod-index-' + uuid.uuid4().hex)
        env = dict(os.environ, GIT_INDEX_FILE=str(index), GIT_LITERAL_PATHSPECS='1')
        def command(*args):
            result = subprocess.run(['git', *args], cwd=self.root, env=env, text=True,
                encoding='utf-8', errors='replace', capture_output=True, timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or result.stdout.strip())
            return result.stdout.strip()
        try:
            command('read-tree', data['base'])
            for edit in data['edits']:
                # No --force: repository exclusions must be respected.
                if edit['after'] is not None:
                    command('add', '--', edit['path'])
                else:
                    command('update-index', '--force-remove', '--', edit['path'])
            tree = command('write-tree')
            commit = self.g.command('commit-tree', tree, '-p', data['base'],
                input=f"Relay mods: {data['action']} | {self.host}\n")
            changed = self.g.command('diff-tree', '--no-commit-id', '--name-only', '-r', '-z',
                                     data['base'], commit, raw=True).split('\0')
            if not set(filter(None, changed)).issubset({e['path'] for e in data['edits']}):
                raise RuntimeError('Refusing to publish files outside the selected mods')
            return commit
        finally:
            index.unlink(missing_ok=True)

    def finish(self, data):
        head = self.g.command('rev-parse', 'HEAD')
        if head == data['base']:
            self.g.command('update-ref', '-m', 'Relay mod-only synchronization', self.g.main_ref,
                           data['commit'], data['base'])
        elif head != data['commit']:
            raise RuntimeError('Published, but local branch changed. Retry after restoring the original branch.')
        self.g.command('reset', data['commit'], '--', *[':(literal)' + e['path'] for e in data['edits']])
        self.journal.unlink()
        return 'Mod changes synchronized to GitHub. World files were not committed.'

    def retry(self):
        data = self.load()
        self.check_repo()
        remote, lock, published = self.inspect_remote(data)
        if published:
            # The server accepted a push whose response may have been lost.
            return self.finish(data)
        if remote != data['base'] or self.g.command('rev-parse', 'HEAD') != data['base']:
            raise RuntimeError('World history changed. Cancel this pending mod operation, synchronize, then retry.')
        if lock and lock != data['lock']:
            raise RuntimeError('Another host owns the lock. Nothing was uploaded; retry when it stops.')
        if not lock:
            self.g.command('push', '--force-with-lease=' + LOCK_REF + ':', self.g.remote,
                           data['lock'] + ':' + LOCK_REF)
        # The lock may have been acquired just after a different host saved.
        if self.g.require_owner(data['lock']) != data['base']:
            raise RuntimeError('Remote changed while taking the lock. Cancel and synchronize first.')
        self.write_files(data, 'after')
        if not data['commit']:
            data['commit'] = self.make_commit(data)
            self.save(data)
        # Exact leases and atomic push prevent overwriting a force-unlocked session.
        self.g.command('push', '--atomic', '--force-with-lease=' + self.g.main_ref + ':' + data['base'],
            '--force-with-lease=' + LOCK_REF + ':' + data['lock'], self.g.remote,
            data['commit'] + ':' + self.g.main_ref, ':' + LOCK_REF)
        return self.finish(data)

    def cancel(self):
        data = self.load()
        self.check_repo()
        _, lock, published = self.inspect_remote(data)
        if published:
            return self.finish(data)
        if self.g.command('rev-parse', 'HEAD') != data['base']:
            raise RuntimeError('Local history changed; cancellation cannot safely restore the original state')
        self.write_files(data, 'before')
        # The real index is never changed before successful publication.
        if lock == data['lock']:
            self.g.delete_owned_lock(data['lock'])
        self.journal.unlink()
        return 'Pending mod operation cancelled; original mod files restored.'
