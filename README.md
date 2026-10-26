# FlowHarmonic · M6

Share PipeWire desktop audio, automatically provision local playback hardware, and control existing Snapcast systems. Python 3.10+, FastAPI,
SQLite, and plain HTML/CSS/JavaScript. [SPEC.md](SPEC.md) is the source of truth.
Application versions are milestone identifiers: **M6**, with a separate build
fingerprint for installation checks. No semantic application versions.

## Install or update

Copy the complete trusted source tree to the target machine:

```bash
./installLinux.sh --check
sudo ./installLinux.sh
```

Open the printed dashboard URL (default `http://localhost:8080`). On a trusted
LAN, use this device's address and port. Existing firewall rules are preserved.

Implemented installer targets: Debian 12/13, Ubuntu 22.04/24.04, Raspberry Pi OS
12/13 (64-bit), Fedora 42/43; x86_64/aarch64 where applicable. Ubuntu 22.04 x86_64 has passed clean installation, reboot, and reinstall in an
audio-equipped VM. Other entries remain **unvalidated distribution targets**:
the installer harness simulates package/account/systemd commands. Actual Fedora
compilation/SELinux behavior and the remaining release/architecture combinations
are still pending. See
[foundation verification](docs/verification.md).

A reinstall stages a new release, retains identity and configuration, backs up
SQLite/configuration/credentials, repairs the service unit and missing app files,
checks the new build's health, and restores the previous app/unit on activation
failure. There is no destructive database migration in M6. Identity schema remains 1;
an additive, versioned local-settings table preserves older-release identity readers. Existing M1
configurations continue to work unchanged, using the local audio server default.
The application remains unprivileged and systemd enables startup after reboot.

## Connect and control audio

By default FH connects to the local server's JSON-RPC TCP endpoint:
`tcp://127.0.0.1:1705`. To use a remote or differently configured server, add/change
only this FlowHarmonic setting in `/etc/flowharmonic/config.toml`:

```toml
snapcast_url = "tcp://192.168.1.50:1705"
# Or an HTTP(S) endpoint, for example:
# snapcast_url = "http://192.168.1.50:1780/jsonrpc"
```

Restart FH with `sudo systemctl restart flowharmonic`. The configured server must
already allow RPC connections from FH. FH does not change a remote server's
firewall, RPC listeners, OS services, or configuration files. One configured
server per installation is supported in M6. TLS uses normal certificate
verification. Redirects, URL credentials, and Snapcast-specific login protocols
are not supported; use an accessible endpoint on a trusted network. TCP/HTTP
transport is unencrypted; use a trusted LAN or a secure tunnel/HTTPS endpoint.
Local hardware provisioning, PipeWire desktop capture, node settings, and local diagnostics are included. LAN discovery and approved system enrollment are included; systemwide audio control remains M7.

The dashboard opens a separate sign-in page. Sign in with the single management
password; there are no accounts, Lock/Unlock controls, setup links, or key entry.
Your browser remembers sign-in across reloads, tabs, service restarts, and reinstalls.
Use **Sign out** on a shared device. Dashboard data and audio controls require
sign-in; application health remains available independently.

The installer puts `flowharmonic` in the installed machine's PATH. On an
interactive first install it offers hidden, confirmed password entry. If setup
was skipped or installation was unattended, use:

```bash
sudo flowharmonic password
```

The same command changes or resets a forgotten password and signs out existing
browsers, without changing identity, device settings or audio routing. Passwords
are never accepted as command arguments. Daily maintenance is:

```bash
flowharmonic                 # help and examples (also works with sudo)
flowharmonic status
flowharmonic --version
sudo flowharmonic name                 # show the node name
sudo flowharmonic name "Living Room"   # rename the node
sudo flowharmonic logs
sudo flowharmonic diagnostics
sudo flowharmonic connections          # membership and pending requests
sudo flowharmonic connections --help   # terminal-only enrollment commands
sudo flowharmonic restart
```

The name command uses the same persistent setting as Node settings in the dashboard.
It works while the web service is stopped and needs no service restart.

No server restart is needed after setting the password. Credentials and session
tokens are hashed in a protected store; the browser uses a remembered HttpOnly
cookie. See [sign-in and maintenance](docs/authentication.md).

