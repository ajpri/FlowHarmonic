"""Read-only local diagnostics. No repair commands, log contents, or credentials."""
import json
import os
import re
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path

from . import VERSION
from .local_audio import local_inventory
from .snapcast import AudioError, Snapcast
from .state import identity, node_name


SERVICE_PROPERTIES = 'Id,ActiveState,SubState,UnitFileState,Result,NRestarts'


def service_status(units):
    """One bounded, read-only systemd query. Unit names never come from HTTP."""
    try:
        result = subprocess.run(['systemctl', 'show', '--no-pager', '--property=' + SERVICE_PROPERTIES, '--', *units],
                                capture_output=True, text=True, timeout=3)
        observed = {}
        for block in result.stdout.split('\n\n'):
            values = dict(line.split('=', 1) for line in block.splitlines() if '=' in line)
            if values.get('Id') in units:
                observed[values['Id']] = values
        return [{'unit': unit, 'name': label, 'state': observed.get(unit, {}).get('ActiveState', 'unknown'),
                 'detail': observed.get(unit, {}).get('SubState', 'Status unavailable'),
                 'startup': observed.get(unit, {}).get('UnitFileState', 'unknown'),
                 'result': observed.get(unit, {}).get('Result', ''),
                 'restarts': observed.get(unit, {}).get('NRestarts', '0')} for unit, label in units.items()]
    except (OSError, subprocess.SubprocessError):
        return [{'unit': unit, 'name': label, 'state': 'unknown',
                 'detail': 'Service status is unavailable. Use sudo flowharmonic logs on this node.'}
                for unit, label in units.items()]


def report(config, database_path, audio=None, build=None):
    checks = []
    def check(name, state, detail):
        checks.append({'name': name, 'state': state, 'detail': detail})
    node = {'version': VERSION, 'build': build or VERSION, 'name': config['name']}
    network_path = database_path.parent / 'network.db'
    if network_path.exists():
        try:
            with closing(sqlite3.connect(f'{network_path.resolve().as_uri()}?mode=ro', uri=True)) as db:
                if db.execute('PRAGMA user_version').fetchone()[0] != 1:
                    raise ValueError('Unsupported network settings')
                raw = db.execute('SELECT membership FROM settings WHERE id=1').fetchone()[0]
                membership = json.loads(raw) if raw else None
            check('System membership', 'ok', membership['name'] if membership else 'Independent node')
        except (sqlite3.Error, ValueError, TypeError, KeyError):
            check('System membership', 'unavailable', 'Stored network settings are unavailable or incompatible. They have not been reset.')
    try:
        with closing(sqlite3.connect(f'{database_path.resolve().as_uri()}?mode=ro', uri=True, timeout=3)) as db:
            intact = db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
            settings = db.execute('SELECT version FROM local_settings WHERE id=1').fetchone()
            if not settings or settings[0] != 1:
                raise ValueError('Unsupported local settings schema')
        node['identity'] = identity(database_path)
        node['name'] = node_name(database_path, config['name'])
        check('Local configuration', 'ok' if intact else 'unavailable',
              'Identity and node settings are stored persistently.' if intact else 'Database integrity needs attention. Restore a backup before reinstalling.')
    except (OSError, sqlite3.Error, TypeError, ValueError):
        check('Local configuration', 'unavailable', 'Local settings could not be read. Inspect the application logs; do not reset the node.')
    etc = Path(os.environ.get('FLOWHARMONIC_CONFIG', '/etc/flowharmonic/config.toml')).parent
    units = {'flowharmonic.service': 'Application', 'flowharmonic-audio.timer': 'Local audio detection',
             'flowharmonic-audio.service': 'Local audio setup'}
    try:
        with (etc / 'infrastructure.json').open() as reader:
            ownership = json.loads(reader.read(8192))
        local = json.loads((etc / 'local-audio.json').read_text())
        managed = ownership.get('server') == 'flowharmonic' and ownership.get('client') == 'flowharmonic'
        check('Audio infrastructure', 'ok', 'Local audio components were provisioned by FlowHarmonic.' if managed else 'Existing infrastructure is controlled without changing its services or configuration.')
        if local.get('owner') == node.get('identity') and local.get('endpoint') == config['snapcast_url']:
            for unit in local.get('owned_units', []):
                if (unit == 'flowharmonic-snapserver.service' or re.fullmatch(r'flowharmonic-playback-[a-f0-9]{20}\.service', unit)):
                    units[unit] = 'Local audio server' if unit == 'flowharmonic-snapserver.service' else 'Local hardware playback'
            unit = local.get('desktop', {}).get('unit', '')
            if isinstance(unit, str) and re.fullmatch(r'flowharmonic-desktop-[0-9]+\.service', unit):
                units[unit] = 'Desktop audio session'
            if local.get('message'):
                check('Local audio setup', 'warning', str(local['message']))
    except (OSError, ValueError, TypeError, AttributeError):
        check('Audio infrastructure', 'warning', 'Local provisioning status is unavailable. Existing audio can still be controlled.')
    try:
        view = local_inventory((audio or Snapcast(config['snapcast_url'])).snapshot(), node.get('identity'), config['snapcast_url'])
        available = sum(d['available'] for d in view['destinations'])
        check('Audio connection', 'ok', f"{len(view['sources'])} sources; {available} connected destinations.")
        check('Audio settings', 'ok', 'Names, routing, volume and mute are stored by the audio server. Disk writes may take a few seconds.')
        for source in view['sources']:
            if source['status'] == 'disabled' and source.get('message'):
                check(source['name'], 'warning', source['message'])
        for destination in view['destinations']:
            if not destination['available']:
                check(destination['name'], 'warning', destination.get('message', 'This destination is disconnected. Its settings are retained.'))
    except AudioError as error:
        check('Audio connection', 'unavailable', str(error))
    return {'node': node, 'audio_endpoint': config['snapcast_url'], 'checks': checks,
            'services': service_status(dict(list(units.items())[:32]))}
