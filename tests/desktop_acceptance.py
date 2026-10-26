"""Opt-in installed-VM audio measurement; run as the active desktop user.

Uses a separate HTTP app/credential store and a file-output destination. It does
not change the installed password. Requires an FH-owned local server, active
PipeWire desktop, and installed M4 application. Test audio is gentle (660 Hz).
"""
import array
import http.cookiejar
import json
import math
import os
import sqlite3
import struct
import subprocess
import sys
import time
import urllib.request
import wave
from pathlib import Path

from flowharmonic.security import Authentication
from flowharmonic.state import initialize
from flowharmonic.snapcast import Snapcast, AudioError

ROOT = Path('/tmp/fh-m4-acceptance')
ROOT.mkdir(exist_ok=True)
STATE = ROOT / 'state'
for _ in range(100):
    metadata = json.loads(Path('/etc/flowharmonic/local-audio.json').read_text())
    if metadata.get('desktop', {}).get('destination'):
        break
    time.sleep(.2)
else:
    raise RuntimeError('No provisioned desktop session')
db = initialize(STATE)
with sqlite3.connect(db) as connection:
    connection.execute('UPDATE node SET identity=? WHERE id=1', (metadata['owner'],))
Authentication(STATE).set_password('isolated M4 acceptance password')
base = 'http://127.0.0.1:18081'
browser = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
processes = []
logs = []
result = {}


def launch(args, name, **kwargs):
    output = (ROOT / (name + '.log')).open('wb')
    logs.append(output)
    process = subprocess.Popen(args, stdout=output, stderr=output, **kwargs)
    processes.append(process)
    return process


