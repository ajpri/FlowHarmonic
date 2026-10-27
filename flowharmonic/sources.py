"""Local M8 source preferences. Snapcast continues to own transport and routing."""
import json
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path

from .state import database, validate_name
from .snapcast import AudioError

KINDS = ('input', 'music', 'bluetooth')
STATES = ('stopped', 'playing', 'paused')
EXTENSIONS = {'.wav', '.flac', '.ogg', '.opus', '.mp3', '.m4a'}


def validate(value):
    if not isinstance(value, dict) or set(value)-{'id','name','kind','device','channels','folder','track','state'}:
        raise ValueError('Unsupported source settings.')
    value = dict(value)

    if not isinstance(value['id'],str) or str(uuid.UUID(value['id']))!=value['id']:raise ValueError('Invalid source identity.')
    value['name'] = validate_name(value['name'])
    if value['kind'] not in KINDS or value['state'] not in STATES:
        raise ValueError('Choose a supported source type and playback state.')
    fields={'id','name','kind','state'} | ({'folder','track'} if value['kind']=='music' else {'device','channels'} if value['kind']=='input' else {'device'})
    if set(value)-fields:raise ValueError('These settings do not apply to this source type.')
    if value['state']=='paused' and value['kind']!='music':
        raise ValueError('Only music sources support pause.')
    if value['kind']=='music':
        folder=value.get('folder','')
        if not isinstance(folder,str) or not Path(folder).is_absolute() or len(folder)>2048 or any(ord(c)<32 for c in folder):
            raise ValueError('Enter an absolute local music folder path.')
        track=value.get('track','')
        if not isinstance(track,str) or len(track)>2048 or (track and (Path(track).is_absolute() or '..' in Path(track).parts or Path(track).suffix.lower() not in EXTENSIONS)):
            raise ValueError('Choose a track inside the selected music folder.')
    else:
        device=value.get('device','')
        if not isinstance(device,str) or len(device)>512 or not device or any(ord(c)<32 for c in device):
            raise ValueError('Choose an input device.')
        if value['kind']=='bluetooth' and not re.fullmatch(r'(?:[0-9A-F]{2}:){5}[0-9A-F]{2}',device):
            raise ValueError('Choose a paired Bluetooth device.')
        if value['kind']=='input':
            channels=value.get('channels')
            if not isinstance(channels,list) or len(channels) not in (1,2) or any(type(c) is not int or not 1<=c<=32 for c in channels) or len(set(channels))!=len(channels):
                raise ValueError('Choose one channel or a pair of distinct channels (1–32).')
    return value


class Sources:
    def __init__(self, directory):
        self.path=Path(directory)/'sources.db'
        fd=os.open(self.path,os.O_CREAT|os.O_RDWR,0o600);os.close(fd);self.path.chmod(0o600)
        with database(self.path) as db:
            version=db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0,1):raise RuntimeError('Source settings are newer than this application; refusing to reset them.')
            if version==0:
                if db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():raise RuntimeError('Unrecognized source database; refusing to reset it.')
                db.executescript('CREATE TABLE source (id TEXT PRIMARY KEY, data TEXT NOT NULL); CREATE TABLE bluetooth (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL); PRAGMA user_version=1;')
            db.execute('SELECT id,data FROM source LIMIT 0');db.execute('SELECT id,data FROM bluetooth LIMIT 0')

    def rows(self):
        with database(self.path) as db:return [validate(json.loads(r[0])) for r in db.execute('SELECT data FROM source ORDER BY rowid')]

    def save(self, value):
        value=validate(value)
        with database(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT count(*) FROM source').fetchone()[0]>=32 and not db.execute('SELECT id FROM source WHERE id=?',(value['id'],)).fetchone():
                raise AudioError('This node already has 32 configured sources.',409)
            db.execute('INSERT INTO source VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',(value['id'],json.dumps(value)))
        return {'saved':True,'id':value['id']}

    def remove(self, identifier):
        uuid.UUID(identifier)
        with database(self.path) as db:db.execute('DELETE FROM source WHERE id=?',(identifier,))
        return {'saved':True}

    def bluetooth(self, command=None):
        with database(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT data FROM bluetooth WHERE id=1').fetchone()
            data=json.loads(row[0]) if row else {}
            if command is not None:
                action=command.get('action')
                if set(command)-{'action','device','accept','confirmation'} or action not in ('pairing','close','confirm','connect','disconnect','forget'):
                    raise ValueError('Unsupported Bluetooth action.')
                if action in ('connect','disconnect','forget') and not re.fullmatch(r'(?:[0-9A-F]{2}:){5}[0-9A-F]{2}',command.get('device','')):
                    raise ValueError('Choose a Bluetooth device.')
                if action=='confirm' and (type(command.get('accept')) is not bool or not re.fullmatch(r'[a-f0-9]{64}',command.get('confirmation',''))):raise ValueError('Confirm or reject the displayed pairing code.')
                data={**command,'nonce':str(uuid.uuid4()),'expires':time.time()+120}
                db.execute('INSERT INTO bluetooth VALUES (1,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',(json.dumps(data),))
                # Only this non-secret command is shared with the capability-free
                # pairing service. Passwords, keys and source preferences stay 0600.
                path=self.path.parent/'bluetooth-request.json'
                try:
                    previous=json.loads(path.read_text())
                    queue=previous.get('requests',[previous]) if isinstance(previous,dict) else []
                    if not isinstance(queue,list):queue=[]
                except (OSError,ValueError):queue=[]
                acknowledged=read_status('/run/flowharmonic-bluetooth/status.json').get('handled',[])
                queue=[r for r in queue if isinstance(r,dict) and type(r.get('expires')) in (int,float) and r['expires']>time.time() and r.get('nonce') not in acknowledged]
                if len(queue)>=8:raise AudioError('Bluetooth requests are waiting. Check its status and try again shortly.',429)
                temporary=path.with_suffix('.next')
                temporary.write_text(json.dumps({'requests':queue+[data]}))
                temporary.chmod(0o640);temporary.replace(path)
            return data


def tracks(folder):
    base=Path(folder).resolve(strict=True)
    if not base.is_dir():raise ValueError('The music folder is unavailable.')
    result=[]
    # Bounded scan, no symlink traversal and no automatic filesystem changes.
    visited=0
    for parent, directories, files in os.walk(base,followlinks=False):
        directories[:]=sorted(d for d in directories if not (Path(parent)/d).is_symlink())
        for name in sorted(files):
            visited+=1
            if visited>20000:raise ValueError('This folder has too many files. Select a smaller music folder.')
            path=Path(parent)/name
            if not path.is_symlink() and path.suffix.lower() in EXTENSIONS:result.append(str(path.relative_to(base)))
            if len(result)>2000:raise ValueError('This folder has more than 2,000 tracks. Select a smaller music folder.')
    return sorted(result)


def read_status(path):
    try:
        value=json.loads(Path(path).read_text())
        if not 0<=time.time()-value['updated']<12:raise ValueError()
        return value
    except (OSError,ValueError,KeyError,TypeError):return {'available':False,'message':'Source is starting or unavailable. Setup retries automatically.'}
