# M5: Standalone Node verification

M5 completes independent local management using the existing FastAPI application,
plain HTML/CSS/JavaScript interface, local Snapcast server, and systemd services.
No coordinator, discovery, enrollment, cloud service, or additional Python
runtime dependency was added.

## What changed

- Node settings in the local dashboard save a display name in SQLite. An additive
  `local_settings` singleton has its own format version (1); the existing identity
  database remains schema 1. The installer backs up the whole database before
  activation. Older releases can read identity and leave the extra table intact;
  they use their previous naming behavior. Unknown settings versions are refused.
- Destination Rename uses Snapcast's supported client-name operation, including
  retained offline clients when the audio server is reachable. Routing, volume,
  mute, and names remain authoritative in Snapcast rather than a second FH state
  database. Unrelated destinations are not regrouped or altered by renaming.
- Diagnostics is a collapsed, authenticated, read-only panel. It reports node
  identity/version/build, local database integrity, audio connectivity, retained
  unavailable destinations, capture availability, provisioning messages, and
  fixed/recorded FH service states. It remains usable during audio-server failure.
- `sudo flowharmonic diagnostics` provides the same basic local report without
  requiring the web application to be running. It drops to the service account
  before inspecting persistent data. It does not return credentials or raw logs,
  execute shell commands, or restart services. Password maintenance stays CLI-only.
- Application recovery no longer exhausts a five-start limit after repeated
  failures. FH-owned audio-server units also explicitly allow retries. Existing
  playback/capture restart policies and the local provisioning timer restore
  owned audio operation. Existing infrastructure does not gain an FH service
  management policy, and the web API has no privileged repair endpoint.
- Application/installer/UI versions report **M5**, with a separate build
  fingerprint. Source switching, per-destination volume/mute, and desktop capture
  retain the previous milestones' behavior.

Normal routing still requires one source selection. Node settings, destination
Rename, and Diagnostics are optional disclosures; no logo, column icons, setup
wizard, control key, or extra authentication steps were introduced.

## Demonstrated acceptance

The native acceptance system was the existing Ubuntu 22.04 x86_64 VM, with virtual
HDA output, Snapcast 0.25.0, PipeWire 0.3.48, and the real logind X11/Openbox/Xvfb
desktop fixture from M4. The node's configured control endpoint was loopback
`tcp://127.0.0.1:1705`. The entire test operated without a coordinator.

A portable, test-only Node runtime ran the **shipped dashboard JavaScript event
handlers** in a minimal DOM against the installed application's real HTTP
service. The test drove the source select, volume range, mute button, name forms,
and Diagnostics refresh. This is event-handler/HTTP integration, not a claim of
a visual browser screenshot or automated browser click-through.

The administrator-issued disposable test session was kept in a root-only file.
The test did not read, reset, or replace the user's password. It retained existing
browser sessions, restored the original names and audio settings, revoked its
own session, and deleted its temporary session/state files after completion.

Results are recorded in [M5-acceptance.json](M5-acceptance.json):

| Requirement | Demonstration |
|---|---|
| Local sources and destinations | The local Desktop Speakers destination was controlled from the node's own web service using local test sources. Before desktop login after reboot, local hardware playback was available too. |
| Source switching | Dashboard select events switched 440 Hz to 880 Hz; an independent local-output recording detected the selected frequency with negligible other-tone content. |
| Volume and mute | Dashboard volume events selected 37%; the live state confirmed it and the local output played at that setting. Dashboard mute produced a recording with peak zero. Existing real-Snapcast tests also verify isolation from another destination's volume/mute. |
| Configuration persistence | A node name and destination name, source 880 Hz, volume 37%, and mute were retained through process failures, reboot/login, and reinstall. Node identity, original TOML configuration, password, and existing sessions remained unchanged. |
| Service recovery | SIGKILL of the application, local audio server, and desktop playback worker recovered automatically; the dashboard reported the outage and restored controls. The audio-server PID stayed unchanged when only FH restarted. Six successive application crashes also recovered. |
| Reboot recovery | Application and local server started automatically, local hardware was available before desktop login, desktop playback resumed after login, and the web controls showed saved state. |
| Basic diagnostics | The dashboard Diagnostics panel remained usable during audio-server failure. The installed diagnostics command also ran successfully. |
| Update compatibility | A separate older M4 application successfully opened the M5 database and returned the same identity, without resetting the additive settings. |

After reboot the desktop fixture was logged in as part of the test environment;
no FlowHarmonic configuration or service steps were needed to resume desktop
operation. Reinstallation used the production installer and retained the same
persistent stores. Test values were restored after collecting evidence.

The final regression suite passed **79 Python tests**, including real Snapcast
control/compatibility, fresh-install/update/repair/rollback command harnesses,
authentication, local-name persistence, offline renaming, read-only diagnostics,
unknown-schema preservation, graph safety, and existing hardware provisioning.
The JavaScript DOM harness, JavaScript syntax checks, Python compilation, and
shell syntax checks passed. Native acceptance covered update/reinstall on the VM;
installer command doubles do not prove native compatibility on other platforms.

