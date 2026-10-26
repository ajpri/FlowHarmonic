"""M6 membership only: approved enrollment and signed node messages, no audio control."""
import base64
import fcntl
import hashlib
import ipaddress
import json
import os
import secrets
import socket
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import uuid
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from . import VERSION
from .state import database, identity, node_name, validate_name

WINDOW = 600
MAX_MESSAGE = 16384


class MembershipLock:
    """Serialize complete membership operations across web and CLI processes."""
    def __init__(self, path):
        self.path = path
        self.thread_lock = threading.RLock()
        self.depth = 0
        self.descriptor = None

    def __enter__(self):
        self.thread_lock.acquire()
        try:
            if self.depth == 0:
                self.descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
                fcntl.flock(self.descriptor, fcntl.LOCK_EX)
            self.depth += 1
        except BaseException:
            if self.descriptor is not None:
                os.close(self.descriptor)
                self.descriptor = None
            self.thread_lock.release()
            raise

    def __exit__(self, *exception):
        self.depth -= 1
        if self.depth == 0:
            os.close(self.descriptor)
            self.descriptor = None
        self.thread_lock.release()


class NetworkError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def public_key(private):
    return private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def code(request_id, system_id, host_key, member_key):
    digest = hashlib.sha256(canonical([request_id, system_id, host_key, member_key])).hexdigest()[:16].upper()
    return ' '.join(digest[i:i + 4] for i in range(0, 16, 4))


def endpoint(value):
    """Only explicit local-network HTTP(S) endpoints; never redirects or proxies."""
    try:
        url = urlsplit(value)
        if (len(value) > 512 or url.scheme not in ('http', 'https') or not url.hostname or
                url.username or url.password or url.query or url.fragment or url.path not in ('', '/') or
                '%' in url.hostname):
            raise ValueError()
        port = url.port or (443 if url.scheme == 'https' else 80)
        if not 1 <= port <= 65535:
            raise ValueError()
    except (ValueError, TypeError):
        raise NetworkError('Enter this node’s local address, such as http://192.168.1.20:8080.', 422)
    return f'{url.scheme}://{url.netloc}'.rstrip('/')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def exchange(url, path, body=None):
    url = endpoint(url)
    parsed = urlsplit(url)
    try:
        # Resolve once and connect to the checked address, preventing DNS rebinding.
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)
        address = addresses[0][4][0]
        ip = ipaddress.ip_address(address)
        if not (ip.is_private or ip.is_loopback) or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            raise NetworkError('Use a reachable address on your local network.', 422)
        # HTTPS keeps its hostname for normal certificate validation. Restrict it
        # to literal addresses so the checked address cannot change on reconnect.
        if parsed.scheme == 'https' and parsed.hostname != address:
            raise NetworkError('For HTTPS, use a local IP address with a valid certificate.', 422)
        host = f'[{address}]' if ':' in address else address
        target = f'{parsed.scheme}://{host}:{parsed.port or (443 if parsed.scheme == "https" else 80)}{path}'
        headers = {'Content-Type': 'application/json', 'Host': parsed.netloc}
        request = urllib.request.Request(target, data=canonical(body) if body is not None else None, headers=headers)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=3) as response:
            raw = response.read(MAX_MESSAGE + 1)
        if len(raw) > MAX_MESSAGE:
            raise ValueError()
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except urllib.error.HTTPError as error:
        if error.code == 429:
            raise NetworkError('That node is receiving too many requests. Try again shortly.', 429) from error
        raise NetworkError('That node could not accept this request. Check its connection status and whether joining is allowed.', 502) from error
    except (OSError, ValueError) as error:
        raise NetworkError('Cannot reach that FlowHarmonic node. Check its address, connection, and firewall.', 503) from error


