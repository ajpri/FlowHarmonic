import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from flowharmonic.app import create_app
from flowharmonic.config import load_config
from flowharmonic.state import initialize
import importlib.util
spec = importlib.util.spec_from_file_location("install_state", Path(__file__).resolve().parents[1] / "scripts/install-state.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config = self.root / 'config.toml'
        self.config.write_text('name = "Office"\nhost = "127.0.0.1"\nport = 8080\n')
        self.environment = patch.dict(os.environ, {
            'FLOWHARMONIC_CONFIG': str(self.config),
            'FLOWHARMONIC_DATA_DIR': str(self.root / 'state'),
        })
        self.environment.start()
        self.discovery = patch('flowharmonic.app.Discovery.start')
        self.discovery.start()

    def tearDown(self):
        self.discovery.stop()
        self.environment.stop()
        self.temporary.cleanup()

    def test_node_name_persists_without_modifying_root_configuration(self):
        before = self.config.read_bytes()
        with TestClient(create_app()) as client:
            self.assertEqual(client.get('/api/settings').status_code, 401)
            self.assertEqual(client.get('/api/diagnostics').status_code, 401)
            self.sign_in(client)
            self.assertEqual(client.post('/api/settings', json={'name': 'Kitchen'}).status_code, 403)
            headers = {'X-FlowHarmonic-Request': '1'}
            for name in (' ', '\n', 'x'*81, 123):
                self.assertEqual(client.post('/api/settings', json={'name': name}, headers=headers).status_code, 422)
            self.assertEqual(client.post('/api/settings', json={'name': ' Kitchen '}, headers=headers).json(), {'name': 'Kitchen'})
            original_id = client.get('/api/node').json()['identity']
            cookies = dict(client.cookies)
        with TestClient(create_app()) as client:
            client.cookies.update(cookies)
            self.assertEqual(client.get('/api/node').json()['name'], 'Kitchen')
            self.assertEqual(client.get('/api/node').json()['identity'], original_id)
        self.assertEqual(self.config.read_bytes(), before)

    def test_diagnostics_remain_accessible_during_audio_failure(self):
        from flowharmonic.snapcast import AudioError
        with TestClient(create_app()) as client:
            self.sign_in(client)
            with patch.object(client.app.state.audio, 'snapshot', side_effect=AudioError('Cannot reach the audio server.')), \
                 patch('flowharmonic.diagnostics.service_status', return_value=[]):
                response = client.get('/api/diagnostics')
            self.assertEqual(response.status_code, 200)
            self.assertTrue(any(c['name'] == 'Audio connection' and c['state'] == 'unavailable' for c in response.json()['checks']))
            self.assertNotIn('password', response.text)
            self.assertNotIn('session', response.json()['node'])

    def test_additive_settings_keep_older_identity_readers_compatible(self):
        from flowharmonic.state import identity, node_name, set_node_name
        path = initialize(self.root / 'state')
        before = identity(path)
        set_node_name(path, 'Independent node')
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT identity FROM node WHERE id=1').fetchone()[0], before)
        self.assertEqual(node_name(initialize(self.root / 'state'), 'Fallback'), 'Independent node')
        with sqlite3.connect(path) as db:
            db.execute('UPDATE local_settings SET version=999')
        with self.assertRaisesRegex(RuntimeError, 'newer'):
            initialize(self.root / 'state')

    def test_unavailable_desktop_source_cannot_be_routed(self):
        with TestClient(create_app()) as client:
            self.sign_in(client)
            inventory = {'sources': [{'id': 'Desktop Audio', 'name': 'Desktop Audio',
                         'status': 'disabled', 'message': 'Log in to a local PipeWire desktop.'}], 'destinations': []}
            with patch.object(client.app.state.audio, 'snapshot', return_value=inventory), patch.object(client.app.state.audio, 'change') as change:
                response = client.post('/api/destinations/desk/source', json={'source_id': 'Desktop Audio'},
                                       headers={'X-FlowHarmonic-Request': '1'})
                self.assertEqual(response.status_code, 409)
                self.assertIn('Log in', response.json()['detail'])
                change.assert_not_called()

    def test_dashboard_and_api(self):
        with TestClient(create_app()) as client:
            health = client.get('/health')
            self.assertEqual(health.status_code, 200)
            self.assertEqual(health.json()['status'], 'ok')
            self.assertEqual(health.json()['version'], 'M6')
            self.assertEqual(client.get('/', follow_redirects=False).headers['location'], '/sign-in')
            self.assertEqual(client.get('/api/node').status_code, 401)
            self.sign_in(client)
            self.assertEqual(client.get('/sign-in', follow_redirects=False).headers['location'], '/')
            self.assertEqual(client.get('/api/node').json()['name'], 'Office')
            with patch.object(client.app.state.audio, 'snapshot', return_value={'sources': [], 'destinations': []}):
                self.assertEqual(client.get('/api/sources').json(), {'sources': []})
                self.assertEqual(client.get('/api/destinations').json(), {'destinations': []})
            self.assertIn('Sources', client.get('/').text)
            self.assertIn('Destinations', client.get('/').text)
            for asset in ('app.js', 'style.css'):
                self.assertEqual(client.get('/static/' + asset).status_code, 200)
            self.assertIn("frame-ancestors 'none'", health.headers['content-security-policy'])
            self.assertEqual(client.post('/api/node', json={'name': 'Changed'}).status_code, 405)

    def test_restart_preserves_identity_and_configuration(self):
        original = self.config.read_bytes()
        with TestClient(create_app()) as client:
            self.sign_in(client)
            first = client.get('/api/node').json()
            cookies = dict(client.cookies)
        with TestClient(create_app()) as client:
            client.cookies.update(cookies)
            self.assertEqual(client.get('/api/node').json(), first)
        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual((self.root / 'state/flowharmonic.db').stat().st_mode & 0o777, 0o640)

    def test_concurrent_initialization_keeps_one_identity(self):
        from concurrent.futures import ThreadPoolExecutor
        from flowharmonic.state import identity
        with ThreadPoolExecutor(max_workers=8) as pool:
            paths = list(pool.map(lambda _: initialize(self.root / 'state'), range(8)))
        self.assertEqual(len({identity(path) for path in paths}), 1)

    def test_health_reports_database_failure(self):
        with TestClient(create_app()) as client:
            with sqlite3.connect(self.root / 'state/flowharmonic.db') as db:
                db.execute('DROP TABLE node')
            self.assertEqual(client.get('/health').status_code, 503)

    def test_future_database_refused_without_changes(self):
        path = initialize(self.root / 'state')
        with sqlite3.connect(path) as db:
            db.execute('PRAGMA user_version = 2')
        before = path.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'newer'):
            initialize(self.root / 'state')
        self.assertEqual(path.read_bytes(), before)
        with self.assertRaisesRegex(RuntimeError, 'Unsupported'):
            installer.backup(str(path), str(self.root / 'backup.db'))

    def test_missing_identity_not_silently_regenerated(self):
        path = initialize(self.root / 'state')
        with sqlite3.connect(path) as db:
            db.execute('DELETE FROM node')
        with self.assertRaisesRegex(RuntimeError, 'missing'):
            initialize(self.root / 'state')

    def test_unknown_database_not_overwritten(self):
        directory = self.root / 'state'
        directory.mkdir()
        with sqlite3.connect(directory / 'flowharmonic.db') as db:
            db.execute('CREATE TABLE important (value TEXT)')
        with self.assertRaisesRegex(RuntimeError, 'Unrecognized'):
            initialize(directory)

    def test_consistent_backup(self):
        path = initialize(self.root / 'state')
        destination = self.root / 'backup.db'
        installer.backup(str(path), str(destination))
        with sqlite3.connect(destination) as db:
            self.assertEqual(db.execute('PRAGMA quick_check').fetchone()[0], 'ok')
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 1)
        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)

    def test_ownership_ledger_survives_reinstall(self):
        path = self.root / 'infrastructure.json'
        installer.record_ownership(path, 'existing', 'flowharmonic')
        original = path.read_bytes()
        installer.record_ownership(path, 'flowharmonic', 'existing')
        self.assertEqual(path.read_bytes(), original)

    def test_invalid_configuration_refused(self):
        for content in ('port = 0', 'port = true', 'name = ""', 'unknown = 1', 'snapcast_url = "file:///etc/passwd"', 'snapcast_url = "tcp://host:0"', 'snapcast_url = "http://user:secret@host/jsonrpc"'):
            self.config.write_text(content)
            with self.assertRaises(ValueError):
                load_config()

    def sign_in(self, client, password='a long test passphrase'):
        if not client.app.state.authentication.configured():
            client.app.state.authentication.set_password(password)
        return client.post('/api/auth/sign-in', json={'password': password},
                           headers={'X-FlowHarmonic-Request': '1'})

    def test_password_setup_and_remembered_sign_in(self):
        with TestClient(create_app()) as client:
            self.assertEqual(client.get('/api/auth').json(), {'configured': False, 'authenticated': False})
            key = 'an obsolete test key that grants no access'
            self.assertNotIn(key, client.get('/').text)
            self.assertNotIn(key, client.get('/api/auth').text)
            self.assertEqual(client.post('/api/auth/setup', json={'password': 'a long test passphrase', 'secret': key}).status_code, 404)
            response = self.sign_in(client)
            self.assertEqual(response.status_code, 200, response.text)
            cookie_header = response.headers['set-cookie']
            for attribute in ('HttpOnly', 'SameSite=strict', 'Max-Age=', 'Path=/'):
                self.assertIn(attribute, cookie_header)
            cookies = dict(client.cookies)
            self.assertEqual(client.get('/api/auth').json(), {'configured': True, 'authenticated': True})
            self.assertFalse((self.root / 'state/control.key').exists())
            self.assertEqual((self.root / 'state/authentication.db').stat().st_mode & 0o777, 0o600)
            self.assertNotIn(b'a long test passphrase', (self.root / 'state/authentication.db').read_bytes())
        # New app process and new tab/browser context carrying the remembered cookie.
        with TestClient(create_app()) as client:
            client.cookies.update(cookies)
            self.assertTrue(client.get('/api/auth').json()['authenticated'])
            with patch.object(client.app.state.audio, 'change', return_value={'sources': [], 'destinations': []}) as change:
                response = client.post('/api/destinations/test/volume', json={'muted': True}, headers={'X-FlowHarmonic-Request': '1'})
                self.assertEqual(response.status_code, 200)
                change.assert_called_once_with('test', percent=None, muted=True)

    def test_sign_out_revokes_only_that_browser(self):
        headers = {'X-FlowHarmonic-Request': '1'}
        with TestClient(create_app()) as client:
            self.assertEqual(self.sign_in(client).status_code, 200)
            first = dict(client.cookies)
            client.cookies.clear()
            response = client.post('/api/auth/sign-in', json={'password': 'a long test passphrase'}, headers=headers)
            self.assertEqual(response.status_code, 200)
            second = dict(client.cookies)
            self.assertNotEqual(first, second)
            client.cookies.clear()
            client.cookies.update(first)
            self.assertEqual(client.post('/api/auth/sign-out', json={}, headers=headers).status_code, 200)
            # A copied cookie is invalid server-side, not merely deleted in the UI.
            client.cookies.clear()
            client.cookies.update(first)
            self.assertFalse(client.get('/api/auth').json()['authenticated'])
            client.cookies.clear()
            client.cookies.update(second)
            self.assertTrue(client.get('/api/auth').json()['authenticated'])

    def test_sign_in_validation_and_request_protection(self):
        headers = {'X-FlowHarmonic-Request': '1'}
        with TestClient(create_app()) as client:
            self.assertEqual(self.sign_in(client).status_code, 200)
            key = 'an obsolete test key that grants no access'
            with patch.object(client.app.state.audio, 'change', return_value={'sources': [], 'destinations': []}) as change:
                for payload in ({'percent': -1}, {'percent': 101}, {'percent': True}, {'percent': '2'}, {'muted': 'false'}, {}, {'percent': 3, 'unknown': 1}):
                    self.assertEqual(client.post('/api/destinations/test/volume', json=payload, headers=headers).status_code, 422)
                self.assertEqual(client.post('/api/destinations/test/volume', json={'muted': True}).status_code, 403)
                self.assertEqual(client.post('/api/destinations/test/volume', json={'muted': True}, headers={**headers, 'Origin': 'http://elsewhere'}).status_code, 403)
                change.assert_not_called()
                self.assertEqual(client.post('/api/destinations/has%2Fslash/volume', json={'percent': 20}, headers={**headers, 'Origin': 'http://testserver'}).status_code, 200)
                change.assert_called_once_with('has/slash', percent=20, muted=None)
            client.cookies.clear()
            self.assertEqual(client.post('/api/destinations/test/volume', json={'muted': True}, headers={'Authorization': f'Bearer {key}'}).status_code, 401)
            self.assertEqual(client.post('/api/auth/sign-in', json={'password': 'wrong password'}, headers=headers).status_code, 401)
            self.assertEqual(client.post('/api/auth/sign-in', json={'password': 'a'*129}, headers=headers).status_code, 422)
            self.assertEqual(client.post('/api/auth/sign-in', json={'password': 'a long test passphrase'}, headers={**headers, 'Origin': 'https://testserver'}).status_code, 403)

    def test_https_cookie_and_expired_session(self):
        from flowharmonic.security import COOKIE_AGE
        import time
        with TestClient(create_app(), base_url='https://testserver') as client:
            response = self.sign_in(client)
            self.assertIn('Secure', response.headers['set-cookie'])
            self.assertTrue(client.get('/api/auth').json()['authenticated'])
            with patch('flowharmonic.security.time.time', return_value=time.time() + COOKIE_AGE + 1):
                self.assertFalse(client.get('/api/auth').json()['authenticated'])

    def test_audio_outage_does_not_break_dashboard_or_health(self):
        from flowharmonic.snapcast import AudioError
        with TestClient(create_app()) as client:
            self.sign_in(client)
            with patch.object(client.app.state.audio, 'snapshot', side_effect=AudioError('Cannot reach the audio server.')):
                self.assertEqual(client.get('/api/audio').status_code, 503)
                self.assertIn('Cannot reach', client.get('/api/audio').json()['detail'])
                self.assertEqual(client.get('/health').status_code, 200)
                self.assertEqual(client.get('/').status_code, 200)

    def test_cli_version(self):
        output = subprocess.check_output([sys.executable, '-m', 'flowharmonic', '--version'], text=True)
        self.assertEqual(output.strip(), 'FlowHarmonic M6')

    def test_command_line_password_change_revokes_all_browsers(self):
        with TestClient(create_app()) as client:
            self.sign_in(client)
            client.app.state.authentication.set_password('a replacement test passphrase')
            self.assertFalse(client.get('/api/auth').json()['authenticated'])
            self.assertEqual(client.get('/api/audio').status_code, 401)
            self.assertEqual(client.get('/', follow_redirects=False).headers['location'], '/sign-in')
            self.assertEqual(client.post('/api/auth/sign-in', json={'password': 'a long test passphrase'}, headers={'X-FlowHarmonic-Request': '1'}).status_code, 401)
            self.assertEqual(self.sign_in(client, 'a replacement test passphrase').status_code, 200)

    def test_legacy_api_cookie_is_upgraded_for_dashboard_requests(self):
        with TestClient(create_app()) as client:
            self.sign_in(client)
            name = client.app.state.cookie_name
            token = client.cookies.get(name)
            client.cookies.clear()
            client.cookies.set(name, token, path='/api')
            self.assertEqual(client.get('/', follow_redirects=False).headers['location'], '/sign-in')
            self.assertTrue(client.get('/api/auth').json()['authenticated'])
            self.assertEqual(client.get('/', follow_redirects=False).status_code, 200)


if __name__ == '__main__':
    unittest.main()
