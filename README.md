# FlowHarmonic

**26.10.27 · Preview Release**

Audio from your desktop, a music folder or an input device, playing where you
choose. FlowHarmonic connects Linux devices into a multizone audio system with a
simple web interface: **sources** are where audio comes from; **destinations** are
where it plays.

Each device works independently. Connect several devices when you want one
place to manage them. FlowHarmonic provisions its own audio services, retains
normal desktop playback and leaves existing Snapcast installations under their
owner's control.

This is a preview, not a stable-release claim. Versions use **YY.MM.DD**, not
semantic versioning. [SPEC.md](SPEC.md) defines the product requirements and
boundaries; [verification](docs/verification.md) distinguishes tested behavior
from remaining gaps.

## Install

Use a trusted copy of this release on the device that will run FlowHarmonic:

```bash
./installLinux.sh --check
sudo ./installLinux.sh
```

The installer installs dependencies, configures automatic startup and local
playback, and prints the dashboard address. Open `http://localhost:8080` on that
device, or its LAN address from another computer. It preserves firewall rules.
During interactive installation, set the management password when prompted. You
can set or reset it later on the installed device:

```bash
sudo flowharmonic password
```

Sign in to the dashboard. Your browser remembers sign-in across tabs, restarts
and reinstalls; use **Sign out** on shared devices. Changing the password signs
out every browser. Password setup and recovery happen through the terminal;
there is no web account-creation flow.

### Linux compatibility

| Distribution | Installer targets | Native VM validation |
| --- | --- | --- |
| Debian | 12/13, x86_64 and aarch64 | Debian 13 x86_64 |
| Ubuntu | 22.04/24.04, x86_64 and aarch64 | Ubuntu 22.04 x86_64 |
| Fedora | 42/43, x86_64 and aarch64 | Fedora 43 x86_64, SELinux enforcing |
| Raspberry Pi OS | 12/13, 64-bit aarch64 | Hardware validation pending |

Other listed releases and ARM targets remain unvalidated. The installer reports
this distinction. Desktop sharing requires a supported PipeWire desktop. Physical
Bluetooth A2DP reception remains unverified; VM tests covered pairing but did not
establish the full reception stream. See the [validation record](docs/verification.md).

## Play audio

Choose a source on a destination, then adjust volume or mute. Local test tones
and Silence are available on an automatically provisioned installation. Offline
destinations retain their last known settings and explain what is unavailable.
Allow about 20 seconds for new source or cross-device setup to finish.

**Node settings** changes the device name. **Rename** changes a destination's
name. Settings survive reboot and reinstall. A node can publish sources, provide
destinations, or do both; the node itself is not an audio source.

### Add sources

Expand **Local source setup** on the device supplying the audio:

- **Microphone, line-in or USB input:** choose a detected input and channel or
  channel pair. A mono input plays on both stereo channels. Adding an input does
  not automatically play it through speakers.
- **Local music folder:** enter a readable folder, choose **Read tracks**, name
  the source and add it. Use Play, Pause and Stop in its source controls. Supported
  files depend on the installed decoder; playback follows the folder's tracks.
- **Bluetooth receiver:** configure the receiver and open the limited pairing
  window. Only approve devices you intend to connect. Pairing and audio support
  depend on the adapter and desktop audio environment.
- **Desktop Audio:** appears when a supported local PipeWire desktop is logged
  in. Normal desktop output stays in place. Capture excludes FlowHarmonic's own
  playback to avoid a feedback loop, and follows login/logout automatically.

These sources require FH-owned local audio components. FlowHarmonic does not
insert capture streams into an independently managed server. Desktop capture is
stereo and supports one active primary-seat PipeWire desktop; PulseAudio-only
sessions and custom JACK/filter graphs are outside the preview's supported path.
Network playback adds buffering latency and is unsuitable for live monitoring.

