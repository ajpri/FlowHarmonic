"""Small root-side desktop-session lifecycle, called only by audio provisioning."""
import grp
import os
import re
import stat
import uuid

from .desktop import SOURCE


def active_session(provisioner):
    result = provisioner.command('loginctl', 'list-sessions', '--no-legend', check=False)
    if result.returncode:
        return None
    sessions = []
    for line in result.stdout.splitlines():
        session = line.split()[0]
        if not re.fullmatch(r'[a-zA-Z0-9]+', session):
            continue
        result = provisioner.command('loginctl', 'show-session', session,
                                     '-p', 'User', '-p', 'Active', '-p', 'Remote', '-p', 'Type', '-p', 'Seat', '-p', 'Class', check=False)
        values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        if (not result.returncode and values.get('Active') == 'yes' and values.get('Remote') == 'no'
                and values.get('Type') in ('wayland', 'x11') and values.get('Seat') == 'seat0'
                and values.get('Class') == 'user'
                and values.get('User', '').isdigit() and int(values['User']) > 0):
            sessions.append((session, int(values['User'])))
    return sessions[0] if len(sessions) == 1 else None


def prepare(provisioner, node, server_user):
    """Create a protected pipe before Snapserver reads its generated config."""
    p = provisioner
    session = active_session(p)
    keep = f'flowharmonic-desktop-{session[1]}.service' if session else None
    pause(p, keep=keep)
    old = p.previous.get('desktop', {})
    unit = old.get('unit')
    if unit and re.fullmatch(r'flowharmonic-desktop-[0-9]+\.service', unit):
        if not session or session != (old.get('session'), old.get('uid')):
            pause(p)
            unit = None
    directory = p.path('/run/flowharmonic-desktop')
    if directory.is_symlink():
        raise RuntimeError('An unrelated path occupies the desktop audio directory; it was retained.')
    directory.mkdir(parents=True, exist_ok=True)
    fifo = directory / 'audio.pcm'
    if fifo.is_symlink() or (fifo.exists() and not stat.S_ISFIFO(fifo.stat().st_mode)):
        raise RuntimeError('An unrelated file occupies the desktop audio pipe; it was retained.')
    if not fifo.exists():
        os.mkfifo(fifo, 0o640)
    uid = session[1] if session else 0
    if p.root == p.root.__class__('/'):
        os.chown(fifo, uid, grp.getgrnam(server_user).gr_gid)
        fifo.chmod(0o640)
    p.status['desktop'] = {'source': SOURCE, 'uid': uid, 'session': session[0] if session else None,
                           'unit': unit, 'message': 'Log in to a local PipeWire desktop to share desktop audio.'}
    if session:
        p.status['desktop']['destination'] = 'fh-' + uuid.uuid5(uuid.UUID(node), 'desktop-playback').hex
        p.status['desktop']['status'] = f'/run/flowharmonic-desktop-{uid}/status.json'
    return session, fifo


def start(provisioner, session, binary_dir, port):
    p = provisioner
    if not session:
        return
    session_id, uid = session
    from .provision import MARKER, unit_quote, write_file
    unit = f'flowharmonic-desktop-{uid}.service'
    path = p.units / unit
    if path.exists() and not path.read_text().startswith(MARKER):
        raise RuntimeError('An unrelated service occupies the desktop capture service name; it was retained.')
    desktop = p.status['desktop']
    desktop['unit'] = unit
    # Record ownership before starting. Never touch a desktop's own services.
    p.save()
    release = p.path('/opt/flowharmonic/current').resolve()
    text = f'''{MARKER}[Unit]
Description=FlowHarmonic desktop audio session
BindsTo=session-{session_id}.scope
After=session-{session_id}.scope flowharmonic-snapserver.service
StartLimitIntervalSec=0
[Service]
User={uid}
WorkingDirectory=/opt/flowharmonic/current
Environment=XDG_RUNTIME_DIR=/run/user/{uid}
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart={unit_quote(release / ".venv/bin/python")} -m flowharmonic.desktop --fifo /run/flowharmonic-desktop/audio.pcm --status {desktop['status']} --snapclient {unit_quote(binary_dir / 'snapclient')} --client-id {desktop['destination']} --port {port}
RuntimeDirectory=flowharmonic-desktop-{uid}
RuntimeDirectoryMode=0755
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/run/flowharmonic-desktop/audio.pcm
CapabilityBoundingSet=
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
UMask=0022
'''
    changed = write_file(path, text)
    p.command('systemctl', 'daemon-reload')
    p.command('systemctl', 'restart' if changed else 'start', unit)


def pause(provisioner, keep=None):
    """Stop only marked FH workers, including recovery after an interrupted setup."""
    from .provision import MARKER
    for path in provisioner.units.glob('flowharmonic-desktop-*.service'):
        if (re.fullmatch(r'flowharmonic-desktop-[0-9]+\.service', path.name)
                and path.name != keep and path.read_text().startswith(MARKER)):
            provisioner.command('systemctl', 'stop', path.name)
