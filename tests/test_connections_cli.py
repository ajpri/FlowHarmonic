"""Terminal-only enrollment shares the web membership store and approval rules."""
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from flowharmonic import cli
from flowharmonic.connections_cli import check_code, confirm_action, text
from flowharmonic.network import Membership
from flowharmonic.state import initialize


class ConnectionsCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.nodes = {}
        for name in ('host', 'member'):
            directory = self.root / name
            path = initialize(directory)
            self.nodes[name] = Membership(directory, {'name': name, 'host': '0.0.0.0', 'port': 8080}, path)
        self.host, self.member = self.nodes.values()
        def exchange(url, path, body=None):
            node = self.nodes[url.removeprefix('http://')]
            return node.info() if path == '/peer/info' else node.receive(body)
        self.transport = patch('flowharmonic.network.exchange', side_effect=exchange)
        self.transport.start()
        self.addCleanup(self.transport.stop)

    def command(self, role, *args, success=True):
        node = self.nodes[role]
        output = io.StringIO()
        with patch.dict(os.environ, {'FLOWHARMONIC_DATA_DIR': str(node.path.parent)}), \
             patch.object(cli.os, 'geteuid', return_value=0), patch.object(cli, 'become_service_user') as drop, \
             patch.object(cli, 'load_config', return_value=node.config), contextlib.redirect_stdout(output):
            if success:
                cli.main(['connections', *args])
            else:
                with self.assertRaises(SystemExit) as error:
                    cli.main(['connections', *args])
                self.assertEqual(error.exception.code, 1)
        drop.assert_called_once_with(node.path.parent)
        return output.getvalue()

    def join(self):
        self.command('host', 'create', 'House')
        self.command('host', 'allow')
        self.command('member', 'join', 'http://host')
        request = self.member.view()['pending'][0]
        self.command('host', 'approve', request['id'], '--code', request['code'])
        self.command('member', 'confirm', '--code', request['code'])
        return request

    def test_terminal_join_two_approvals_wrong_code_and_shared_persistence(self):
        self.assertIn('Independent node', self.command('host'))
        self.command('host', 'create', 'House')
        self.command('host', 'allow')
        output = self.command('member', 'join', 'http://host')
        self.assertIn('Verification code:', output)
        request = self.member.view()['pending'][0]
        self.assertIn(request['id'], self.command('host', 'requests'))
        self.command('host', 'approve', request['id'], '--code', 'wrong', success=False)
        self.command('member', 'confirm', '--code', request['code'], success=False)
        self.assertEqual(self.host.view()['peers'], [])
        self.command('host', 'approve', request['id'], '--code', request['code'].lower())
        self.assertIsNone(self.member.view()['membership'])
        self.command('member', 'confirm', '--code', 'wrong', success=False)
        self.command('member', 'confirm', '--code', request['code'])
        self.assertEqual(self.host.view()['membership']['id'], self.member.view()['membership']['id'])
        self.assertIn('authenticated', self.command('member', 'refresh'))
        # New process objects (including the running web app) read the same state.
        restored = Membership(self.member.path.parent, self.member.config, self.member.identity_path)
        self.assertEqual(restored.view(), self.member.view())
        self.command('member', 'leave', '--yes')
        self.assertIsNone(self.member.view()['membership'])
        self.assertEqual(self.host.view()['peers'], [])
        self.command('host', 'leave', '--yes')

    def test_reject_cancel_remove_and_close(self):
        self.join()
        self.command('host', 'remove', self.member.node_id, '--yes')
        self.command('member', 'refresh', success=False)
        self.assertIsNone(self.member.view()['membership'])
        self.command('member', 'join', 'http://host')
        request = self.member.view()['pending'][0]
        self.command('host', 'reject', request['id'])
        self.assertIn('rejected', self.command('member', 'refresh'))
        self.command('member', 'cancel')
        self.command('host', 'close')
        self.command('member', 'join', 'http://host', success=False)
        self.assertFalse(self.host.view()['accepting'])

    def test_noninteractive_confirmation_required_and_terminal_output_is_safe(self):
        with patch('sys.stdin.isatty', return_value=False):
            with self.assertRaises(RuntimeError): check_code('ABCD EFGH', None)
            with self.assertRaises(RuntimeError): confirm_action('Leave?', False)
        self.assertNotIn('\x1b', text('Untrusted\x1b[2J\nnode'))
        self.assertNotIn('\n', text('Untrusted\nnode'))
        with patch('builtins.input', return_value='no'), patch('sys.stdin.isatty', return_value=True):
            with self.assertRaises(RuntimeError): confirm_action('Leave?', False)
        with patch('builtins.input', return_value='abcd efgh'), patch('sys.stdin.isatty', return_value=True):
            check_code('ABCD EFGH', None)
        self.command('host', 'create', 'House')
        with patch('sys.stdin.isatty', return_value=False):
            self.command('host', 'leave', success=False)
        self.assertIsNotNone(self.host.view()['membership'])

    def test_discovery_is_browse_only_and_unprivileged_access_is_refused(self):
        with patch('flowharmonic.connections_cli.Discovery') as discovery, patch('flowharmonic.connections_cli.time.sleep'):
            discovery.return_value.snapshot.return_value = {'nodes': [], 'message': 'No nearby nodes'}
            self.assertIn('manual connection', self.command('host', 'discover', '--wait', '1'))
            self.assertFalse(discovery.call_args.kwargs['advertise'])
            discovery.return_value.close.assert_called_once()
        with patch.object(cli.os, 'geteuid', return_value=1000), patch.object(cli, 'become_service_user') as drop:
            with self.assertRaises(SystemExit) as error:
                cli.main(['connections'])
            self.assertEqual(error.exception.code, 1)
            drop.assert_not_called()

    def test_web_and_cli_operations_use_an_interprocess_lock(self):
        # A fresh interpreter must wait until the current operation releases the
        # lock. The ready marker avoids timing assumptions about process startup.
        marker = self.root / 'ready'
        script = '''import pathlib,sys
from flowharmonic.network import Membership
p=pathlib.Path(sys.argv[1]); m=Membership(p,{'name':'member'},p/'flowharmonic.db')
pathlib.Path(sys.argv[2]).write_text('ready')
print(m.view()['membership'],flush=True)
'''
        with self.member.lock:
            with self.member.lock:  # CLI approval rechecks nest safely.
                process = subprocess.Popen([sys.executable, '-c', script, str(self.member.path.parent), str(marker)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    import time
                    deadline = time.monotonic() + 5
                    while not marker.exists() and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertTrue(marker.exists())
                    with self.assertRaises(subprocess.TimeoutExpired): process.communicate(timeout=.1)
                except BaseException:
                    process.kill(); process.communicate(); raise
        out, err = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 0, err)
        self.assertEqual(out.strip(), 'None')


if __name__ == '__main__':
    unittest.main()
