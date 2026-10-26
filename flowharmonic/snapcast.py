"""Small JSON-RPC adapter. Snapcast remains the authority for live audio state."""
import json
import socket
import threading
import time
import uuid
import urllib.error
import urllib.request
from urllib.parse import urlsplit

MAX_MESSAGE = 4 * 1024 * 1024


class AudioError(Exception):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Snapcast:
    def __init__(self, url, timeout=3):
        self.url = urlsplit(url)
        self.timeout = timeout
        self.lock = threading.Lock()

    def call(self, method, **params):
        request_id = uuid.uuid4().hex
        payload = json.dumps({'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params}).encode()
        try:
            if self.url.scheme == 'tcp':
                deadline = time.monotonic() + self.timeout
                with socket.create_connection((self.url.hostname, self.url.port or 1705), self.timeout) as connection:
                    connection.sendall(payload + b'\r\n')
                    with connection.makefile('rb') as reader:
                        # Ignore notifications, with a total deadline and byte bound.
                        remaining = MAX_MESSAGE
                        while remaining > 0:
                            connection.settimeout(max(0.001, deadline - time.monotonic()))
                            if time.monotonic() >= deadline:
                                raise TimeoutError()
                            line = reader.readline(remaining + 1)
                            if not line or len(line) > remaining:
                                raise ValueError('Missing or oversized response')
                            remaining -= len(line)
                            result = json.loads(line)
                            if isinstance(result, dict) and result.get('id') == request_id:
                                break
                        else:
                            raise ValueError('Oversized response')
            else:
                request = urllib.request.Request(self.url.geturl(), payload, {'Content-Type': 'application/json'})
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
                with opener.open(request, timeout=self.timeout) as response:
                    body = response.read(MAX_MESSAGE + 1)
                    if len(body) > MAX_MESSAGE:
                        raise ValueError('Oversized response')
                    result = json.loads(body)
            if not isinstance(result, dict) or result.get('jsonrpc') != '2.0' or result.get('id') != request_id:
                raise ValueError('Invalid response')
            if 'error' in result:
                raise AudioError('The audio server could not complete the request. Refresh and try again.', 502)
            if not isinstance(result.get('result'), dict):
                raise ValueError('Missing result')
            return result['result']
        except AudioError:
            raise
        except urllib.error.HTTPError as error:
            raise AudioError('The audio server did not accept the request. Check its address and access settings.', 502) from error
        except (OSError, urllib.error.URLError, TimeoutError) as error:
            message = 'Cannot reach the audio server. Check its address and connection, then try again.'
            if method != 'Server.GetStatus':
                message += ' The change may have applied; refresh before trying again.'
            raise AudioError(message) from error
        except (ValueError, TypeError) as error:
            raise AudioError('The audio server returned an unreadable response. Check the connection settings and server version.', 502) from error

    def status(self):
        result = self.call('Server.GetStatus')
        try:
            server = result['server']
            if not isinstance(server['streams'], list) or not isinstance(server['groups'], list):
                raise ValueError('Invalid inventory')
            for stream in server['streams']:
                if not isinstance(stream['id'], str) or not isinstance(stream['status'], str):
                    raise ValueError('Invalid source')
                if not isinstance(stream.get('uri', {}).get('query', {}), dict):
                    raise ValueError('Invalid source name')
                if not isinstance(stream.get('uri', {}).get('query', {}).get('name', ''), str):
                    raise ValueError('Invalid source name')
            for group in server['groups']:
                if not isinstance(group['id'], str) or not isinstance(group['stream_id'], str):
                    raise ValueError('Invalid group')
                if type(group['muted']) is not bool or not isinstance(group['clients'], list):
                    raise ValueError('Invalid group')
                for client in group['clients']:
                    if not isinstance(client['id'], str) or type(client['connected']) is not bool:
                        raise ValueError('Invalid destination')
                    if not isinstance(client['config'].get('name', ''), str) or not isinstance(client.get('host', {}).get('name', ''), str):
                        raise ValueError('Invalid destination name')
                    volume = client['config']['volume']
                    if type(volume['percent']) is not int or not 0 <= volume['percent'] <= 100:
                        raise ValueError('Invalid volume')
                    if type(volume['muted']) is not bool:
                        raise ValueError('Invalid mute')
            return server
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise AudioError('The audio server returned an unsupported response. Check its version and try again.', 502) from error

    @staticmethod
    def inventory(server):
        sources = [{'id': stream['id'], 'name': stream.get('uri', {}).get('query', {}).get('name') or f'Source {index + 1}',
                    'status': stream['status']} for index, stream in enumerate(server['streams'])]
        destinations = []
        for group in server['groups']:
            for client in group['clients']:
                volume = client['config']['volume']
                destinations.append({'id': client['id'],
                                     'name': client['config'].get('name') or client.get('host', {}).get('name') or f'Destination {len(destinations) + 1}',
                                     'source_id': group['stream_id'], 'volume': volume['percent'],
                                     'muted': volume['muted'] or group['muted'], 'available': client['connected']})
        return {'sources': sources, 'destinations': destinations}

    def snapshot(self):
        with self.lock:
            return self.inventory(self.status())

    @staticmethod
    def find(server, destination):
        for group in server['groups']:
            for client in group['clients']:
                if client['id'] == destination:
                    if not client['connected']:
                        raise AudioError('This destination is offline. Reconnect it before changing audio.', 409)
                    return group, client
        raise AudioError('This destination is no longer available. Refresh the dashboard.', 404)

    def separate(self, server, destination):
        group, client = self.find(server, destination)
        if len(group['clients']) > 1:
            # A newly detached group is unmuted. Preserve effective client mute.
            if group['muted'] and not client['config']['volume']['muted']:
                self.call('Client.SetVolume', id=destination, volume={**client['config']['volume'], 'muted': True})
            self.call('Group.SetClients', id=group['id'], clients=[item['id'] for item in group['clients'] if item['id'] != destination])
        group, client = self.find(self.status(), destination)
        if len(group['clients']) != 1:
            raise AudioError('Audio changed elsewhere while this request was running. Refresh and try again.', 409)
        return group, client

    def change(self, destination, *, source_id=None, percent=None, muted=None):
        with self.lock:
            server = self.status()
            group, client = self.find(server, destination)
            if source_id is not None:
                if not any(stream['id'] == source_id and stream['status'] != 'disabled' for stream in server['streams']):
                    raise AudioError('This source is no longer available. Choose another source.', 404)
                if group['stream_id'] != source_id:
                    group, client = self.separate(server, destination)
                    self.call('Group.SetStream', id=group['id'], stream_id=source_id)
            else:
                if muted is False and group['muted']:
                    group, client = self.separate(server, destination)
                    self.call('Group.SetMute', id=group['id'], mute=False)
                volume = dict(client['config']['volume'])
                if percent is not None:
                    volume['percent'] = percent
                if muted is not None:
                    volume['muted'] = muted
                self.call('Client.SetVolume', id=destination, volume=volume)
            observed = self.status()
            group, client = self.find(observed, destination)
            volume = client['config']['volume']
            if ((source_id is not None and group['stream_id'] != source_id) or
                    (percent is not None and volume['percent'] != percent) or
                    (muted is not None and (volume['muted'] or group['muted']) != muted)):
                raise AudioError('The change could not be confirmed. Refresh to see the current audio settings.', 409)
            return self.inventory(observed)

    def rename(self, destination, name):
        with self.lock:
            server = self.status()
            if not any(client['id'] == destination for group in server['groups'] for client in group['clients']):
                raise AudioError('This destination is no longer available. Refresh the dashboard.', 404)
            self.call('Client.SetName', id=destination, name=name)
            observed = self.status()
            if not any(client['id'] == destination and client['config'].get('name') == name
                       for group in observed['groups'] for client in group['clients']):
                raise AudioError('The name could not be confirmed. Refresh to see its current value.', 409)
            return self.inventory(observed)
