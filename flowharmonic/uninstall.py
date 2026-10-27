"""Local administrator removal. Inspect first; remove only FH-owned resources."""
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import stat
import uuid
from contextlib import closing

from .backup import DATABASES

FIXED = {
    'flowharmonic.service': ('Description=FlowHarmonic\n', ' -m flowharmonic\n'),
    'flowharmonic-audio.service': ('Description=FlowHarmonic local audio provisioning\n', ' -m flowharmonic.provision\n'),
    'flowharmonic-audio.timer': ('Description=Retry FlowHarmonic audio detection and setup\n', 'Unit=flowharmonic-audio.service\n'),
    'flowharmonic-bluetooth.service': ('Description=FlowHarmonic Bluetooth pairing window\n', ' -m flowharmonic.bluetooth\n'),
}
DYNAMIC = re.compile(r'flowharmonic-(?:playback-[a-f0-9]{20}|desktop-[0-9]+|source-[a-f0-9-]{36})\.service')
RELEASE = re.compile(r'(?:M[1-9][0-9]?|[0-9]{2}\.[0-9]{2}\.[0-9]{2})-[0-9]{8}T[0-9]{6}Z-[A-Za-z0-9]+')


def path_at(root, name):
    path = root / name.lstrip('/')
    # No directory supplied by a mutable database or followed through a symlink.
    for parent in [path.parent, *path.parent.parents]:
        if parent == root.parent: break
        if parent.is_symlink():
            raise RuntimeError(f'Unrelated symbolic-link directory retained: {parent}')
    return path


def owned_unit(path):
    if path.is_symlink() or not path.is_file(): return False
    text = path.read_text()
    if DYNAMIC.fullmatch(path.name):
        return text.startswith('# Managed by FlowHarmonic local audio\n')
    signatures = FIXED.get(path.name)
    return bool(signatures and all(value in text for value in signatures) and
                (path.name.endswith('.timer') or 'WorkingDirectory=/opt/flowharmonic/current\n' in text) and
                (path.name.endswith('.timer') or 'ExecStart=/opt/flowharmonic/current/.venv/bin/python' in text))


def read_membership(directory):
    result = {'identity': None, 'role': 'independent', 'membership': None}
    for name in ('flowharmonic.db', 'network.db'):
        path = directory / name
        if path.is_symlink(): raise RuntimeError(f'Unrelated symbolic-link database retained: {path}')
        if not path.exists(): continue
        try:
            with closing(sqlite3.connect(f'{path.resolve().as_uri()}?mode=ro', uri=True)) as db:
                if name == 'flowharmonic.db':
                    result['identity'] = db.execute('SELECT identity FROM node WHERE id=1').fetchone()[0]
                else:
                    row = db.execute('SELECT membership FROM settings WHERE id=1').fetchone()
                    result['membership'] = json.loads(row[0]) if row and row[0] else None
        except (sqlite3.Error, TypeError, ValueError) as error:
            raise RuntimeError('Cannot read node identity/membership. Restore a backup before removal; no files were changed.') from error
    membership = result['membership']
    if membership:
        result['role'] = 'system host' if membership['host_id'] == result['identity'] else 'member'
    return result


def plan(root=Path('/'), purge=False):
    root = Path(root)
    etc = path_at(root, '/etc/flowharmonic')
    data = path_at(root, '/var/lib/flowharmonic')
    app = path_at(root, '/opt/flowharmonic')
    units = path_at(root, '/etc/systemd/system')
    for container in (etc, data, app, units):
        if container.is_symlink(): raise RuntimeError(f'Unrelated symbolic-link directory retained: {container}')
    ledger = etc / 'infrastructure.json'
    ownership = json.loads(ledger.read_text()) if ledger.is_file() and not ledger.is_symlink() else {}
    if ownership and any(ownership.get(key) not in ('existing', 'flowharmonic') for key in ('server', 'client')):
        raise RuntimeError('Infrastructure ownership is invalid; no resources were removed.')
    selected, retained = [], []
    for unit in sorted(units.glob('flowharmonic*')):
        if unit.name not in FIXED and not DYNAMIC.fullmatch(unit.name): continue
        if owned_unit(unit):
            if unit.name == 'flowharmonic-snapserver.service': continue
            selected.append(unit.name)
        else: retained.append(str(unit))
    server = units / 'flowharmonic-snapserver.service'
    if server.exists() or server.is_symlink():
        if (ownership.get('server') == 'flowharmonic' and not server.is_symlink() and
                ('Description=FlowHarmonic local audio server\n' in server.read_text()) and
                ('# Managed by FlowHarmonic local audio\n' in server.read_text() or
                 'ExecStart=/opt/flowharmonic/snapcast/0.30.0/bin/snapserver ' in server.read_text())):
            selected.append(server.name)
        else: retained.append(str(server))
    releases = []
    release_root = path_at(root, '/opt/flowharmonic/releases')
    if release_root.is_symlink(): raise RuntimeError('An unrelated release directory was retained.')
    for release in sorted(release_root.glob('*')):
        if (not release.is_symlink() and release.is_dir() and RELEASE.fullmatch(release.name) and
                (release/'BUILD').is_file() and not (release/'BUILD').is_symlink() and
                (release/'BUILD').read_text().strip() == release.name):
            releases.append(str(release))
        else: retained.append(str(release))
    current = app / 'current'
    if current.exists() or current.is_symlink():
        if not current.is_symlink() or str(current.resolve()) not in releases:
            raise RuntimeError('The active application is not an identified FH release; no resources were removed.')
    launcher = path_at(root, '/usr/local/bin/flowharmonic')
    remove_launcher = (launcher.is_file() and not launcher.is_symlink() and
                       '# Managed by FlowHarmonic installer\n' in launcher.read_text())
    if (launcher.exists() or launcher.is_symlink()) and not remove_launcher: retained.append(str(launcher))
    binaries = []
    for component in ('server','client'):
        binary = path_at(root, f'/opt/flowharmonic/snapcast/0.30.0/bin/snap{component}')
        if ownership.get(component) == 'flowharmonic' and not (component=='server' and str(server) in retained) and binary.is_file() and not binary.is_symlink(): binaries.append(str(binary))
    return {'purge':purge, 'units':selected, 'releases':releases, 'binaries':binaries,
            'launcher':str(launcher) if remove_launcher else None, 'retained':retained,
            'node':read_membership(data), 'ownership':ownership}


