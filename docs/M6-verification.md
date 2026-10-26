# M6: Discovery and Enrollment

M6 adds local-network discovery, suggested enrollment, persistent membership,
join/leave, and a small authenticated peer protocol. Version reporting is **M6**,
with a separate build fingerprint. Systemwide audio control remains M7.

Terminal-only connection management is also available through
`sudo flowharmonic connections`. See [terminal commands and acceptance](M6-terminal-connections.md)
and [terminal acceptance results](M6-terminal-acceptance.json). The follow-up suite
passed 97 tests. Native tests completed discovery and both approvals through the
installed CLI, with the same membership visible through the web API. CLI checks
also worked with the member's local web service stopped. The original 92-test and
dashboard acceptance results below remain the initial M6 evidence.

## What was built

- IPv4 mDNS/DNS-SD service `_flowharmonic._tcp.local.` using python-zeroconf.
  Each node advertises minimal identity/name/version and system membership hints.
  System hosts advertise whether the ten-minute joining window is open.
- A collapsed **Connections** section beneath the existing audio panels. It
  displays nearby nodes/systems and suggests joining; it never joins automatically.
- A minimal system registry on the node where the user creates a system. This
  bootstraps M6 membership; it does not activate central audio coordination.
- Manual LAN-address connection when multicast is unavailable.
- Two-sided enrollment: request, compare the displayed verification codes,
  approve on the system host, and confirm on the joining node. Both dashboards
  require their own local authenticated session and protect browser writes from CSRF.
- Persistent Ed25519 node keys and pinned peer keys. Messages and responses are
  signed over the operation, system, sender, recipient, body, timestamp, nonce,
  and response correlation. Persisted nonces reject replay across app restarts.
- Bounded enrollment windows, ten-minute request expiry, bounded pending storage,
  bounded message bodies, and peer-message rate limiting. Unknown/unapproved
  nodes cannot issue management operations. M6 implements membership and ping
  only; it does not add remote audio controls or privileged service operations.
- Online/offline leave, request rejection/cancellation, member removal, system
  dissolution, and readable connection failures. Local audio stays independent.
- Protected `network.db`, schema 1, mode 0600; installer integrity checks and
  SQLite backups preserve membership and keys through updates. Existing identity
  schema remains 1 and existing browser credentials/sessions are retained.
- Discovery runs inside the existing unprivileged application. The systemd
  sandbox permits AF_NETLINK because Linux interface enumeration needs it;
  root privileges and generic shell access are not added to the app.
- Diagnostics report discovery and stored system membership. Network changes
  reopen multicast sockets automatically; failure preserves standalone operation
  and manual enrollment, with automatic retries.

## Demonstrated acceptance

The native fixture used the authorized Ubuntu 22.04 x86_64 VM. Two independent
FH processes had separate persistent identities, signing keys, browser-session
stores, configuration, and network stacks. A veth LAN connected the ordinary
installed node to a second node in a separate Linux network namespace. These
were two independent node instances on one Linux VM, not two physical machines
or two independently installed operating systems. Both used the installed M6
application. The second node's temporary service/network units are test fixtures,
not shipped product services or an alternative installation mode.

The shipped `app.js` and `network.js` ran with a minimal test DOM and real HTTP
requests to both services. The test invoked actual form, checkbox, and button
event handlers. This is DOM/event-handler plus HTTP acceptance evidence, not
visual browser automation. A root-only fixture issued disposable browser sessions
through the existing credential store without reading or changing the installed
password. Those sessions were revoked after testing.

| Criterion | Verification |
|---|---|
| LAN node discovery | Both nodes discovered the other's distinct identity via actual multicast DNS over the veth LAN, before either had membership. |
| Existing-system discovery | After creating a system and opening joining on one node, the other discovered its system name, host identity, and joining availability automatically. |
| Suggested, never automatic enrollment | Discovery left both independent. Sending a request did not join. Host approval alone still did not join. |
| Explicit join approval | Both dashboards displayed the same verification code. The host's checked approval and joining node's checked confirmation completed membership. |
| Persistent node identity | Node UUIDs and signing keys matched before/after crashes, reboot, and reinstall. |
| Same managed system | Both node dashboards reported the same system UUID; the host listed the second node as an approved member. |
| Authenticated communication | A joined member sent a signed membership check and verified the pinned host's signed response. This continued after recovery. |
| Join and leave | Dashboard leave removed the member locally and from the host. Manual-address joining, cancellation, and host dissolution were also exercised. |
| Graceful failures | Stopping the system host produced an understandable error while retaining membership. Starting it restored authenticated communication. |
| Installability and local independence | The actual installer upgraded and reinstalled the primary node. Health, original identity/configuration/password sessions, and independent local audio services remained available. |

