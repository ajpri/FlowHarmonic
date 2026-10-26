"""Developer-only real Snapcast fixture. Never shipped by installLinux.sh.

No audio hardware is opened: clients use Snapcast's file player with null output.
Test tones, server state, and logs live entirely in the supplied directory.
"""
import argparse
import getpass
import warnings
import math
import os
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flowharmonic.snapcast import Snapcast


def available_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class LiveFixture:
    def __init__(self, directory, server_binary, client_binary):
        self.root = Path(directory)
        self.root.mkdir(parents=True, exist_ok=True)
        self.processes = []
        self.logs = []
        self.stop = threading.Event()
        self.ports = [available_port() for _ in range(3)]
        rpc, http, audio = self.ports
        (self.root / 'server-data').mkdir(exist_ok=True)
        config = f'''[server]
datadir = {self.root}/server-data
[http]
bind_to_address = 127.0.0.1
port = {http}
[tcp]
bind_to_address = 127.0.0.1
port = {rpc}
[stream]
bind_to_address = 127.0.0.1
port = {audio}
codec = pcm
source = pipe://{self.root}/tone-a?name=Test%20A&sampleformat=48000:16:2
source = pipe://{self.root}/tone-b?name=Test%20B&sampleformat=48000:16:2
'''
        self.config = self.root / 'snapserver.conf'
        self.config.write_text(config)
        self.rpc = Snapcast(f'tcp://127.0.0.1:{rpc}', timeout=1)
        self.http_url = f'http://127.0.0.1:{http}/jsonrpc'
        try:
            self.start([server_binary, '--config', str(self.config)], 'server')
            self.wait(lambda: len(self.rpc.snapshot()['sources']) == 2)
            for name, frequency in (('tone-a', 440), ('tone-b', 880)):
                threading.Thread(target=self.tone, args=(self.root / name, frequency), daemon=True).start()
            for index, name in enumerate(('office', 'kitchen')):
                self.start([client_binary, '--host', '127.0.0.1', '--port', str(audio),
                            '--hostID', f'fh-m2-{name}', '--instance', str(index + 1),
                            '--player', 'file:filename=null'], name)
            self.wait(lambda: len([d for d in self.rpc.snapshot()['destinations'] if d['available']]) == 2)
            for destination in self.rpc.snapshot()['destinations']:
                name = 'Office' if 'office' in destination['id'] else 'Kitchen'
                self.rpc.call('Client.SetName', id=destination['id'], name=name)
            self.wait(lambda: all(s['status'] == 'playing' for s in self.rpc.snapshot()['sources']))
        except BaseException:
            self.close()
            raise

    def start(self, command, name):
        log = (self.root / f'{name}.log').open('ab')
        self.logs.append(log)
        process = subprocess.Popen(command, stdout=log, stderr=log)
        self.processes.append(process)
        return process

    def wait(self, predicate):
        for _ in range(100):
            try:
                if predicate():
                    return
            except Exception:
                pass
            if any(process.poll() is not None for process in self.processes):
                raise RuntimeError(f'Test process stopped; inspect {self.root}/*.log')
            time.sleep(0.1)
        raise RuntimeError(f'Test fixture timed out; inspect {self.root}/*.log')

    def tone(self, path, frequency):
        frames = b''.join(struct.pack('<hh', *([int(1000 * math.sin(2 * math.pi * frequency * n / 48000))] * 2)) for n in range(4800))
        try:
            with path.open('wb', buffering=0) as output:
                while not self.stop.is_set():
                    output.write(frames)
                    self.stop.wait(0.1)
        except (OSError, BrokenPipeError):
            pass

    def close(self):
        self.stop.set()
        for process in reversed(self.processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        for log in self.logs:
            log.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', required=True)
    parser.add_argument('--client', required=True)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--web-port', type=int, default=8081)
    args = parser.parse_args()
    fixture = LiveFixture(args.directory, args.server, args.client)
    try:
        app_config = fixture.root / 'flowharmonic.toml'
        app_config.write_text(f'name="M2 test device"\nhost="127.0.0.1"\nport={args.web_port}\nsnapcast_url="{fixture.rpc.url.geturl()}"\n')
        app_data = fixture.root / 'app-state'
        from flowharmonic.security import Authentication
        app_data.mkdir(exist_ok=True)
        authentication = Authentication(app_data)
        if not authentication.configured():
            with warnings.catch_warnings():
                warnings.simplefilter('error', getpass.GetPassWarning)
                password = getpass.getpass('Test fixture password (12–128 characters): ')
                if password != getpass.getpass('Confirm test fixture password: '):
                    raise ValueError('Passwords did not match')
            authentication.set_password(password)
        env = {**os.environ, 'FLOWHARMONIC_CONFIG': str(app_config), 'FLOWHARMONIC_DATA_DIR': str(app_data)}
        app = subprocess.Popen([sys.executable, '-m', 'flowharmonic'], env=env, cwd=Path(__file__).resolve().parents[1])
        fixture.processes.append(app)
        print(f'Test dashboard: http://127.0.0.1:{args.web_port}', flush=True)
        print(f'Snapcast RPC: {fixture.rpc.url.geturl()}', flush=True)
        print(f'Snapcast HTTP: {fixture.http_url}', flush=True)
        app.wait()
    except KeyboardInterrupt:
        pass
    finally:
        fixture.close()