def display(proposed):
    print('FlowHarmonic removal plan' + (' — PURGE' if proposed['purge'] else ' — preserve configuration'))
    print('Node: ' + (proposed['node']['identity'] or 'identity unavailable') + ' · ' + proposed['node']['role'])
    for unit in proposed['units']: print('Stop and remove FH service: ' + unit)
    print('FH playback and capture listed above will stop, including sources used by other devices.')
    for release in proposed['releases']: print('Remove application release: ' + release)
    for binary in proposed['binaries']: print('Remove FH-built audio executable: ' + binary)
    if proposed['launcher']: print('Remove maintenance command: ' + proposed['launcher'])
    print('Preserve distribution packages, preexisting Snapcast services/configuration, and unrelated files.')
    for name in proposed['retained']: print('Retain unrecognized resource: ' + name)
    if proposed['purge']:
        print('PURGE removes FH databases, identity, names, credentials, membership, source definitions, scenes and backups. Reinstall cannot recover them.')
    else:
        print('Preserve /etc/flowharmonic and /var/lib/flowharmonic, including identity, credentials, membership, scenes and backups, for reinstall.')
    if proposed['node']['role'] == 'system host':
        print('This is a system host. Central management will stop for all members. Audio from its removed sources and local players will stop; independent playback elsewhere may continue. There is no automatic replacement coordinator.')
    elif proposed['node']['role'] == 'member':
        print('After confirmation, attempt authenticated departure notification. If the host is unreachable its stale entry may need manual removal. Local membership/trust is preserved unless purged; a successful notification requires explicit enrollment when reinstalled.')


def notify_departure(directory=Path('/var/lib/flowharmonic')):
    """Run as the service account; never reset local membership or trust keys."""
    from .config import load_config
    from .network import Membership, NetworkError
    from .state import database
    member = Membership(directory, load_config(), directory/'flowharmonic.db')
    with member.lock, database(member.path) as db:
        membership = member.current(db)
    if not membership or member.host(membership): return
    try:
        result = member.send(membership['host_url'], membership['host_id'], membership['id'], membership['host_key'],
                             'leave', {'enrollment':membership['enrollment']})
        if not result.get('left'): raise NetworkError('Departure was not confirmed.')
        with member.lock, database(member.path) as db:
            db.execute('UPDATE lifecycle SET departure=? WHERE id=1', (membership['enrollment'],))
        print('System host notified. Reinstallation requires explicit enrollment; local membership and trust keys remain preserved.')
    except NetworkError:
        print('System host unreachable or departure unconfirmed. Local uninstall continues. Its stale member entry may need manual removal; preserved membership may resume if still approved.')


def remove_tree(path):
    if path.is_symlink(): raise RuntimeError(f'An unrelated symbolic link was retained: {path}')
    if path.is_dir(): shutil.rmtree(path)


def remove_empty(path, stop):
    while path != stop and path.is_relative_to(stop):
        try: path.rmdir()
        except OSError: break
        path = path.parent


def clean_runtime(root):
    sources=path_at(root,'/run/flowharmonic-sources')
    if sources.is_dir() and not sources.is_symlink():
        for directory in sources.iterdir():
            try:
                if str(uuid.UUID(directory.name))!=directory.name or directory.is_symlink():continue
            except ValueError:continue
            marker=directory/'.flowharmonic'
            if marker.is_file() and not marker.is_symlink() and marker.read_text()==directory.name:
                for name in ('audio.pcm','config.json','.flowharmonic'):
                    path=directory/name
                    if path.exists() or path.is_symlink():path.unlink()
                remove_empty(directory,sources.parent)
    fifo=path_at(root,'/run/flowharmonic-desktop/audio.pcm')
    if not fifo.is_symlink() and fifo.exists() and stat.S_ISFIFO(fifo.stat().st_mode):fifo.unlink()
    remove_empty(fifo.parent,path_at(root,'/run'))


