"""Installed node maintenance and terminal connection management."""
import argparse
import getpass
import json
import os
import pwd
import subprocess
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import warnings

from . import VERSION
from .config import data_directory, load_config
from .security import Authentication, needs_password
from .state import initialize, node_name, set_node_name, validate_name
from .network import NetworkError


def dashboard_url(config):
    host = config['host']
    if host in ('0.0.0.0', '::'):
        host = '127.0.0.1' if host == '0.0.0.0' else '::1'
    if ':' in host:
        host = f'[{host}]'
    return f"http://{host}:{config['port']}"


def become_service_user(directory):
    try:
        account = pwd.getpwnam('flowharmonic')
    except KeyError as error:
        raise RuntimeError('The service account is missing. Rerun installLinux.sh.') from error
    if directory.stat().st_uid != account.pw_uid:
        raise RuntimeError('Application data permissions need repair. Rerun installLinux.sh.')
    # SQLite journals and credential files must belong to the unprivileged app,
    # including when a password command is interrupted or the machine loses power.
    os.initgroups(account.pw_name, account.pw_gid)
    os.setgid(account.pw_gid)
    os.setuid(account.pw_uid)


def change_password(only_if_needed=False):
    directory = data_directory()
    if only_if_needed and not needs_password(directory):
        return
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        message = 'Use an interactive terminal: sudo flowharmonic password'
        if only_if_needed:
            print(message)
            return
        raise RuntimeError(message)
    if os.geteuid() != 0:
        raise RuntimeError('Run with sudo: sudo flowharmonic password')
    if not directory.is_dir():
        raise RuntimeError('FlowHarmonic is not installed. Run installLinux.sh first.')
    print('Set the management password (12–128 characters). This signs out all browsers.')
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        while True:
            password = getpass.getpass('New password: ')
            confirmation = getpass.getpass('Confirm password: ')
            if password != confirmation:
                print('Passwords did not match. Try again.')
            elif not 12 <= len(password) <= 128:
                print('Use a password of 12–128 characters.')
            else:
                break
    become_service_user(directory)
    Authentication(directory).set_password(password)
    print('Password saved. Sign in through the dashboard; no service restart is needed.')


def status(config):
    base = dashboard_url(config)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(base + '/health', timeout=3) as response:
            health = json.load(response)
        with opener.open(base + '/api/auth', timeout=3) as response:
            auth = json.load(response)
    except (OSError, ValueError) as error:
        raise RuntimeError('Application is unavailable. Check sudo flowharmonic logs.') from error
    print(f"FlowHarmonic {health['version']}: {health['status']}")
    print(f"Identity: {health['identity']}")
    print(f'Dashboard: {base}/')
    print('Password: ' + ('configured' if auth['configured'] else 'not set; run sudo flowharmonic password'))


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='flowharmonic',
        description='FlowHarmonic application and node maintenance',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''Examples:
  flowharmonic status                   Show health and dashboard address
  sudo flowharmonic name                Show the node name
  sudo flowharmonic name "Living Room"  Change the node name
  sudo flowharmonic password            Set or reset the management password
  sudo flowharmonic diagnostics         Check local audio and services
  sudo flowharmonic connections         Show system membership and requests
  sudo flowharmonic connections --help  Manage connections from a terminal
  sudo flowharmonic logs                Show recent application logs
  sudo flowharmonic restart             Restart the application

Run flowharmonic COMMAND --help for help with a command.
Run maintenance commands on the machine where FlowHarmonic is installed.''')
    parser.add_argument('--version', action='version', version=f'FlowHarmonic {VERSION}')
    commands = parser.add_subparsers(dest='command')
    commands.add_parser('serve', help='Run the web service (normally started by systemd)')
    commands.add_parser('diagnostics', help='Show read-only local diagnostics (requires sudo)')
    commands.add_parser('status', help='Show application health, identity, and dashboard address')
    name_parser = commands.add_parser('name', help='Show or change the persistent node name (requires sudo)')
    name_parser.add_argument('name', nargs='?', help='New node name (1–80 characters)')
    password_parser = commands.add_parser('password', help='Set or change the management password using hidden terminal input')
    password_parser.add_argument('--if-needed', action='store_true', help=argparse.SUPPRESS)
    commands.add_parser('logs', help='Show the latest 50 application log entries')
    commands.add_parser('restart', help='Restart and verify the application service')
    from . import connections_cli
    connections_cli.add_parser(commands)
    args = parser.parse_args(argv)
    try:
        if args.command == 'password':
            change_password(args.if_needed)
            return
        if args.command in ('logs', 'restart', 'diagnostics', 'name', 'connections') and os.geteuid() != 0:
            raise RuntimeError(f'Run with sudo: sudo flowharmonic {args.command}')
        if args.command == 'logs':
            subprocess.run(['journalctl', '-u', 'flowharmonic.service', '-n', '50', '--no-pager'], check=True)
            return
        config = load_config()
        if args.command == 'connections':
            directory = data_directory()
            if not directory.is_dir():
                raise RuntimeError('FlowHarmonic is not installed. Run installLinux.sh first.')
            become_service_user(directory)
            connections_cli.run(args, directory, config)
            return
        if args.command == 'name':
            name = validate_name(args.name) if args.name is not None else None
            directory = data_directory()
            if not (directory / 'flowharmonic.db').is_file():
                raise RuntimeError('Application database is missing. Restore its backup; identity will not be reset.')
            become_service_user(directory)
            path = initialize(directory)
            if name is not None:
                set_node_name(path, name)
            print(node_name(path, config['name']))
            return
        if args.command == 'diagnostics':
            from .diagnostics import report
            become_service_user(data_directory())
            result = report(config, data_directory() / 'flowharmonic.db')
            print(json.dumps(result, indent=2))
            return
        if args.command == 'status':
            status(config)
            return
        if args.command == 'restart':
            subprocess.run(['systemctl', 'restart', 'flowharmonic.service'], check=True)
            for attempt in range(20):
                try:
                    status(config)
                    return
                except RuntimeError:
                    if attempt == 19:
                        raise
                    time.sleep(.5)
        else:
            import uvicorn
            uvicorn.run('flowharmonic.app:app', host=config['host'], port=config['port'], proxy_headers=False)
    except (EOFError, KeyboardInterrupt):
        parser.exit(130, '\nCommand cancelled.\n')
    except (OSError, RuntimeError, ValueError, NetworkError, getpass.GetPassWarning, subprocess.CalledProcessError, sqlite3.Error) as error:
        parser.exit(1, f'FlowHarmonic: {error}\n')