Under **Node settings**, source visibility controls which sources appear in new
systemwide selections. Hiding a source retains its current playback and capture.
Hide all sources on a speaker-only device. Visibility is a presentation setting,
not a security boundary.

## Connect devices

Every device has its own password and local dashboard. To manage several devices
from one dashboard:

1. On the first device, open **Connections**, create a named system and choose
   **Allow join requests**. The request window lasts ten minutes.
2. On another device, request the nearby system. If discovery is unavailable,
   enter the first device's LAN URL under **Connect using an address**.
3. Compare every group of the verification code on both dashboards. Approve on
   the system host, then confirm on the joining device.
4. On the host dashboard, select sources for destinations across the system.
   FlowHarmonic configures its players automatically; no Snapcast edits are needed.

Discovery alone grants no access. A forwarded localhost URL in your browser is
not the host's LAN address: use an address the joining device can reach.

The host coordinates new audio changes. Existing playback can continue through
an outage of its FH web service, but loss of the source machine or audio server
interrupts that audio. There is no automatic replacement-host election.
**Leave system** returns a device to independent operation; **Dissolve system**
on the host revokes the entire system's memberships. Local settings remain.

### Terminal-only connections

On the first device:

```bash
sudo flowharmonic connections create "Home"
sudo flowharmonic connections allow
```

On the second device:

```bash
sudo flowharmonic connections discover
sudo flowharmonic connections join http://192.168.1.20:8080
```

Use the actual host LAN address. On the host, list requests and approve the
printed request ID; compare the complete code when prompted:

```bash
sudo flowharmonic connections requests
sudo flowharmonic connections approve REQUEST-ID
```

On the joining device, confirm the matching code and verify the connection:

```bash
sudo flowharmonic connections confirm
sudo flowharmonic connections refresh
```

`sudo flowharmonic connections --help` lists leave, removal and other commands.
On the host, `connections leave` dissolves the whole system. See the
[complete terminal guide](docs/M6-terminal-connections.md) for noninteractive
confirmation and offline behavior.

## Scenes

Open **Scenes**, enter a name, select destinations and save their current source,
volume and mute settings. Apply the scene to request those settings again.
Unavailable destinations report their own result; applying a scene is not an
atomic operation across machines. Saved assignments recover when the required
nodes, sources and players reconnect.

## Maintenance

Run these commands on the installed machine, using SSH if needed. Running
`flowharmonic` or `sudo flowharmonic` without arguments displays help.

```bash
flowharmonic --version
flowharmonic status
sudo flowharmonic name "Living Room"
sudo flowharmonic password
sudo flowharmonic diagnostics
sudo flowharmonic logs
sudo flowharmonic restart
sudo flowharmonic connections
```

The dashboard's **Diagnostics** panel also reports identity, build, audio
connectivity and owned-service status. `GET /health` is available without sign-in.

### Update or repair

A trusted source tree can update or repair an existing installation:

```bash
sudo ./installLinux.sh
```

Reinstallation stages a separate release, retains identity and configuration,
saves protected pre-activation backups, checks startup and restores the previous
application/service on activation failure. It does not roll back OS packages or
silently replace databases with older copies.

For packaged updates, obtain the archive and its SHA256 from a trusted channel:

```bash
sudo flowharmonic update /tmp/FlowHarmonic-26.10.27.tar.gz --sha256 TRUSTED_SHA256 --check
sudo flowharmonic update /tmp/FlowHarmonic-26.10.27.tar.gz --sha256 TRUSTED_SHA256
```

A direct HTTPS URL also works. Check verifies and reports the artifact version
without installing. There is no hosted update feed or automatic installation.
A checksum downloaded from an untrusted source alongside the archive does not
establish authenticity. **For the first upgrade from M10 or earlier, run the
trusted source installer once:** those older update commands only understand
milestone versions. This preview recognizes both older milestone and date versions.

### Back up and restore

```bash
sudo flowharmonic backup /root/flowharmonic-private.zip
sudo flowharmonic restore /root/flowharmonic-private.zip
```

