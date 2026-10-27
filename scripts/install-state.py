"""Installer-only state checks, ownership ledger, and consistent SQLite backups."""
import json
import sqlite3
import sys
from pathlib import Path


def record_ownership(path, server, client):
    path = Path(path)
    if path.exists():
        data = json.loads(path.read_text())
        for component in ('server', 'client'):
            if data.get(component) not in ('existing', 'flowharmonic'):
                raise ValueError('Invalid infrastructure ownership ledger')
    else:
        data = {'server': server, 'client': client}
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, indent=2) + '\n')
        temporary.chmod(0o644)
        temporary.replace(path)
    print(data['server'], data['client'])


def backup(database, destination, identity_database=True, network_database=False, coordination_database=False, sources_database=False, scenes_database=False):
    path = Path(database)
    if not path.exists():
        print('')
        return
    source = sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True)
    try:
        version = source.execute('PRAGMA user_version').fetchone()[0]
        if version != 1:
            raise RuntimeError(f'Unsupported database schema {version}; active release was not replaced')
        if source.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise RuntimeError('Database integrity check failed')
        identity = ''
        if scenes_database:
            source.execute('SELECT id,scope,name,data FROM scene LIMIT 0')
            source.execute('SELECT destination,data FROM assignment LIMIT 0')
        elif sources_database:
            source.execute('SELECT id,data FROM source LIMIT 0');source.execute('SELECT id,data FROM bluetooth LIMIT 0')
        elif coordination_database:
            for table, fields in [('visibility','source,visible'),('node','id,data'),('route','destination,data'),('playback','destination,data')]:
                source.execute(f'SELECT {fields} FROM {table} LIMIT 0')
        elif network_database:
            source.execute('SELECT private_key, membership, accepting FROM settings LIMIT 0')
            source.execute('SELECT identity, public_key, name, enrollment FROM peer LIMIT 0')
        elif identity_database:
            identity = source.execute('SELECT identity FROM node WHERE id=1').fetchone()[0]
        else:
            source.execute('SELECT salt, hash FROM password LIMIT 0')
            source.execute('SELECT hash, expires FROM session LIMIT 0')
        with sqlite3.connect(destination) as target:
            source.backup(target)
        Path(destination).chmod(0o600)
        print(identity)
    finally:
        source.close()


if __name__ == '__main__':
    if sys.argv[1] == 'ownership':
        record_ownership(*sys.argv[2:])
    elif sys.argv[1] == 'backup':
        backup(*sys.argv[2:])
    elif sys.argv[1] == 'backup-auth':
        backup(*sys.argv[2:], identity_database=False)
    elif sys.argv[1] == 'backup-network':
        backup(*sys.argv[2:], network_database=True)
    elif sys.argv[1] == 'backup-coordination':
        backup(*sys.argv[2:],coordination_database=True)
    elif sys.argv[1] == 'backup-sources':
        backup(*sys.argv[2:],sources_database=True)
    elif sys.argv[1] == 'backup-scenes':
        backup(*sys.argv[2:],scenes_database=True)
    else:
        raise SystemExit('Unknown installer state command')