class Membership:
    def __init__(self, directory, config, identity_path):
        self.path = directory / 'network.db'
        self.config = config
        self.identity_path = identity_path
        self.node_id = identity(identity_path)
        self.lock = MembershipLock(directory / 'network.lock')
        self.failure_lock = threading.Lock()
        self.attempts = []
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        self.path.chmod(0o600)
        with database(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise RuntimeError('Network settings are newer than this application; refusing to modify them')
            if version == 0:
                if db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                    raise RuntimeError('Unrecognized network database; refusing to reset it')
                key = Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
                db.execute('CREATE TABLE settings (id INTEGER PRIMARY KEY CHECK(id=1), private_key BLOB NOT NULL, membership TEXT, accepting INTEGER NOT NULL)')
                db.execute('INSERT INTO settings VALUES (1, ?, NULL, 0)', (key,))
                db.execute('CREATE TABLE peer (identity TEXT PRIMARY KEY, public_key TEXT NOT NULL, name TEXT NOT NULL, enrollment TEXT NOT NULL)')
                db.execute('CREATE TABLE pending (id TEXT PRIMARY KEY, direction TEXT NOT NULL, data TEXT NOT NULL, status TEXT NOT NULL, expires INTEGER NOT NULL)')
                db.execute('CREATE TABLE nonce (sender TEXT NOT NULL, value TEXT NOT NULL, expires INTEGER NOT NULL, PRIMARY KEY(sender,value))')
                db.execute('PRAGMA user_version=1')
            row = db.execute('SELECT private_key, membership, accepting FROM settings WHERE id=1').fetchone()
            if row is None:
                raise RuntimeError('Network identity is missing; restore its backup instead of resetting')
            self.key = Ed25519PrivateKey.from_private_bytes(row[0])
            db.execute('SELECT identity, public_key, name, enrollment FROM peer LIMIT 0')
            db.execute('SELECT id, direction, data, status, expires FROM pending LIMIT 0')
            db.execute('SELECT sender, value, expires FROM nonce LIMIT 0')
        self.public = public_key(self.key)

    @property
    def name(self):
        return node_name(self.identity_path, self.config['name'])

    def current(self, db):
        raw = db.execute('SELECT membership FROM settings WHERE id=1').fetchone()[0]
        return json.loads(raw) if raw else None

    def host(self, membership):
        return membership and membership['host_id'] == self.node_id

    def cleanup(self, db):
        now = int(time.time())
        db.execute('DELETE FROM nonce WHERE expires<?', (now,))
        db.execute('DELETE FROM pending WHERE expires<?', (now,))

    def info(self):
        with database(self.path) as db:
            membership = self.current(db)
            accepting = db.execute('SELECT accepting FROM settings WHERE id=1').fetchone()[0] > time.time()
        return {'protocol': 1, 'identity': self.node_id, 'name': self.name, 'version': VERSION,
                'public_key': self.public, 'system': {'id': membership['id'], 'name': membership['name'],
                'host_id': membership['host_id']} if membership else None,
                'accepting': bool(self.host(membership) and accepting)}

    def view(self):
        with self.lock, database(self.path) as db:
            self.cleanup(db)
            membership = self.current(db)
            peers = [{'identity': row[0], 'name': row[1]} for row in db.execute('SELECT identity,name FROM peer ORDER BY name')]
            pending = []
            for row in db.execute('SELECT id,direction,data,status,expires FROM pending ORDER BY expires'):
                data = json.loads(row[2])
                pending.append({'id': row[0], 'direction': row[1], 'status': row[3], 'expires': row[4],
                                'name': data['name'], 'system_name': data['system_name'], 'code': data['code']})
        return {'membership': {k: v for k, v in membership.items() if k not in ('host_key',)} if membership else None,
                'is_host': bool(self.host(membership)), 'accepting': self.info()['accepting'], 'peers': peers, 'pending': pending}

    def create(self, name):
        name = validate_name(name)
        with self.lock, database(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            if self.current(db):
                raise NetworkError('This node already belongs to a system. Leave it before creating another.')
            self.cleanup(db)
            if db.execute("SELECT 1 FROM pending WHERE direction='out'").fetchone():
                raise NetworkError('Cancel the pending join request before creating a system.')
            membership = {'id': str(uuid.uuid4()), 'name': name, 'host_id': self.node_id, 'host_key': self.public, 'host_url': ''}
            db.execute('UPDATE settings SET membership=?, accepting=0 WHERE id=1', (json.dumps(membership),))
        return self.view()

    def allow(self, enabled):
        with self.lock, database(self.path) as db:
            if not self.host(self.current(db)):
                raise NetworkError('Allow join requests on the system host.')
            db.execute('UPDATE settings SET accepting=? WHERE id=1', (int(time.time()) + WINDOW if enabled else 0,))
        return self.view()

    def sign(self, recipient, system_id, action, payload, reply_to=''):
        message = {'protocol': 1, 'sender': self.node_id, 'recipient': recipient, 'system': system_id,
                   'action': action, 'payload': payload, 'timestamp': int(time.time()),
                   'nonce': secrets.token_hex(16), 'reply_to': reply_to, 'public_key': self.public}
        message['signature'] = base64.b64encode(self.key.sign(canonical(message))).decode()
        return message

    def verify(self, message, expected_key=None, reply_to=None):
        try:
            fields = {'protocol', 'sender', 'recipient', 'system', 'action', 'payload', 'timestamp', 'nonce', 'reply_to', 'public_key', 'signature'}
            if (not isinstance(message, dict) or set(message) != fields or len(canonical(message)) > MAX_MESSAGE or
                    type(message['protocol']) is not int or message['protocol'] != 1 or
                    type(message['timestamp']) is not int or abs(time.time() - message['timestamp']) > 120 or
                    message['recipient'] != self.node_id or not isinstance(message['payload'], dict) or
                    any(not isinstance(message[k], str) for k in fields - {'protocol', 'timestamp', 'payload'}) or
                    len(message['nonce']) != 32 or len(message['reply_to']) not in (0, 32)):
                raise ValueError()
            uuid.UUID(message['sender'])
            uuid.UUID(message['system'])
            key = message['public_key']
            if expected_key is not None and key != expected_key:
                raise ValueError()
            if reply_to is not None and message['reply_to'] != reply_to:
                raise ValueError()
            unsigned = {k: v for k, v in message.items() if k != 'signature'}
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(key)).verify(base64.b64decode(message['signature'], validate=True), canonical(unsigned))
        except (ValueError, TypeError, KeyError, InvalidSignature):
            raise NetworkError('Node authentication failed. Check both devices’ clocks and approved membership.', 403)
        with database(self.path) as db:
            self.cleanup(db)
            try:
                db.execute('INSERT INTO nonce VALUES (?,?,?)', (message['sender'], message['nonce'], int(time.time()) + 240))
            except sqlite3.IntegrityError:
                raise NetworkError('This node message has already been used. Refresh and try again.', 403)
        return message['payload']

    def send(self, url, recipient, system_id, key, action, payload):
        message = self.sign(recipient, system_id, action, payload)
        response = exchange(url, '/peer/message', message)
        result = self.verify(response, key, message['nonce'])
        if response['sender'] != recipient or response['system'] != system_id or response['action'] != action:
            raise NetworkError('That node returned a response for a different system.', 403)
        return result

    def request_join(self, url, expected_id=None):
        url = endpoint(url)
        with self.lock:
            with database(self.path) as db:
                self.cleanup(db)
                if self.current(db) or db.execute("SELECT 1 FROM pending WHERE direction='out'").fetchone():
                    raise NetworkError('Leave the current system or cancel the pending request first.')
            remote = exchange(url, '/peer/info')
            try:
                system = remote['system']
                uuid.UUID(remote['identity'])
                uuid.UUID(system['id'])
                Ed25519PublicKey.from_public_bytes(bytes.fromhex(remote['public_key']))
                if (remote['protocol'] != 1 or system['host_id'] != remote['identity'] or
                        remote['identity'] == self.node_id or expected_id and expected_id != remote['identity']):
                    raise ValueError()
                validate_name(remote['name'])
                validate_name(system['name'])
            except (TypeError, KeyError, ValueError):
                raise NetworkError('That address is not an available FlowHarmonic system host.', 422)
            if not remote.get('accepting'):
                raise NetworkError('On the system host, run sudo flowharmonic connections allow or choose Allow join requests in Connections, then try again.')
            request_id = str(uuid.uuid4())
            verification = code(request_id, system['id'], remote['public_key'], self.public)
            data = {'name': remote['name'], 'peer_id': remote['identity'], 'key': remote['public_key'], 'url': url,
                    'system_id': system['id'], 'system_name': system['name'], 'code': verification}
            # Store before the network request so a lost reply can be retried safely.
            with database(self.path) as db:
                db.execute('INSERT INTO pending VALUES (?,?,?, ?,?)', (request_id, 'out', json.dumps(data), 'pending', int(time.time()) + WINDOW))
            try:
                self.send(url, remote['identity'], system['id'], remote['public_key'], 'request', {'id': request_id, 'name': self.name})
            except NetworkError:
                # Keep request and key pin; Refresh retries the same request id.
                raise
        return self.view()

    def approve(self, request_id, approve):
        with self.lock, database(self.path) as db:
            self.cleanup(db)
            if not self.host(self.current(db)):
                raise NetworkError('Approve join requests on the system host.')
            row = db.execute("SELECT status FROM pending WHERE id=? AND direction='in'", (request_id,)).fetchone()
            if row is None:
                raise NetworkError('This join request expired or was cancelled. Request to join again.')
            if approve:
                db.execute("UPDATE pending SET status='approved' WHERE id=?", (request_id,))
            else:
                db.execute("UPDATE pending SET status='rejected' WHERE id=?", (request_id,))
        return self.view()

    def sync(self, confirm=False):
        with self.lock:
            with database(self.path) as db:
                self.cleanup(db)
                membership = self.current(db)
                row = db.execute("SELECT id,data FROM pending WHERE direction='out'").fetchone()
            if row:
                request_id, raw = row
                data = json.loads(raw)
                result = self.send(data['url'], data['peer_id'], data['system_id'], data['key'],
                                   'confirm' if confirm else 'request', {'id': request_id, 'name': self.name})
                with database(self.path) as db:
                    if result.get('status') == 'joined':
                        membership = {'id': data['system_id'], 'name': data['system_name'], 'host_id': data['peer_id'],
                                      'host_key': data['key'], 'host_url': data['url'], 'enrollment': request_id}
                        db.execute('UPDATE settings SET membership=? WHERE id=1', (json.dumps(membership),))
                        db.execute('DELETE FROM pending')
                    elif result.get('status') in ('pending', 'approved', 'rejected'):
                        db.execute('UPDATE pending SET status=? WHERE id=?', (result['status'], request_id))
                    else:
                        raise NetworkError('This join request is no longer available. Cancel it and request to join again.')
            elif membership and not self.host(membership):
                result = self.send(membership['host_url'], membership['host_id'], membership['id'], membership['host_key'],
                                   'ping', {'enrollment': membership['enrollment']})
                if not result.get('member'):
                    with database(self.path) as db:
                        db.execute('UPDATE settings SET membership=NULL, accepting=0 WHERE id=1')
                    raise NetworkError('The system host has removed this membership. This node is independent again.')
            elif confirm:
                raise NetworkError('There is no pending system to join.')
        result = self.view()
        result['message'] = 'System host authenticated successfully.' if membership and not self.host(membership) else 'Membership refreshed.'
        return result

    def cancel(self):
        with self.lock, database(self.path) as db:
            db.execute("DELETE FROM pending WHERE direction='out'")
        # Requests on the other node expire; deleting them never approves access.
        return self.view()

    def leave(self):
        warning = None
        with self.lock:
            with database(self.path) as db:
                membership = self.current(db)
            if membership and not self.host(membership):
                try:
                    self.send(membership['host_url'], membership['host_id'], membership['id'], membership['host_key'],
                              'leave', {'enrollment': membership['enrollment']})
                except NetworkError:
                    warning = 'Left locally. The system host is unreachable; its member list may still show this node until removed there.'
            with database(self.path) as db:
                db.execute('UPDATE settings SET membership=NULL, accepting=0 WHERE id=1')
                db.execute('DELETE FROM peer')
                db.execute('DELETE FROM pending')
        result = self.view()
        result['message'] = warning or 'This node is independent. Local audio settings are unchanged.'
        return result

    def remove(self, peer_id):
        with self.lock, database(self.path) as db:
            if not self.host(self.current(db)):
                raise NetworkError('Remove members on the system host.')
            db.execute('DELETE FROM peer WHERE identity=?', (peer_id,))
        return self.view()

    def receive(self, message):
        # Bound unauthenticated work and pending-request storage globally.
        with self.failure_lock:
            now = time.monotonic()
            self.attempts = [t for t in self.attempts if t > now - 60]
            if len(self.attempts) >= 120:
                raise NetworkError('Too many node messages. Try again in a minute.', 429)
            self.attempts.append(now)
        payload = self.verify(message)
        action = message['action']
        sender = message['sender']
        key = message['public_key']
        with self.lock, database(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            self.cleanup(db)
            membership = self.current(db)
            peer = db.execute('SELECT public_key,enrollment FROM peer WHERE identity=?', (sender,)).fetchone()
            known = bool(self.host(membership) and membership['id'] == message['system'] and peer and
                         peer[0] == key and peer[1] == payload.get('enrollment'))
            if action in ('request', 'confirm'):
                try:
                    request_id = payload['id']
                    if not isinstance(request_id, str):
                        raise ValueError()
                    uuid.UUID(request_id)
                    name = validate_name(payload['name'])
                except (KeyError, ValueError, TypeError):
                    raise NetworkError('This join request is invalid.', 422)
                if not self.host(membership) or membership['id'] != message['system'] or sender == self.node_id:
                    raise NetworkError('This node is not hosting the requested system.')
                if peer and peer[0] == key and peer[1] == request_id:
                    result = {'status': 'joined'}  # lost confirmation response retry
                else:
                    row = db.execute("SELECT data,status FROM pending WHERE id=? AND direction='in'", (request_id,)).fetchone()
                    if row and (json.loads(row[0])['peer_id'] != sender or json.loads(row[0])['key'] != key):
                        raise NetworkError('This join request does not match the requesting device.', 403)
                    if row is None:
                        if action != 'request' or peer:
                            raise NetworkError('Request to join again before confirming membership.')
                        accepting = db.execute('SELECT accepting FROM settings WHERE id=1').fetchone()[0]
                        if accepting <= time.time():
                            raise NetworkError('Joining is closed. Allow join requests on the system host.')
                        if db.execute('SELECT COUNT(*) FROM pending').fetchone()[0] >= 20:
                            raise NetworkError('Too many pending join requests. Wait for them to expire.', 429)
                        data = {'name': name, 'peer_id': sender, 'key': key, 'system_name': membership['name'],
                                'code': code(request_id, membership['id'], self.public, key)}
                        db.execute('INSERT INTO pending VALUES (?,?,?,?,?)', (request_id, 'in', json.dumps(data), 'pending', int(time.time()) + WINDOW))
                        status = 'pending'
                    else:
                        status = row[1]
                    if action == 'confirm':
                        if status != 'approved':
                            raise NetworkError('The system host must approve this request before joining.', 403)
                        db.execute('INSERT INTO peer VALUES (?,?,?,?)', (sender, key, name, request_id))
                        db.execute('DELETE FROM pending WHERE id=?', (request_id,))
                        result = {'status': 'joined'}
                    else:
                        result = {'status': status}
            elif action == 'ping':
                if self.host(membership):
                    result = {'member': known, 'identity': self.node_id, 'name': self.name, 'version': VERSION}
                elif (membership and membership['id'] == message['system'] and membership['host_id'] == sender and
                      membership['host_key'] == key and membership['enrollment'] == payload.get('enrollment')):
                    result = {'member': True, 'identity': self.node_id, 'name': self.name, 'version': VERSION}
                else:
                    # An old system host can confirm revocation without granting access.
                    result = {'member': False}
            elif action == 'leave' and known:
                db.execute('DELETE FROM peer WHERE identity=?', (sender,))
                result = {'left': True}
            else:
                raise NetworkError('This node operation is not authorized by an approved membership.', 403)
        return self.sign(sender, message['system'], action, result, message['nonce'])
