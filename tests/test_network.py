"""Real signing, persistence, two-sided approval and hostile enrollment messages."""
import copy
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from flowharmonic.app import create_app
from flowharmonic.network import Membership, NetworkError, code, endpoint, exchange
from flowharmonic.state import identity, initialize


class MembershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.nodes = []
        self.urls = {}
        for name in ('Office', 'Living Room', 'Stranger'):
            directory = self.root / name
            path = initialize(directory)
            node = Membership(directory, {'name': name}, path)
            self.nodes.append(node)
            self.urls['http://' + name.replace(' ', '').lower()] = node
        self.host, self.member, self.stranger = self.nodes
        self.url = 'http://office'
        self.transport = patch('flowharmonic.network.exchange', side_effect=self.exchange)
        self.transport.start()
        self.addCleanup(self.transport.stop)

    def exchange(self, url, path, body=None):
        node = self.urls[url]
        return node.info() if path == '/peer/info' else node.receive(body)

    def request(self):
        self.host.create('House')
        self.host.allow(True)
        return self.member.request_join(self.url)['pending'][0]['id']

    def joined(self):
        request_id = self.request()
        self.host.approve(request_id, True)
        self.member.sync(confirm=True)
        return request_id

    def test_two_sided_approval_keys_and_membership_survive_restart(self):
        original_identity = self.member.node_id
        request_id = self.request()
        self.assertIsNone(self.member.view()['membership'])
        self.assertEqual(self.host.view()['peers'], [])
        self.assertEqual(self.host.view()['pending'][0]['code'], self.member.view()['pending'][0]['code'])
        with self.assertRaises(NetworkError):
            self.member.sync(confirm=True)
        self.host.approve(request_id, True)
        self.assertIsNone(self.member.sync()['membership'])
        self.assertEqual(self.host.view()['peers'], [])
        self.member.sync(confirm=True)
        self.assertEqual(self.member.view()['membership']['id'], self.host.view()['membership']['id'])
        self.assertEqual(self.host.view()['peers'][0]['identity'], original_identity)
        for old in (self.host, self.member):
            restored = Membership(old.path.parent, old.config, old.identity_path)
            self.assertEqual(restored.public, old.public)
            self.assertEqual(restored.view(), old.view())
            self.assertEqual(restored.path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(identity(old.identity_path), old.node_id)
        self.assertIn('authenticated', self.member.sync()['message'])
        # Signatures grant no browser or audio API authority.
        signed = self.member.sign(self.host.node_id, self.host.info()['system']['id'], 'volume', {'percent': 1})
        with self.assertRaises(NetworkError):
            self.host.receive(signed)

    def test_closed_window_rejection_expiry_and_automatic_join_are_prevented(self):
        self.host.create('House')
        with self.assertRaises(NetworkError):
            self.member.request_join(self.url)
        self.host.allow(True)
        request_id = self.member.request_join(self.url)['pending'][0]['id']
        self.host.approve(request_id, False)
        with self.assertRaises(NetworkError):
            self.member.sync(confirm=True)
        self.assertIsNone(self.member.view()['membership'])
        self.assertEqual(self.host.view()['peers'], [])
        with patch('flowharmonic.network.time.time', return_value=time.time() + 601):
            self.assertFalse(self.host.info()['accepting'])
            self.assertEqual(self.host.view()['pending'], [])
            self.assertEqual(self.member.view()['pending'], [])

    def test_tampering_wrong_key_audience_timestamp_and_replay_fail(self):
        request_id = self.joined()
        system_id = self.host.info()['system']['id']
        message = self.member.sign(self.host.node_id, system_id, 'ping', {'enrollment': request_id})
        tampered = copy.deepcopy(message)
        tampered['payload']['enrollment'] = 'changed'
        with self.assertRaises(NetworkError):
            self.host.receive(tampered)
        self.assertTrue(self.member.verify(self.host.receive(message), self.host.public, message['nonce'])['member'])
        used_message = message
        with self.assertRaises(NetworkError):
            self.host.receive(message)
        for changed in ('audience', 'clock', 'key'):
            with self.subTest(changed=changed):
                message = self.member.sign(self.host.node_id, system_id, 'ping', {'enrollment': request_id})
                if changed == 'audience':
                    message = self.member.sign(self.stranger.node_id, system_id, 'ping', {'enrollment': request_id})
                elif changed == 'clock':
                    with patch('flowharmonic.network.time.time', return_value=time.time() - 121):
                        message = self.member.sign(self.host.node_id, system_id, 'ping', {})
                else:
                    with self.assertRaises(NetworkError):
                        self.host.verify(message, self.stranger.public)
                    continue
                with self.assertRaises(NetworkError):
                    self.host.receive(message)
        forged = self.stranger.sign(self.host.node_id, system_id, 'ping', {'enrollment': request_id})
        self.assertFalse(self.stranger.verify(self.host.receive(forged), self.host.public, forged['nonce'])['member'])
        # Nonces stay used across service restarts.
        restarted = Membership(self.host.path.parent, self.host.config, self.host.identity_path)
        with self.assertRaises(NetworkError):
            restarted.receive(used_message)

    def test_peer_removal_leave_offline_leave_and_host_dissolution(self):
        self.joined()
        self.host.remove(self.member.node_id)
        with self.assertRaises(NetworkError):
            self.member.sync()
        self.assertIsNone(self.member.view()['membership'])
        request_id = self.member.request_join(self.url)['pending'][0]['id']
        self.host.approve(request_id, True)
        self.member.sync(confirm=True)
        self.member.leave()
        self.assertEqual(self.host.view()['peers'], [])
        self.assertIsNone(self.member.view()['membership'])
        request_id = self.member.request_join(self.url)['pending'][0]['id']
        self.host.approve(request_id, True)
        self.member.sync(confirm=True)
        with patch('flowharmonic.network.exchange', side_effect=NetworkError('Offline')):
            self.assertIn('unreachable', self.member.leave()['message'])
        self.assertIsNone(self.member.view()['membership'])
        self.host.leave()
        self.assertFalse(self.host.view()['peers'])

    def test_lost_responses_retry_same_request_without_extra_approval(self):
        request_id = self.request()
        self.host.approve(request_id, True)
        actual = self.exchange
        def lose(url, path, body=None):
            result = actual(url, path, body)
            if body and body['action'] == 'confirm':
                raise NetworkError('Lost response')
            return result
        with patch('flowharmonic.network.exchange', side_effect=lose):
            with self.assertRaises(NetworkError):
                self.member.sync(confirm=True)
        self.assertIsNone(self.member.view()['membership'])
        self.member.sync(confirm=True)
        self.assertEqual(len(self.host.view()['peers']), 1)
        self.assertIsNotNone(self.member.view()['membership'])

    def test_newer_database_is_preserved_and_endpoint_validation(self):
        with sqlite3.connect(self.member.path) as db:
            db.execute('PRAGMA user_version=999')
        before = self.member.path.read_bytes()
        with self.assertRaises(RuntimeError):
            Membership(self.member.path.parent, self.member.config, self.member.identity_path)
        self.assertEqual(before, self.member.path.read_bytes())
        for url in ('ftp://10.0.0.1', 'http://user:pass@10.0.0.1', 'http://10.0.0.1/path', 'http://10.0.0.1?query', 'http://10.0.0.1:99999'):
            with self.subTest(url=url), self.assertRaises(NetworkError):
                endpoint(url)


class NetworkAPITests(unittest.TestCase):
    def test_manual_targets_cannot_rebind_or_reach_public_or_link_local_addresses(self):
        # The real connector checks the resolved address before any HTTP request.
        for address in ('8.8.8.8', '169.254.169.254', '0.0.0.0', '224.0.0.251'):
            with self.subTest(address=address), patch('flowharmonic.network.socket.getaddrinfo',
                    return_value=[(2, 1, 6, '', (address, 8080))]), \
                 patch('flowharmonic.network.urllib.request.build_opener') as connect:
                with self.assertRaises(NetworkError):
                    exchange('http://nearby.example:8080', '/peer/info')
                connect.assert_not_called()

    def test_sessions_csrf_size_limits_and_public_metadata(self):
        import os
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {'FLOWHARMONIC_DATA_DIR': temporary,
                'FLOWHARMONIC_CONFIG': temporary + '/config.toml'}), patch('flowharmonic.app.Discovery.start'):
            with TestClient(create_app()) as client:
                self.assertEqual(client.get('/api/network').status_code, 401)
                self.assertEqual(client.post('/api/network/create', json={'name': 'House'}).status_code, 401)
                info = client.get('/peer/info').json()
                self.assertEqual(set(info), {'protocol', 'identity', 'name', 'version', 'public_key', 'system', 'accepting'})
                self.assertEqual(client.post('/peer/message', content='x'*17000).status_code, 413)
                self.assertEqual(client.post('/peer/message', json={}).status_code, 403)
                self.assertEqual(client.post('/peer/message', content='bad').status_code, 422)
                token = client.app.state.authentication
                token.set_password('a test management password')
                headers = {'X-FlowHarmonic-Request': '1'}
                client.post('/api/auth/sign-in', json={'password': 'a test management password'}, headers=headers)
                self.assertEqual(client.post('/api/network/create', json={'name': 'House'}).status_code, 403)
                self.assertEqual(client.post('/api/network/create', json={'name': 'House'}, headers={**headers, 'Origin': 'http://evil'}).status_code, 403)
                self.assertEqual(client.post('/api/network/create', json={'name': 'House'}, headers=headers).status_code, 200)
                self.assertEqual(client.post('/api/network/allow', json={'enabled': True}, headers=headers).status_code, 200)
                self.assertTrue(client.get('/api/network').json()['accepting'])
                self.assertEqual(client.post('/api/network/leave', json={}, headers=headers).status_code, 200)
                self.assertIsNone(client.get('/api/network').json()['membership'])


if __name__ == '__main__':
    unittest.main()
