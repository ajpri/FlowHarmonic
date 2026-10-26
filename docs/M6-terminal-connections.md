# Terminal connections (M6)

Every connection operation is available from a terminal on the installed node:

```bash
sudo flowharmonic connections --help
sudo flowharmonic connections          # membership, members and pending codes
sudo flowharmonic connections discover # nearby nodes and systems; waits 5 seconds
```

Run commands on each node directly or through SSH. No browser or dashboard password
is needed for these local sudo commands. Each node still uses its own persistent
identity and approved signing keys; sudo does not bypass approval by the other node.

## Join two nodes

On the node hosting the system:

```bash
sudo flowharmonic connections create "Home"
sudo flowharmonic connections allow
```

The joining window lasts ten minutes; no request is accepted automatically.
On the other node, discover the system, then request to join its host's LAN URL:

```bash
sudo flowharmonic connections discover
sudo flowharmonic connections join http://192.168.1.20:8080
```

The join command prints a request ID and verification code. Compare every group
of that code with the system host's terminal output:

```bash
# On the system host:
sudo flowharmonic connections requests
sudo flowharmonic connections approve REQUEST-ID --code "CODE FROM JOINING NODE"
```

On the joining node, finish by entering the matching code shown by the system host:

```bash
sudo flowharmonic connections confirm --code "CODE FROM HOST"
sudo flowharmonic connections refresh
```

Replace the uppercase placeholders with the actual values. `approve` and `confirm`
prompt for the other node's code when `--code` is omitted in an interactive terminal.
Incorrect codes do not approve or complete membership. Codes are public verification
values, not passwords. Requests expire after ten minutes. The same process works
between a terminal and dashboard: compare their codes and approve each side there.

Use `connections join URL` directly if multicast discovery is unavailable. The
URL must be reachable from the joining node, not just from your SSH client. Use the
actual LAN address rather than a browser's forwarded localhost address. The
existing M6 trusted-LAN, signing, clock, and firewall requirements still apply.

## Other operations

```bash
sudo flowharmonic connections status
sudo flowharmonic connections requests
sudo flowharmonic connections refresh         # fetch approval or authenticate host
sudo flowharmonic connections close           # stop allowing new requests
sudo flowharmonic connections reject REQUEST-ID
sudo flowharmonic connections cancel          # cancel local outgoing request
sudo flowharmonic connections remove NODE-ID  # system host only; prompts to confirm
sudo flowharmonic connections leave           # prompts to confirm
```

On a system host, `leave` dissolves its system and revokes all memberships. For
noninteractive removal or leaving, pass `--yes`. Approval and joining always
require the matching code; there is no skip-verification option.

The CLI and dashboard share `network.db`. A protected `network.lock` file serializes
complete membership operations between processes, including approval rechecks and
network exchanges. Prompts do not hold the lock while waiting for a person. The
CLI starts as root to verify local administrator access, then runs as the existing
unprivileged FH service account so SQLite journals and lock files retain correct
ownership. Terminal discovery browses without re-advertising the running node.
No browser sessions, temporary passwords, or additional management endpoints are
introduced. CLI status/local operations work without the local web service; joining
and connection checks still need the system host's FH service reachable.

Leaving while the host is unreachable revokes local membership and reports the
remaining stale host entry; remove it on the host when reachable. Cancelling a
request removes it locally, and the host's pending request expires. No command
changes audio configuration, routing, names, or unrelated services.

## Verification

`tests/test_connections_cli.py` exercises a terminal-only two-node enrollment,
incorrect-code refusal, host approval before joining, persistent shared state,
leave, remove, reject, cancel, closed joining, prompt cancellation, sudo refusal,
browse-only discovery, safe terminal output, and actual cross-process locking.

`tests/connections_cli_acceptance.py` exercises the installed command on the same
disposable two-node virtual LAN documented in [M6 verification](M6-verification.md).
It checks real mDNS discovery, manual joining, both code checks, membership in both
CLI and web API, authenticated communication with the member web service stopped,
removal, rejection, cancellation, leave, and system dissolution. Run it as root on
the authorized test VM after the existing M6 fixture's `prepare` phase, then run
the fixture's `cleanup` phase. It restores the primary node to independent state.
