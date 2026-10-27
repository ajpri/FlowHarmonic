"""Opt-in real-server acceptance checks; set SNAPSERVER_BINARY and SNAPCLIENT_BINARY."""
import os
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote
from unittest.mock import patch

from fastapi.testclient import TestClient
from flowharmonic.app import create_app
from flowharmonic.snapcast import Snapcast
from live_fixture import LiveFixture


@unittest.skipUnless(os.environ.get('SNAPSERVER_BINARY') and os.environ.get('SNAPCLIENT_BINARY'),
                     'Set SNAPSERVER_BINARY and SNAPCLIENT_BINARY for real Snapcast tests')
class RealSnapcastTests(unittest.TestCase):
    def test_real_control_compatibility_and_restart(self):
        with tempfile.TemporaryDirectory(prefix='fh-m2-real-') as directory:
            root = Path(directory)
            fixture = LiveFixture(root, os.environ['SNAPSERVER_BINARY'], os.environ['SNAPCLIENT_BINARY'])
            try:
                original_config = fixture.config.read_bytes()
                initial = fixture.rpc.snapshot()
                office = next(d['id'] for d in initial['destinations'] if d['name'] == 'Office')
                kitchen = next(d['id'] for d in initial['destinations'] if d['name'] == 'Kitchen')
                office_path = quote(office, safe='')
                kitchen_path = quote(kitchen, safe='')
                config = root / 'app.toml'
                for url in (fixture.rpc.url.geturl(), fixture.http_url):
                    # Existing user-managed topology, deliberately grouped.
                    group, _ = fixture.rpc.find(fixture.rpc.status(), office)
                    fixture.rpc.call('Group.SetClients', id=group['id'], clients=[office, kitchen])
                    fixture.rpc.call('Group.SetStream', id=group['id'], stream_id='Test A')
                    fixture.rpc.call('Group.SetMute', id=group['id'], mute=False)
                    for identifier in (office, kitchen):
                        fixture.rpc.call('Client.SetVolume', id=identifier, volume={'percent': 70, 'muted': False})
                    config.write_text(f'name="Existing system"\nhost="127.0.0.1"\nport=8080\nsnapcast_url="{url}"\n')
                    with patch.dict(os.environ, {'FLOWHARMONIC_CONFIG': str(config), 'FLOWHARMONIC_DATA_DIR': str(root / 'state')}):
                        with TestClient(create_app()) as app:
                            if not app.app.state.authentication.configured():
                                app.app.state.authentication.set_password('real Snapcast test passphrase')
                            headers = {'X-FlowHarmonic-Request': '1'}
                            self.assertEqual(app.post('/api/auth/sign-in', json={'password': 'real Snapcast test passphrase'}, headers=headers).status_code, 200)
                            headers = {'X-FlowHarmonic-Request': '1'}
                            identity = app.get('/api/node').json()['identity']
                            before = app.get('/api/audio').json()
                            self.assertEqual({s['name'] for s in before['sources']}, {'Test A', 'Test B'})
                            self.assertTrue(all(d['available'] for d in before['destinations']))
                            for source in ('Test B', 'Test A', 'Test B'):
                                response = app.post(f'/api/destinations/{office_path}/source', json={'source_id': source}, headers=headers)
                                self.assertEqual(response.status_code, 200, response.text)
                                observed = {d['id']: d for d in response.json()['destinations']}
                                self.assertEqual(observed[office]['source_id'], source)
                                self.assertEqual(observed[kitchen]['source_id'], 'Test A')
                            response = app.post(f'/api/destinations/{office_path}/volume', json={'percent': 31, 'muted': True}, headers=headers)
                            self.assertEqual(response.status_code, 200, response.text)
                            observed = {d['id']: d for d in response.json()['destinations']}
                            self.assertEqual(observed[office]['volume'], 31)
                            self.assertTrue(observed[office]['muted'])
                            self.assertEqual(observed[kitchen]['volume'], 70)
                            self.assertFalse(observed[kitchen]['muted'])
                            # Regroup and mute externally, then unmute only Office.
                            group, _ = fixture.rpc.find(fixture.rpc.status(), office)
                            fixture.rpc.call('Group.SetClients', id=group['id'], clients=[office, kitchen])
                            fixture.rpc.call('Group.SetMute', id=group['id'], mute=True)
                            response = app.post(f'/api/destinations/{office_path}/volume', json={'muted': False}, headers=headers)
                            self.assertEqual(response.status_code, 200, response.text)
                            observed = {d['id']: d for d in response.json()['destinations']}
                            self.assertFalse(observed[office]['muted'])
                            self.assertTrue(observed[kitchen]['muted'])
                        # FH shuts down without stopping/reconfiguring independent infrastructure.
                        self.assertTrue(all(process.poll() is None for process in fixture.processes))
                        self.assertEqual(fixture.config.read_bytes(), original_config)
                        fixture.rpc.call('Client.SetVolume', id=office, volume={'percent': 42, 'muted': False})
                        self.assertEqual(next(d for d in fixture.rpc.snapshot()['destinations'] if d['id'] == office)['volume'], 42)
                        # M9 restores the assignment explicitly saved through FH
                        # when it restarts; the independent server stayed usable.
                        with TestClient(create_app()) as app:
                            if not app.app.state.authentication.configured():
                                app.app.state.authentication.set_password('real Snapcast test passphrase')
                            headers = {'X-FlowHarmonic-Request': '1'}
                            self.assertEqual(app.post('/api/auth/sign-in', json={'password': 'real Snapcast test passphrase'}, headers=headers).status_code, 200)
                            self.assertEqual(app.get('/api/node').json()['identity'], identity)
                            self.assertEqual(next(d for d in app.get('/api/audio').json()['destinations'] if d['id'] == office)['volume'], 31)
                # A disconnected destination remains visible and cannot be changed.
                fixture.processes[2].terminate()
                fixture.processes[2].wait(timeout=5)
                with patch.dict(os.environ, {'FLOWHARMONIC_CONFIG': str(config), 'FLOWHARMONIC_DATA_DIR': str(root / 'state')}):
                    with TestClient(create_app()) as app:
                        if not app.app.state.authentication.configured():
                            app.app.state.authentication.set_password('real Snapcast test passphrase')
                        headers = {'X-FlowHarmonic-Request': '1'}
                        self.assertEqual(app.post('/api/auth/sign-in', json={'password': 'real Snapcast test passphrase'}, headers=headers).status_code, 200)
                        import time
                        for _ in range(30):
                            observed = app.get('/api/audio').json()['destinations']
                            if not next(d for d in observed if d['id'] == kitchen)['available']:
                                break
                            time.sleep(0.1)
                        self.assertFalse(next(d for d in observed if d['id'] == kitchen)['available'])
                        self.assertTrue(next(d for d in observed if d['id'] == office)['available'])
                        self.assertEqual(app.post('/api/auth/sign-in', json={'password': 'real Snapcast test passphrase'}, headers=headers).status_code, 200)
                        response = app.post(f'/api/destinations/{kitchen_path}/volume', json={'percent': 10}, headers=headers)
                        self.assertEqual(response.status_code, 409)
                        self.assertIn('offline', response.json()['detail'])
                # Connection outage leaves the FH dashboard and health endpoint available.
                fixture.processes[0].terminate()
                fixture.processes[0].wait(timeout=5)
                with patch.dict(os.environ, {'FLOWHARMONIC_CONFIG': str(config), 'FLOWHARMONIC_DATA_DIR': str(root / 'state')}):
                    with TestClient(create_app()) as app:
                        if not app.app.state.authentication.configured():
                            app.app.state.authentication.set_password('real Snapcast test passphrase')
                        headers = {'X-FlowHarmonic-Request': '1'}
                        self.assertEqual(app.post('/api/auth/sign-in', json={'password': 'real Snapcast test passphrase'}, headers=headers).status_code, 200)
                        response = app.get('/api/audio')
                        self.assertEqual(response.status_code, 200)
                        self.assertFalse(response.json()['audio_available'])
                        self.assertIn('Cannot reach', response.json()['local_message'])
                        self.assertEqual(app.get('/health').status_code, 200)
                        self.assertEqual(app.get('/').status_code, 200)
            finally:
                fixture.close()


if __name__ == '__main__':
    unittest.main()
