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


def backup(database, destination, identity_database=True, network_database=False):
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
        if network_database:
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
    else:
        raise SystemExit('Unknown installer state command')
