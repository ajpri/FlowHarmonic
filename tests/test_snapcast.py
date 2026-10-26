import copy
import json
import socket
import socketserver
import threading
import unittest
from unittest.mock import patch

from flowharmonic.snapcast import AudioError, Snapcast


def client(identifier, muted=False):
    return {'id': identifier, 'connected': True, 'config': {'name': identifier, 'volume': {'percent': 70, 'muted': muted}}, 'host': {'name': 'host'}}


def state():
    return {'streams': [{'id': name, 'status': 'playing', 'uri': {'query': {'name': name}}} for name in ('A', 'B')],
            'groups': [{'id': 'original', 'stream_id': 'A', 'muted': False, 'clients': [client('Office'), client('Kitchen')]}]}


class AudioControlTests(unittest.TestCase):
    def setUp(self):
        self.server = state()
        self.calls = []
        self.audio = Snapcast('tcp://127.0.0.1:1705')
        self.audio.call = self.call

    def call(self, method, **params):
        self.calls.append((method, params))
        if method == 'Server.GetStatus':
            return {'server': copy.deepcopy(self.server)}
        if method in ('Client.SetVolume', 'Client.SetName'):
            for group in self.server['groups']:
                for item in group['clients']:
                    if item['id'] == params['id']:
                        if method == 'Client.SetName':
                            item['config']['name'] = params['name']
                        else:
                            item['config']['volume'] = params['volume'].copy()
        else:
            group = next(group for group in self.server['groups'] if group['id'] == params['id'])
            if method == 'Group.SetClients':
                for item in list(group['clients']):
                    if item['id'] not in params['clients']:
                        group['clients'].remove(item)
                        self.server['groups'].append({'id': 'observed-new-group', 'stream_id': group['stream_id'], 'muted': False, 'clients': [item]})
            elif method == 'Group.SetStream':
                group['stream_id'] = params['stream_id']
            elif method == 'Group.SetMute':
                group['muted'] = params['mute']
            else:
                raise AssertionError(method)
        return {}

    def test_rename_preserves_routing_volume_and_offline_client(self):
        self.server['groups'][0]['clients'][0]['connected'] = False
        result = self.audio.rename('Office', 'Desk speakers')
        destination = next(d for d in result['destinations'] if d['id'] == 'Office')
        self.assertEqual(destination['name'], 'Desk speakers')
        self.assertEqual(destination['source_id'], 'A')
        self.assertEqual(destination['volume'], 70)
        self.assertFalse(any(method.startswith('Group.') for method, _ in self.calls))
        with self.assertRaises(AudioError):
            self.audio.rename('missing', 'No such destination')

    def test_route_separates_and_uses_observed_group(self):
        result = self.audio.change('Office', source_id='B')
        destinations = {item['id']: item for item in result['destinations']}
        self.assertEqual(destinations['Office']['source_id'], 'B')
        self.assertEqual(destinations['Kitchen']['source_id'], 'A')
        self.assertIn(('Group.SetStream', {'id': 'observed-new-group', 'stream_id': 'B'}), self.calls)
        # Another controller moves Office; FH re-observes membership on next operation.
        self.server['groups'][1]['id'] = 'changed-elsewhere'
        self.audio.change('Office', source_id='A')
        self.assertIn(('Group.SetStream', {'id': 'changed-elsewhere', 'stream_id': 'A'}), self.calls)

    def test_noop_route_does_not_regroup(self):
        self.audio.change('Office', source_id='A')
        self.assertTrue(all(method == 'Server.GetStatus' for method, _ in self.calls))

    def test_volume_preserves_mute_and_peer(self):
        self.server['groups'][0]['clients'][0]['config']['volume']['muted'] = True
        result = self.audio.change('Office', percent=24)
        destinations = {d['id']: d for d in result['destinations']}
        self.assertEqual(destinations['Office']['volume'], 24)
        self.assertTrue(destinations['Office']['muted'])
        self.assertEqual(destinations['Kitchen']['volume'], 70)
        self.assertFalse(any(method.startswith('Group.') for method, _ in self.calls))

    def test_unmute_only_one_member_of_muted_group(self):
        self.server['groups'][0]['muted'] = True
        result = self.audio.change('Office', muted=False)
        destinations = {d['id']: d for d in result['destinations']}
        self.assertFalse(destinations['Office']['muted'])
        self.assertTrue(destinations['Kitchen']['muted'])
        self.assertTrue(self.server['groups'][0]['muted'])

    def test_route_preserves_effective_group_mute(self):
        self.server['groups'][0]['muted'] = True
        result = self.audio.change('Office', source_id='B')
        self.assertTrue(all(d['muted'] for d in result['destinations']))

    def test_offline_missing_source_and_missing_client_refuse_writes(self):
        self.server['groups'][0]['clients'][0]['connected'] = False
        for destination, source in (('Office', 'B'), ('missing', 'B'), ('Kitchen', 'missing')):
            with self.assertRaises(AudioError):
                self.audio.change(destination, source_id=source)
        self.assertTrue(all(method == 'Server.GetStatus' for method, _ in self.calls))

    def test_shared_group_after_external_regroup_is_not_changed(self):
        # Simulate another controller keeping the destination in a shared group.
        original = self.call
        def concurrent(method, **params):
            if method == 'Group.SetClients':
                return {}
            return original(method, **params)
        self.audio.call = concurrent
        with self.assertRaisesRegex(AudioError, 'changed elsewhere'):
            self.audio.change('Office', source_id='B')
        self.assertFalse(any(method == 'Group.SetStream' for method, _ in self.calls))

    def test_invalid_snapshot_is_readable_error(self):
        for server in ({}, {'groups': [], 'streams': [None]}, {'groups': [None], 'streams': []}):
            with patch.object(self.audio, 'call', return_value={'server': server}):
                with self.assertRaisesRegex(AudioError, 'unsupported response'):
                    self.audio.snapshot()


