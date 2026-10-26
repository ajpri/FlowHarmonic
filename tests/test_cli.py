"""CLI uses hidden input, requires local administrative access, and preserves state."""
import getpass
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from flowharmonic import cli
from flowharmonic.security import Authentication
from flowharmonic.state import identity, initialize, node_name


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.auth = Authentication(self.directory)
        self.password = 'original management passphrase'
        self.auth.set_password(self.password)
        self.token = self.auth.sign_in(self.password)
        self.environment = patch.dict(os.environ, {'FLOWHARMONIC_DATA_DIR': str(self.directory)})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def test_password_change_is_hidden_confirmed_and_revokes_sessions(self):
        with patch.object(cli.sys, 'stdin', Mock(isatty=lambda: True)), patch.object(cli.sys, 'stdout', Mock(isatty=lambda: True)), \
             patch.object(cli.os, 'geteuid', return_value=0), patch.object(cli, 'become_service_user') as drop, \
             patch.object(cli.getpass, 'getpass', side_effect=['different', 'mismatch', 'replacement management passphrase', 'replacement management passphrase']) as prompt:
            cli.main(['password'])
        drop.assert_called_once_with(self.directory)
        self.assertEqual(prompt.call_count, 4)
        self.assertFalse(self.auth.authenticated(self.token))
        self.assertTrue(self.auth.authenticated(self.auth.sign_in('replacement management passphrase')))

    def test_cancel_and_unsafe_input_leave_password_and_sessions_unchanged(self):
        for error in (EOFError(), KeyboardInterrupt(), getpass.GetPassWarning('No protected input')):
            with self.subTest(error=type(error).__name__):
                with patch.object(cli.sys, 'stdin', Mock(isatty=lambda: True)), patch.object(cli.sys, 'stdout', Mock(isatty=lambda: True)), \
                     patch.object(cli.os, 'geteuid', return_value=0), patch.object(cli.getpass, 'getpass', side_effect=error), \
                     self.assertRaises(SystemExit):
                    cli.main(['password'])
                self.assertTrue(self.auth.authenticated(self.token))

    def test_unprivileged_password_restart_and_logs_are_refused(self):
        with patch.object(cli.sys, 'stdin', Mock(isatty=lambda: True)), patch.object(cli.sys, 'stdout', Mock(isatty=lambda: True)), \
             patch.object(cli.os, 'geteuid', return_value=1000), patch.object(cli.getpass, 'getpass') as prompt, patch.object(cli.subprocess, 'run') as run:
            for command in ('password', 'restart', 'logs', 'diagnostics', 'name'):
                with self.assertRaises(SystemExit) as error:
                    cli.main([command])
                self.assertEqual(error.exception.code, 1)
        prompt.assert_not_called()
        run.assert_not_called()
        self.assertTrue(self.auth.authenticated(self.token))

    def test_name_persists_without_service_or_credentials_changes(self):
        path = initialize(self.directory)
        original_identity = identity(path)
        with patch.object(cli.os, 'geteuid', return_value=0), patch.object(cli, 'become_service_user') as drop, \
             patch.object(cli, 'load_config', return_value={'name': 'Original'}), \
             patch('builtins.print') as output, patch.object(cli.subprocess, 'run') as run:
            cli.main(['name'])
            output.assert_called_with('Original')
            cli.main(['name', '  Living Room  '])
            output.assert_called_with('Living Room')
            cli.main(['name'])
            output.assert_called_with('Living Room')
        self.assertEqual(drop.call_count, 3)
        run.assert_not_called()
        self.assertEqual(node_name(initialize(self.directory), 'Original'), 'Living Room')
        self.assertEqual(identity(path), original_identity)
        self.assertTrue(self.auth.authenticated(self.token))

    def test_invalid_name_and_missing_database_do_not_create_or_change_state(self):
        with patch.object(cli.os, 'geteuid', return_value=0), patch.object(cli, 'become_service_user') as drop, \
             patch.object(cli, 'load_config', return_value={'name': 'Original'}):
            for name in ('', '   ', 'x' * 81, 'two\nnames', 'bad\x7f'):
                with self.subTest(name=repr(name)), self.assertRaises(SystemExit):
                    cli.main(['name', name])
            with self.assertRaises(SystemExit):
                cli.main(['name', 'Living Room'])
            drop.assert_not_called()
        self.assertFalse((self.directory / 'flowharmonic.db').exists())
        self.assertTrue(self.auth.authenticated(self.token))

    def test_unattended_installer_does_not_prompt_or_change_existing_password(self):
        with patch.object(cli.sys, 'stdin', Mock(isatty=lambda: False)), patch.object(cli.getpass, 'getpass') as prompt:
            cli.main(['password', '--if-needed'])
        prompt.assert_not_called()
        self.assertTrue(self.auth.authenticated(self.token))
        with patch.object(cli.sys, 'stdin', Mock(isatty=lambda: False)), self.assertRaises(SystemExit):
            cli.main(['password'])

    def test_first_unattended_setup_remains_unconfigured(self):
        other = self.directory / 'new-node'
        other.mkdir()
        with patch.dict(os.environ, {'FLOWHARMONIC_DATA_DIR': str(other)}), patch.object(cli.sys, 'stdin', Mock(isatty=lambda: False)), patch.object(cli.getpass, 'getpass') as prompt:
            cli.main(['password', '--if-needed'])
        prompt.assert_not_called()
        self.assertFalse((other / 'authentication.db').exists())


if __name__ == '__main__':
    unittest.main()
