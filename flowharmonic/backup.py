"""Administrator-only, bounded configuration archives. Never extract archive paths."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile
import uuid
from contextlib import closing, contextmanager

from . import VERSION

DATABASES = ('flowharmonic.db', 'authentication.db', 'network.db', 'coordination.db', 'sources.db', 'scenes.db')
LIMIT = 64 * 1024 * 1024
# Stop writers/provisioning, but leave audio players and existing infrastructure running.
WRITERS = ('flowharmonic-audio.timer', 'flowharmonic-audio.service', 'flowharmonic-bluetooth.service', 'flowharmonic.service')


def check_db(path, name):
    if Path(path).is_symlink(): raise ValueError('Symbolic-link database paths are not supported for backup or restore.')
    with closing(sqlite3.connect(f'{Path(path).resolve().as_uri()}?mode=ro', uri=True)) as db:
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok' or db.execute('PRAGMA user_version').fetchone()[0] != 1:
            raise ValueError(f'{name}: unsupported or damaged database. No files were restored.')
        fields = {
            'flowharmonic.db': ('SELECT identity FROM node WHERE id=1', 'SELECT version,name FROM local_settings WHERE id=1'),
            'authentication.db': ('SELECT salt,hash FROM password', 'SELECT hash,expires FROM session'),
            'network.db': ('SELECT private_key,membership,accepting FROM settings', 'SELECT identity,public_key,name,enrollment FROM peer'),
            'coordination.db': ('SELECT source,visible FROM visibility', 'SELECT id,data FROM node', 'SELECT destination,data FROM route', 'SELECT destination,data FROM playback'),
            'sources.db': ('SELECT id,data FROM source', 'SELECT id,data FROM bluetooth'),
            'scenes.db': ('SELECT id,scope,name,data FROM scene', 'SELECT destination,data FROM assignment'),
        }
        for query in fields[name]:
            db.execute(query).fetchall()
        if name == 'flowharmonic.db':
            return db.execute('SELECT identity FROM node WHERE id=1').fetchone()[0]


def export(directory, config_path, destination):
    directory, config_path, destination = Path(directory), Path(config_path), Path(destination)
    with tempfile.TemporaryDirectory() as temporary:
        files = {}
        for name in DATABASES:
            source = directory / name
            if source.exists():
                check_db(source, name)
                target = Path(temporary) / name
                with closing(sqlite3.connect(f'{source.resolve().as_uri()}?mode=ro', uri=True)) as src, closing(sqlite3.connect(target)) as dst:
                    src.backup(dst)
                files[name] = target.read_bytes()
        if 'flowharmonic.db' not in files:
            raise ValueError('Application identity is missing. Restore an existing backup instead.')
        files['config.toml'] = config_path.read_bytes()
        ledger = config_path.parent / 'infrastructure.json'
        files['infrastructure.json'] = ledger.read_bytes()
        manifest = {'format': 1, 'milestone': VERSION, 'identity': check_db(directory / 'flowharmonic.db', 'flowharmonic.db'),
                    'created': int(time.time()), 'files': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
        if sum(map(len, files.values())) > LIMIT:
            raise ValueError('Configuration is too large to back up (64 MiB maximum).')
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'wb') as output, zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
                archive.writestr('manifest.json', json.dumps(manifest))
                for name, data in files.items():
                    archive.writestr(name, data)
            with destination.open('rb') as output:
                os.fsync(output.fileno())
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
    return manifest


def read_archive(archive_path, directory, config_path, replace_identity=False):
    archive_path, directory, config_path = Path(archive_path), Path(directory), Path(config_path)
    if archive_path.stat().st_size > LIMIT + 1024 * 1024:
        raise ValueError('Backup exceeds the 64 MiB configuration limit.')
    allowed = set(DATABASES) | {'manifest.json', 'config.toml', 'infrastructure.json'}
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if len(set(names)) != len(names) or set(names) - allowed or sum(i.file_size for i in archive.infolist()) > LIMIT + 65536:
            raise ValueError('Backup has unexpected files or exceeds the size limit.')
        if 'manifest.json' not in names:
            raise ValueError('Backup manifest is missing.')
        manifest = json.loads(archive.read('manifest.json'))
        if (not isinstance(manifest, dict) or type(manifest.get('format')) is not int or manifest['format'] != 1 or
                not isinstance(manifest.get('files'), dict) or not isinstance(manifest.get('identity'), str)):
            raise ValueError('Unsupported or incomplete backup manifest.')
        try:
            uuid.UUID(manifest['identity'])
        except ValueError as error:
            raise ValueError('Backup identity is invalid.') from error
        if set(manifest['files']) != set(names) - {'manifest.json'}:
            raise ValueError('Unsupported or incomplete backup manifest.')
        if not {'flowharmonic.db', 'config.toml', 'infrastructure.json'} <= set(names):
            raise ValueError('Backup is missing identity or installation settings.')
        files = {name: archive.read(name) for name in names if name != 'manifest.json'}
        if any(hashlib.sha256(data).hexdigest() != manifest['files'][name] for name, data in files.items()):
            raise ValueError('Backup integrity check failed. No files were restored.')
    with tempfile.TemporaryDirectory() as temporary:
        for name in DATABASES:
            if name in files:
                path = Path(temporary) / name
                path.write_bytes(files[name])
                restored_id = check_db(path, name)
                if name == 'flowharmonic.db' and restored_id != manifest['identity']:
                    raise ValueError('Backup identity does not match its manifest.')
        # Validate TOML and known settings using the normal configuration reader.
        from .config import load_config
        config = Path(temporary) / 'config.toml'
        config.write_bytes(files['config.toml'])
        original = os.environ.get('FLOWHARMONIC_CONFIG')
        try:
            os.environ['FLOWHARMONIC_CONFIG'] = str(config)
            load_config()
        finally:
            if original is None: os.environ.pop('FLOWHARMONIC_CONFIG', None)
            else: os.environ['FLOWHARMONIC_CONFIG'] = original
    try:
        current_id = check_db(directory / 'flowharmonic.db', 'flowharmonic.db')
    except (sqlite3.Error, OSError, TypeError, ValueError):
        # Root-owned hardware metadata can identify a damaged installation.
        current_id = json.loads((config_path.parent / 'local-audio.json').read_text()).get('owner')
    if manifest['identity'] != current_id and not replace_identity:
        raise ValueError('This backup belongs to another node. Restore it on its original installation, or explicitly use --replace-identity after taking the original node offline.')
    if json.loads(files['infrastructure.json']) != json.loads((config_path.parent / 'infrastructure.json').read_text()):
        raise ValueError('Infrastructure ownership has changed. Existing services were retained; reconcile ownership before restoring.')
    # Do not retain settings absent from an older archive (which would mix states).
    return manifest, files


def snapshot_files(directory, config_path):
    files={}
    paths={name:Path(directory)/name for name in DATABASES}
    paths.update({name+suffix:Path(directory)/(name+suffix) for name in DATABASES for suffix in ('-wal','-shm','-journal')})
    paths.update({'config.toml':Path(config_path),'infrastructure.json':Path(config_path).parent/'infrastructure.json'})
    for name,path in paths.items():
        try: fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        except FileNotFoundError: continue
        with os.fdopen(fd,'rb') as stream:
            import stat
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):raise ValueError('Configuration contains an unexpected special file.')
            files[name]=stream.read(LIMIT+1)
        if sum(map(len,files.values()))>LIMIT:raise ValueError('Existing configuration exceeds the 64 MiB recovery limit.')
    return files


def save_damaged_snapshot(files, destination):
    # Forensics copy only. Ordinary restore continues to require valid schemas.
    fd=os.open(destination,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'wb') as output,zipfile.ZipFile(output,'w') as archive:
        archive.writestr('manifest.json',json.dumps({'format':1,'damaged_snapshot':True,
            'files':{name:hashlib.sha256(data).hexdigest() for name,data in files.items()}}))
        for name,data in files.items():archive.writestr(name,data)



def replace_file(path, payload, mode, uid=None, gid=None):
    fd, name = tempfile.mkstemp(prefix='.restore-', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as output:
            os.fchmod(output.fileno(), mode)
            output.write(payload); output.flush(); os.fsync(output.fileno())
            if uid is not None:
                os.fchown(output.fileno(), uid, gid)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def restore_files(files, directory, config_path, uid, gid, restore_journals=False):
    directory, config_path = Path(directory), Path(config_path)
    for name in DATABASES:
        path = directory / name
        if name in files:
            replace_file(path, files[name], 0o600, uid, gid)
        else:
            path.unlink(missing_ok=True)
        for suffix in ('-wal', '-shm', '-journal'):
            path.with_name(name + suffix).unlink(missing_ok=True)
            if restore_journals and name+suffix in files:
                replace_file(path.with_name(name+suffix),files[name+suffix],0o600,uid,gid)
    replace_file(config_path, files['config.toml'], 0o644)
    for parent in (directory, config_path.parent):
        fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)


@contextmanager
def quiesce():
    active = [unit for unit in WRITERS if subprocess.run(['systemctl', 'is-active', '--quiet', unit], check=False).returncode == 0]
    try:
        # Timer first, so it cannot launch another provisioner while stopped.
        for unit in WRITERS:
            subprocess.run(['systemctl', 'stop', unit], check=True)
        yield
    finally:
        for unit in reversed(active):
            subprocess.run(['systemctl', 'start', unit], check=True)


def run(args, directory, config_path):
    import fcntl
    with open('/run/lock/flowharmonic-install.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('An install or backup operation is already running.') from error
        if args.command == 'backup':
            with quiesce():
                export(directory, config_path, args.file)
            print(f'Configuration saved to {args.file}. Contains credentials and trust keys; keep it private. Audio players were left running.')
            return
        replace_identity = getattr(args, 'replace_identity', False)
        manifest, files = read_archive(args.file, directory, config_path, replace_identity)
        print(f"Restore configuration for node {manifest['identity']} from {args.file}.")
        print('This replaces configuration, scenes, credentials and membership on this node. Saved audio assignments may resume. Other nodes are not restored.')
        print('Only restore a trusted backup. A checksum detects damage; it does not authenticate the archive.')
        confirmation = 'RESTORE'
        if replace_identity:
            print('IDENTITY REPLACEMENT: the original node must be offline. This restores its credentials and system trust on this installation; never run both copies together.')
            confirmation = 'RESTORE ' + manifest['identity']
        if not sys.stdin.isatty() or input('Type ' + confirmation + ' to continue: ') != confirmation:
            raise RuntimeError('Restore cancelled. No files were changed.')
        account = pwd.getpwnam('flowharmonic')
        backups = Path(directory) / 'backups'
        backups.mkdir(mode=0o700, exist_ok=True)
        recovery = backups / ('before-restore-' + str(time.time_ns()) + '.zip')
        metadata = Path(config_path).parent / 'local-audio.json'
        previous_metadata = metadata.read_bytes() if metadata.exists() else None
        previous_files = None
        try:
            with quiesce():
                # Keep a complete protected recovery copy before replacing anything.
                previous_files = snapshot_files(directory, config_path)
                try:
                    export(directory, config_path, recovery)
                except (sqlite3.Error, ValueError):
                    # A valid backup must also repair a damaged current store.
                    recovery.unlink(missing_ok=True)
                    save_damaged_snapshot(previous_files, recovery)
                    print('Existing data is damaged; a private raw pre-restore snapshot was retained for diagnosis.')
                restore_files(files, directory, config_path, account.pw_uid, account.pw_gid)
                # Keep current generated ownership metadata. The provisioner
                # regenerates inventory from the restored UUID; discarding its
                # owned-unit list would make running FH players look foreign.
            # Recovery must also work when damaged data prevented app startup.
            subprocess.run(['systemctl', 'start', 'flowharmonic.service'], check=True)
            verify_startup()
        except BaseException:
            if recovery.exists() and previous_files is not None:
                with quiesce():
                    restore_files(previous_files, directory, config_path, account.pw_uid, account.pw_gid, restore_journals=True)
                    if previous_metadata is not None: replace_file(metadata, previous_metadata, 0o644)
                print('Restore failed. Previous configuration reinstated; its private backup was retained.', file=sys.stderr)
            raise
        print(f'Restored and application health verified. Audio setup retries automatically. Pre-restore backup: {recovery}')


def verify_startup():
    from .cli import status
    from .config import load_config
    for attempt in range(20):
        try:
            status(load_config())
            return
        except RuntimeError:
            if attempt == 19:
                raise
            time.sleep(.5)
