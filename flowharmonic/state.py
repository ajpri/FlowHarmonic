"""One SQLite database, outside the application release."""
import sqlite3
import uuid
from contextlib import contextmanager

from . import SCHEMA_VERSION


@contextmanager
def database(path):
    connection = sqlite3.connect(path, timeout=10)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize(directory):
    directory.mkdir(mode=0o750, parents=True, exist_ok=True)
    path = directory / "flowharmonic.db"
    with database(path) as db:
        # Serialize first startup; a second process must see the same identity.
        db.execute("BEGIN IMMEDIATE")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError("Database is newer than this application; refusing to modify it")
        if version == 0:
            existing = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if existing:
                raise RuntimeError("Unrecognized database; refusing to initialize over existing data")
            db.execute("CREATE TABLE node (id INTEGER PRIMARY KEY CHECK (id = 1), identity TEXT NOT NULL)")
            db.execute("INSERT INTO node VALUES (1, ?)", (str(uuid.uuid4()),))
            db.execute("PRAGMA user_version = 1")
        # Additive, independently versioned local settings. Older releases can
        # still read identity schema 1 and ignore this table during rollback.
        db.execute("CREATE TABLE IF NOT EXISTS local_settings (id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL, name TEXT)")
        db.execute("INSERT OR IGNORE INTO local_settings VALUES (1, 1, NULL)")
        if db.execute("SELECT version FROM local_settings WHERE id=1").fetchone()[0] != 1:
            raise RuntimeError("Local settings are newer than this application; refusing to modify them")
        row = db.execute("SELECT identity FROM node WHERE id = 1").fetchone()
        if row is None:
            raise RuntimeError("Database identity is missing; restore a backup instead of resetting")
        uuid.UUID(row[0])
    path.chmod(0o640)
    return path


def identity(path):
    with database(path) as db:
        return db.execute("SELECT identity FROM node WHERE id = 1").fetchone()[0]


def node_name(path, default):
    with database(path) as db:
        row = db.execute('SELECT name FROM local_settings WHERE id=1').fetchone()
        return row[0] if row and row[0] is not None else default


def validate_name(value):
    if not 1 <= len(value) <= 80:
        raise ValueError('Use a name of 1–80 characters without control characters.')
    value = value.strip()
    if not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('Use a name of 1–80 characters without control characters.')
    return value


def set_node_name(path, name):
    with database(path) as db:
        db.execute('UPDATE local_settings SET name=? WHERE id=1', (name,))
