"""Destructive-to-the-test-session checks for a disposable M4 VM ONLY.

Run as root in the prepared VM. Stops its test user's PipeWire and graphical
session, then starts a replacement session. Never run on a real user's desktop.
"""
import json
import os
import signal
import subprocess
import time
import urllib.request
from pathlib import Path

from flowharmonic.local_audio import local_inventory
from flowharmonic.snapcast import Snapcast

results = {}
metadata = json.loads(Path('/etc/flowharmonic/local-audio.json').read_text())
uid = metadata['desktop']['uid']
assert uid == 1000 and os.geteuid() == 0
unit = metadata['desktop']['unit']


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def user_command(*args):
    return command('runuser', '-u', 'ubuntu', '--', 'env', f'XDG_RUNTIME_DIR=/run/user/{uid}',
                   f'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus', *args)


def source():
    health = json.load(urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3))
    assert health['status'] == 'ok' and health['version'] == 'M4'
    view = local_inventory(Snapcast('tcp://127.0.0.1:1705').snapshot(), metadata['owner'], 'tcp://127.0.0.1:1705')
    return next(s for s in view['sources'] if s['id'] == 'Desktop Audio')


def wait(predicate):
    for _ in range(200):
        if predicate():
            return
        time.sleep(.2)
    raise RuntimeError('Timed out waiting for desktop lifecycle state')


def available():
    return source()['status'] != 'disabled'


def sessions():
    return {line.split()[0] for line in command('loginctl', 'list-sessions', '--no-legend').splitlines()}


try:
    wait(available)
    initial = command('systemctl', 'show', unit, '-p', 'MainPID', '--value')
    children = command('ps', '--ppid', initial, '-o', 'pid=,comm=').splitlines()
    gst_pid = int(next(line.split()[0] for line in children if 'gst-launch' in line))
    os.kill(gst_pid, signal.SIGSTOP)
    wait(lambda: not available())
    results['stalled_capture_message'] = source()['message']
    wait(available)
    results['stalled_worker_recovered'] = command('systemctl', 'show', unit, '-p', 'MainPID', '--value') != initial
    user_command('systemctl', '--user', 'stop', 'wireplumber.service', 'pipewire-pulse.service',
                 'pipewire-pulse.socket', 'pipewire.service', 'pipewire.socket')
    wait(lambda: not available())
    results['pipewire_outage_message'] = source()['message']
    user_command('systemctl', '--user', 'start', 'pipewire.socket', 'pipewire.service',
                 'pipewire-pulse.socket', 'pipewire-pulse.service', 'wireplumber.service')
    wait(available)
    results['pipewire_recovered'] = True
    session = json.loads(Path('/etc/flowharmonic/local-audio.json').read_text())['desktop']['session']
    command('loginctl', 'terminate-session', session)
    wait(lambda: command('systemctl', 'show', unit, '-p', 'MainPID', '--value') == '0')
    command('systemctl', 'start', 'flowharmonic-audio')
    wait(lambda: not available())
    results['logout_message'] = source()['message']
    before = sessions()
    display = ':' + str(100 + int(time.time()) % 1000)
    command('systemd-run', '--unit=fh-m4-test-desktop-return-' + str(time.time_ns()), '--uid=ubuntu', '--property=PAMName=login',
            '--setenv=XDG_SESSION_TYPE=x11', '--setenv=XDG_SEAT=seat0', '--setenv=XDG_VTNR=2',
            '--setenv=DISPLAY=' + display, '/bin/bash', '-c', f'Xvfb {display} -screen 0 1024x768x24 & sleep 1; openbox & wait')
    wait(lambda: bool(sessions() - before))
    new_session = next(iter(sessions() - before))
    command('loginctl', 'activate', new_session)
    command('systemctl', 'start', 'flowharmonic-audio')
    wait(available)
    results['new_login_recovered'] = True
    results['health_available_during_checks'] = True
    results['passed'] = all(results.get(key) is True for key in
                            ('stalled_worker_recovered', 'pipewire_recovered', 'new_login_recovered'))
finally:
    Path('/tmp/fh-m4-lifecycle-result.json').write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps(results, indent=2))
