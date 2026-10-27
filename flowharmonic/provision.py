"""Root-only provisioning of explicitly FH-owned local audio resources.

Invoked by installer/systemd, never by the web API. All subprocesses use fixed
commands and argument lists. Persistent, root-owned metadata records ownership.
"""
import argparse
import hashlib
import json
import math
import os
import re
import socket
import sqlite3
import struct
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlsplit

from .config import load_config
from . import VERSION
from .desktop import SOURCE as DESKTOP_SOURCE
from .desktop_provision import prepare as prepare_desktop, start as start_desktop, pause as pause_desktop
from .hardware import playback_outputs, probe_output
from .snapcast import AudioError, Snapcast
from .playback_target import target as playback_target, joined

MARKER = '# Managed by FlowHarmonic local audio\n'
SOURCES = [('silence', 'Silence', 0), ('tone-440', 'Test tone 440 Hz', 440), ('tone-880', 'Test tone 880 Hz', 880)]


def write_file(path, content, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = content.encode() if isinstance(content, str) else content
    if path.exists() and path.read_bytes() == payload:
        return False
    temporary = path.with_suffix(path.suffix + '.next')
    temporary.write_bytes(payload)
    temporary.chmod(mode)
    temporary.replace(path)
    return True


def unit_quote(value):
    if any(ord(c) < 32 for c in str(value)):
        raise ValueError('Control characters in service argument')
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'


def test_audio(directory):
    """Generate fixed test assets once. Snapcast reads, paces, and loops them."""
    directory.mkdir(parents=True, exist_ok=True)
    for filename, _, frequency in SOURCES:
        path = directory / (filename + '.pcm')
        # Five seconds: a gentle one-second tone followed by four seconds of rest.
        # No runtime generator, custom transport, or audio encoder is introduced.
        frames = bytearray(48000 * 5 * 4)
        if frequency:
            for frame in range(48000):
                fade = min(1, frame / 480, (47999 - frame) / 480)
                sample = int(512 * fade * math.sin(2 * math.pi * frequency * frame / 48000))
                struct.pack_into('<hh', frames, frame * 4, sample, sample)
        write_file(path, frames)


def server_configuration(base, assets, desktop_fifo=None, expose=False, extra_sources=()):
    if expose:
        # Only the generated, FH-owned stream listener is opened to the LAN.
        # Management listeners stay on loopback; the original base file is retained.
        lines=[]
        section=''
        for line in base.splitlines():
            if re.match(r'^\s*\[',line): section=line.strip()
            if section in ('[stream]','[tcp]','[http]') and re.match(r'^\s*bind_to_address\s*=',line): continue
            lines.append(line)
            if section in ('[tcp]','[http]') and re.match(r'^\s*\[',line): lines.append('bind_to_address = 127.0.0.1')
        base='\n'.join(lines)+'\n'
        if '[stream]' not in base: base+='\n[stream]\n'
        base=base.replace('[stream]','[stream]\nbind_to_address = 0.0.0.0',1)
    for line in base.splitlines():
        match = re.match(r'\s*source\s*=\s*(.*)', line)
        if match:
            name = parse_qs(urlsplit(match[1]).query).get('name', [''])[0]
            if name in {name for _, name, _ in SOURCES} | ({DESKTOP_SOURCE} if desktop_fifo else set()):
                raise RuntimeError('An existing source uses a reserved test-source name; its configuration was retained.')
    lines = [f'source = file://{assets / (filename + ".pcm")}?{urlencode({"name": name, "sampleformat": "48000:16:2", "codec": "pcm"}, quote_via=quote)}' for filename, name, _ in SOURCES]
    for fifo,identifier in extra_sources:
        if any(parse_qs(urlsplit(match[1]).query).get('name',[''])[0]==identifier for match in re.finditer(r'^\s*source\s*=\s*(.*)',base,re.M)):
            raise RuntimeError('An existing stream uses a configured source identity; its configuration was retained.')
        lines.append(f'pipe://{fifo}?'+urlencode({'name':identifier,'mode':'read','sampleformat':'48000:16:2','codec':'pcm'}))
        lines[-1]='source = '+lines[-1]
    if desktop_fifo:
        lines.append(f'source = pipe://{desktop_fifo}?name=Desktop%20Audio&mode=read&sampleformat=48000:16:2&codec=pcm')
    block = '\n'.join(lines) + '\n'
    match = re.search(r'^\s*\[stream\]\s*$', base, re.M)
    if match:
        return MARKER + base[:match.end()] + '\n' + block + base[match.end():]
    return MARKER + base + '\n[stream]\n' + block


class Provisioner:
    def __init__(self, root=Path('/'), runner=subprocess.run, detector=playback_outputs, probe=probe_output):
        self.root = Path(root)
        self.runner, self.detector, self.probe = runner, detector, probe
        self.etc = self.path('/etc/flowharmonic')
        self.units = self.path('/etc/systemd/system')
        self.status_path = self.etc / 'local-audio.json'
        self.previous = json.loads(self.status_path.read_text()) if self.status_path.exists() else {}
        self.status = {'version': VERSION, 'message': '', 'destinations': [], 'owned_units': self.previous.get('owned_units', [])}
        if self.previous.get('desktop'):
            self.status['desktop'] = self.previous['desktop'].copy()

    def path(self, value):
        return self.root / value.lstrip('/')

    def command(self, *args, check=True):
        result = self.runner(list(args), capture_output=True, text=True, timeout=30)
        if check and result.returncode:
            raise RuntimeError(f'Local audio service action failed: {args[1] if len(args) > 1 else args[0]}. {result.stderr.strip()}')
        return result

    def save(self, progress=False):
        status = dict(self.status)
        if progress:
            # Ownership must be durable before service mutations, while readers
            # keep seeing the last complete inventory until detection finishes.
            for key in ('destinations', 'sources', 'inputs'):
                if key in self.previous:
                    status[key] = self.previous[key]
        write_file(self.status_path, json.dumps(status, indent=2) + '\n')

    def own_unit(self, name, text):
        path = self.units / name
        if path.exists() and name not in self.status['owned_units'] and not path.read_text().startswith(MARKER):
            # The M1/M2 Fedora unit is also explicitly owned in infrastructure.json.
            legacy = name == 'flowharmonic-snapserver.service' and 'Description=FlowHarmonic local audio server\n' in path.read_text()
            if not legacy:
                raise RuntimeError('An unrelated service occupies a local audio service name; it was retained.')
        if name not in self.status['owned_units']:
            self.status['owned_units'].append(name)
        self.save(progress=True)  # Save ownership before creating/starting anything.
        return write_file(path, MARKER + text)

    def provision(self, config, audio=None):
        self.status['endpoint'] = config['snapcast_url']
        ownership = json.loads((self.etc / 'infrastructure.json').read_text())
        if ownership.get('server') != 'flowharmonic' or ownership.get('client') != 'flowharmonic':
            pause_desktop(self)
            from .source_provision import pause as pause_sources
            pause_sources(self)
            self.status['sources']=[]
            self.status.pop('desktop', None)
            self.status['message'] = 'Existing audio infrastructure was left unchanged. Its available sources and destinations remain controllable.'
            self.save()
            return self.status
        url = urlsplit(config['snapcast_url'])
        if url.hostname not in ('127.0.0.1', 'localhost', '::1'):
            pause_desktop(self)
            from .source_provision import pause as pause_sources
            pause_sources(self)
            self.status['sources']=[]
            self.status.pop('desktop', None)
            self.status['message'] = 'Another audio server is selected. Local provisioning is paused; existing playback is retained.'
            self.save()
            return self.status
        db_path = self.path('/var/lib/flowharmonic/flowharmonic.db')
        with sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True) as db:
            node = db.execute('SELECT identity FROM node WHERE id = 1').fetchone()[0]
        uuid.UUID(node)
        if self.previous.get('owner') and self.previous['owner'] != node:
            raise RuntimeError('Local audio ownership does not match this node; existing resources were retained.')
        self.status['owner'] = node
        fedora = self.path('/opt/flowharmonic/snapcast/0.30.0/bin/snapserver').exists()
        binary_dir = self.path('/opt/flowharmonic/snapcast/0.30.0/bin' if fedora else '/usr/bin')
        for binary in ('snapserver', 'snapclient'):
            if not os.access(binary_dir / binary, os.X_OK):
                raise RuntimeError('A required local audio component is missing. Rerun the installer to repair it.')
        base_path = self.etc / 'snapserver.conf' if fedora else self.path('/etc/snapserver.conf')
        base = base_path.read_text() if base_path.exists() else ''
        def setting(section, option, default):
            match = re.search(r'^\s*\[' + re.escape(section) + r'\]\s*$(.*?)(?=^\s*\[|\Z)', base, re.M | re.S)
            values = re.findall(r'^\s*' + re.escape(option) + r'\s*=\s*(.*?)\s*$', match[1], re.M) if match else []
            return values[-1] if values else default
        rpc_port = int(setting('tcp', 'port', '1705'))
        http_port = int(setting('http', 'port', '1780'))
        port = url.port or (1705 if url.scheme == 'tcp' else 443 if url.scheme == 'https' else 80)
        if port != (rpc_port if url.scheme == 'tcp' else http_port) or url.scheme == 'https':
            pause_desktop(self)
            from .source_provision import pause as pause_sources
            pause_sources(self)
            self.status['sources']=[]
            self.status.pop('desktop', None)
            self.status['message'] = 'A different audio endpoint is selected. Local provisioning is paused; existing playback is retained.'
            self.save()
            return self.status
        stream_port = int(setting('stream', 'port', '1704'))
        self.status['stream_port'] = stream_port
        if not 1 <= stream_port <= 65535:
            raise RuntimeError('Invalid local audio port; original configuration was retained.')
        assets = self.path('/var/lib/flowharmonic-audio/tones')
        test_audio(assets)
        generated = self.etc / 'local-snapserver.conf'
        # Debian packages use _snapserver; some distributions use snapserver.
        passwd = self.path('/etc/passwd')
        packaged_user = '_snapserver' if passwd.exists() and any(line.startswith('_snapserver:') for line in passwd.read_text().splitlines()) else 'snapserver'
        user = 'flowharmonic-snapcast' if fedora else packaged_user

        state = 'flowharmonic-snapcast' if fedora else 'snapserver'
        data = setting('server', 'datadir', str(self.path('/var/lib/' + state)))
        if not Path(data).is_absolute() or any(c in data for c in '\r\n'):
            raise RuntimeError('Invalid local server data directory; original configuration was retained.')
        server_unit = 'flowharmonic-snapserver.service'
        unit_changed = self.own_unit(server_unit, f'''[Unit]
Description=FlowHarmonic local audio server
After=network.target
StartLimitIntervalSec=0
[Service]
User={user}
Group={user}
EnvironmentFile=-/etc/default/snapserver
ExecStart={unit_quote(binary_dir / 'snapserver')} --config {unit_quote(generated)} {unit_quote("--server.datadir=" + data)} $SNAPSERVER_OPTS
StateDirectory={state}
RuntimeDirectory=flowharmonic-snapcast
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
UMask=0027
[Install]
WantedBy=multi-user.target
''')
        session, fifo = prepare_desktop(self, node, user)
        from .source_provision import prepare as prepare_sources
        extra_sources=prepare_sources(self,session,user)
        changed = write_file(generated, server_configuration(base, assets, fifo, joined(self.root),extra_sources))
        if not fedora:
            self.command('systemctl', 'disable', '--now', 'snapserver.service')
            self.command('systemctl', 'disable', '--now', 'snapclient.service')
        self.command('systemctl', 'daemon-reload')
        self.command('systemctl', 'enable', server_unit)
        if changed or unit_changed:
            self.command('systemctl', 'restart', server_unit)
        else:
            self.command('systemctl', 'start', server_unit)
        audio = audio or Snapcast(config['snapcast_url'])
        for attempt in range(10):
            try:
                observed = audio.status()
                if {name for _, name, _ in SOURCES} <= {s['id'] for s in observed['streams']}:
                    break
                raise RuntimeError('Test sources were not observed on the selected local server.')
            except AudioError:
                if attempt == 9:
                    raise
                time.sleep(1)
        desired = []
        initialized_cards = set()
        for output in ([] if session else self.detector()):
            identifier = 'fh-' + uuid.uuid5(uuid.UUID(node), output['key']).hex
            name = socket.gethostname() + ' - ' + output['name']
            unit = 'flowharmonic-playback-' + output['key'] + '.service'
            row = {'id': identifier, 'name': name, 'device': output['device'], 'unit': unit, 'message': ''}
            if not output['connected'] and unit not in self.previous.get('owned_units', []):
                continue
            self.status['destinations'].append(row)
            if not output['connected']:
                row['message'] = 'No display or receiver is connected to this output.'
                continue
            unit_path = self.units / unit
            marked = (unit_path.is_file() and not unit_path.is_symlink() and
                      unit_path.read_text().startswith(MARKER))
            active = (unit in self.previous.get('owned_units', []) or marked) and self.command('systemctl', 'is-active', '--quiet', unit, check=False).returncode == 0
            problem = '' if active else self.probe(output['device'])
            if problem:
                row['message'] = problem
                continue
            # Standard ALSA profiles initialize a new, unsaved card's muted
            # power-on defaults. Never reinitialize owned outputs or saved state.
            card = output['device'].split('CARD=', 1)[1].split(',', 1)[0]
            if unit not in self.previous.get('owned_units', []) and not marked and card not in initialized_cards and not self.path('/var/lib/alsa/asound.state').exists():
                result = self.command('alsactl', 'init', card, check=False)
                # ALSA reports 99 after successfully applying its generic profile.
                if result.returncode not in (0, 99):
                    raise RuntimeError('The local sound card could not be initialized automatically.')
                initialized_cards.add(card)
            desired.append(unit)
            playback_host, playback_port = playback_target(self.root,node,identifier,stream_port)
            text = f'''[Unit]
Description=FlowHarmonic playback output
After=network.target sound.target {server_unit}
Wants={server_unit}
StartLimitIntervalSec=0
[Service]
User=flowharmonic-audio
Group=flowharmonic-audio
SupplementaryGroups=audio
ExecStart={unit_quote(binary_dir / 'snapclient')} --host {playback_host} --port {playback_port} --hostID {identifier} --player alsa --soundcard {unit_quote(output['device'])} --mixer software
Restart=always
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
CapabilityBoundingSet=
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
[Install]
WantedBy=multi-user.target
'''
            modified = self.own_unit(unit, text)
            self.command('systemctl', 'daemon-reload')
            self.command('systemctl', 'enable', unit)
            self.command('systemctl', 'restart' if modified else 'start', unit)
        # Remove only recorded FH units for hardware that disappeared/unavailable.
        for unit in list(self.previous.get('owned_units', [])):
            if unit == server_unit or unit in desired:
                continue
            if not re.fullmatch(r'flowharmonic-playback-[a-f0-9]{20}\.service', unit):
                raise RuntimeError('Unrecognized recorded local audio service; it was retained.')
            self.command('systemctl', 'disable', '--now', unit)
            path = self.units / unit
            if path.exists() and path.read_text().startswith(MARKER):
                path.unlink()
            self.status['owned_units'].remove(unit)
        self.command('systemctl', 'daemon-reload')
        start_desktop(self, session, binary_dir, stream_port)
        if session:
            self.status['destinations'].append({'id': self.status['desktop']['destination'],
                'name': socket.gethostname() + ' - Desktop Speakers', 'message': ''})
        # Friendly initial names only; do not overwrite later user-assigned names.
        for attempt in range(10):
            observed = audio.status()
            clients = {c['id']: c for g in observed['groups'] for c in g['clients']}
            if all(row['id'] in clients or row['message'] for row in self.status['destinations']):
                break
            time.sleep(0.2)
        for row in self.status['destinations']:
            if row['id'] in clients and not clients[row['id']]['config'].get('name'):
                audio.call('Client.SetName', id=row['id'], name=row['name'])
        if not self.status['destinations']:
            self.status['message'] = 'No connected local playback hardware was found. You can still control existing destinations.'
        self.save()
        return self.status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/'), help='Alternate filesystem root for isolated tests')
    args = parser.parse_args()
    if args.root == Path('/') and os.geteuid() != 0:
        raise SystemExit('Local audio provisioning requires the system service or installer.')
    provisioner = Provisioner(args.root)
    try:
        provisioner.provision(load_config())
    except Exception as error:
        provisioner.status['message'] = 'Local audio setup could not finish. Playback settings were retained; setup will retry automatically.'
        provisioner.status['error'] = str(error)
        provisioner.save(progress=True)
        print(str(error), file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
