"""Password/session behavior independent of audio and the web framework."""
import sqlite3
import tempfile
import time
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import unittest
from pathlib import Path
from unittest.mock import patch

from flowharmonic.security import Authentication, SignInError, needs_password


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.auth = Authentication(self.directory)
        self.password = 'remember this test passphrase'

    def tearDown(self):
        self.temp.cleanup()

    def test_password_change_revokes_sessions_and_stores_only_hashes(self):
        self.assertTrue(needs_password(self.directory))
        self.auth.set_password(self.password)
        self.assertFalse(needs_password(self.directory))
        token = self.auth.sign_in(self.password)
        self.assertTrue(self.auth.authenticated(token))
        with sqlite3.connect(self.auth.path) as db:
            self.assertNotEqual(db.execute('SELECT hash FROM session').fetchone()[0], token)
        self.assertNotIn(token.encode(), self.auth.path.read_bytes())
        self.assertNotIn(self.password.encode(), self.auth.path.read_bytes())
        self.auth.set_password('a new management passphrase')
        self.assertFalse(self.auth.authenticated(token))
        self.assertFalse((self.directory / 'control.key').exists())

    def test_failed_password_change_is_atomic(self):
        self.auth.set_password(self.password)
        token = self.auth.sign_in(self.password)
        with self.assertRaises(ValueError):
            self.auth.set_password('short')
        with sqlite3.connect(self.auth.path) as db:
            db.execute("CREATE TRIGGER reject_session_delete BEFORE DELETE ON session BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.auth.set_password('a new management passphrase')
        self.assertTrue(self.auth.authenticated(token))
        with sqlite3.connect(self.auth.path) as db:
            db.execute('DROP TRIGGER reject_session_delete')
        self.assertTrue(self.auth.authenticated(self.auth.sign_in(self.password)))

    def test_concurrent_old_password_login_cannot_outlive_reset(self):
        from flowharmonic.security import password_hash
        self.auth.set_password(self.password)
        other = Authentication(self.directory)
        verifying = threading.Event()
        release = threading.Event()
        def delayed_hash(password, salt):
            if password == self.password:
                verifying.set()
                if not release.wait(5):
                    raise RuntimeError('Test verification was not released')
            return password_hash(password, salt)
        with patch('flowharmonic.security.password_hash', side_effect=delayed_hash), ThreadPoolExecutor(max_workers=2) as pool:
            login = pool.submit(self.auth.sign_in, self.password)
            self.assertTrue(verifying.wait(5))
            reset = pool.submit(other.set_password, 'replacement concurrent passphrase')
            try:
                reset.result(timeout=1)
            except TimeoutError:
                pass
            finally:
                release.set()
            token = login.result(timeout=5)
            reset.result(timeout=5)
        self.assertFalse(self.auth.authenticated(token))
        self.assertTrue(self.auth.authenticated(self.auth.sign_in('replacement concurrent passphrase')))

    def test_sign_in_rate_limit_and_recovery(self):
        self.auth.set_password(self.password)
        now = time.monotonic()
        with patch('flowharmonic.security.time.monotonic', return_value=now):
            for _ in range(8):
                with self.assertRaises(SignInError) as error:
                    self.auth.sign_in('wrong password')
                self.assertEqual(error.exception.status, 401)
            with self.assertRaises(SignInError) as error:
                self.auth.sign_in(self.password)
            self.assertEqual(error.exception.status, 429)
        with patch('flowharmonic.security.time.monotonic', return_value=now + 61):
            self.assertTrue(self.auth.authenticated(self.auth.sign_in(self.password)))

    def test_unknown_store_is_refused_without_reset(self):
        with sqlite3.connect(self.auth.path) as db:
            db.execute('PRAGMA user_version = 99')
        before = self.auth.path.read_bytes()
        with self.assertRaises(RuntimeError):
            Authentication(self.directory)
        self.assertEqual(self.auth.path.read_bytes(), before)

    def test_signed_out_and_invalid_tokens_are_rejected(self):
        self.auth.set_password(self.password)
        token = self.auth.sign_in(self.password)
        self.assertFalse(self.auth.authenticated(''))
        self.assertFalse(self.auth.authenticated('x' * 129))
        self.assertFalse(self.auth.authenticated('x' * 43))
        self.auth.sign_out(token)
        self.assertFalse(Authentication(self.directory).authenticated(token))


if __name__ == '__main__':
    unittest.main()
