# M8: Additional Sources — implementation and verification

Application version: **M8**. Validation date: 2026-10-26.

**Acceptance is partial:** music and input capture/routing are demonstrated in
VMs, and Bluetooth code-confirmation pairing is demonstrated. Bluetooth A2DP
reception/routing has not been demonstrated. The user explicitly requested VM-only
testing and documentation of this gap. Do not treat M8's complete acceptance as
proven until the remaining reception test passes.

## Built

- A plain local source setup panel: add, independently name, edit, start/stop and
  remove configured sources. New sources start stopped and never route themselves
  to speakers. M7 routing and show/hide controls work with their stable stream IDs.
- Music folder selection, bounded track listing, track selection, play, pause,
  resume, stop and ordered looping playback using FFmpeg. Pause retains the live
  decoder's position; a restart starts at the selected track rather than restoring
  an exact sample position.
- Physical input discovery and exact device selection: PipeWire audio sources in
  a local graphical session, ALSA capture devices without one. Select one channel
  or a pair; mono is duplicated to stereo. Inputs keep their own names and lifecycle,
  independent of any speakers on the same interface. USB serial/product identity
  and stable OS paths prevent fallback to an unrelated default input.
- Bluetooth pairing window, explicit code/device approval, paired/connected device
  status, trust/connect, disconnect and forget. A configured receiver captures its
  exact BlueZ/PipeWire input when available. Missing hardware/transport is reported
  without capturing a different microphone or blocking other sources.
- Protected schema-1 source preferences, installer backups, unprivileged source
  workers and automatically managed FH-owned pipes/services. Existing Snapcast
  configuration, unrelated services, desktop defaults and music permissions remain
  under their existing owners.

Bluetooth control uses the installed BlueZ tools. Its root service has an empty
capability set and reads a bounded mode-0640 command queue through its intended
supplementary group. Passwords, sessions, keys and source settings remain mode
0600. Commands are fixed actions, expire, and carry nonces; approval is bound to
the current pairing request. Pairing closes after two minutes or explicit close,
restoring prior pairable/discoverable flags. Terminal redraws cannot create another
approval. The source workers cannot run shell commands or alter services.

## Acceptance checks

| Spec criterion | Native evidence | How to verify |
| --- | --- | --- |
| Configure, start and route local music without infrastructure edits | Source form selected `/srv/fh-m8-acceptance`, read tracks, selected a file and started it. The dashboard's source selector routed it to the Ubuntu VM's own desktop destination. Actual QEMU output contained 440 Hz left and 880 Hz right. | Add a readable music folder, choose Read tracks, choose a track, Play, then select that source on a destination. |
| Basic play/pause and track selection | Shipped UI handlers passed Play/Pause/Resume/Stop. Selecting `second.wav` produced 660 Hz in both recorded output channels. Native decoder tests passed on Ubuntu and Fedora. | Pause during a track, resume, then edit the track selection; listen for each change. Stop should end decoding and Play should restart the selected track. |
| Named microphone, line-in or USB capture with device/channel selection | A real kernel ALSA loopback interface supplied 440 Hz on channel 1 and 880 Hz on channel 2. The UI configured a separately named input selecting channel 2; both destination channels then contained 880 Hz, excluding 440 Hz. This exercises the native PipeWire/ALSA capture path, not physical USB/microphone hardware. | Select an actual supported input, choose `1` or `1,2`, name it and Start. Select the named source on a destination. Verify the selected physical channels. |
| Input setup does not enable monitoring | Both new sources were stopped on creation. Starting capture left the VM destination on Silence until explicit routing. Link tests permit only the configured source's ports into the FH capture node, never speaker monitors/default inputs. | Add and Start an input while destinations are on Silence. Confirm speaker routing and normal desktop output are unchanged. |
| Disconnect reporting and exact-device recovery | Disabled only the test loopback card's input profile. FH reported its configured input disconnected while preserving device identity, channel 2 and requested playing state. Restoring that profile restored capture automatically. | Disconnect/reconnect the configured device. Its name/settings must stay intact; another/default input must not be substituted. |
| Bluetooth pairing | Two kernel virtual BR/EDR controllers paired through BlueZ after matching codes were explicitly approved through the authenticated FH API. Paired-device status appeared. | Enable pairing, pair a phone, compare and approve its code, then check the paired/connected status. |
| Bluetooth audio source reception and routing | **Not demonstrated.** Virtual controllers paired but did not establish an A2DP audio transport. A configured receiver remained unavailable while music/input sources continued; it did not fall back to the available microphone input. | On a Bluetooth-capable Linux PipeWire desktop, pair and trust/connect a phone, add/start its named receiver, play phone audio, then select that source on a destination. Check disconnect/reconnect recovery. This is the remaining acceptance gap. |
| Installable interface and persistent source configuration | Normal M8 installation/reinstall passed on Ubuntu 22.04 x86_64 and Fedora 43 x86_64; Fedora SELinux remained enforcing. Both ran native source/decoder tests. Final reinstall retained all three source configurations; Ubuntu reboot retained their IDs, names, selections and enabled states and automatically resumed the music worker. Identity and remembered credentials were retained. | Reinstall with `sudo ./installLinux.sh`, restart/reboot, sign in and compare source IDs, names, device/channel/folder selections and requested states. |

