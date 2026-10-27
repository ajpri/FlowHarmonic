"""Exercise the production installer in a rebased filesystem, without root.

This does NOT validate distribution package availability, systemd, or reboot.
"""
import json
import http.cookiejar
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        for directory in ('scripts', 'packaging', 'flowharmonic'):
            shutil.copytree(REPO / directory, self.source / directory, ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copy(REPO / 'requirements.txt', self.source)
        text = (REPO / 'installLinux.sh').read_text()
        for path in ('/etc/os-release', '/run/systemd/system', '/run/lock', '/opt/flowharmonic',
                     '/etc/flowharmonic', '/var/lib/flowharmonic', '/etc/systemd/system', '/usr/local/bin'):
            text = text.replace(path, str(self.root) + path)
        helper = self.source / 'scripts/snapcast-fedora.sh'
        helper_text = helper.read_text()
        for path in ('/opt/flowharmonic', '/etc/flowharmonic', '/var/lib/flowharmonic', '/etc/systemd/system', '/usr/local/bin'):
            helper_text = helper_text.replace(path, str(self.root) + path)
        helper.write_text(helper_text)
        launcher = self.source / 'packaging/flowharmonic'
        launcher.write_text(launcher.read_text().replace('/opt/flowharmonic', str(self.root) + '/opt/flowharmonic'))
        text = text.replace('[[ $EUID == 0 ]]', '[[ 1 == 1 ]]')
        self.script = self.source / 'installLinux.sh'
        self.script.write_text(text)
        for path in ('etc', 'run/systemd/system', 'run/lock', 'etc/systemd/system', 'etc/flowharmonic'):
            (self.root / path).mkdir(parents=True, exist_ok=True)
        (self.root / 'usr/bin').mkdir(parents=True)
        for name in ('snapserver', 'snapclient'):
            executable = self.root / 'usr/bin' / name
            executable.write_text('#!/bin/sh\nexit 0\n')
            executable.chmod(0o755)
        self.os_release = self.root / 'etc/os-release'
        self.os_release.write_text('ID=debian\nVERSION_ID=12\n')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            self.port = listener.getsockname()[1]
        (self.root / 'etc/flowharmonic/config.toml').write_text(f'name="Office"\nhost="127.0.0.1"\nport={self.port}\n')
        binary = self.root / 'bin'
        binary.mkdir()
        for command in ('apt-get', 'dnf', 'python3', 'id', 'useradd', 'chown', 'install', 'systemctl', 'sleep', 'restorecon', 'usermod', 'groupadd'):
            path = binary / command
            path.write_text(f'#!{sys.executable}\n' + (REPO / 'tests/installer_command.py').read_text().split('\n', 1)[1])
            path.chmod(0o755)
        self.env = {**os.environ, 'PATH': str(binary) + ':' + os.environ['PATH'],
                    'FH_TEST_ROOT': str(self.root), 'FH_TEST_PYTHON': sys.executable}
        self.env['FLOWHARMONIC_CONFIG'] = str(self.root / 'etc/flowharmonic/config.toml')
        self.env['FLOWHARMONIC_DATA_DIR'] = str(self.root / 'var/lib/flowharmonic')

    def tearDown(self):
        subprocess.run([str(self.root / 'bin/systemctl'), 'stop', 'flowharmonic.service'], env=self.env, capture_output=True)
        self.temp.cleanup()

    def run_installer(self, success=True):
        result = subprocess.run(['bash', str(self.script)], env=self.env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
        logs = (self.root / 'service.log').read_text() if (self.root / 'service.log').exists() else ''
        self.assertEqual(result.returncode == 0, success, result.stdout + logs)
        return result

    def node(self):
        from flowharmonic.security import Authentication
        for _ in range(50):
            try:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/health', timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)
        else:
            self.fail((self.root / 'service.log').read_text())
        auth = Authentication(self.root / 'var/lib/flowharmonic')
        if not auth.configured():
            auth.set_password('installer retention passphrase')
        browser = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        request = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/auth/sign-in',
            data=json.dumps({'password': 'installer retention passphrase'}).encode(),
            headers={'Content-Type': 'application/json', 'X-FlowHarmonic-Request': '1'})
        browser.open(request).close()
        return json.load(browser.open(f'http://127.0.0.1:{self.port}/api/node'))

    def test_install_reinstall_repair_and_failed_update(self):
        self.run_installer()
        original = self.node()
        launcher = self.root / 'usr/local/bin/flowharmonic'
        self.assertTrue(os.access(launcher, os.X_OK))
        self.assertEqual(subprocess.check_output([str(launcher), '--version'], env=self.env, cwd='/tmp', text=True).strip(), 'FlowHarmonic 26.10.27')
        self.assertIn('Examples:', subprocess.check_output([str(launcher)], env=self.env, cwd='/tmp', text=True))
        self.assertIn('Identity:', subprocess.check_output([str(launcher), 'status'], env=self.env, cwd='/tmp', text=True))
        legacy_key = self.root / 'var/lib/flowharmonic/control.key'
        legacy_key.write_text('an old local secret retained only for rollback\n')
        original_key = legacy_key.read_bytes()
        browser = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        request = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/auth/sign-in',
            data=json.dumps({'password': 'installer retention passphrase'}).encode(),
            headers={'Content-Type': 'application/json', 'X-FlowHarmonic-Request': '1'})
        self.assertTrue(json.load(browser.open(request))['authenticated'])

        current = self.root / 'opt/flowharmonic/current'
        first_release = current.resolve()
        config = self.root / 'etc/flowharmonic/config.toml'
        config.write_text(config.read_text().replace('Office', 'Kitchen'))
        (self.root / 'etc/systemd/system/flowharmonic.service').write_text('broken unit')
        # Repair a deleted application file while retaining SQLite and settings.
        (first_release / 'flowharmonic/static/style.css').unlink()
        self.run_installer()
        self.assertNotEqual(current.resolve(), first_release)
        self.assertEqual((self.root / 'var/lib/flowharmonic/control.key').read_bytes(), original_key)
        self.assertTrue((current / 'flowharmonic/static/style.css').exists())
        self.assertTrue(json.load(browser.open(f'http://127.0.0.1:{self.port}/api/auth'))['authenticated'])
        self.assertTrue(list((self.root / 'var/lib/flowharmonic/backups').glob('*/authentication.db')))
        self.assertTrue(list((self.root / 'var/lib/flowharmonic/backups').glob('*/network.db')))
        self.assertEqual(self.node(), {**original, 'name': 'Kitchen'})
        self.assertIn('ExecStart=', (self.root / 'etc/systemd/system/flowharmonic.service').read_text())
        subprocess.run([str(self.root / 'bin/systemctl'), 'stop', 'flowharmonic.service'], env=self.env, check=True)
        (self.root / 'etc/systemd/system/flowharmonic.service').unlink()
        self.run_installer()
        self.assertEqual(self.node(), {**original, 'name': 'Kitchen'})
        working_release = current.resolve()
        # Candidate passes import/version checks but cannot serve health.
        app = self.source / 'flowharmonic/app.py'
        app.write_text('raise RuntimeError("Injected startup failure")\n')
        failed = self.run_installer(success=False)
        self.assertIn('restoring the previous application', failed.stdout)
        self.assertEqual(current.resolve(), working_release)
        self.assertEqual(self.node(), {**original, 'name': 'Kitchen'})
        self.assertTrue(json.load(browser.open(f'http://127.0.0.1:{self.port}/api/auth'))['authenticated'])
        self.assertTrue(list((self.root / 'var/lib/flowharmonic/backups').glob('*/flowharmonic.db')))

    def test_existing_snapcast_untouched(self):
        self.env['FH_TEST_EXISTING'] = '1'
        self.run_installer()
        commands = [json.loads(line) for line in (self.root / 'commands.log').read_text().splitlines()]
        for command in commands:
            if command[0] == 'apt-get':
                self.assertNotIn('snapserver', command)
                self.assertNotIn('snapclient', command)
            if command[0] == 'systemctl' and command[1] != 'cat':
                self.assertNotIn('snapserver.service', command)
                self.assertNotIn('snapclient.service', command)
        ownership = json.loads((self.root / 'etc/flowharmonic/infrastructure.json').read_text())
        self.assertEqual(ownership, {'server': 'existing', 'client': 'existing'})

    def test_unsupported_release_rejected_before_mutation(self):
        self.os_release.write_text('ID=fedora\nVERSION_ID=99\n')
        result = self.run_installer(success=False)
        self.assertIn('Unsupported platform', result.stdout)
        self.assertFalse((self.root / 'opt').exists())

    def test_fedora_owned_components_repair(self):
        self.os_release.write_text('ID=fedora\nVERSION_ID=42\n')
        # Skip native compilation with cached binary stand-ins. This tests Fedora
        # provisioning/repair, not compiler/package compatibility.
        binary = self.root / 'opt/flowharmonic/snapcast/0.30.0/bin'
        binary.mkdir(parents=True)
        for component in ('snapserver', 'snapclient'):
            path = binary / component
            path.write_text('#!/bin/sh\nexit 0\n')
            path.chmod(0o755)
        self.run_installer()
        original = self.node()
        self.run_installer()
        self.assertEqual(self.node(), original)
        self.assertTrue((self.root / 'etc/systemd/system/flowharmonic-snapserver.service').exists())
        self.assertTrue((self.root / 'etc/flowharmonic/snapserver.conf').exists())
        commands = [json.loads(line) for line in (self.root / 'commands.log').read_text().splitlines()]
        self.assertIn(['systemctl', 'enable', 'flowharmonic-snapserver.service'], commands)
        self.assertIn(['systemctl', 'start', 'flowharmonic-audio.service'], commands)
        self.assertTrue(any(command[0] == 'dnf' for command in commands))
        self.assertFalse(any(command[0] == 'apt-get' for command in commands))

    def test_missing_database_refused_on_reinstall(self):
        self.run_installer()
        current = self.root / 'opt/flowharmonic/current'
        previous = current.resolve()
        database = self.root / 'var/lib/flowharmonic/flowharmonic.db'
        saved = database.with_suffix('.saved')
        database.rename(saved)
        result = self.run_installer(success=False)
        self.assertIn('identity will not be reset', result.stdout)
        self.assertEqual(current.resolve(), previous)
        self.assertFalse(database.exists())
        saved.rename(database)

    def test_unrelated_path_command_is_retained(self):
        launcher = self.root / 'usr/local/bin/flowharmonic'
        launcher.parent.mkdir(parents=True)
        launcher.write_text('#!/bin/sh\necho unrelated command\n')
        result = self.run_installer(success=False)
        self.assertIn('unrelated', result.stdout)
        self.assertEqual(launcher.read_text(), '#!/bin/sh\necho unrelated command\n')
        self.assertFalse((self.root / 'opt').exists())

    def test_platform_matrix(self):
        script = f'''source "{REPO}/scripts/install-common.sh"
platform_supported debian 12 x86_64 || exit 1
platform_supported ubuntu 24.04 aarch64 || exit 1
platform_supported fedora 42 x86_64 || exit 1
platform_supported fedora 43 aarch64 || exit 1
platform_supported raspbian 12 aarch64 || exit 1
if platform_supported fedora 99 x86_64; then exit 1; fi
if platform_supported ubuntu 24.04 riscv64; then exit 1; fi
if platform_supported pop 22.04 x86_64; then exit 1; fi
'''
        subprocess.run(['bash', '-c', script], check=True)


if __name__ == '__main__':
    unittest.main()
