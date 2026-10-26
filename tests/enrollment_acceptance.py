#!/usr/bin/env python3
"""Disposable Ubuntu VM fixture: two FH processes in independent network namespaces.

Run as root only on the authorized test VM. No installed password is read/reset.
The second node is a fixture, not a new product service or installation mode.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request

ROOT = Path('/var/tmp/fh-m6-testing')
DATA = Path('/var/lib/flowharmonic-m6-peer')
CONFIG = Path('/etc/flowharmonic-m6-peer.toml')
PYTHON = '/opt/flowharmonic/current/.venv/bin/python'
NODE = '/var/tmp/fh-m5-testing/node'
PEER_URL = 'http://10.206.0.2:8080'


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def wait(url):
    for attempt in range(50):
        try:
            return json.load(urllib.request.urlopen(url + '/health', timeout=2))
        except OSError:
            time.sleep(.2)
    raise RuntimeError('Node did not become healthy')


def session(directory):
    # Root initiates; the service user owns every SQLite journal and write.
    code = '''import json,sys
from pathlib import Path
from flowharmonic.security import Authentication
from flowharmonic.state import database,identity
p=Path(sys.argv[1]); a=Authentication(p)
with database(a.path) as db: token=a.new_session(db)
print(json.dumps({'cookie':'fh_session_'+identity(p/'flowharmonic.db').replace('-','')[:12]+'='+token}))'''
    result = subprocess.check_output(['runuser', '-u', 'flowharmonic', '--', PYTHON, '-c', code, str(directory)], cwd='/opt/flowharmonic/current', text=True)
    return json.loads(result)


def prepare():
    ROOT.mkdir(mode=0o700, exist_ok=True)
    if not (ROOT / 'before.json').exists():
        with sqlite3.connect('/var/lib/flowharmonic/flowharmonic.db') as db:
            before = {'identity': db.execute('SELECT identity FROM node WHERE id=1').fetchone()[0]}
        network = Path('/var/lib/flowharmonic/network.db')
        if network.exists():
            with sqlite3.connect(network) as db:
                if db.execute('SELECT membership FROM settings WHERE id=1').fetchone()[0] is not None:
                    raise RuntimeError('Test requires an independent primary node; existing system will not be modified')
                before['public_key_hash'] = hashlib.sha256(db.execute('SELECT private_key FROM settings WHERE id=1').fetchone()[0]).hexdigest()
        before['config_hash'] = hashlib.sha256(Path('/etc/flowharmonic/config.toml').read_bytes()).hexdigest()
        (ROOT / 'before.json').write_text(json.dumps(before))
    run('install', '-d', '-m', '0750', '-o', 'flowharmonic', '-g', 'flowharmonic', str(DATA))
    CONFIG.write_text('name="M6 Living Room"\nhost="0.0.0.0"\nport=8080\nsnapcast_url="tcp://127.0.0.1:1705"\n')
    setup = ROOT / 'network.sh'
    setup.write_text('''#!/bin/sh
set -eu
ip netns list | cut -d' ' -f1 | grep -qx fh-m6-peer && exit 0
ip netns add fh-m6-peer
ip link add fh-m6-host type veth peer name fh-m6-node
ip link set fh-m6-node netns fh-m6-peer
ip addr add 10.206.0.1/24 dev fh-m6-host
ip link set fh-m6-host up
ip -n fh-m6-peer link set lo up
ip -n fh-m6-peer addr add 10.206.0.2/24 dev fh-m6-node
ip -n fh-m6-peer link set fh-m6-node up
ip -n fh-m6-peer route add default via 10.206.0.1
''')
    setup.chmod(0o700)
    Path('/etc/systemd/system/fh-m6-test-network.service').write_text(f'''[Unit]
Description=Disposable M6 acceptance LAN
Before=fh-m6-test-peer.service
[Service]
Type=oneshot
ExecStart={setup}
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
''')
    Path('/etc/systemd/system/fh-m6-test-peer.service').write_text(f'''[Unit]
Description=Disposable independent M6 acceptance node
Requires=fh-m6-test-network.service
After=fh-m6-test-network.service
[Service]
User=flowharmonic
Group=flowharmonic
NetworkNamespacePath=/run/netns/fh-m6-peer
WorkingDirectory=/opt/flowharmonic/current
Environment=FLOWHARMONIC_CONFIG={CONFIG}
Environment=FLOWHARMONIC_DATA_DIR={DATA}
ExecStart={PYTHON} -m flowharmonic serve
Restart=on-failure
[Install]
WantedBy=multi-user.target
''')
    run('systemctl', 'daemon-reload')
    run('systemctl', 'enable', '--now', 'fh-m6-test-network.service', 'fh-m6-test-peer.service')
    wait(PEER_URL)
    # Reopen primary discovery sockets for the newly created virtual LAN.
    run('systemctl', 'restart', 'flowharmonic.service')
    wait('http://127.0.0.1:8080')
    sessions = {'host': session(Path('/var/lib/flowharmonic')), 'member': session(DATA)}
    (ROOT / 'sessions.json').write_text(json.dumps(sessions))
    (ROOT / 'sessions.json').chmod(0o600)
    print('Two independent nodes ready; disposable browser sessions stored privately.')


def ui(mode):
    run(NODE, str(ROOT / 'enrollment_ui_acceptance.js'), mode)


def cleanup():
    sessions = json.loads((ROOT / 'sessions.json').read_text())
    for role, directory in [('host', Path('/var/lib/flowharmonic')), ('member', DATA)]:
        token = sessions[role]['cookie'].split('=', 1)[1]
        code = '''import sys
from pathlib import Path
from flowharmonic.security import Authentication
Authentication(Path(sys.argv[1])).sign_out(sys.stdin.read())'''
        run('runuser', '-u', 'flowharmonic', '--', PYTHON, '-c', code, str(directory), input=token, text=True, cwd='/opt/flowharmonic/current')
    (ROOT / 'sessions.json').unlink()
    run('systemctl', 'disable', '--now', 'fh-m6-test-peer.service', 'fh-m6-test-network.service')
    run('ip', 'netns', 'del', 'fh-m6-peer')
    for unit in ('fh-m6-test-peer.service', 'fh-m6-test-network.service'):
        Path('/etc/systemd/system', unit).unlink()
    run('systemctl', 'daemon-reload')
    CONFIG.unlink(missing_ok=True)
    shutil.move(str(DATA), str(ROOT / ('peer-data-' + str(int(time.time())))))
    before = json.loads((ROOT / 'before.json').read_text())
    health = wait('http://127.0.0.1:8080')
    assert health['identity'] == before['identity']
    assert hashlib.sha256(Path('/etc/flowharmonic/config.toml').read_bytes()).hexdigest() == before['config_hash']
    with sqlite3.connect('/var/lib/flowharmonic/network.db') as db:
        assert db.execute('SELECT membership FROM settings WHERE id=1').fetchone()[0] is None
        if 'public_key_hash' in before:
            assert hashlib.sha256(db.execute('SELECT private_key FROM settings WHERE id=1').fetchone()[0]).hexdigest() == before['public_key_hash']
    print('Test sessions revoked; fixture services and LAN removed. Original independent node retained.')


if __name__ == '__main__':
    if os.geteuid() != 0:
        raise SystemExit('Run only as root on the disposable acceptance VM')
    if sys.argv[1] == 'prepare': prepare()
    elif sys.argv[1] == 'cleanup': cleanup()
    else: ui(sys.argv[1])