Additional automated tests verify signature/body tampering, wrong keys,
wrong recipients, stale timestamps, replay after restart, unapproved confirmation,
expired/rejected requests, offline leave, member removal, lost confirmation
responses, newer-schema refusal, session/CSRF protection, malicious discovery
records, discovery socket failures, and forbidden manual connection targets.

The final Python suite passed **92 tests**, including real Snapcast control,
installer repair/rollback and existing desktop/provisioning/security regressions.
The existing JavaScript dashboard regression harness also passed. Python compile,
JavaScript syntax, and shell syntax checks passed.

Sanitized native results and final version/build are in
[M6-acceptance.json](M6-acceptance.json).

## Verify on two machines

1. Copy this trusted source tree to each supported Linux machine, then run
   `./installLinux.sh --check` and `sudo ./installLinux.sh`. Set each machine's
   password when prompted, or with `sudo flowharmonic password`.
2. Open each machine's dashboard and sign in. Both must be on the same LAN.
   Permit UDP 5353 and the configured dashboard TCP port through the intended
   network/firewall. The installer preserves existing firewall rules.
3. Open **Connections**. Confirm each node appears on the other. No membership
   or audio configuration should change merely from discovery.
4. On one node, create a named system and choose **Allow join requests**. On the
   other, request to join the discovered system.
5. Compare every group of the verification code on both dashboards. Check the
   matching-code box and approve on the host; refresh the joining node if needed,
   check its matching-code box, and choose **Confirm and join**.
6. Confirm both show the same system name. The host lists the new member.
   **Refresh connections** on the member reports successful host authentication.
7. Restart/reboot both machines, then reinstall the current source. Confirm
   identities, membership, names, and signed connection checks are retained.
   Browser sign-in should still be remembered while its session is valid.
8. Stop/disconnect the host temporarily. Refreshing connections on the member
   should give a readable error and retain membership. Restore the host and refresh.
9. Choose **Leave system** on the member and confirm. Both dashboards should
   reflect the departure; local audio settings should be unchanged. If the host
   was offline, remove its stale member entry when it becomes reachable.
10. If discovery is unavailable, open joining on the host and enter its actual
    LAN URL under **Connect using an address**. Complete the same approval flow.
    Do not enter the SSH-forwarded localhost URL shown on a different computer.

## Reproduce the native fixture

Only run these test-only scripts on a disposable Ubuntu VM with the documented
primary FH installation. They create temporary systemd fixture units and a network
namespace. They deliberately refuse to replace an existing primary membership.

- `tests/enrollment_acceptance.py prepare` creates the second node and veth LAN,
  and stores root-only temporary browser sessions under `/var/tmp/fh-m6-testing`.
- Place `tests/enrollment_ui_acceptance.js` and `tests/dom_fixture.js` there too.
  The wrapper expects a test-only Node executable at `/var/tmp/fh-m5-testing/node`;
  it is not an application dependency. Then run the wrapper's `exercise` phase.
- Restart/kill the two app processes and run `verify`; reboot and run `verify`;
  reinstall the source, restart the temporary peer service to follow the new
  release, and run `verify` again. Preserve the fixture data between phases.
- Run `finish` for host outage/recovery, leave, manual request/cancel, and system
  dissolution. Run `cleanup` to revoke test sessions and remove fixture services
  and the veth LAN. Root-only result logs may be retained for evidence.

## Limits and deviations

- No M7 routing, source aggregation, source visibility controls, coordinator-owned
  audio state, or M8 source types are implemented. M6's system host is only a
  membership authority, the minimum needed to enroll nodes into a named system.
- Native acceptance used two isolated node instances on Ubuntu 22.04 in one VM.
  Separate physical-machine/router multicast behavior, Fedora/SELinux, ARM, and
  the rest of the advertised installer target matrix remain unvalidated.
- Automatic discovery is IPv4 mDNS. Manual private IPv6-address connections are
  possible; multicast discovery across subnets or isolated Wi-Fi networks depends
  on network configuration. Firewalls are not rewritten automatically.
- Peer messages are signed but HTTP does not encrypt metadata. Trusted-LAN HTTP
  is the existing deployment boundary. Compare verification codes through trusted
  dashboards; use an encrypted tunnel for dashboard access on an untrusted network.
  No passwords/private keys are exchanged during enrollment. Automatic TLS and
  public-internet deployment are not added. Peer clocks must be within two minutes.
- Leaving offline revokes trust locally immediately but cannot update an offline
  host's registry. Remove the stale entry there; a previously authorized device's
  signing key remains trusted by that host until removal. Cancelled pending
  requests expire on the other node. Dissolved/removed membership is cleared by
  the member at its next successful connection refresh. M7's continuous remote
  status/reconciliation is not implemented early.
- Existing audio ownership, desktop capture and deferred Snapcast persistence
  limitations remain as documented for M3–M5. Enrollment does not modify services
  or settings belonging to existing Snapcast installations.