def api(path, body=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(base + path, data=data,
        headers={'Content-Type': 'application/json', 'X-FlowHarmonic-Request': '1'})
    return json.load(browser.open(request, timeout=5))


def wait(predicate):
    for _ in range(150):
        try:
            value = predicate()
            if value:
                return value
        except (OSError, ValueError, StopIteration):
            pass
        time.sleep(.2)
    raise RuntimeError('Timed out waiting for desktop acceptance state')


def graph():
    return json.loads(subprocess.check_output(['pw-dump']))


def defaults(objects):
    return [m for o in objects if o['type'].endswith(':Metadata')
            for m in o.get('metadata', []) if m.get('key') in ('default.audio.sink', 'default.configured.audio.sink')]


def amplitude(raw, frequency):
    samples = array.array('h', raw[:len(raw)//4*4])
    # Last two seconds, left channel. Keep analysis standard-library only.
    samples = samples[-192000::2]
    if not samples:
        raise RuntimeError('No captured samples')
    c = sum(s * math.cos(2*math.pi*frequency*i/48000) for i,s in enumerate(samples))
    s = sum(s * math.sin(2*math.pi*frequency*i/48000) for i,s in enumerate(samples))
    return round(2*math.hypot(c,s)/len(samples), 3)


try:
    env = {**os.environ, 'FLOWHARMONIC_DATA_DIR': str(STATE), 'FLOWHARMONIC_CONFIG': '/etc/flowharmonic/config.toml'}
    launch([sys.executable, '-m', 'uvicorn', 'flowharmonic.app:app', '--host', '127.0.0.1', '--port', '18081'], 'http', env=env)
    wait(lambda: api('/health')['version'] == 'M4')
    api('/api/auth/sign-in', {'password': 'isolated M4 acceptance password'})
    def ready_inventory():
        a = api('/api/audio')
        return a if any(s['id'] == 'Desktop Audio' and s['status'] != 'disabled' for s in a['sources']) else None
    inventory = wait(ready_inventory)
    result['desktop_source_available'] = True
    before = graph()
    result['default_before'] = defaults(before)
    desktop_id = metadata['desktop']['destination']
    # Keep physical PC silent while the automated VM measurement runs.
    if any(d['id'] == 'fh-listening-test-pc' and d['available'] for d in inventory['destinations']):
        api('/api/destinations/fh-listening-test-pc/source', {'source_id': 'Silence'})
    api('/api/destinations/' + desktop_id + '/source', {'source_id': 'Test tone 880 Hz'})
    api('/api/destinations/' + desktop_id + '/volume', {'percent': 100, 'muted': False})
    measured = ROOT / 'received.pcm'
    launch(['/usr/bin/snapclient', '--host', '127.0.0.1', '--hostID', 'fh-m4-measurement',
            '--player', 'file:filename=' + str(measured), '--mixer', 'software'], 'receiver')
    wait(lambda: any(d['id'] == 'fh-m4-measurement' and d['available'] for d in api('/api/audio')['destinations']))
    api('/api/destinations/fh-m4-measurement/volume', {'percent': 100, 'muted': False})
    routed = api('/api/destinations/fh-m4-measurement/source', {'source_id': 'Desktop Audio'})
    result['web_api_route_confirmed'] = any(d['id'] == 'fh-m4-measurement' and d['source_id'] == 'Desktop Audio' for d in routed['destinations'])
    wav = ROOT / 'desktop-660.wav'
    with wave.open(str(wav), 'wb') as output:
        output.setparams((2, 2, 48000, 0, 'NONE', 'not compressed'))
        chunk = b''.join(struct.pack('<hh', *([int(1000*math.sin(2*math.pi*660*n/48000))]*2)) for n in range(48000))
        for _ in range(24):
            output.writeframes(chunk)
    playback = launch(['pw-play', str(wav)], 'desktop-app')
    time.sleep(4)
    during = graph()
    nodes = {o['id']: o.get('info', {}).get('props', {}) for o in during if o['type'].endswith(':Node')}
    links = [o['info'] for o in during if o['type'].endswith(':Link')]
    (ROOT / 'during-graph.json').write_text(json.dumps(during, indent=2))
    capture_nodes = {i for i,p in nodes.items() if p.get('node.name') == 'flowharmonic.desktop.capture'}
    app_nodes = {i for i,p in nodes.items() if p.get('media.filename') == str(wav)}
    snap_nodes = {i for i,p in nodes.items() if p.get('application.process.binary') == 'snapclient'}
    result['normal_speaker_links'] = sum(l['output-node-id'] in app_nodes and nodes.get(l['input-node-id'], {}).get('media.class') == 'Audio/Sink' for l in links)
    result['capture_app_links'] = sum(l['output-node-id'] in app_nodes and l['input-node-id'] in capture_nodes for l in links)
    result['capture_snapclient_links'] = sum(l['output-node-id'] in snap_nodes and l['input-node-id'] in capture_nodes for l in links)
    result['capture_microphone_links'] = sum(nodes.get(l['output-node-id'], {}).get('media.class') == 'Audio/Source' and l['input-node-id'] in capture_nodes for l in links)
    # A test-only monitor recording independently proves the desktop still plays.
    sink = next(i for i,p in nodes.items() if p.get('media.class') == 'Audio/Sink')
    monitor = ROOT / 'local-speakers.wav'
    recording = launch(['pw-record', '--target', str(sink), '--rate', '48000', '--channels', '2', '--format', 's16', str(monitor)], 'local-monitor')
    time.sleep(7)
    result['received_660_amplitude'] = amplitude(measured.read_bytes(), 660)
    result['received_880_amplitude'] = amplitude(measured.read_bytes(), 880)
    recording.terminate(); recording.wait(timeout=5)
    with wave.open(str(monitor)) as recording_file:
        local = recording_file.readframes(recording_file.getnframes())
    result['local_speaker_660_amplitude'] = amplitude(local, 660)
    playback.terminate(); playback.wait(timeout=5)
    offset = measured.stat().st_size
    time.sleep(7)
    result['fh_only_capture_peak'] = max(map(abs, array.array('h', measured.read_bytes()[offset+48000*4:])), default=0)
    result['default_after'] = defaults(graph())
    result['default_unchanged'] = result['default_before'] == result['default_after']
    assert result['normal_speaker_links'] >= 2, result
    assert result['capture_app_links'] >= 2, result
    assert result['capture_snapclient_links'] == result['capture_microphone_links'] == 0, result
    assert result['received_660_amplitude'] > 500, result
    assert result['local_speaker_660_amplitude'] > 50, result
    assert result['received_880_amplitude'] < 5, result
    assert result['fh_only_capture_peak'] < 5, result
    assert result['default_unchanged'], result
    result['passed'] = True
finally:
    try:
        api('/api/destinations/' + metadata['desktop']['destination'] + '/source', {'source_id': 'Silence'})
        api('/api/auth/sign-out', {})
    except Exception:
        pass
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
    for log in logs:
        log.close()
    try:
        Snapcast('tcp://127.0.0.1:1705').call('Server.DeleteClient', id='fh-m4-measurement')
    except AudioError:
        pass
    (ROOT / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
