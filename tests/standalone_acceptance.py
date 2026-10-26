"""Installed M5 acceptance orchestrator for the disposable Ubuntu desktop VM.

Root issues/revokes a private temporary session; the user's password and sessions
are retained. Browser event handlers run in a minimal DOM against real HTTP.
The fixture changes names/routing temporarily, kills only FH-owned services, and
uses a test-only local monitor recording to measure audio output.
"""
import argparse
import array
import hashlib
import json
import math
import os
import sqlite3
import subprocess
import time
import urllib.request
import wave
from pathlib import Path

TEST = Path('/var/tmp/fh-m5-testing')
STATE = Path('/var/lib/flowharmonic/backups/m5-acceptance-state.json')
SESSION = Path('/var/lib/flowharmonic/backups/m5-test-session.json')
DATABASE = Path('/var/lib/flowharmonic/flowharmonic.db')
AUTH = Path('/var/lib/flowharmonic/authentication.db')


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def private_json(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as output:
        json.dump(value, output, indent=2)


def rows(path, query):
    with sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True) as db:
        return db.execute(query).fetchall()


def api(path, body=None):
    cookie = json.loads(SESSION.read_text())['cookie']
    request = urllib.request.Request('http://127.0.0.1:8080' + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Cookie': cookie, 'Content-Type': 'application/json', 'X-FlowHarmonic-Request': '1'})
    return json.load(urllib.request.urlopen(request, timeout=15))


def ui(mode):
    return json.loads(run(str(TEST / 'node'), str(TEST / 'standalone_ui_acceptance.js'), mode))


def wait(predicate, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            result = predicate()
            if result:
                return result
        except (OSError, ValueError, StopIteration):
            pass
        time.sleep(.2)
    raise RuntimeError('Acceptance condition timed out')


def strength(samples, frequency):
    # Peak spectral amplitude across one-second windows, matching the pulse tone.
    best = 0
    for start in range(0, len(samples)-48000, 48000):
        block = samples[start:start+48000]
        c = sum(s*math.cos(2*math.pi*frequency*i/48000) for i,s in enumerate(block))
        s = sum(s*math.sin(2*math.pi*frequency*i/48000) for i,s in enumerate(block))
        best = max(best, 2*math.hypot(c,s)/len(block))
    return round(best, 3)


def record(label):
    state = json.loads(STATE.read_text())
    uid = state['uid']
    graph = json.loads(run('runuser', '-u', 'ubuntu', '--', 'env', f'XDG_RUNTIME_DIR=/run/user/{uid}', 'pw-dump'))
    sink = next(o['id'] for o in graph if o['type'].endswith(':Node') and o.get('info', {}).get('props', {}).get('media.class') == 'Audio/Sink')
    output = Path('/tmp/fh-m5-' + label + '.wav')
    with (TEST / (label + '.log')).open('wb') as log:
        process = subprocess.Popen(['runuser', '-u', 'ubuntu', '--', 'env', f'XDG_RUNTIME_DIR=/run/user/{uid}',
             'pw-record', '--target', str(sink), '--rate', '48000', '--channels', '2', '--format', 's16', str(output)], stdout=log, stderr=log)
        time.sleep(8)
        process.terminate()
        process.wait(timeout=5)
    with wave.open(str(output)) as recording:
        assert recording.getframerate() == 48000 and recording.getnchannels() == 2
        samples = array.array('h', recording.readframes(recording.getnframes()))[::2]
    assert len(samples) > 5*48000
    return {'440_amplitude': strength(samples, 440), '880_amplitude': strength(samples, 880),
            'peak': max(map(abs, samples), default=0)}


def durable_settings():
    state = json.loads(STATE.read_text())
    config = json.loads(Path('/var/lib/snapserver/server.json').read_text())
    for group in config['Groups']:
        for client in group['clients']:
            if client['id'] == state['destination']:
                return (group['stream_id'] == 'Test tone 880 Hz' and client['config']['name'] == 'M5 local speakers'
                        and client['config']['volume'] == {'percent': 37, 'muted': True})
    return False


def prepare():
    local = json.loads(Path('/etc/flowharmonic/local-audio.json').read_text())
    assert local['desktop']['uid'] == 1000 and local['desktop']['session']
    assert not STATE.exists() and not SESSION.exists(), 'Complete or clean up the previous acceptance run first'
    identity = rows(DATABASE, 'SELECT identity FROM node WHERE id=1')[0][0]
    existing_sessions = [r[0] for r in rows(AUTH, 'SELECT hash FROM session')]
    auth_row = rows(AUTH, 'SELECT salt,hash FROM password')[0]
    # Token is captured in a private pipe and file, never printed or supplied on
    # a command line. SQLite writes use the service user to preserve ownership.
    code = '''from pathlib import Path
from flowharmonic.security import Authentication
from flowharmonic.state import database
p=Path('/var/lib/flowharmonic')
a=Authentication(p)
with database(a.path) as db:
 print(a.new_session(db))
'''
    token = run('runuser', '-u', 'flowharmonic', '--', '/opt/flowharmonic/current/.venv/bin/python', '-c', code)
    private_json(SESSION, {'cookie': 'fh_session_' + identity.replace('-', '')[:12] + '=' + token})
    destination = next(d for d in api('/api/audio')['destinations'] if d['id'] == local['desktop']['destination'])
    private_json(STATE, {'identity': identity, 'uid': 1000, 'destination': destination['id'],
        'client_unit': local['desktop']['unit'], 'original_destination': destination,
        'original_name': api('/api/node')['name'], 'original_preference': rows(DATABASE, 'SELECT name FROM local_settings WHERE id=1')[0][0],
        'config_digest': hashlib.sha256(Path('/etc/flowharmonic/config.toml').read_bytes()).hexdigest(),
        'password_digest': hashlib.sha256(auth_row[0]+auth_row[1]).hexdigest(), 'original_sessions': existing_sessions})
    return {'prepared': True}


def exercise():
    results = {'source_switch_440': ui('tone440')}
    time.sleep(2)
    results['tone440'] = record('tone440')
    assert results['tone440']['440_amplitude'] > 20 and results['tone440']['880_amplitude'] < 5, results
    results['source_switch_880'] = ui('tone880')
    time.sleep(2)
    results['tone880'] = record('tone880')
    assert results['tone880']['880_amplitude'] > 20 and results['tone880']['440_amplitude'] < 5, results
    results['mute_control'] = ui('mute')
    time.sleep(2)
    results['muted'] = record('muted')
    assert results['muted']['peak'] < 5, results
    results['naming_and_diagnostics'] = ui('persist')
    wait(durable_settings, 30)
    results['audio_settings_reached_disk'] = True
    server_pid = run('systemctl', 'show', 'flowharmonic-snapserver', '-p', 'MainPID', '--value')
    results['application_recovery'] = ui('app-recovery')
    results['audio_server_kept_running_during_application_restart'] = server_pid == run('systemctl', 'show', 'flowharmonic-snapserver', '-p', 'MainPID', '--value')
    wait(durable_settings, 30)
    results['server_recovery'] = ui('server-recovery')
    results['playback_recovery'] = ui('client-recovery')
    results['local_settings_retained'] = ui('verify')
    results['no_coordinator'] = api('/api/diagnostics')['audio_endpoint'] == 'tcp://127.0.0.1:1705'
    wait(durable_settings, 30)
    results['passed'] = True
    (TEST / 'exercise-result.json').write_text(json.dumps(results, indent=2)+'\n')
    return results


def verify():
    state = json.loads(STATE.read_text())
    result = {'ui': ui('verify'), 'identity_retained': api('/api/node')['identity'] == state['identity'],
              'audio_settings_on_disk': durable_settings(),
              'configuration_retained': hashlib.sha256(Path('/etc/flowharmonic/config.toml').read_bytes()).hexdigest() == state['config_digest']}
    auth = rows(AUTH, 'SELECT salt,hash FROM password')[0]
    result['password_retained'] = hashlib.sha256(auth[0]+auth[1]).hexdigest() == state['password_digest']
    result['original_browser_sessions_retained'] = set(state['original_sessions']) <= {r[0] for r in rows(AUTH, 'SELECT hash FROM session')}
    result['diagnostics_available'] = bool(api('/api/diagnostics')['checks'])
    assert all(v for k,v in result.items() if k != 'ui'), result
    result['passed'] = True
    return result


def cleanup():
    state = json.loads(STATE.read_text())
    original = state['original_destination']
    api('/api/settings', {'name': state['original_name']})
    api('/api/destinations/'+state['destination']+'/name', {'name': original['name']})
    api('/api/destinations/'+state['destination']+'/source', {'source_id': original['source_id']})
    api('/api/destinations/'+state['destination']+'/volume', {'percent': original['volume'], 'muted': original['muted']})
    code = '''import sqlite3,sys
with sqlite3.connect('/var/lib/flowharmonic/flowharmonic.db') as db:
 db.execute('UPDATE local_settings SET name=? WHERE id=1',(None if sys.argv[1]=='null' else __import__('json').loads(sys.argv[1]),))
'''
    run('runuser','-u','flowharmonic','--','/opt/flowharmonic/current/.venv/bin/python','-c',code,json.dumps(state['original_preference']))
    api('/api/auth/sign-out', {})
    SESSION.unlink(); STATE.unlink()
    return {'original_names_and_audio_restored': True, 'test_session_revoked': True}


if __name__ == '__main__':
    assert os.geteuid() == 0 and TEST.is_dir(), 'Run only in the prepared disposable VM'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['prepare','exercise','verify','cleanup'])
    args = parser.parse_args()
    print(json.dumps(globals()[args.phase](), indent=2))
