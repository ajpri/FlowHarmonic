#!/usr/bin/env python3
"""Sandbox command double. Used ONLY by test_installer.py, never the installer.

Package/system/account commands are simulated. Application startup and HTTP
health checks use real Python processes, sockets, SQLite, and release files.
"""
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

root = Path(os.environ['FH_TEST_ROOT'])
command = Path(sys.argv[0]).name
args = sys.argv[1:]
with (root / 'commands.log').open('a') as log:
    log.write(json.dumps([command, *args]) + '\n')
real_python = os.environ['FH_TEST_PYTHON']

if command == 'python3':
    if args[:2] == ['-m', 'venv']:
        binary = Path(args[2]) / '.venv-placeholder'
        binary.parent.joinpath('bin').mkdir(parents=True)
        shim = binary.parent / 'bin/python'
        shim.write_text('#!/bin/sh\nif [ "$1" = "-m" ] && [ "$2" = "pip" ]; then exit 0; fi\nexec "' + real_python + '" "$@"\n')
        shim.chmod(0o755)
        sys.exit(0)
    os.execv(real_python, [real_python, *args])
if command in ('apt-get', 'dnf', 'useradd', 'chown', 'restorecon', 'usermod', 'groupadd'):
    sys.exit(0)
if command == 'id':
    sys.exit(0)
if command == 'sleep':
    import time
    time.sleep(0.1)
    sys.exit(0)
if command == 'install':
    filtered = []
    index = 0
    while index < len(args):
        if args[index] in ('-o', '-g'):
            index += 2
        else:
            filtered.append(args[index])
            index += 1
    os.execv('/usr/bin/install', ['/usr/bin/install', *filtered])
if command == 'systemctl':
    unit = args[-1]
    operation = args[0]
    pid_path = root / 'app.pid'
    enabled = root / 'enabled'
    if operation == 'start' and unit == 'flowharmonic-audio.service':
        sys.path.insert(0, str(root / 'opt/flowharmonic/current'))
        from flowharmonic.provision import Provisioner, SOURCES
        from flowharmonic.config import load_config
        class Audio:
            def status(self):
                return {'streams': [{'id': name} for _, name, _ in SOURCES], 'groups': []}
        def simulated(args, **kwargs):
            return subprocess.run(args, env=os.environ, capture_output=True, text=True)
        Provisioner(root=root, runner=simulated, detector=lambda: []).provision(load_config(), audio=Audio())
        sys.exit(0)
    if operation == 'cat':
        sys.exit(0 if os.environ.get('FH_TEST_EXISTING') == '1' else 1)
    if operation == 'show':
        print('loaded' if (root / 'etc/systemd/system/flowharmonic.service').exists() else 'not-found')
        sys.exit(0)
    if operation == 'stop' and not pid_path.exists() and not (root / 'etc/systemd/system/flowharmonic.service').exists():
        sys.exit(5)
    if operation == 'is-enabled':
        sys.exit(0 if enabled.exists() else 1)
    if 'flowharmonic.service' not in args:
        sys.exit(0)
    if operation == 'enable':
        enabled.touch()
    elif operation == 'disable':
        enabled.unlink(missing_ok=True)
    elif operation in ('stop', 'restart'):
        if pid_path.exists():
            pid = int(pid_path.read_text())
            try:
                os.kill(pid, signal.SIGTERM)
                import time
                for _ in range(100):
                    status = Path(f'/proc/{pid}/stat')
                    if not status.exists() or status.read_text().split()[2] == 'Z':
                        break
                    time.sleep(0.02)
            except (ProcessLookupError, FileNotFoundError):
                pass
            pid_path.unlink()
        if operation == 'restart':
            release = root / 'opt/flowharmonic/current'
            env = {**os.environ, 'FLOWHARMONIC_CONFIG': str(root / 'etc/flowharmonic/config.toml'),
                   'FLOWHARMONIC_DATA_DIR': str(root / 'var/lib/flowharmonic')}
            env.pop('PYTHONPATH', None)
            with (root / 'service.log').open('ab') as log:
                process = subprocess.Popen([real_python, '-m', 'flowharmonic'], cwd=release,
                                           env=env, stdout=log, stderr=log, start_new_session=True)
            pid_path.write_text(str(process.pid))
    sys.exit(0)
raise SystemExit(f'Unhandled test command {command}: {args}')
