# M9 — Scenes and Reliability

Implementation and VM acceptance evidence, 2026-10-26 (America/Chicago; some runs
crossed 2026-10-27 UTC). M9 only; the M9 requirements and acceptance criteria in
SPEC.md were not changed. The storage layout now includes `scenes.db`.

## Built

- Authenticated, CSRF-protected scene save, apply and remove APIs and a plain
  **Scenes** section in the existing dashboard. Select destinations and name the
  scene; its source assignments, volumes and mute states are saved in SQLite.
- Independent-node scenes and coordinator-owned multizone scenes. Members direct
  scene management to their coordinator. System scenes are scoped to the system
  identity, so old systems' scenes are not accidentally applied after rejoining.
- Persistent standalone assignments and reconciliation of previously confirmed
  coordinator routes after audio clients/servers restart or lose their settings.
  Only destinations changed through FH have saved recovery intent. Joined nodes
  do not replay independent routing over coordinator decisions.
- Cached inventory and last known settings during outages; understandable source,
  destination and recovery errors. Routine root provisioning preserves the last
  complete inventory while saving ownership before service changes.
- Administrator CLI configuration backup/restore. Protected archives include all
  six FH SQLite stores and application configuration, with format/schema/identity,
  ownership, checksum, size and member-name validation. Archives are never extracted
  to paths supplied by an archive. No new dependencies.
- Restore requires interactive confirmation, takes a protected pre-restore backup,
  restarts FH writers and verifies health. A replacement/startup failure reinstates
  the previous configuration. Staging files are cleaned up on write failures.
- Installer backups include scenes. Identity, names, authentication, source
  definitions and membership remain outside application releases. Version is M9.

## Acceptance demonstration

Two existing test VMs were upgraded from M8 using `installLinux.sh`: Ubuntu 22.04
x86_64 and Fedora 42 x86_64 (SELinux enforcing). They retained their identities:

- Ubuntu: `a890de3c-074a-4920-b3c8-329f5b3d005a`
- Fedora: `3ead16b8-d2d0-47be-9ebc-88bcbf85ce50`

The user explicitly approved temporary test enrollment and cleanup. Their
isolated VM LAN was enabled for the test; no manual audio configuration was used.

| Criterion/check | Demonstration |
|---|---|
| Save and restore multizone configuration | The real signed-in in-app browser saved a scene containing both VM speaker destinations. After switching both to 880 Hz at 67%, clicking Apply restored 440 Hz and independent volumes of 24% and 35%. A second scene restored measurable levels of 80% and 90%. |
| Save volume and mute | Standalone native scene restored 440 Hz, 32% and muted after changing source, volume and mute. Automated multizone tests also restore mute per destination. |
| Service crash recovery | SIGKILL of Ubuntu FH and its FH-owned Snapcast server was followed by automatic systemd recovery and verification of the saved standalone routing/volume/mute. |
| Recover lost underlying settings | With the coordinator stopped, both real Snapcast clients were changed directly to 880 Hz, 71% and muted, leaving FH intent unchanged. Restarting FH restored 440 Hz, 80%/90% and unmuted on both zones automatically. |
| Reboot recovery | Fedora rebooted while centrally routed. Identity, membership, 440 Hz and the saved independent volume returned automatically. |
| Disconnected device | Stopping the FH-owned Ubuntu playback client produced unavailable status retaining 440 Hz, 32% and mute with an understandable disconnection message. Restart restored controls/settings. Tests also cover missing scene destinations, partial results and recovery without silently replacing an input. |
| Configuration restore | Both VMs exported root-only archives. After changing each node's name, interactive `restore` restored the original name and verified health. Ubuntu retained its scene, identity, password and remembered browser sign-in; Fedora retained membership. |
| Reinstall | Both M9 candidates were reinstalled through the shipped installer. Identity, routing, scenes and temporary system membership persisted. The existing browser remained signed in. |
| Audio output | Existing QEMU sound-device recordings contained the restored 440 Hz signal on both VMs. After recovery from deliberately lost settings, amplitudes were 147.914 (Ubuntu) and 107.561 (Fedora); 880 Hz leakage was below 0.1. Both recordings were 44.1 kHz. These are PCM sample amplitudes, not acoustic sound levels. |
| Existing infrastructure | Regression tests verify existing Snapcast configurations/services are retained and external destinations are never retargeted by OS-level provisioning. Recovery uses normal authenticated FH commands and Snapcast RPC. |