Choose a source directly on a destination. Adjust its volume or click Mute /
Unmute. Changes are confirmed by rereading the server; the UI polls every five
seconds for outside changes. Offline destinations show last known settings and an explanation. On
connection failure the dashboard stays available, reports an understandable
error, hides unavailable controls, and retries. A failed/timed-out write may already have
applied; refresh before retrying. `/health` reports FH readiness independently of
audio connectivity.

Routing separates the selected destination only when needed, using observed group
membership; no group identifiers appear in the UI. Other destinations keep their
source, volume, and mute. Group mute is accounted for when reporting or changing
individual mute. Snapcast remains responsible for persistence of its own audio
settings, transport, synchronization, and playback. Concurrent outside topology
writes cannot be atomic with FH changes: refresh if another controller is editing
the same destinations. FH reports conflicts rather than inventing group IDs.

## Existing infrastructure and recovery

Existing Snapcast binaries/units are recorded as `existing` in
`/etc/flowharmonic/infrastructure.json` before provisioning. FH does not reinstall,
configure, enable, stop, or restart them. The web application only uses supported
RPC inventory/routing/volume operations; it never controls OS services or changes
source definitions. Existing names, latency, sources, and configuration files
are retained. Snapcast remains independently usable when FH stops.

Fresh Debian-family installs use distribution `snapserver` and `snapclient`
packages. On Fedora, missing components are compiled from checksum-pinned
upstream Snapcast 0.30.0 into `/opt/flowharmonic/snapcast/0.30.0`.

On an FH-owned local installation, a root-only provisioning service detects ALSA
playback outputs, creates one unprivileged Snapclient service per usable output,
and adds Silence, Test tone 440 Hz, and Test tone 880 Hz to a private server
configuration. Silence is the initial source. Test tones are quiet one-second
pulses separated by four seconds of silence. Snapcast handles all playback,
pacing, transport, and synchronization.

The original server configuration is retained. Hardware identities and client
IDs remain stable across reinstalls. Disconnected HDMI outputs are omitted;
busy outputs appear with an explanation and are retried automatically. A timer
checks every 15 seconds for local desktop sessions and newly available hardware. New outputs on cards without saved ALSA mixer state receive the distribution’s
standard initialization once. Saved mixer state and previously owned outputs
are retained; the default desktop output is unchanged. During a local desktop session, FH uses a session-owned playback client through the existing desktop mixer instead of opening hardware directly. Only FH-owned hardware players are paused; existing audio services are retained.

If either Snapcast component predates FH, or a remote endpoint is selected,
local provisioning is skipped. FH does not assume ownership of those components.
The dashboard continues controlling the selected server through RPC.

| Path | Purpose |
| --- | --- |
| `/opt/flowharmonic/releases/M6-…/` | Root-owned app and per-release venv |
| `/opt/flowharmonic/current` | Atomic link to active release |
| `/etc/flowharmonic/config.toml` | Preserved device name, listener, and audio endpoint |
| `/etc/flowharmonic/infrastructure.json` | Preserved ownership ledger |
| `/etc/flowharmonic/local-audio.json` | Provisioning ownership and hardware status |
| `/etc/flowharmonic/local-snapserver.conf` | Generated configuration for the owned local server |
| `/var/lib/flowharmonic-audio/tones/` | Fixed PCM test-source assets |
| `/var/lib/flowharmonic/flowharmonic.db` | Schema 1, persistent node UUID |
| `/var/lib/flowharmonic/authentication.db` | Password hash and hashed remembered sessions, mode 0600 |
| `/usr/local/bin/flowharmonic` | Installed maintenance command using the active release |
| `/var/lib/flowharmonic/backups/M6-…/` | Root-only pre-activation backups |

```bash
systemctl status flowharmonic
journalctl -u flowharmonic -b
curl --fail http://127.0.0.1:8080/health
curl --fail http://127.0.0.1:8080/api/audio
/opt/flowharmonic/current/.venv/bin/python -m flowharmonic --version
```

Offline destinations show their last known settings and a readable explanation,
instead of disabled grey controls. Connected destinations show normal controls
after sign-in.

