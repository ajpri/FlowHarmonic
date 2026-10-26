# M2 · Snapcast Control: acceptance and verification

Recorded October 25, 2026. M2 control acceptance was demonstrated against a real,
independently running Snapcast system. Clean distribution install/reboot checks
from M1 remain pending; this result does not validate the full OS support matrix.

## Built

- Local or remote JSON-RPC endpoint via TCP or HTTP(S), configured in FH TOML.
- Live sources/streams and destinations/clients with current source, volume,
  effective mute (including group mute), and client availability.
- Direct source selection, independent volume, and individual mute/unmute.
- Group separation only when necessary, using server-observed group IDs.
- Readable errors for connection loss, malformed responses, denied RPC requests,
  missing endpoints, offline clients, conflicts, and failed confirmation.
- A persistent 0600 control key protects mutation endpoints; cross-origin browser
  writes are rejected. No key is returned by the API or stored in browser storage.
- M2 application/build reporting, preserved schema-1 identity/configuration,
  updated installer checks, and control-key backup/retention.

No new runtime dependencies, services, source definitions, hardware provisioning,
capture processes, discovery, or coordinator features were added to the app.
`tests/live_fixture.py` is developer test code and is not installed by FH.

## Acceptance evidence

| Requirement | Demonstrated result |
| --- | --- |
| Switch multiple test sources through the UI | Real Snapcast exposed Test A and Test B. Through the browser, Office changed A → B → A → B. Kitchen retained A, including when both clients initially shared a group. No Snapcast configuration edits were made during control. |
| Individual volume/mute | Browser changed Office from 70% to 69% and muted it; Kitchen stayed at 70%, unmuted. Kitchen's volume was also changed and restored through its encoded client ID. Server-observed state matched the UI. |
| Existing Snapcast compatibility | Automated real-server checks exercised TCP and HTTP, regrouped/muted clients through an outside RPC controller, then verified FH operated on fresh state. FH shutdown left the server and clients running and independently controllable. Snapcast text configuration bytes remained unchanged. |
| Graceful connection errors | Pausing the real test server caused Audio unavailable, a readable error, stale-state warning, and disabled controls. Resuming restored Audio connected and enabled controls automatically, without reloading. |
| Offline destination | A real client was terminated; it remained listed as offline, its write request returned 409, and the other destination stayed available. |
| Persistence/install foundation | Harness verified reinstall/repair, retained identity/configuration/control key, and recovery from a failed candidate. Privileged package/systemd operations were simulated. |

Browser evidence: [controls](M2-dashboard.png), [connection outage](M2-outage.png).
The test clients used Snapcast's null file-output player, so no physical audio
hardware was opened. This proves real protocol control and server-observed
routing; it does not claim audible playback or M3 hardware provisioning.

## Executed checks

Host: Pop!_OS 22.04 x86_64, Python 3.10.12. Production Python dependencies remain
those hash-locked during M1. Real server: Ubuntu Jammy distribution Snapcast
**0.25.0**; real clients: official upstream Snapclient **0.30.0**, two instances.
Packages/binaries and the missing client library were extracted under `/tmp`;
no host packages, system accounts, systemd units, or existing Snapcast
configuration were installed or changed. Servers listened on loopback test ports.

- Full suite with real binaries enabled: **33 tests passed**, 23.255 seconds.
- Expanded real-server check additionally verified an actual disconnected client
  and correctly URL-encoded client IDs containing `#`.
- `bash -n` on installer and shell helpers: passed.
- Python `compileall` on app, scripts and tests: passed.
- Browser control, outage, automatic recovery, and retained test state after
  application/fixture restart: passed.

The TCP/HTTP adapters are tested for notifications, request-ID correlation,
timeouts/refused connections, malformed/oversized replies, RPC failures, HTTP
redirect rejection, invalid inventory, stale grouping, and effective group mute.
API tests cover authorization, origin checks, strict volume/mute validation,
readiness during audio failure, key persistence/privacy, and URL-encoded IDs.

## Repeat the automated acceptance check

Use working Snapcast server/client binaries, including their shared libraries.
With system-installed binaries, from the repository root:

```bash
export SNAPSERVER_BINARY="$(command -v snapserver)"
export SNAPCLIENT_BINARY="$(command -v snapclient)"
.venv/bin/python -m unittest discover -s tests -v
```

Install `httpx==0.28.1` in the development venv for TestClient. If binaries were
extracted rather than installed, set their absolute paths and `LD_LIBRARY_PATH`
as required. Without both binary variables, the real-server test is explicitly
skipped; unit tests and the installer harness are not equivalent acceptance.
Local sockets must be permitted. Tests create their own temporary server config,
test tones, and file-output clients and clean up their own processes.

## Repeat the browser acceptance check

With the same binaries available, start a separate fixture (not the normal FH
installer). Use a new writable directory, and keep this terminal running:

```bash
.venv/bin/python tests/live_fixture.py \
  --server "$SNAPSERVER_BINARY" \
  --client "$SNAPCLIENT_BINARY" \
  --directory /tmp/fh-m2-acceptance \
  --web-port 8081
```

1. Choose the fixture password in its terminal prompt, then open the printed
   dashboard URL and sign in. Later visits retain the browser session.
2. Confirm two playing sources and Office/Kitchen destinations. Select Test B for
   Office, Test A again, then Test B. Confirm Kitchen stays on its original source.
3. Change Office volume and mute; verify Kitchen is unchanged. The selected source,
   percentage, and mute button must match independent `Server.GetStatus` reads.
4. Change grouping and group mute through an independent Snapcast controller;
   refresh FH, then change/unmute one destination. Its peers must retain state.
5. Stop/pause only this fixture's server, confirm an understandable error and
   disabled controls, then restart/resume it and confirm automatic recovery.
6. Stop FH while leaving the independent Snapcast server/clients running; verify
   normal Snapcast control still works. The automated real-server test performs
   this independently of the all-in-one browser fixture's cleanup behavior.

Stop the fixture with Ctrl+C; it cleans up its own processes. The fixture's
initial configuration creates the test sources before FH starts. FH itself
never provisions those sources. For a preexisting installation, simply use its
already configured multiple sources and destination instead of this fixture.

## Verify remote operation and installation retention

On a target machine, set only FH's `snapcast_url` to the existing server's
`tcp://address:1705` or HTTP(S) `/jsonrpc` URL, restart FH, then repeat browser
steps 1–4. Ensure the server already allows RPC from that machine. This session
used loopback endpoints on separate ports, not a second physical network host;
LAN firewall/TLS/remote-host behavior must be checked in the deployment.

For retention, record `/api/node`, the FH config checksum, and the credential-store
backup. Reinstall with `sudo ./installLinux.sh`, compare those values, confirm
`M2`, and verify the dashboard still controls the selected server. Reboot and
repeat on a disposable supported system. The complete distribution matrix and
foundation procedure remain in [verification.md](verification.md).

## Scope decisions and limitations

- One selected server per FH installation; connection settings are administrator
  TOML settings, not a new setup wizard. No Snapcast config edits are needed for
  normal routing, volume or mute changes.
- Supported endpoint transports: newline-delimited JSON-RPC TCP and HTTP(S) POST.
  WebSocket notifications and Snapcast-specific authentication/login are not
  implemented. HTTPS uses normal certificate trust; URL credentials are rejected.
- The local original control key was a bearer credential for trusted-LAN use. Public remote
  access and node/coordinator trust are outside M2. Use secure transport on an
  untrusted network; plain HTTP does not encrypt the key.
- Snapshot reads confirm changes, but Snapcast has no compare-and-swap transaction
  spanning regrouping and routing. Simultaneous outside topology edits can race;
  FH reports detected conflicts and partial/uncertain writes need a refresh.
- Snapcast owns persistent routing and volume state. FH does not duplicate it or
  automatically restore audio settings on startup.
- Clean distribution install/reboot validation, actual Fedora source compilation,
  and enforcing-SELinux testing remain outstanding from the foundation milestone.


Current UI update: the historical control-key/unlock interaction is superseded
by [remembered password sign-in](authentication.md). Original M2 evidence above
records the behavior tested at that time. The current real-server test signs in
through the new API before routing or volume/mute operations.