## Repeatable verification

1. Install/update both supported test nodes with `sudo ./installLinux.sh`. Sign in
   through the local dashboard and enroll them using the normal explicit approval
   and matching-code flow.
2. On the coordinator select an available source for two destinations and set
   different volumes/mute states. Open Scenes, enter a name, select both
   destinations and save. Change their controls, then Apply the scene. Verify both
   source selections, volume values and mute states match the saved settings.
3. Restart FH, the FH-owned audio server or an FH-owned player. Verify settings
   and playback recover automatically. Reboot a member and verify it rejoins and
   resumes the saved assignment. Stopping an owned player temporarily should show
   a readable disconnected state; reconnecting it should restore ordinary controls.
   Do not interrupt services on an unrelated existing installation without its
   administrator's permission.
4. On each node run `sudo flowharmonic backup /root/fh-check.zip`. Change the node
   name or save/remove a test scene, then run
   `sudo flowharmonic restore /root/fh-check.zip` and type `RESTORE`. Verify the
   old state, identity and health return. Restore configuration on its original
   node only. Back up every system member separately.
5. Rerun the installer and confirm identity, scenes, source definitions,
   membership and remembered sign-in remain. Finish tests on Silence and remove
   disposable scenes/membership.

## Limits and deviations

- Backup/restore is administrator CLI-only; the dashboard explains the commands.
  Archives contain credentials and trust keys. They are protected with mode 0600,
  not encrypted or signed. Copy/store them securely and restore only trusted files.
- Restore targets the same installed node and unchanged infrastructure ownership.
  It does not clone identity/trust to new hardware, install OS packages, copy music,
  restore external Snapcast configuration or restore BlueZ's OS pairing store.
  Configuration recovery after replacement hardware or complete disk loss has not
  been demonstrated. Reconstructing a managed system requires each member's backup;
  membership changes since backup can require re-enrollment.
- Scene application is per destination, not an atomic operation across machines.
  An unavailable/hidden source or disconnected device produces a named result;
  successful destinations remain changed. Reconnect/start the missing endpoint
  and apply again. Scenes save routing, not track selection or source lifecycle.
- File replacements are atomic individually. A protected pre-restore archive and
  rollback cover ordinary failures, but sudden power loss midway through replacing
  several stores is not an atomic multi-file transaction; repair may require
  restoring that archive from the CLI. This fault-injection case is unverified.
- VM-only verification, as requested. Real speaker hot-unplug and acoustic output
  are not asserted. The previously documented M8 Bluetooth A2DP hardware gap remains;
  M9 does not claim to resolve it. No M10 updater/removal features were added.


## Automated results and cleanup

Final suite: **130 tests, 129 passed, one skipped** in 78.386 seconds. Real
Snapcast TCP/HTTP compatibility was enabled and passed. The skipped native FFmpeg
music decoder test passed in the 11-source-test suite on **both VMs**; all four
backup tests also passed on each. Dashboard and scene JavaScript regressions,
Python compilation, and installer shell syntax checks passed.

Disposable M9 scenes and the explicitly approved temporary membership were
removed. Both VM speakers returned to local Silence. The PC listening destination
was unchanged. Protected test backups remain in root-only locations on the VMs.
See [machine-readable results](M9-acceptance.json) and the
[scene-interface screenshot captured during testing](M9-scenes.jpg).