Application code/configuration/units are protected from writes by the web service.
Keep FH on a trusted LAN; it has no public-internet deployment model or TLS login
service. Control requests require a valid browser session and reject cross-origin
browser writes. No unrestricted shell execution or generic RPC forwarding API is exposed.

Update distribution remains trusted local source; downloads of Python packages
are hash-locked, OS packages use repository verification, and the Fedora source
archive has a pinned SHA-256 checksum. Previous/failed releases and backups are
retained. Rollback restores FH code and unit, not OS packages or audio changes,
and never silently restores an old database. A newer/unknown database is refused.
An existing installation with a missing database is not given a new identity.
Power loss/SIGKILL cannot run the rollback trap; rerun repair while retaining data.
There is no remote update feed, automatic pruning, or uninstaller in M6.

## Standalone node (M5)

M5's local audio controls continue to work independently in M6.

Each installation works independently through its local dashboard. No coordinator,
cloud service, or other FH node is required. Use local test sources or Desktop
Audio, choose a source on a destination, and adjust volume/mute directly.

Expand **Node settings** to change the node's display name. Expand **Rename** on a
destination to change its name, including a retained offline destination when the
audio server is available. Expand **Diagnostics** for identity/build, configuration
integrity, audio connectivity, unavailable-device explanations, and the status of
FH-owned services. Diagnostics remain usable when the audio connection fails.
These panels add no steps to normal routing. Password maintenance remains CLI-only.

The web service saves the node name in an additive `local_settings` table in
`flowharmonic.db`. It takes precedence over the preserved TOML default after the
first web edit. Reinstall and restart retain it, with node identity unchanged.
Older releases can still read identity schema 1 and leave the extra table intact;
they use their previous naming behavior during rollback. Unknown local-settings
schema versions are refused rather than reset.

Snapcast remains authoritative for destination names, routing, volume, and mute.
These settings live in its persistent data directory. Snapcast defers disk writes
by a few seconds; abrupt failure immediately after a change can lose a change
that has not reached disk. M5 does not add a second routing database, scenes, or
M9's broader backup/reliability features. Existing independently managed Snapcast
systems keep their own storage and services.

Systemd automatically restarts failed FH services. Repeated application crashes
continue retrying instead of exhausting a short restart limit. Audio detection
repairs owned playback/capture services and resumes after login/reboot; FH never
restarts unrelated services from the web interface. `sudo flowharmonic diagnostics`
provides a read-only local report even when the web service is down.

See [M5 standalone verification](docs/M5-verification.md) for measured UI controls,
service/reboot/reinstall recovery evidence, repeat steps, and platform limits.

## Desktop Audio (M4)

On a PipeWire desktop, sign in to FH and play audio in a desktop application.
**Desktop Audio** becomes selectable on a destination. Normal desktop playback
continues through the existing speakers and the default output remains unchanged.
A **Desktop Speakers** destination uses the existing desktop mixer when its
PulseAudio compatibility service is available.

FH automatically follows one active local X11 or Wayland session on `seat0`.
SSH sessions, login greeters, and background user managers do not enable capture.
Logout stops the session worker immediately; login/session switches are detected
within about 15 seconds. Repeated installation preserves identity, credentials,
and routing. Capture failures show an explanation and retry automatically.

Capture adds links from ordinary application playback streams to a private
PipeWire input. It does not capture a microphone or whole-speaker monitor.
Snapclient/FH playback streams are excluded, so routing Desktop Audio back to
Desktop Speakers does not recursively capture itself. Existing speaker links,
default devices, and unrelated desktop services are retained.

The installer adds PipeWire inspection tools and its GStreamer capture plugin;
it does not replace PulseAudio, start a new desktop audio server, or change your
desktop's configuration. GStreamer handles raw stereo 48 kHz capture and PipeWire
mixing; Snapcast handles distribution. No new Python dependency is required.
Ubuntu 22.04's older `pw-record` lacks the required raw/property options, which is
why this integration uses the packaged PipeWire GStreamer plugin.