The UI tests execute the shipped JavaScript using a minimal DOM/event-handler
harness against the actual installed HTTP service. They are not visual browser
assertions. Decoder tests and frequency measurements use real native processes
and recorded VM audio. The temporary virtual controllers, input profile changes,
tone fixtures and test-session restarts are test setup, not product installation
steps or changes made to the user's physical desktop.

Sanitized measurements and persistence evidence are in
[M8-acceptance.json](M8-acceptance.json). Output was recorded at 44,100 Hz:

- Music: 440 Hz amplitude 455.282 left, 880 Hz amplitude 637.145 right.
- Selected input channel 2: 880 Hz amplitude 60.058 on both output channels;
  440 Hz amplitude 0.042 on both.
- Second music track: 660 Hz amplitude 412.248 on both output channels;
  other measured frequencies below 0.3.

## Automated checks

```sh
SNAPSERVER_BINARY=/path/to/snapserver SNAPCLIENT_BINARY=/path/to/snapclient \
  .venv/bin/python -m unittest discover -s tests -v
node tests/test_dashboard.js
node --check flowharmonic/static/sources.js
bash -n installLinux.sh
```

The final suite ran **119 tests**: 118 passed and the native decoder test was
skipped locally because this machine lacks FFmpeg. All **11 source tests passed
natively on both VMs**, including the real decoder test. Dashboard JavaScript,
Python compilation and installer shell syntax checks also passed. Tests cover authenticated/CSRF-protected configuration,
strict source/channel validation, persistence, unknown-schema refusal, source
ownership, bounded music scanning, track path containment, exact PipeWire links,
pairing prompt/nonce handling and queued Bluetooth actions.

## Limits and deviations

No M9 scenes/reliability engine, M10 uninstall, new account model or additional
source types were added. The M8 section of SPEC.md was not weakened or rewritten;
only its storage layout gained `sources.db`.

- Bluetooth audio is **unverified** end to end, as agreed for VM-only validation.
- Bluetooth reception currently requires a supported local graphical PipeWire /
  BlueZ A2DP session. Headless Bluetooth reception and legacy PIN-only pairing are
  unsupported. This is a supported-environment limitation, not a claim that all
  Linux Bluetooth setups meet M8 acceptance.
- Physical microphone/line-in/USB devices were not available in the VMs. Their
  shared native capture path was tested with kernel loopback hardware.
- Automatic publication requires the FH-provisioned local Snapcast stack. FH
  retains existing infrastructure and continues controlling its existing streams.
- Folders must already be readable by the unprivileged service. FH does not alter
  private-folder permissions. Codec support depends on the distribution decoder.
- Inputs that require changing a hardware capture selector/profile must first be
  exposed by the OS. FH selects the exposed device and channels and does not
  change existing mixer/profile settings. Exclusive device use can report busy.
- Existing M7 trusted-LAN and unencrypted Snapcast transport limits still apply.

Remaining Bluetooth reception verification must pass before declaring the full
M8 acceptance criteria complete.


Final cleanup verified: all three temporary sources were removed through the UI,
their owned streams disappeared automatically, test media and offline loopback
clients were removed, connected destinations were left on Silence, and the
disposable test session was revoked. Both VMs retain M8 with their prior identities
and credentials. The VM reboot ended the transient desktop, input-feed and virtual
Bluetooth fixtures. No physical host audio configuration was changed.
