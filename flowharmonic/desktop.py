"""PipeWire session capture. Only FH input links are added or removed.

PipeWire’s GStreamer source owns capture/conversion; Snapcast owns transport and synchronization.
No speaker monitors, microphones, defaults, or existing playback links are changed.
"""
import argparse
import json
import os
import signal
import subprocess
import time
from pathlib import Path

CAPTURE_NODE = 'flowharmonic.desktop.capture'
SOURCE = 'Desktop Audio'


def graph_links(objects):
    """Return desired and existing links into our stereo capture node."""
    clients = {o['id']: o.get('info', {}).get('props', {}) for o in objects if o['type'].endswith(':Client')}
    nodes = {}
    for o in objects:
        if o['type'].endswith(':Node'):
            properties = o.get('info', {}).get('props', {})
            nodes[o['id']] = {**clients.get(int(properties.get('client.id', -1)), {}), **properties}
    ports = {o['id']: o.get('info', {}).get('props', {}) for o in objects if o['type'].endswith(':Port')}
    links = [o['info'] for o in objects if o['type'].endswith(':Link') and 'info' in o]
    capture = {i for i, p in nodes.items() if p.get('node.name') == CAPTURE_NODE}
    inputs = {p.get('audio.channel'): i for i, p in ports.items()
              if int(p.get('node.id', -1)) in capture and p.get('port.direction') == 'in'}
    existing = {(int(l['output-port-id']), int(l['input-port-id'])) for l in links
                if int(l['input-node-id']) in capture}
    # Only applications already playing to a speaker sink qualify. Never tap
    # microphone/source/monitor/filter nodes, even when they carry audio.
    audible = {int(l['output-node-id']) for l in links
               if nodes.get(int(l['input-node-id']), {}).get('media.class') == 'Audio/Sink'}
    desired = set()
    for i, p in ports.items():
        node_id = int(p.get('node.id', -1))
        n = nodes.get(node_id, {})
        if node_id not in audible or n.get('media.class') != 'Stream/Output/Audio' or p.get('port.direction') != 'out':
            continue
        labels = ' '.join(str(n.get(k, '')) for k in
                          ('application.process.binary', 'application.name', 'node.name')).lower()
        if 'snapclient' in labels or 'flowharmonic' in labels:
            continue
        channel = p.get('audio.channel')
        channels = ('FL', 'FR') if channel == 'MONO' else (channel,)
        for channel in channels:
            if channel in inputs:
                desired.add((i, inputs[channel]))
    return desired, existing, bool(capture), bool(audible)


def run(*args, check=True):
    return subprocess.run(args, capture_output=True, text=True, timeout=5, check=check)


def save_status(path, available, message, **extra):
    payload = {'available': available, 'message': message, 'updated': time.time(), **extra}
    temporary = path.with_suffix('.next')
    temporary.write_text(json.dumps(payload) + '\n')
    temporary.chmod(0o644)
    temporary.replace(path)


def capture(fifo, status, snapclient=None, client_id=None, port=1704, host='127.0.0.1'):
    running = True
    recorder = player = None
    def stop(*_):
        nonlocal running
        running = False
        if recorder is None:
            raise InterruptedError('Desktop capture was stopped.')
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    status.parent.mkdir(parents=True, exist_ok=True)
    save_status(status, False, 'Desktop audio is starting.')
    try:
        # A blocking writer rendezvous avoids an EOF/retry race with older
        # Snapserver pipe readers. systemd terminates this wait on logout.
        fd = os.open(fifo, os.O_WRONLY | os.O_NOFOLLOW)
        try:
            recorder = subprocess.Popen([
                'gst-launch-1.0', '-q', 'pipewiresrc', 'always-copy=true',
                'client-name=FlowHarmonic desktop capture',
                'stream-properties=props,node.name=(string)' + CAPTURE_NODE +
                ',node.autoconnect=(string)false,node.always-process=(string)true,node.want-driver=(string)true',
                '!', 'audio/x-raw,format=S16LE,rate=48000,channels=2',
                '!', 'fdsink', 'fd=1', 'sync=false'], stdout=fd)
        finally:
            os.close(fd)
        last_written = -1
        last_progress = time.monotonic()
        # The desktop server retains hardware access. Use its existing mixer,
        # rather than opening an ALSA hardware device alongside the desktop.
        while running:
            if recorder.poll() is not None:
                raise RuntimeError('The desktop capture process stopped. Capture will retry automatically.')
            counters = dict(line.split(':', 1) for line in Path(f'/proc/{recorder.pid}/io').read_text().splitlines())
            written = int(counters['wchar'])
            if written != last_written:
                last_written, last_progress = written, time.monotonic()
            objects = json.loads(run('pw-dump').stdout)
            desired, existing, ready, _ = graph_links(objects)
            # An idle graph need not deliver PCM. A stalled active application
            # (or stopped capture process) must recover without manual action.
            if time.monotonic() - last_progress > 5:
                state = Path(f'/proc/{recorder.pid}/status').read_text()
                stopped = any(line.startswith('State:') and line.split()[1] in ('T', 't') for line in state.splitlines())
                if desired or stopped:
                    raise RuntimeError('Desktop capture stopped delivering audio. Capture will retry automatically.')
                last_progress = time.monotonic()
            # Delete only links ending at our own capture node.
            for output, input_ in existing - desired:
                run('pw-link', '-d', str(output), str(input_), check=False)
            for output, input_ in desired - existing:
                run('pw-link', str(output), str(input_), check=False)
            pulse = Path(os.environ['XDG_RUNTIME_DIR']) / 'pulse/native'
            if snapclient and pulse.exists() and (player is None or player.poll() is not None):
                player = subprocess.Popen([snapclient, '--host', host, '--port', str(port),
                                           '--hostID', client_id, '--player', 'pulse', '--mixer', 'software'],
                                          env={**os.environ, 'PULSE_SERVER': 'unix:' + str(pulse)})
            player_ready = player is not None and player.poll() is None
            message = ('Desktop audio is ready.' if desired else 'Desktop audio is ready. Play audio in a desktop application.') if ready else 'Waiting for the desktop audio connection.'
            if not ready:
                message = 'Desktop audio is starting. Capture will retry automatically if it cannot connect.'
            save_status(status, ready, message, playback=player_ready,
                        playback_message='' if player_ready else 'Desktop playback needs the desktop’s PulseAudio compatibility service.')
            time.sleep(1)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, RuntimeError) as error:
        print(str(error), flush=True)
        message = str(error) if isinstance(error, RuntimeError) else 'Desktop audio is unavailable. Check that PipeWire is running in your desktop session; capture will retry automatically.'
        save_status(status, False, message)
        return 1
    finally:
        for child in (recorder, player):
            if child is not None and child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
        if not running:
            save_status(status, False, 'The desktop session ended. Capture will resume after a local desktop login.')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fifo', type=Path, required=True)
    parser.add_argument('--status', type=Path, required=True)
    parser.add_argument('--snapclient')
    parser.add_argument('--client-id')
    parser.add_argument('--port', type=int, default=1704)
    parser.add_argument('--host',default='127.0.0.1')
    args = parser.parse_args()
    raise SystemExit(capture(args.fifo, args.status, args.snapclient, args.client_id, args.port,args.host))


if __name__ == '__main__':
    main()
