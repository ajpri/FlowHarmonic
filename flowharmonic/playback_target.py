"""Read-only root provisioning boundary: network targets for FH-owned players only."""
import ipaddress
import json
import sqlite3
from contextlib import closing


def target(root, node, destination, port):
    default=('127.0.0.1',port)
    path=root/'var/lib/flowharmonic/coordination.db'
    if not path.exists():
        return default
    try:
        with closing(sqlite3.connect(f'{(root/"var/lib/flowharmonic/network.db").resolve().as_uri()}?mode=ro',uri=True,timeout=1)) as db:
            raw=db.execute('SELECT membership FROM settings WHERE id=1').fetchone()[0]
            membership=json.loads(raw) if raw else None
        with closing(sqlite3.connect(f'{path.resolve().as_uri()}?mode=ro',uri=True,timeout=1)) as db:
            if db.execute('PRAGMA user_version').fetchone()[0] != 1:
                return default
            row=db.execute('SELECT data FROM playback WHERE destination=?',(destination,)).fetchone()
        if not row or not membership:
            return default
        value=json.loads(row[0]);ip=ipaddress.ip_address(value['host'])
        if (value['owner']!=node or value['system']!=membership['id'] or type(value['port']) is not int or not 1<=value['port']<=65535 or
                not (ip.is_private or ip.is_loopback) or ip.is_multicast or ip.is_unspecified or ip.is_link_local):
            return default
        return str(ip),value['port']
    except (OSError,sqlite3.Error,ValueError,KeyError,TypeError):
        return default


def joined(root):
    try:
        path=root/'var/lib/flowharmonic/network.db'
        with closing(sqlite3.connect(f'{path.resolve().as_uri()}?mode=ro',uri=True,timeout=1)) as db:
            return bool(db.execute('SELECT membership FROM settings WHERE id=1').fetchone()[0])
    except (OSError,sqlite3.Error,TypeError):
        return False