Current boundaries: capture requires an FH-owned local Snapcast installation,
one active primary-seat PipeWire desktop, and applications linked directly to an
audio sink. PulseAudio-only desktops, multiple simultaneous seats, custom JACK/
filter graphs, and surround channels beyond the front stereo pair are not
supported. Existing or remote Snapcast servers remain controllable and unchanged;
FH does not publish new capture streams into infrastructure it does not own.
Remote playback has Snapcast buffering latency and is unsuitable for interactive
monitoring. Desktop-audio sharing includes ordinary application sounds, so stop
playback or log out when you do not want them shared.

See [M4 verification](docs/M4-verification.md) for repeatable acceptance checks,
recorded-audio measurements, and the distribution validation limits.

## Develop and verify

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --only-binary=:all: --require-hashes -r requirements.txt
cp packaging/config.toml .flowharmonic-config.toml
FLOWHARMONIC_CONFIG="$PWD/.flowharmonic-config.toml" \
  FLOWHARMONIC_DATA_DIR="$PWD/.flowharmonic" .venv/bin/python -m flowharmonic
```

The UI flow can also be checked with `node tests/test_dashboard.js` (development only).

For automated tests also install `httpx==0.28.1`, then run:

```bash
.venv/bin/python -m unittest discover -s tests -v
bash -n installLinux.sh scripts/install-common.sh scripts/snapcast-fedora.sh scripts/audio-drivers.sh
```

The real Snapcast test is skipped unless `SNAPSERVER_BINARY` and
`SNAPCLIENT_BINARY` point to working binaries. Test processes need local sockets.
See [M2 acceptance, real-server test commands and results](docs/M2-verification.md),
[M3 local-audio verification](docs/M3-verification.md),
[M4 desktop-audio verification](docs/M4-verification.md),
and [historical M1 results](docs/M1-results.md).

API: authenticated `GET /api/settings`, `POST /api/settings` with `{"name":"…"}`,
`GET /api/diagnostics`, and `POST /api/destinations/{id}/name` with `{"name":"…"}`;
`GET /health`, `/api/node`, `/api/audio`, `/api/sources`, `/api/destinations`;
`GET /api/auth`; `POST /api/auth/sign-in`, `/api/auth/sign-out`;
protected `POST /api/destinations/{id}/source` with
`{"source_id":"…"}`, and `/api/destinations/{id}/volume` with
`{"percent":0..100}` and/or `{"muted":true|false}`. Writes send `X-FlowHarmonic-Request: 1` and the remembered session cookie.
Dashboard reads require the session too. Legacy bearer keys, `/api/unlock`, and
web password-setup endpoints are no longer accepted. There is no API for editing the Snapcast connection settings.

Snapcast references: [official JSON-RPC API](https://github.com/snapcast/snapcast/blob/v0.30.0/doc/json_rpc_api/control.md),
[upstream build guide](https://github.com/snapcast/snapcast/blob/v0.30.0/doc/build.md).

## Discovery and enrollment (M6)

For terminal-only devices, use `sudo flowharmonic connections`. See
[terminal enrollment](docs/M6-terminal-connections.md) for the complete two-node
command sequence. It uses the same membership as the dashboard, with matching-code
approval on both sides. Local sudo access replaces browser sign-in for CLI actions.

### Connect two nodes from terminals

Run commands on each machine where FlowHarmonic is installed, directly or through
SSH. If you are viewing a VM through a forwarded localhost dashboard, run the
commands inside that VM.

On the first node, create a system and open its ten-minute joining window:

```bash
sudo flowharmonic connections create "Home"
sudo flowharmonic connections allow
```

On the second node, discover the first and request to join:

```bash
sudo flowharmonic connections discover
sudo flowharmonic connections join http://192.168.1.20:8080
```

Replace the example address with the first node's actual LAN address. The join
command prints a request ID and verification code. On the first node:

```bash
sudo flowharmonic connections requests
sudo flowharmonic connections approve REQUEST-ID
```

Replace `REQUEST-ID` with the printed request ID. Compare every group of the code
on both nodes; when prompted, enter the code shown on the second node. Then, on
the second node:

```bash
sudo flowharmonic connections confirm
sudo flowharmonic connections refresh
```

The confirm command prompts for the matching code shown on the first node.
Refresh verifies authenticated communication with the system host.

```bash
sudo flowharmonic connections          # current membership and requests
sudo flowharmonic connections --help   # all connection commands
sudo flowharmonic connections leave    # asks for confirmation
```

**On the system host, `leave` dissolves the whole system and revokes its
memberships.** Local audio settings remain intact. The
[full terminal guide](docs/M6-terminal-connections.md) also covers rejection,
cancellation, member removal, noninteractive commands, and offline behavior.

### Connect from the dashboard

Open **Connections** below the audio panels. Nearby FH nodes and system hosts
appear automatically; discovery alone grants no access and changes no audio.

1. On the first node, create a named system and choose **Allow join requests**.
   This opens a ten-minute window; it does not approve anyone.
2. On another node, choose **Request to join** for the discovered system.
3. Compare the verification code in both signed-in dashboards. On the system
   host, check that it matches and approve the request.
4. On the joining node, refresh if needed, check the matching code, and choose
   **Confirm and join**. Both nodes now retain the same system membership.

The system host in M6 holds membership only. It does not collect remote sources,
change audio routing, replace existing audio servers, or disable local components.
Central audio management is M7. Creating a system requires no installation role
choice. Requests expire after ten minutes. Each installation keeps its own local
password; no dashboard password or private signing key is sent to another node.

If discovery is blocked, use **Connect using an address** with the system host's
LAN URL, for example `http://192.168.1.20:8080`. An SSH-forwarded localhost address
in your browser is not the host's LAN address. The backend connects from the node
requesting enrollment. IPv4 mDNS uses `_flowharmonic._tcp.local.` and UDP 5353;
node HTTP uses the configured dashboard TCP port (8080 by default). Existing
firewall rules are preserved; both paths must be allowed on the intended LAN.
Discovery failure does not prevent manual enrollment or local audio controls.
IPv6 private-address manual connections are supported; mDNS discovery is IPv4.

