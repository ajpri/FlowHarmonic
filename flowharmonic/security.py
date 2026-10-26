"""Local password and remembered browser sessions, outside replaceable releases."""
import hashlib
import os
import secrets
import sqlite3
import threading
import time
from collections import deque

from .state import database

COOKIE_AGE = 365 * 24 * 60 * 60


def password_hash(password, salt):
    # OWASP's low-memory scrypt profile; use the standard library on small nodes.
    return hashlib.scrypt(password.encode('utf-8'), salt=salt, n=2**14, r=8, p=5,
                          maxmem=32 * 1024 * 1024, dklen=32)


class SignInError(Exception):
    def __init__(self, message, status=401):
        super().__init__(message)
        self.status = status


class Authentication:
    def __init__(self, directory):
        self.directory = directory
        self.path = directory / 'authentication.db'
        # Credentials have their own small versioned store. The identity database
        # stays compatible with earlier milestone releases and application rollback.
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        self.path.chmod(0o600)
        with database(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise RuntimeError('Unsupported authentication database; restore a compatible backup')
            if version == 0:
                if db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                    raise RuntimeError('Unrecognized authentication database; refusing to reset it')
                db.execute('CREATE TABLE password (id INTEGER PRIMARY KEY CHECK(id=1), salt BLOB NOT NULL, hash BLOB NOT NULL)')
                db.execute('CREATE TABLE session (hash TEXT PRIMARY KEY, expires INTEGER NOT NULL)')
                db.execute('PRAGMA user_version = 1')
            db.execute('SELECT salt, hash FROM password LIMIT 0')
            db.execute('SELECT hash, expires FROM session LIMIT 0')
        self._password_lock = threading.Lock()
        self._failures = deque()

    def configured(self):
        with database(self.path) as db:
            return db.execute('SELECT 1 FROM password WHERE id=1').fetchone() is not None

    def authenticated(self, token):
        if not token or len(token) > 128:
            return False
        digest = hashlib.sha256(token.encode()).hexdigest()
        with database(self.path) as db:
            return db.execute('SELECT 1 FROM session WHERE hash=? AND expires>?',
                              (digest, int(time.time()))).fetchone() is not None

    @staticmethod
    def new_session(db):
        now = int(time.time())
        db.execute('DELETE FROM session WHERE expires<=?', (now,))
        token = secrets.token_urlsafe(32)
        db.execute('INSERT INTO session VALUES (?, ?)',
                   (hashlib.sha256(token.encode()).hexdigest(), now + COOKIE_AGE))
        return token

    def set_password(self, password):
        """Local maintenance only; replace credentials and revoke sessions atomically."""
        if not isinstance(password, str) or not 12 <= len(password) <= 128:
            raise ValueError('Use a password of 12–128 characters.')
        with self._password_lock:
            salt = secrets.token_bytes(16)
            digest = password_hash(password, salt)
            with database(self.path) as db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('INSERT INTO password VALUES (1, ?, ?) ON CONFLICT(id) DO UPDATE SET salt=excluded.salt, hash=excluded.hash',
                           (salt, digest))
                db.execute('DELETE FROM session')
            self._failures.clear()

    def sign_in(self, password):
        with self._password_lock:
            now = time.monotonic()
            while self._failures and self._failures[0] <= now - 60:
                self._failures.popleft()
            if len(self._failures) >= 8:
                raise SignInError('Too many sign-in attempts. Try again in a minute.', 429)
            with database(self.path) as db:
                # The CLI is a separate process. Serialize password verification
                # with resets so an old-password login cannot create a session
                # after the reset has revoked earlier sessions.
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT salt, hash FROM password WHERE id=1').fetchone()
                if row is None:
                    raise SignInError('Set the management password on this device with: sudo flowharmonic password.', 409)
                if not secrets.compare_digest(password_hash(password, row[0]), row[1]):
                    self._failures.append(now)
                    raise SignInError('That password is incorrect. Try again.')
                return self.new_session(db)

    def sign_out(self, token):
        with database(self.path) as db:
            db.execute('DELETE FROM session WHERE hash=?', (hashlib.sha256(token.encode()).hexdigest(),))


def needs_password(directory):
    """Read-only installer check; never create root-owned application files."""
    path = directory / 'authentication.db'
    if not path.exists():
        return True
    with sqlite3.connect(f'{path.resolve().as_uri()}?mode=ro', uri=True) as db:
        return db.execute('SELECT 1 FROM password WHERE id=1').fetchone() is None
