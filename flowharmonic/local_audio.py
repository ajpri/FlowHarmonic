"""Read root-owned provisioning results; the web process cannot provision hardware."""
import json
import os
import time
from pathlib import Path


def local_inventory(inventory, node_id, endpoint):
    path = Path(os.environ.get('FLOWHARMONIC_CONFIG', '/etc/flowharmonic/config.toml')).parent / 'local-audio.json'
    if not path.exists():
        return inventory
    try:
        status = json.loads(path.read_text())
        if status.get('endpoint') != endpoint:
            return inventory
        if status.get('owner') not in (None, node_id):
            return inventory
        inventory['local_message'] = status.get('message', '')
        desktop_inventory(inventory, status.get('desktop', {}))
        from .sources import read_status
        for row in status.get('sources',[]):
            source=next((s for s in inventory['sources'] if s['id']==row['id']),None)
            if source is None:
                source={'id':row['id'],'name':row['name'],'status':'disabled'}
                inventory['sources'].append(source)
            observed=read_status('/run/flowharmonic-source-'+row['id'].removeprefix('fh-source-')+'/status.json')
            source.update(name=row['name'],status='playing' if observed.get('available') and row['state']!='stopped' else 'disabled',message=observed.get('message','Unavailable.'))
        observed = {row['id']: row for row in inventory['destinations']}
        for row in status.get('destinations', []):
            if row['id'] in observed:
                if row.get('message'):
                    observed[row['id']]['available'] = False
                    observed[row['id']]['message'] = row['message']
                continue
            inventory['destinations'].append({'id': row['id'], 'name': row['name'], 'source_id': None,
                                              'volume': 0, 'muted': True, 'available': False,
                                              'message': row.get('message') or 'Local playback is starting or temporarily unavailable.'})
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        inventory['local_message'] = 'Local audio setup status is unavailable. Existing destinations remain controllable.'
    return inventory


def desktop_inventory(inventory, desktop):
    if not desktop:
        return
    source = next((s for s in inventory['sources'] if s['id'] == desktop.get('source')), None)
    message = desktop.get('message', 'Desktop audio is unavailable.')
    available = playback = False
    if desktop.get('session') and type(desktop.get('uid')) is int:
        try:
            # Construct the path from the root-owned UID, never a user-supplied path.
            path = Path(f"/run/flowharmonic-desktop-{desktop['uid']}/status.json")
            with path.open() as reader:
                observed = json.loads(reader.read(8192))
            fresh = 0 <= time.time() - observed['updated'] < 10
            available = fresh and observed.get('available') is True
            playback = fresh and observed.get('playback') is True
            message = observed.get('message', message) if fresh else 'Desktop audio stopped responding. Capture will retry automatically.'
        except (OSError, ValueError, TypeError, KeyError):
            message = 'Desktop audio is starting or unavailable. Capture will retry automatically.'
    if source:
        if not available:
            source['status'] = 'disabled'
        source['message'] = message
    elif desktop.get('source'):
        inventory['sources'].append({'id': desktop['source'], 'name': 'Desktop Audio', 'status': 'disabled', 'message': message})
    for destination in inventory['destinations']:
        if destination['id'] == desktop.get('destination') and not playback:
            destination['available'] = False
            destination['message'] = 'Desktop playback is unavailable. Check the desktop audio session.'