Backups contain settings, scenes, identity, credentials and membership trust;
keep them private. Restore validates integrity, schema and ownership, requires
confirmation, retains a pre-restore recovery copy and verifies application health.
A valid backup can repair a damaged current database.

After replacing hardware or purging an installation, install FH first and take
the original node offline before reconstructing its identity:

```bash
sudo flowharmonic restore /root/flowharmonic-private.zip --replace-identity
```

Confirm `RESTORE` followed by the archive's full UUID. Never run two copies of
one identity together. Infrastructure ownership must match; a backup cannot
convert someone else's audio server into FH-owned infrastructure. Back up each
system member separately. User music, external Snapcast state, OS Bluetooth
pairings and OS audio policy are not included. Multi-file restore is not atomic
against sudden power loss.

### Uninstall

```bash
sudo flowharmonic uninstall --dry-run
sudo flowharmonic uninstall
sudo flowharmonic uninstall --purge --dry-run
sudo flowharmonic uninstall --purge
```

Dry-run changes no files, services or membership. Default uninstall requires
`UNINSTALL`, removes recognized FH application/audio services and code, and
preserves identity, configuration, credentials, membership, scenes and backups
for reinstall. Shared packages, service accounts, user media, independently
managed Snapcast and unrecognized files remain.

Purge additionally requires `PURGE` and removes recognized FH persistent data,
identity, credentials and backups. Save recovery archives outside FH's data
directory before purging.

The plan explains which playback/capture stops and the consequences for other
nodes. A member attempts authenticated departure notification. After successful
notification, reinstall requires explicit leave/re-enrollment; local trust is
retained until then. If the host is unreachable, removal proceeds with a warning
about its stale entry. Removing the system host ends central management without
electing a replacement.

## Existing Snapcast and network access

An existing Snapcast installation remains independently usable. To select another
server, set `snapcast_url` in `/etc/flowharmonic/config.toml` and restart FH:

```toml
snapcast_url = "tcp://192.168.1.50:1705"
# HTTPS JSON-RPC is also supported:
# snapcast_url = "https://audio.example.org/jsonrpc"
```

The server must already allow the connection. FH does not change its listeners,
firewall, services or configuration. One configured server per node is supported.
Independent clients can use sources on their existing server; FH does not
retarget players it did not provision. Snapcast may retain retired clients as
offline records rather than deleting them automatically.

Use a trusted LAN or an encrypted tunnel. Default HTTP and Snapcast audio are
unencrypted; signed joined-node commands authenticate management but do not
encrypt metadata or audio. Dashboard changes require sign-in and reject
cross-origin writes. Normal HTTPS certificate validation applies; redirects and
credentials embedded in endpoint URLs are rejected. There is no public-internet
hosting or automatic TLS setup in this preview.

Discovery uses IPv4 mDNS UDP 5353. The dashboard uses TCP 8080 by default;
FH-owned joined audio uses TCP 1704, with management RPC restricted to loopback.
Allow the intended paths in your own firewall. Manual enrollment works when
multicast discovery is unavailable. Device clocks must be within two minutes.

## Development and verification

The product uses Python 3.10+, FastAPI, SQLite and HTML/CSS/vanilla JavaScript.
Persistent data is separate from root-owned application releases:

- `/opt/flowharmonic/releases/` and `/opt/flowharmonic/current`: code and environments.
- `/etc/flowharmonic/`: application configuration and infrastructure ownership.
- `/var/lib/flowharmonic/`: identity, settings, credentials, trust and backups.
- `/usr/local/bin/flowharmonic`: maintenance command.

See [verification](docs/verification.md) for coverage and known gaps, and the
[maintainer handoff](docs/maintainer-handoff.md) for reproducing development and
testing on a fresh computer. Historical milestone reports record their original
test versions; they are not the current product version.

## License

FlowHarmonic is licensed under the GNU General Public License v3.0. See [LICENSE](LICENSE).
