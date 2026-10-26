#!/usr/bin/env python3
"""Run as root after enrollment_acceptance.py prepare on the disposable M6 VM."""
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import urllib.request

ROOT = Path('/var/tmp/fh-m6-testing')
COMMAND = '/usr/local/bin/flowharmonic'
URLS = {'host': 'http://127.0.0.1:8080', 'member': 'http://10.206.0.2:8080'}


def command(role, *args, success=True):
    prefix = [] if role == 'host' else ['ip', 'netns', 'exec', 'fh-m6-peer', 'env',
        'FLOWHARMONIC_CONFIG=/etc/flowharmonic-m6-peer.toml',
        'FLOWHARMONIC_DATA_DIR=/var/lib/flowharmonic-m6-peer']
    result = subprocess.run([*prefix, COMMAND, 'connections', *args], capture_output=True, text=True, timeout=40)
    assert (result.returncode == 0) == success, (role, args[0] if args else 'status', result.stdout, result.stderr)
    return result.stdout


def web(role, path):
    sessions = json.loads((ROOT / 'sessions.json').read_text())
    request = urllib.request.Request(URLS[role] + path, headers={'Cookie': sessions[role]['cookie']})
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.load(response)


def request_and_codes():
    member = command('member', 'join', 'http://10.206.0.1:8080')
    host = command('host', 'requests')
    request_id = re.search(r'Request: ([0-9a-f-]+)', member).group(1)
    code = re.search(r'Verification code: ([0-9A-F ]+)', member).group(1).strip()
    assert code in host and request_id in host
    return request_id, code


def main():
    assert os.geteuid() == 0
    assert web('host', '/api/network')['membership'] is None
    assert web('member', '/api/network')['membership'] is None
    member_id = web('member', '/peer/info')['identity']
    host_id = web('host', '/peer/info')['identity']
    assert member_id in command('host', 'discover', '--wait', '5')
    assert host_id in command('member', 'discover', '--wait', '5')
    command('host', 'create', 'M6 terminal acceptance')
    command('host', 'allow')
    assert 'M6 terminal acceptance' in command('member', 'discover', '--wait', '5')
    request_id, code = request_and_codes()
    command('host', 'approve', request_id, '--code', 'WRONG CODE', success=False)
    command('member', 'confirm', '--code', code, success=False)
    assert web('host', '/api/network')['peers'] == []
    command('host', 'approve', request_id, '--code', code)
    assert web('member', '/api/network')['membership'] is None
    command('member', 'confirm', '--code', 'WRONG CODE', success=False)
    command('member', 'confirm', '--code', code)
    assert web('host', '/api/network')['membership']['id'] == web('member', '/api/network')['membership']['id']
    assert 'authenticated' in command('member', 'refresh')
    subprocess.run(['systemctl', 'stop', 'fh-m6-test-peer.service'], check=True)
    try:
        assert 'Joined member' in command('member', 'status')
        assert 'authenticated' in command('member', 'refresh')
    finally:
        subprocess.run(['systemctl', 'start', 'fh-m6-test-peer.service'], check=True)
    command('host', 'remove', member_id, '--yes')
    command('member', 'refresh', success=False)
    assert 'Independent node' in command('member', 'status')
    request_id, code = request_and_codes()
    command('host', 'reject', request_id)
    assert 'rejected' in command('member', 'refresh')
    command('member', 'cancel')
    request_id, code = request_and_codes()
    command('host', 'approve', request_id, '--code', code)
    command('member', 'confirm', '--code', code)
    command('member', 'leave', '--yes')
    assert web('host', '/api/network')['peers'] == []
    command('host', 'close')
    command('member', 'join', 'http://10.206.0.1:8080', success=False)
    command('host', 'leave', '--yes')
    assert web('host', '/api/network')['membership'] is None
    uid = pwd.getpwnam('flowharmonic').pw_uid
    for directory in (Path('/var/lib/flowharmonic'), Path('/var/lib/flowharmonic-m6-peer')):
        for name in ('network.db', 'network.lock'):
            stat = (directory / name).stat()
            assert stat.st_uid == uid and stat.st_mode & 0o777 == 0o600
    result = {'terminal_only_join': True, 'real_mdns_discovery': True, 'managed_system_discovery': True,
        'wrong_codes_refused': True, 'both_approvals_required': True, 'web_and_cli_membership_match': True,
        'authenticated_refresh': True, 'cli_works_with_local_web_service_stopped': True,
        'remove_reject_cancel_leave_and_dissolve': True, 'service_user_file_ownership': True,
        'primary_node_restored_independent': True}
    (ROOT / 'cli-result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