def execute(proposed, root=Path('/'), runner=subprocess.run):
    root = Path(root)
    units = path_at(root, '/etc/systemd/system')
    # Stop all writers before removing code; timer first so it cannot relaunch.
    ordered = sorted(proposed['units'], key=lambda name:(0 if name.endswith('.timer') else 1 if name in FIXED else 2))
    for unit in ordered:
        runner(['systemctl','disable','--now',unit], check=True)
    if proposed['node']['role'] == 'member' and root == Path('/'):
        result = runner([sys.executable,'-m','flowharmonic.uninstall','--notify'], cwd='/opt/flowharmonic/current',
                        user='flowharmonic', group='flowharmonic', extra_groups=[], check=False)
        if result.returncode: print('Departure notification failed. Local uninstall continues; check the host’s member list.')
    for unit in ordered:
        path = units / unit
        # Root-owned units may have been deliberately replaced since planning.
        valid = owned_unit(path) if unit != 'flowharmonic-snapserver.service' else (not path.is_symlink() and path.exists() and 'Description=FlowHarmonic local audio server\n' in path.read_text())
        if not valid: raise RuntimeError('A service changed during removal and was retained: ' + unit)
        path.unlink()
    runner(['systemctl','daemon-reload'], check=True)
    clean_runtime(root)
    current = path_at(root, '/opt/flowharmonic/current')
    if current.is_symlink(): current.unlink()
    if proposed['launcher']: Path(proposed['launcher']).unlink()
    for release in proposed['releases']: remove_tree(Path(release))
    for binary in proposed['binaries']:
        path = Path(binary); path.unlink(); remove_empty(path.parent, path_at(root,'/opt'))
    if proposed['purge']:
        data = path_at(root,'/var/lib/flowharmonic')
        for name in (*DATABASES, 'control.key','network.lock','bluetooth-request.json'):
            for suffix in ('','-wal','-shm','-journal') if name.endswith('.db') else ('',):
                path = data/(name+suffix)
                if path.is_file() or path.is_symlink(): path.unlink()
        if not (data/'backups').is_symlink(): remove_tree(data/'backups')
        else: print('Unrelated backup-directory symbolic link retained: '+str(data/'backups'))
        etc = path_at(root,'/etc/flowharmonic')
        for name in ('config.toml','infrastructure.json','local-audio.json','local-snapserver.conf','snapserver.conf'):
            path=etc/name
            if path.is_file() and not path.is_symlink():
                if name=='snapserver.conf' and proposed['ownership'].get('server')!='flowharmonic': continue
                if name=='local-snapserver.conf' and not path.read_text().startswith('# Managed by FlowHarmonic local audio\n'): continue
                path.unlink()
        # Only a positively identified, FH-provisioned server owns these stores.
        if 'flowharmonic-snapserver.service' in proposed['units']:
            for name in ('/var/lib/flowharmonic-snapcast/server.json','/var/lib/snapserver/server.json'):
                path=path_at(root,name)
                if path.is_file() and not path.is_symlink(): path.unlink()
        remove_empty(data, path_at(root,'/var/lib'))
        remove_empty(etc, path_at(root,'/etc'))
    # Deterministic generated tone assets can always be reprovisioned.
    if proposed['ownership'].get('server')=='flowharmonic':
        assets=path_at(root,'/var/lib/flowharmonic-audio/tones')
        for name in ('silence.pcm','tone-440.pcm','tone-880.pcm'):
            path=assets/name
            if path.is_file() and not path.is_symlink(): path.unlink()
        remove_empty(assets, path_at(root,'/var/lib'))
    remove_empty(path_at(root,'/opt/flowharmonic/releases'),path_at(root,'/opt'))
    print('FlowHarmonic removed. ' + ('FH identity and recognized persistent data purged.' if proposed['purge'] else 'Configuration and identity retained. Run installLinux.sh from a trusted source tree to reinstall.'))


def run(args):
    proposed = plan(purge=args.purge)
    if args.dry_run:
        display(proposed); print('Dry run: no files, services or memberships changed.'); return
    with open('/run/lock/flowharmonic-install.lock','a') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as error: raise RuntimeError('An installation or maintenance operation is running.') from error
        proposed = plan(purge=args.purge)
        display(proposed)
        if not sys.stdin.isatty() or input('Type UNINSTALL to continue: ')!='UNINSTALL':
            raise RuntimeError('Cancelled. No services or files were changed.')
        if args.purge and input('Type PURGE to permanently remove identity, credentials and backups: ')!='PURGE':
            raise RuntimeError('Purge cancelled. No services or files were changed.')
        if plan(purge=args.purge)!=proposed:
            raise RuntimeError('Installation or membership changed during confirmation. Review the removal plan again.')
        execute(proposed)


if __name__=='__main__':
    import pwd
    if sys.argv[1:]!=['--notify'] or os.geteuid()!=pwd.getpwnam('flowharmonic').pw_uid:
        raise SystemExit('Use sudo flowharmonic uninstall.')
    notify_departure()
