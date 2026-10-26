"""Local-administrator enrollment. Shared state/protocol with the dashboard."""
import secrets
import sys
import time

from .discovery import Discovery
from .network import Membership, NetworkError


def add_parser(commands):
    parser = commands.add_parser('connections', help='Discover nodes and manage system membership (requires sudo)',
        description='Terminal connection management. Compare verification codes on both nodes before approving or confirming a join.',
        epilog='Example: sudo flowharmonic connections discover. Run connections COMMAND --help for details.')
    actions = parser.add_subparsers(dest='connection_command')
    actions.add_parser('status', help='Show membership, members, and pending requests (default)')
    discover = actions.add_parser('discover', help='Find nearby nodes and systems using mDNS')
    discover.add_argument('--wait', type=int, choices=range(1, 31), default=5, metavar='SECONDS', help='Listen for 1–30 seconds (default: 5)')
    create = actions.add_parser('create', help='Create a named system on this node')
    create.add_argument('name', help='System name (1–80 characters)')
    actions.add_parser('allow', help='Allow join requests for ten minutes; each still needs approval')
    actions.add_parser('close', help='Close the window for new join requests')
    join = actions.add_parser('join', help='Request to join a system using its host’s LAN URL')
    join.add_argument('url', help='Example: http://192.168.1.20:8080')
    actions.add_parser('requests', help='Show pending requests and verification codes')
    approve = actions.add_parser('approve', help='Approve a request after comparing the other node’s code')
    approve.add_argument('request_id', help='Request ID from connections requests')
    approve.add_argument('--code', help='Matching verification code shown on the joining node; prompted if omitted')
    reject = actions.add_parser('reject', help='Reject an incoming request')
    reject.add_argument('request_id')
    confirm = actions.add_parser('confirm', help='Finish joining after host approval and code comparison')
    confirm.add_argument('--code', help='Matching verification code shown on the system host; prompted if omitted')
    actions.add_parser('refresh', help='Refresh pending approval or authenticate the joined system host')
    actions.add_parser('cancel', help='Cancel the local pending join request')
    leave = actions.add_parser('leave', help='Leave the system; on the host, dissolve it and revoke memberships')
    leave.add_argument('--yes', action='store_true', help='Confirm leaving or dissolving without a prompt')
    remove = actions.add_parser('remove', help='Remove a member from the system host')
    remove.add_argument('node_id', help='Node identity from connections status')
    remove.add_argument('--yes', action='store_true', help='Confirm removal without a prompt')


def text(value):
    # Advertised names are untrusted. Never print terminal control sequences.
    return ''.join(character if character.isprintable() else '?' for character in str(value))


def show(state):
    member = state['membership']
    if member:
        print(f"System: {text(member['name'])} ({member['id']})")
        print('Role: ' + ('System host' if state['is_host'] else 'Joined member'))
        if state['is_host']:
            print('New join requests: ' + ('allowed for up to ten minutes' if state['accepting'] else 'closed'))
        for peer in state['peers']:
            print(f"Member: {text(peer['name'])} | {peer['identity']}")
    else:
        print('Independent node. No system membership.')
    for pending in state['pending']:
        print(f"Request: {pending['id']} | {pending['direction']} | {pending['status']} | {text(pending['name'])} | {text(pending['system_name'])}")
        print(f"Verification code: {pending['code']}")
        print('Compare every group with the other node’s terminal or dashboard.')
        if pending['direction'] == 'in' and pending['status'] == 'pending':
            print(f"Next: sudo flowharmonic connections approve {pending['id']} --code \"CODE FROM JOINING NODE\"")
        elif pending['direction'] == 'in' and pending['status'] == 'approved':
            print('Approved here. Confirm the matching code on the joining node.')
        elif pending['direction'] == 'out' and pending['status'] == 'rejected':
            print('Next: sudo flowharmonic connections cancel')
        elif pending['direction'] == 'out':
            print('Next: approve on the system host, then run sudo flowharmonic connections confirm --code "CODE FROM HOST"')
    if not state['pending']:
        print('No pending join requests.')
    if state.get('message'):
        print(text(state['message']))