## Verify through the local interface

1. On an installed supported node, open its printed dashboard URL and sign in.
   No coordinator address or membership is required. If initial password setup
   is needed, run `sudo flowharmonic password` on that installed machine.
2. Select **Test tone 440 Hz**, then **Test tone 880 Hz**, on a connected local
   destination. Confirm the source changes and the selected tone plays locally.
   Adjust Volume and use Mute/Unmute. Select Silence when finished.
3. Optionally open Node settings and save a node name. Open Rename on a
   destination and save a destination name. Reload the dashboard; both remain.
4. Open Diagnostics and refresh it. Confirm the local configuration and audio
   connection checks and service states. An idle successful local-setup oneshot
   is shown as waiting for the next check, not as a broken service.
5. Restart the application with `sudo flowharmonic restart`, then reload. Confirm
   identity, names, selected source, volume/mute, and remembered sign-in remain.
6. Reboot the node. Reopen the dashboard after startup. On a desktop, log in to
   the desktop normally and allow about 15 seconds for session detection. Verify
   the local destination and saved controls return.
7. Rerun `sudo ./installLinux.sh`. Confirm the same identity, names, audio
   settings, and valid browser session remain, with version M5.

Audio changes are confirmed by rereading live state. Allow a few seconds of
normal operation before a reboot/failure test so Snapcast can write its settings.
Do not intentionally kill a person's working audio services merely to follow
these basic verification steps.

For local diagnostics if the web application is unavailable:

```bash
flowharmonic status
sudo flowharmonic diagnostics
sudo flowharmonic logs
```

The demonstration at the PC's `localhost:18080` forwards to the remote VM.
FlowHarmonic maintenance commands belong inside that VM, and Desktop Audio in
that demo comes from the VM's desktop. The PC remains an optional receiving
Snapclient, not a required coordinator.

## Repeat destructive acceptance tests in the disposable VM

`tests/standalone_acceptance.py`, `standalone_ui_acceptance.js`, and
`dom_fixture.js` are development fixtures and are not installed with the product.
The orchestrator requires the prepared Ubuntu VM, root, an active local desktop
session for user `ubuntu` (UID 1000), and a test-only Node executable in
`/var/tmp/fh-m5-testing/node`. Copy the three fixtures into that private directory.
Run from `/opt/flowharmonic/current`:

```bash
sudo env PYTHONPATH=. .venv/bin/python /var/tmp/fh-m5-testing/standalone_acceptance.py prepare
sudo env PYTHONPATH=. .venv/bin/python /var/tmp/fh-m5-testing/standalone_acceptance.py exercise
sudo env PYTHONPATH=. .venv/bin/python /var/tmp/fh-m5-testing/standalone_acceptance.py verify
sudo env PYTHONPATH=. .venv/bin/python /var/tmp/fh-m5-testing/standalone_acceptance.py cleanup
```

Exercise measures local tones and kills only the recorded FH application/server/
playback services. It temporarily changes names and controls. Verify can be run
again after reboot/login or reinstall, using the private state and session files
that persist in `/var/lib/flowharmonic/backups/`. Cleanup must be run to restore
those original values and revoke the temporary test session. Only structured,
credential-free results are exported as project evidence.

## Limits and deviations

- Snapcast remains the audio-settings authority and defers disk writes. A crash
  or power loss immediately after an applied change can lose an unsaved change;
  M5 does not promise power-loss-atomic audio settings or add M9 scenes, routing
  reconciliation, or export/restore features. Recovery was demonstrated with
  settings observed on disk before the failure/reboot tests.
- M5 adds node naming, not a general web editor for root-owned listener/server
  connection configuration. Advanced connection settings remain in the preserved
  TOML file. Changing a node name in the dashboard takes precedence over its
  TOML name until explicitly changed again; older releases use the TOML name
  while retaining the new settings table.
- Existing infrastructure is controlled through RPC but is not automatically
  repaired or restarted by FH. This preserves ownership boundaries; failures in
  externally managed services need their administrator's attention.
- M4 capture boundaries remain: one primary-seat PipeWire desktop, an FH-owned
  local installation for automatic capture provisioning, and ordinary stereo
  application streams. Independent direct-hardware players are paused during
  desktop sessions in favor of the desktop mixer.
- Native M5 testing covered Ubuntu 22.04 x86_64/X11. Wayland, Fedora/SELinux, ARM,
  and the remaining distribution/release targets still need native acceptance
  runs. The inherited trusted-LAN HTTP/HTTPS boundary is unchanged.
- No M6 discovery/enrollment, M7 coordination, M8 additional sources, M9 scenes,
  or M10 release/distribution features were added.