**Refresh connections** also sends an authenticated membership check to the
system host. An outage preserves membership and displays a readable error.
**Leave system** revokes the local membership even when the host is offline;
remove its stale entry on the host if necessary. A host can remove a member or
**Dissolve system**. Removed members clear their membership at their next successful
connection refresh. Audio, identity, names, and browser passwords remain unchanged.
Cancelling a pending request removes it locally; the unapproved request on the
host expires. No automatic enrollment or automatic audio reconfiguration occurs.

Membership and Ed25519 signing keys live in protected
`/var/lib/flowharmonic/network.db` (schema 1, mode 0600), separately from node
identity schema 1 and browser authentication. Updates back up this file with
SQLite's backup API before activating a release. Reinstall and reboot preserve
keys, approvals, membership, and valid browser sessions. M5 rollback ignores this
additional database; M5 does not provide enrollment. Unknown network schemas are
refused rather than reset. Keep backups private because they contain signing keys.

All peer messages and responses are signed and bound to sender, recipient,
system, operation, request nonce, timestamp, and body. A persisted replay cache
rejects reused messages. Joined communication pins the keys approved with the
matching verification code. Devices' clocks must be within two minutes.
Membership authorizes only the small M6 peer protocol, never browser sessions,
privileged maintenance, arbitrary RPC calls, or audio controls. The protocol is
signed HTTP on a trusted LAN; it does not encrypt metadata. Sign into dashboards
over a trusted network or an encrypted tunnel and compare codes before approval.
Manual peer connections reject public/link-local targets, credentials in URLs,
redirects and proxies. Automatic TLS provisioning remains outside M6.

Protected API: `GET /api/network`; `POST /api/network/create` (`name`), `/allow`
(`enabled`), `/join` (`url`, optional discovered `identity`), `/requests/{id}`
(`approve`), `/confirm`, `/sync`, `/cancel`, `/leave`, `/remove/{identity}`.
Browser writes use the same session and CSRF checks as audio controls. Public
`GET /peer/info` returns minimal enrollment metadata; `POST /peer/message`
accepts bounded, signed protocol messages, not browser management commands.

See [M6 verification and acceptance evidence](docs/M6-verification.md).
The implementation uses [python-zeroconf](https://python-zeroconf.readthedocs.io/en/stable/api.html)
for standard mDNS and [cryptography's Ed25519 implementation](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/)
for signing rather than implementing either primitive in FH.
