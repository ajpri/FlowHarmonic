"""Named routing snapshots; audio remains controlled by Coordination and Snapcast."""
import json
import os
import uuid

from .snapcast import AudioError
from .network import NetworkError
from .state import database, validate_name


class Scenes:
    def __init__(self, coordination):
        self.coordination = coordination
        self.path = coordination.path.parent / 'scenes.db'
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        self.path.chmod(0o600)
        with database(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise RuntimeError('Scenes database is newer than this application; refusing to reset it')
            if version == 0:
                if db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                    raise RuntimeError('Unrecognized scenes database; refusing to reset it')
                db.execute('CREATE TABLE scene (id TEXT PRIMARY KEY, scope TEXT NOT NULL, name TEXT NOT NULL, data TEXT NOT NULL)')
                db.execute('CREATE TABLE assignment (destination TEXT PRIMARY KEY, data TEXT NOT NULL)')
                db.execute('PRAGMA user_version=1')
            db.execute('SELECT id,scope,name,data FROM scene LIMIT 0')
            db.execute('SELECT destination,data FROM assignment LIMIT 0')

    def scope(self):
        membership = self.coordination.current()
        if membership and not self.coordination.membership.host(membership):
            raise AudioError('Manage scenes from the system coordinator’s dashboard.', 409)
        return membership['id'] if membership else 'local'

    def view(self):
        try:
            scope = self.scope()
        except AudioError as error:
            return {'scenes': [], 'manageable': False, 'message': str(error)}
        with database(self.path) as db:
            rows = db.execute('SELECT id,name,data FROM scene WHERE scope=? ORDER BY name,id', (scope,)).fetchall()
        return {'scenes': [{'id': key, 'name': name, 'destinations': json.loads(data)} for key, name, data in rows],
                'manageable': True, 'message': ''}

    def save(self, name, destinations):
        scope = self.scope()
        name = validate_name(name)
        if not destinations or len(destinations) > 128 or len(set(destinations)) != len(destinations):
            raise AudioError('Select between 1 and 128 different destinations.', 422)
        view = self.coordination.dashboard()
        selected = []
        for key in destinations:
            row = next((d for d in view['destinations'] if d['id'] == key), None)
            if not row or not row.get('available') or row.get('pending') or not row.get('source_id') or row.get('playback_available') is False:
                raise AudioError('Wait for the selected destinations to connect before saving a scene.', 409)
            selected.append({k: row[k] for k in ('id', 'name', 'source_id', 'volume', 'muted')})
        with database(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT count(*) FROM scene').fetchone()[0] >= 100:
                raise AudioError('Remove an old scene before saving another. Up to 100 scenes can be saved.', 409)
            key = str(uuid.uuid4())
            db.execute('INSERT INTO scene VALUES (?,?,?,?)', (key, scope, name, json.dumps(selected)))
        return {'id': key, **self.view()}

    def remove(self, key):
        with database(self.path) as db:
            db.execute('DELETE FROM scene WHERE id=? AND scope=?', (key, self.scope()))
        return self.view()

    def apply(self, key):
        with self.coordination.operation:
            return self._apply(key)

    def _apply(self, key):
        with database(self.path) as db:
            row = db.execute('SELECT data FROM scene WHERE id=? AND scope=?', (key, self.scope())).fetchone()
        if not row:
            raise AudioError('This scene is no longer available. Refresh the scene list.', 404)
        results = []
        # Each destination is independent. Report partial success rather than
        # claiming an atomic multizone operation across unavailable machines.
        for saved in json.loads(row[0]):
            try:
                self.coordination.change(saved['id'], {'source_id': saved['source_id']})
                self.coordination.change(saved['id'], {'percent': saved['volume'], 'muted': saved['muted']})
                results.append({'name': saved['name'], 'applied': True, 'message': 'Saved settings requested; reconnecting destinations resume automatically.'})
            except (AudioError, NetworkError) as error:
                results.append({'name': saved['name'], 'applied': False, 'message': str(error)})
        return {'results': results}

    def remember(self, inventory, destination):
        with database(self.path) as db:
            for row in inventory['destinations']:
                if row['id'] == destination and row.get('source_id') and row.get('available'):
                    db.execute('INSERT INTO assignment VALUES (?,?) ON CONFLICT DO UPDATE SET data=excluded.data',
                               (row['id'], json.dumps({k: row[k] for k in ('source_id', 'volume', 'muted', 'name')})))

    def decorate(self, inventory):
        with database(self.path) as db:
            saved = {key: json.loads(data) for key, data in db.execute('SELECT destination,data FROM assignment')}
        for row in inventory['destinations']:
            intent = saved.get(row['id'])
            if not intent:
                continue
            if not row.get('available'):
                row.update(intent)
                row['volume'] = intent['volume']
                row['message'] = row.get('message') or 'This destination is disconnected. Saved settings resume when it reconnects.'
            elif not any(s['id'] == intent['source_id'] and s['status'] != 'disabled' for s in inventory['sources']):
                row.update(playback_available=False, message='The saved source is unavailable. Choose another source or wait for it to reconnect.')

    def recover_local(self):
        with database(self.path) as db:
            saved = {key: json.loads(data) for key, data in db.execute('SELECT destination,data FROM assignment')}
        if not saved:
            return
        inventory = self.coordination.local()
        for key, intent in saved.items():
            row = next((d for d in inventory['destinations'] if d['id'] == key), None)
            if not row or not row.get('available'):
                continue
            if not any(s['id'] == intent['source_id'] and s['status'] != 'disabled' for s in inventory['sources']):
                continue
            if row['source_id'] != intent['source_id']:
                self.coordination.audio.change(key, source_id=intent['source_id'])
            if row['volume'] != intent['volume'] or row['muted'] != intent['muted']:
                self.coordination.audio.change(key, percent=intent['volume'], muted=intent['muted'])
            if row['name'] != intent['name']:
                self.coordination.audio.rename(key, intent['name'])
