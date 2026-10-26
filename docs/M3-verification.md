# M3 · Local Audio Provisioning

## Implemented behavior

- Detect ALSA playback devices, use hardware-path-based identities, and ignore capture-only endpoints.
- Create one stable Snapcast client per connected, available local output.
- Provision Silence and two quiet test tones through Snapcast's file-source reader.
- Install standard ALSA tools and initialize new outputs only when no saved
  hardware mixer state exists. Do not reset previously owned outputs.
- Run fixed root provisioning operations outside the unprivileged web application.
- Automatically enable/start owned services and retry unavailable hardware every minute.
- Preserve preexisting infrastructure, original server configuration, node UUID,
  control key, user configuration, and observed routing settings on reinstall.
- Display understandable local setup/hardware failures without preventing dashboard use.

No desktop capture, music library, Bluetooth, discovery, coordinator, or scenes
are included. Application version is M3; persistent database schema remains 1.

## Automated verification

The complete suite passed 45 tests, including real Snapcast TCP/HTTP control.
Installer tests simulate operating-system package/account/systemd operations;
they are not proof of a clean distribution installation.

Provisioning tests cover stable hardware IDs, capture filtering, HDMI connection
status, owned service creation, repeat provisioning without playback restart,
foreign infrastructure preservation, remote endpoint selection, busy outputs,
missing hardware, removal of owned outputs, reserved-name collisions, and
matching application/endpoint ownership when displaying local hardware status,
distribution service accounts, ALSA generic initialization, and preservation of
saved mixer state.

## Fresh-system acceptance procedure

Use a disposable supported Linux system with a connected ALSA playback device
and no preexisting Snapcast installation. Virtual HDA output is suitable if the
hypervisor records its actual audio output.

1. Copy the complete trusted source tree. Run `sudo ./installLinux.sh` once.
   Do not manually configure audio, Snapcast, or systemd.
2. Open the printed dashboard URL. Confirm M3, three test sources, and a local
   destination. Set the management password at the installer prompt or with `sudo flowharmonic password`, then sign in.
   Returning browsers remain signed in automatically.
3. Select Test tone 440 Hz, then Test tone 880 Hz. Allow at least ten seconds
   per source because the tones pulse once every five seconds. Confirm actual
   audio at the output (or inspect the hypervisor's recorded waveform).
4. Select Silence. Test volume and mute, then leave playback silent.
5. Record `/api/node`, configuration/control-key checksums, and the local client
   ID. Reboot. Confirm the dashboard and local destination return automatically
   and retain those values. Repeat the installer and compare them again.
6. Review `systemctl status flowharmonic flowharmonic-audio.timer`,
   `/etc/flowharmonic/local-audio.json`, and provisioning logs if setup fails:
   `journalctl -u flowharmonic-audio -b`.

For an existing Snapcast system, record its configuration checksums and service
state before running the installer. Verify they remain unchanged and its streams
and clients remain controllable. Local provisioning deliberately skips mixed
ownership as well as wholly preexisting installations.

## Acceptance status

Final candidate: Ubuntu 22.04.5 x86_64, official Canonical cloud image, kernel
5.15.0-198-generic, distribution Snapcast 0.25.0. A disposable KVM guest ran on
the authorized Pop!_OS 24.04 testing host. QEMU's virtual HDA output recorded the
actual ALSA playback path. No FlowHarmonic packages or services were installed
on the testing host itself.

- Clean installer completed successfully without manual audio/service/configuration
  steps. It installed missing kernel audio modules and initialized the fresh
  hardware mixer through standard ALSA profiles.
- Dashboard and health endpoint reported M3; Silence was the initial selection.
- Reboot restored the web app, local server, and playback service automatically.
- Reinstall completed successfully without resetting playback hardware.
- Both comparisons retained node UUID `a890de3c-074a-4920-b3c8-329f5b3d005a`,
  customized device name `M3 acceptance`, configuration/key checksums, original
  Snapcast configuration checksum, and destination ID
  `fh-de60a1779da15a1b9348e8abda9e7859`.
- On the final build after reboot and reinstall, the user selected 440 Hz,
  then 880 Hz, then Silence through the web dashboard. The hypervisor's actual
  hardware-output recording contained both tones: measured 440.0 Hz and 880.0 Hz
  in complete 250 ms pulse windows. Final observed routing returned to Silence.
  No API-generated tone selections were made on this final VM.

Evidence: [recording measurements](recording-evidence.json), short unmodified
[440 Hz recording](tone-440.wav), [880 Hz recording](tone-880.wav), and
[retention baseline/results](M3-acceptance.json). Clips are quiet 250 ms excerpts
of the virtual sound-card recording, not copies of the generated source assets.

The user exercised dashboard source selection successfully. Automated sidebar
browser access was rejected by the app's browser security policy; browser
interaction evidence is user-confirmed rather than an automated screenshot.
Distribution/architecture targets beyond the executed VM remain unvalidated,
including Fedora source compilation and enforcing SELinux.

## Recovery boundaries

Application activation has rollback to its previous code/unit. Audio provisioning
runs after the new web application is healthy; an audio failure retains the
working application, reports incomplete setup, and retries. Audio provisioning
is idempotent but is not a transaction across OS packages and systemd operations.
Reinstall backs up configuration, database, control key, and local audio metadata.
It does not reset an incompatible/corrupt database or replace foreign services.


## Remaining validation and scope limits

M3 acceptance is demonstrated on Ubuntu 22.04 x86_64 with virtual HDA. USB,
Raspberry Pi audio, physical speakers, other supported releases/architectures,
and Fedora compilation/SELinux still need actual hardware/distribution runs.
These are validation limits, not claims of tested compatibility. ALSA hardware
availability is required; an output held by a desktop sound service is reported
unavailable and retried. PipeWire desktop integration remains M4.

The installer leaves preexisting Snapcast components untouched and skips local
provisioning when either component is externally owned. This conservative
boundary avoids silently modifying mixed ownership infrastructure. Existing
streams and clients remain controllable through the M2 interface.

There are no additions beyond M3. The interface retains the requested plain
text branding and source/destination columns, without logos or icons.


## Physical remote listening follow-up

The user confirmed hearing the remote VM’s 440 Hz source on their physical PC.
A temporary Snapclient received the stream through an SSH tunnel and played
through the PC’s existing PipeWire/PulseAudio output using ALSA’s pulse device.
No desktop default, system volume, packages, or host services were changed.
At the user’s request, routing returned to Silence and the temporary player
was terminated. This is a manual cross-host playback check, not automatic node
discovery, enrollment, or an M4 desktop-capture implementation.


## Remembered sign-in follow-up

The interim control-key/unlock UI has been replaced with the agreed one-password
flow. See [authentication.md](authentication.md) for first use, persistence,
migration and recovery. Earlier screenshots and control-key references above
describe the historical acceptance run; current repeat steps use password setup
and remembered browser sessions. This is an M3 usability/security correction,
not node enrollment or coordinator authentication.


## Installed maintenance and sign-in-page update

Password management is now terminal-only using `sudo flowharmonic password`.
The installed PATH command also supports status, logs, restart and version.
A separate sign-in page replaces the inline authentication form and web setup
links. Offline outputs show readable last-known state instead of grey controls.
Earlier key/setup-link evidence is historical; use [current instructions](authentication.md).