def check_code(expected, supplied):
    if supplied is None:
        if not sys.stdin.isatty():
            raise RuntimeError('Supply --code "CODE FROM OTHER NODE", or use an interactive terminal.')
        supplied = input('Enter the verification code shown on the other node: ')
    normalized = ''.join(supplied.split()).upper()
    if not secrets.compare_digest(normalized.encode(), ''.join(expected.split()).upper().encode()):
        raise RuntimeError('Verification codes do not match. Do not approve; check both nodes or cancel the request.')


def confirm_action(message, yes):
    if yes:
        return
    if not sys.stdin.isatty():
        raise RuntimeError('Use an interactive terminal to confirm, or pass --yes.')
    if input(message + ' Type yes to continue: ').strip().lower() != 'yes':
        raise RuntimeError('Cancelled. Membership is unchanged.')


def run(args, directory, config):
    path = directory / 'flowharmonic.db'
    if not path.is_file() or not (directory / 'network.db').is_file():
        raise RuntimeError('Installed application or network database is missing. Start FlowHarmonic or restore its backup; identity will not be reset.')
    membership = Membership(directory, config, path)
    command = args.connection_command or 'status'
    if command == 'discover':
        discovery = Discovery(membership, config, advertise=False)
        discovery.start()
        try:
            print(f'Looking for nearby nodes for {args.wait} seconds…')
            time.sleep(args.wait)
            found = discovery.snapshot()
        finally:
            discovery.close()
        print(text(found['message']))
        for node in found['nodes']:
            print(f"{text(node['name'])} | {node['identity']} | {text(node['url'])}")
            if node['system_id']:
                print(f"  System: {text(node['system_name'])} | {'Host' if node['is_host'] else 'Member'}")
            if node['is_host']:
                print('  Joining: ' + ('requests allowed; approval required' if node['accepting'] else 'closed; run connections allow on this host'))
        if not found['nodes']:
            print('No nearby nodes found. For manual connection: sudo flowharmonic connections join http://HOST-LAN-IP:8080')
        return
    if command in ('status', 'requests'):
        result = membership.view()
    elif command == 'create':
        result = membership.create(args.name)
        print('To accept requests: sudo flowharmonic connections allow')
    elif command in ('allow', 'close'):
        result = membership.allow(command == 'allow')
    elif command == 'join':
        result = membership.request_join(args.url)
    elif command == 'approve':
        pending = next((item for item in membership.view()['pending'] if item['id'] == args.request_id and item['direction'] == 'in'), None)
        if pending is None:
            raise NetworkError('That incoming request is unavailable or expired. Run connections requests.')
        check_code(pending['code'], args.code)
        with membership.lock:
            current = next((item for item in membership.view()['pending'] if item['id'] == args.request_id and item['direction'] == 'in'), None)
            if current is None or current['code'] != pending['code']:
                raise NetworkError('That incoming request is unavailable or expired. Run connections requests.')
            result = membership.approve(args.request_id, True)
    elif command == 'reject':
        result = membership.approve(args.request_id, False)
    elif command == 'confirm':
        state = membership.sync()
        pending = next((item for item in state['pending'] if item['direction'] == 'out'), None)
        if pending is None or pending['status'] != 'approved':
            raise NetworkError('The system host must approve the request first. Run connections refresh.')
        check_code(pending['code'], args.code)
        with membership.lock:
            current = next((item for item in membership.view()['pending'] if item['direction'] == 'out'), None)
            if current is None or current['id'] != pending['id'] or current['code'] != pending['code']:
                raise NetworkError('The pending request changed. Run connections refresh and compare codes again.')
            result = membership.sync(confirm=True)
    elif command == 'refresh':
        result = membership.sync()
    elif command == 'cancel':
        result = membership.cancel()
    elif command == 'leave':
        state = membership.view()
        confirm_action('Dissolve this system and revoke all memberships?' if state['is_host'] else 'Leave this system?', args.yes)
        with membership.lock:
            if membership.view()['membership'] != state['membership']:
                raise NetworkError('System membership changed. Check connections status before leaving.')
            result = membership.leave()
    elif command == 'remove':
        state = membership.view()
        confirm_action(f'Remove member {text(args.node_id)}?', args.yes)
        with membership.lock:
            if membership.view()['membership'] != state['membership']:
                raise NetworkError('System membership changed. Check connections status before removing a member.')
            result = membership.remove(args.node_id)
    show(result)
