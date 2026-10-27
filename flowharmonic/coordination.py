"""M7 central inventory and routing. Snapcast carries audio; FH issues operations."""
import copy
import ipaddress
import json
import os
import socket
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from .network import NetworkError
from .snapcast import AudioError
from .state import database, validate_name


def address(value):
    ip = ipaddress.ip_address(value)
    if not (ip.is_private or ip.is_loopback) or ip.is_unspecified or ip.is_multicast or ip.is_link_local:
        raise ValueError('Use a local-network audio address')
    return str(ip)


def route_address(peer):
    ip = ipaddress.ip_address(peer)
    with socket.socket(socket.AF_INET6 if ip.version == 6 else socket.AF_INET, socket.SOCK_DGRAM) as connection:
        connection.connect((str(ip), 9))
        return address(connection.getsockname()[0])


def split_id(value):
    try:
        node, local = value.split('/', 1)
        uuid.UUID(node)
        if not local or len(local) > 1024:
            raise ValueError()
        return node, local
    except (ValueError, AttributeError):
        raise AudioError('This source or destination is no longer available. Refresh the dashboard.', 404)


class Coordination:
    def __init__(self, membership, snapshot, audio, metadata=None):
        self.membership, self.snapshot, self.audio = membership, snapshot, audio
        self.path = membership.path.parent / 'coordination.db'
        self.metadata = metadata or (Path(os.environ.get('FLOWHARMONIC_CONFIG', '/etc/flowharmonic/config.toml')).parent / 'local-audio.json')
        self.stop_event = threading.Event()
        self.thread = None
        self.operation = threading.RLock()
        self.last_error = ''
        self.last_contact = 0
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        self.path.chmod(0o600)
        with database(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise RuntimeError('Coordination settings are newer than this application; refusing to reset them')
            if version == 0:
                if db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                    raise RuntimeError('Unrecognized coordination database; refusing to reset it')
                db.execute('CREATE TABLE visibility (source TEXT PRIMARY KEY, visible INTEGER NOT NULL)')
                db.execute('CREATE TABLE node (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
                db.execute('CREATE TABLE route (destination TEXT PRIMARY KEY, data TEXT NOT NULL)')
                db.execute('CREATE TABLE playback (destination TEXT PRIMARY KEY, data TEXT NOT NULL)')
                db.execute('PRAGMA user_version=1')
            for table, fields in [('visibility','source,visible'),('node','id,data'),('route','destination,data'),('playback','destination,data')]:
                db.execute(f'SELECT {fields} FROM {table} LIMIT 0')

        from .scenes import Scenes
        self.scenes = Scenes(self)

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True, name='fh-coordination')
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=8)

    def current(self):
        with database(self.membership.path) as db:
            return self.membership.current(db)

    def records(self, table):
        with database(self.path) as db:
            return {row[0]: json.loads(row[1]) for row in db.execute(f'SELECT * FROM {table}')}

    def put(self, table, key, value):
        with database(self.path) as db:
            db.execute(f'INSERT INTO {table} VALUES (?,?) ON CONFLICT DO UPDATE SET data=excluded.data', (key,json.dumps(value)))

    def local(self, inventory=None, strict=False):
        fresh = True
        try:
            inventory = self.snapshot() if inventory is None else inventory
        except AudioError as error:
            fresh = False
            if strict: raise
            inventory = copy.deepcopy(self.records('node').get(self.membership.node_id,{}).get('inventory',{'sources':[],'destinations':[]}))
            inventory['local_message']=str(error)
            for source in inventory['sources']: source.update(status='disabled',message=str(error))
            for dest in inventory['destinations']: dest.update(available=False,message=str(error))
        inventory = copy.deepcopy(inventory)
        try:
            metadata = json.loads(self.metadata.read_text())
            owned = metadata.get('owner') == self.membership.node_id and metadata.get('endpoint') == self.membership.config['snapcast_url']
            owned_ids = {row['id'] for row in metadata.get('destinations', [])} if owned else set()
            ready_ids = {row['id'] for row in metadata.get('destinations',[]) if not row.get('message')} if owned else set()
            infrastructure = json.loads((self.metadata.parent / 'infrastructure.json').read_text())
            export = owned and infrastructure.get('server') == 'flowharmonic' and infrastructure.get('client') == 'flowharmonic'
        except (OSError, ValueError, KeyError, TypeError):
            owned_ids, ready_ids, export = set(), set(), False
        with database(self.path) as db:
            visibility = dict(db.execute('SELECT source,visible FROM visibility'))
        for source in inventory['sources']:
            source['visible'] = bool(visibility.get(source['id'], True))
        for destination in inventory['destinations']:
            destination['owned'] = destination['id'] in owned_ids
            destination['ready'] = destination['id'] in ready_ids and not destination.get('message')
        server_host=urlsplit(self.membership.config['snapcast_url']).hostname
        transport_host=None
        if server_host not in ('127.0.0.1','localhost','::1'):
            transport_host=address(socket.getaddrinfo(server_host,None,type=socket.SOCK_STREAM)[0][4][0])
        inventory.update({'audio_available': fresh, 'identity': self.membership.node_id, 'name': self.membership.name,'transport_host':transport_host,
                          'exportable': bool(export), 'port': metadata.get('stream_port',1704) if export else self.membership.config.get('snapcast_stream_port',1704),
                          'web_port': self.membership.config['port']})
        if fresh:
            record = self.records('node').get(self.membership.node_id, {})
            record['inventory'] = inventory
            self.put('node', self.membership.node_id, record)
        return inventory

    def visibility(self, source, visible):
        if type(visible) is not bool or not any(s['id'] == source for s in self.local()['sources']):
            raise AudioError('That source is no longer available. Refresh the dashboard.', 404)
        with database(self.path) as db:
            db.execute('INSERT INTO visibility VALUES (?,?) ON CONFLICT DO UPDATE SET visible=excluded.visible',(source,int(visible)))
        return {'saved': True}

    def store_node(self, node, inventory, system, url=''):
        # The sender's authenticated identity overrides all advertised identities.
        if not isinstance(inventory, dict) or any(not isinstance(inventory.get(k), list) or len(inventory[k]) > 128 for k in ('sources','destinations')):
            raise NetworkError('This node returned an unsupported audio inventory.', 422)
        for source in inventory['sources']:
            if not isinstance(source.get('id'),str) or not 0 < len(source['id']) <= 1024 or type(source.get('visible')) is not bool:
                raise NetworkError('This node returned an unsupported source.', 422)
        for dest in inventory['destinations']:
            if (not isinstance(dest.get('id'),str) or not 0 < len(dest['id']) <= 1024 or type(dest.get('owned')) is not bool or
                    type(dest.get('volume')) is not int or not 0 <= dest['volume'] <= 100 or type(dest.get('muted')) is not bool):
                raise NetworkError('This node returned an unsupported destination.', 422)
        port = inventory.get('port',1704)
        if type(port) is not int or not 1 <= port <= 65535:
            raise NetworkError('This node returned an unsupported audio port.', 422)
        self.put('node',node,{'system':system,'inventory':inventory,'url':url,'seen':time.time()})

    def host_view(self):
        membership = self.current()
        if not self.membership.host(membership):
            raise NetworkError('This node is not the coordinator.')
        local = self.local()
        self.store_node(self.membership.node_id,local,membership['id'])
        with database(self.membership.path) as db:
            members = {row[0]:row[1] for row in db.execute('SELECT identity,name FROM peer')}
        members[self.membership.node_id] = self.membership.name
        records = self.records('node')
        routes = self.records('route')
        sources, candidates, nodes = [], [], []
        raw_clients = {}
        for node, name in members.items():
            record = records.get(node,{})
            online = record.get('system') == membership['id'] and time.time()-record.get('seen',0) < 20
            view = record.get('inventory',{}) if record.get('system') == membership['id'] else {}
            nodes.append({'id':node,'name':view.get('name',name),'available':online})
            for source in view.get('sources',[]):
                row = {**source,'id':node+'/'+source['id'],'node_id':node,'node_name':view.get('name',name)}
                if not online:
                    row.update(status='disabled',message='This source node is disconnected.')
                sources.append(row)
            for destination in view.get('destinations',[]):
                raw_clients[(node,destination['id'])] = {**destination,'available':online and destination['available']}
                candidates.append({**destination,'id':node+'/'+destination['id'],'node_id':node,'node_name':view.get('name',name),
                                   'source_id':node+'/'+destination['source_id'] if destination.get('source_id') else None,
                                   'available':online and destination['available']})
        owned_ids = {split_id(row['id'])[1] for row in candidates if row.get('owned')}
        destinations = []
        for destination in candidates:
            _, client = split_id(destination['id'])
            if not destination.get('owned') and client in owned_ids:
                continue  # A routed FH client is listed only under its hardware owner.
            intent = routes.get(destination['id'])
            if intent and intent['system'] == membership['id']:
                source_node, source_id = split_id(intent['source_id'])
                observed = raw_clients.get((source_node,client))
                if observed and observed['available']:
                    destination.update(name=observed['name'],volume=observed['volume'],muted=observed['muted'],
                                       source_id=source_node+'/'+observed['source_id'],available=True)
                else:
                    destination.update(source_id=intent['source_id'],volume=intent['percent'],muted=intent['muted'],available=bool(destination.get('ready')),
                                       playback_available=False,message='Connecting to the selected source.' if not intent.get('applied') else 'The selected source is unavailable. Choose another source or wait for it to reconnect.')
                if not next(n['available'] for n in nodes if n['id']==destination['node_id']):
                    destination.update(available=False,message='This destination node is disconnected. Existing playback may continue.')
                if not intent.get('applied'):
                    destination['message'] = intent.get('error') or 'Connecting to the selected source.'
                    destination['pending'] = True
            destinations.append(destination)
        return {'sources':[s for s in sources if s['visible']], 'all_sources':sources,'destinations':destinations,
                'nodes':nodes,'local_message':'','system_message':membership['name']+' · Coordinator connected'}

    def dashboard(self, inventory=None):
        membership = self.current()
        if not membership:
            view = self.local(inventory)
            self.scenes.decorate(view)
            view['all_sources'] = copy.deepcopy(view['sources'])
            view['sources'] = [s for s in view['sources'] if s['visible']]
            return view
        if self.membership.host(membership):
            return self.host_view()
        cache=self.records('node').get('system',{})
        cached = cache.get('inventory',{}) if cache.get('system')==membership['id'] else {}
        cached = cached or {'sources':[],'all_sources':[],'destinations':[],'nodes':[]}
        view = copy.deepcopy(cached)
        view['destinations'] = [d for d in view['destinations'] if d['node_id']==self.membership.node_id]
        if time.time()-self.last_contact > 20:
            view['system_message'] = 'Coordinator unavailable. Existing playback continues; new routing waits for reconnection. Node settings, diagnostics, and leaving the system remain available.'
            for destination in view['destinations']:
                destination.update(available=False,message='The coordinator is unavailable. Last known settings are shown.')
        return view

    def call_node(self, node, action, payload):
        membership = self.current()
        if node == self.membership.node_id:
            return self.control(action,payload)
        with database(self.membership.path) as db:
            peer = db.execute('SELECT public_key,enrollment FROM peer WHERE identity=?',(node,)).fetchone()
        record = self.records('node').get(node)
        if not peer or not record or record['system'] != membership['id']:
            raise NetworkError('This node has not connected to the coordinator yet.')
        return self.membership.send(record['url'],node,membership['id'],peer[0],'coord.control',
                                    {'enrollment':peer[1],'action':action,'change':payload})

    def control(self, action, payload):
        if action == 'source':
            view=self.local()
            source=next((s for s in view['sources'] if s['id']==payload['source']),None)
            if not source or not source['visible'] or source['status']=='disabled':
                raise AudioError('This source is hidden or unavailable.',409)
            return {'exportable':view['exportable']}
        if action == 'visibility':
            return self.visibility(payload['source'],payload['visible'])
        if action == 'playback':
            dest = payload['destination']
            if not any(d['id']==dest and d.get('owned') for d in self.local()['destinations']):
                raise AudioError('This destination is not provisioned by FlowHarmonic; its services were left unchanged.',409)
            target = dict(payload)
            target['host'] = address(target['host'])
            if type(target['port']) is not int or not 1 <= target['port'] <= 65535:
                raise AudioError('Invalid audio connection.',422)
            target['owner'] = self.membership.node_id
            target['system'] = self.current()['id']
            self.put('playback',dest,target)
            return {'accepted':True}
        if action == 'apply':
            destination = payload['destination']
            change = validate_change(payload['change'])
            if not any(d['id']==destination for d in self.audio.snapshot()['destinations']):
                raise AudioError('The destination is connecting to this source. Playback will retry automatically.',409)
            if 'name' in change:
                self.audio.rename(destination,validate_name(change['name']))
            if change.get('source_id') is not None:
                self.audio.change(destination,source_id=change['source_id'])
            if 'percent' in change or 'muted' in change:
                self.audio.change(destination,percent=change.get('percent'),muted=change.get('muted'))
            return {'applied':True}
        raise NetworkError('This coordinator operation is not supported.',422)

    def change(self, destination, change):
        with self.operation:
            return self._change(destination, change)

    def _change(self, destination, change):
        membership = self.current()
        if membership and not self.membership.host(membership):
            self.membership.send(membership['host_url'],membership['host_id'],membership['id'],membership['host_key'],
                'coord.command',{'enrollment':membership['enrollment'],'destination':destination,'change':change})
            self.tick()
            return self.dashboard()
        if not membership:
            if 'source_id' in change and not any(s['id']==change['source_id'] for s in self.dashboard()['sources']):
                raise AudioError('This source is hidden or unavailable.',409)
            if 'name' in change:
                result=self.audio.rename(destination,change['name'])
            elif 'source_id' in change:
                result=self.audio.change(destination,source_id=change['source_id'])
            else:
                result=self.audio.change(destination,percent=change.get('percent'),muted=change.get('muted'))
            self.scenes.remember(result, destination)
            return self.dashboard(result)
        with self.operation:
            view = self.host_view()
            target = next((d for d in view['destinations'] if d['id']==destination),None)
            if not target:
                raise AudioError('This destination is no longer available.',404)
            node, client = split_id(destination)
            if 'source_id' not in change:
                intent = self.records('route').get(destination)
                source_node = split_id(intent['source_id'])[0] if intent and intent['system']==membership['id'] else node
                if not intent or intent['system'] != membership['id'] or intent.get('applied'):
                    self.call_node(source_node,'apply',{'destination':client,'change':change})
                if (not intent or intent['system'] != membership['id']) and target.get('source_id'):
                    intent = {'system': membership['id'], 'source_id': target['source_id'], 'percent': target['volume'],
                              'muted': target['muted'], 'name': target['name'], 'applied': True}
                if intent and intent['system']==membership['id']:
                    if 'percent' in change: intent['percent']=change['percent']
                    if 'muted' in change: intent['muted']=change['muted']
                    if 'name' in change: intent['name']=change['name']
                    intent['generation']=str(uuid.uuid4())
                    self.put('route',destination,intent)
            else:
                source = next((s for s in view['sources'] if s['id']==change['source_id'] and s['status']!='disabled'),None)
                if not source:
                    raise AudioError('This source is hidden, disconnected, or unavailable. Choose another source.',409)
                source_node, source_id = split_id(source['id'])
                self.call_node(source_node,'source',{'source':source_id})
                if source_node == node and not target.get('owned'):
                    self.call_node(node,'apply',{'destination':client,'change':{'source_id':source_id}})
                    self.put('route', destination, {'system':membership['id'], 'source_id':source['id'], 'percent':target['volume'],
                                                   'muted':target['muted'], 'name':target['name'], 'applied':True, 'generation':str(uuid.uuid4())})
                else:
                    if not target.get('owned'):
                        raise AudioError('Cross-node routing requires an FH-provisioned destination. Existing audio services were retained.',409)
                    records = self.records('node')
                    transport=records[source_node]['inventory'].get('transport_host')
                    if transport:
                        host=address(transport)
                    elif source_node == node:
                        host = '127.0.0.1'
                    elif source_node == self.membership.node_id:
                        host = route_address(urlsplit(records[node]['url']).hostname)
                    else:
                        host = address(urlsplit(records[source_node]['url']).hostname)
                    intent = {'system':membership['id'],'source_id':source['id'],'percent':target['volume'],'muted':target['muted'],
                              'name':target['name'],'applied':False,'generation':str(uuid.uuid4())}
                    self.call_node(node,'playback',{'destination':client,'host':host,'port':records[source_node]['inventory'].get('port',1704),
                                                  'source_id':source['id'],'generation':intent['generation']})
                    self.put('route',destination,intent)
        return self.host_view()

    def set_visibility(self, source, visible):
        membership = self.current()
        if not membership:
            self.visibility(source,visible)
        elif self.membership.host(membership):
            with self.operation:
                node, local = split_id(source)
                self.call_node(node,'visibility',{'source':local,'visible':visible})
                record=self.records('node').get(node)
                if record:
                    for row in record['inventory']['sources']:
                        if row['id']==local: row['visible']=visible
                    self.put('node',node,record)
        else:
            self.membership.send(membership['host_url'],membership['host_id'],membership['id'],membership['host_key'],
                'coord.command',{'enrollment':membership['enrollment'],'visibility':{'source_id':source,'visible':visible}})
            self.tick()
        return {'saved':True}

    def receive(self, action, payload, sender, remote):
        membership = self.current()
        if action == 'coord.report':
            port = payload.get('inventory',{}).get('web_port')
            if type(port) is not int or not 1 <= port <= 65535:
                raise NetworkError('Invalid node address.',422)
            host = address(remote)
            url = 'http://'+('['+host+']' if ':' in host else host)+':'+str(port)
            self.store_node(sender,payload['inventory'],membership['id'],url)
            return self.host_view()
        if action == 'coord.command':
            if 'visibility' in payload:
                change=payload['visibility'];node, source=split_id(change['source_id'])
                if node != sender: raise NetworkError('Manage source visibility on its node or the coordinator.',403)
                return self.set_visibility(change['source_id'],change['visible'])
            destination=payload['destination']
            if split_id(destination)[0] != sender:
                raise NetworkError('Local node controls can change only this node’s destinations.',403)
            self.change(destination,validate_change(payload['change']))
            return {'accepted':True}
        if action == 'coord.control':
            return self.control(payload['action'],payload['change'])
        raise NetworkError('Unsupported coordinator operation.',422)

    def tick(self):
        membership = self.current()
        if not membership:
            with self.operation:
                self.scenes.recover_local()
            return
        if not self.membership.host(membership):
            result = self.membership.send(membership['host_url'],membership['host_id'],membership['id'],membership['host_key'],'coord.report',
                {'enrollment':membership['enrollment'],'inventory':self.local()})
            self.put('node','system',{'system':membership['id'],'inventory':result})
            self.last_contact = time.time()
            self.last_error = ''
            return
        self.host_view()
        for destination, intent in self.records('route').items():
            if intent['system'] != membership['id']:
                continue
            # Reapply saved intent after clients or servers restart.
            source_node, source_id = split_id(intent['source_id'])
            _, client = split_id(destination)
            record = self.records('node').get(source_node, {})
            actual = next((d for d in record.get('inventory', {}).get('destinations', []) if d['id'] == client), None)
            if (intent.get('applied') and actual and actual.get('available') and
                    actual.get('source_id') == source_id and actual.get('volume') == intent['percent'] and
                    actual.get('muted') == intent['muted'] and actual.get('name') == intent['name']):
                continue
            source_node, source_id = split_id(intent['source_id'])
            _, client = split_id(destination)
            try:
                with self.operation:
                    current=self.records('route').get(destination,{})
                    if current.get('generation')!=intent['generation']: continue
                    self.call_node(source_node,'apply',{'destination':client,'change':{'source_id':source_id,'percent':intent['percent'],
                                                                                'muted':intent['muted'],'name':intent['name']}})
                    intent.update(applied=True,error='')
            except (AudioError,NetworkError) as error:
                intent['error']=str(error)
            # A concurrent newer command must never be replaced by an old retry.
            with database(self.path) as db:
                current = db.execute('SELECT data FROM route WHERE destination=?',(destination,)).fetchone()
                if current and json.loads(current[0])['generation']==intent['generation']:
                    db.execute('UPDATE route SET data=? WHERE destination=?',(json.dumps(intent),destination))

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.tick()
                self.last_error = ''
            except (NetworkError,AudioError,OSError,ValueError,KeyError,TypeError,sqlite3.Error) as error:
                self.last_error = str(error)
            self.stop_event.wait(5)


def validate_change(change):
    if not isinstance(change,dict) or not change or set(change)-{'source_id','percent','muted','name'}:
        raise NetworkError('Unsupported audio change.',422)
    if 'source_id' in change and (not isinstance(change['source_id'],str) or len(change['source_id'])>1100):
        raise NetworkError('Invalid source.',422)
    if 'percent' in change and (type(change['percent']) is not int or not 0 <= change['percent'] <= 100):
        raise NetworkError('Invalid volume.',422)
    if 'muted' in change and type(change['muted']) is not bool:
        raise NetworkError('Invalid mute setting.',422)
    if 'name' in change:
        change['name']=validate_name(change['name'])
    return change