class WireTests(unittest.TestCase):
    def serve(self, respond):
        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                payload = json.loads(self.rfile.readline())
                respond(self.wfile, payload)
        server = socketserver.TCPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return Snapcast(f'tcp://127.0.0.1:{server.server_address[1]}', timeout=0.1)

    def test_notifications_and_correlated_reply(self):
        def respond(output, payload):
            output.write(b'{"jsonrpc":"2.0","method":"Server.OnUpdate"}\n')
            output.write(json.dumps({'jsonrpc': '2.0', 'id': payload['id'], 'result': {'server': state()}}).encode() + b'\n')
        self.assertEqual(len(self.serve(respond).snapshot()['sources']), 2)

    def test_rpc_error_and_malformed_json(self):
        for body in (b'no JSON\n', b'{"jsonrpc":"2.0","id":"wrong","result":{}}\n'):
            with self.assertRaisesRegex(AudioError, 'unreadable'):
                self.serve(lambda output, payload: output.write(body)).snapshot()
        def respond(output, payload):
            output.write(json.dumps({'jsonrpc': '2.0', 'id': payload['id'], 'error': {'message': 'private implementation details'}}).encode()+b'\n')
        with self.assertRaisesRegex(AudioError, 'could not complete'):
            self.serve(respond).snapshot()

    def test_oversized_reply_is_rejected(self):
        with patch('flowharmonic.snapcast.MAX_MESSAGE', 64):
            with self.assertRaisesRegex(AudioError, 'unreadable'):
                self.serve(lambda output, payload: output.write(b'x' * 100 + b'\n')).snapshot()

    def test_http_jsonrpc_and_rejected_redirect(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                if self.path == '/redirect':
                    self.send_response(302)
                    self.send_header('Location', '/jsonrpc')
                    self.end_headers()
                    return
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                body = json.dumps({'jsonrpc': '2.0', 'id': payload['id'], 'result': {'server': state()}}).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        server = HTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f'http://127.0.0.1:{server.server_port}'
        self.assertEqual(len(Snapcast(url + '/jsonrpc').snapshot()['destinations']), 2)
        with self.assertRaisesRegex(AudioError, 'did not accept'):
            Snapcast(url + '/redirect').snapshot()

    def test_timeout_and_connection_refused(self):
        import time
        with self.assertRaisesRegex(AudioError, 'Cannot reach'):
            self.serve(lambda output, payload: time.sleep(0.2)).snapshot()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        with self.assertRaisesRegex(AudioError, 'Cannot reach'):
            Snapcast(f'tcp://127.0.0.1:{port}', timeout=0.1).snapshot()


if __name__ == '__main__':
    unittest.main()
