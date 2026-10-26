# M4: Desktop Audio verification

M4 adds automatic desktop playback capture to the existing M3 installation.
Application version is **M4**; the identity database remains schema 1.

## What is installed

- The root audio provisioner detects an active, nonremote X11/Wayland user session
  on the primary seat through logind. It starts an unprivileged worker as that
  user, bound to the session scope. Greeters and SSH logins do not qualify.
- A protected FIFO carries raw stereo 48 kHz/16-bit audio into the FH-owned local
  Snapcast server's **Desktop Audio** source. The original server configuration
  is retained; only FH's generated configuration changes.
- PipeWire's packaged GStreamer source captures audio. The worker adds links from
  ordinary playback applications already connected to an audio sink. It keeps
  their speaker links, excludes Snapclient/FH playback, and never connects a
  microphone or whole-sink monitor to the product capture node.
- A session-owned Snapclient uses the desktop's existing PulseAudio compatibility
  service for **Desktop Speakers**. FH-owned direct hardware players are paused
  during the session. The desktop keeps access to its sound devices.
- Login/session changes are checked every 15 seconds. Logout stops the worker
  through its session binding. Failed or stalled capture retries automatically;
  stale/missing session status disables source selection with a readable reason.
- The dashboard remains plain HTML/CSS/JavaScript with no logo or column icons.
  Source availability changes refresh even while a destination control has focus.

No default output changes, microphone setup, desktop audio-server replacement,
remote node enrollment, discovery, coordinator, music library, or Bluetooth
features were added. Existing Snapcast installations remain independently usable.

## Demonstrated environment and results

The installed acceptance run used an Ubuntu 22.04 x86_64 VM with a virtual HDA
output, PipeWire 0.3.48, WirePlumber 0.4.8, and Snapcast 0.25.0. A real logind X11
user session ran Xvfb/Openbox as the desktop fixture. This is a controlled desktop
fixture, not a claim of validation on every desktop environment or distribution.

The production installer upgraded/reinstalled the VM and generated its services
and capture source automatically. The fixture's desktop/audio services establish
a test desktop; they are not manual FlowHarmonic setup steps required of users.
The test did not install FlowHarmonic or change audio defaults on the physical PC.

An isolated HTTP instance used the installed application, the same live audio
server and node identity, and disposable test credentials. It exercised the
normal authenticated source/volume endpoints without reading or resetting the
user's installed password. The shipped JavaScript was separately exercised in
the controlled DOM harness; these are HTTP/DOM tests, not an automated visual
browser click-through.

The recorded-audio check played a gentle 660 Hz WAV through the desktop player,
routed **Desktop Audio** to a real Snapclient file-output destination through the
web API, and independently recorded the normal local speaker monitor. It also
played FH's 880 Hz test source through Desktop Speakers to challenge feedback
exclusion. The monitor recording is test instrumentation only; the product does
not capture the whole speaker monitor.

Results are saved in [M4-acceptance.json](M4-acceptance.json):

- Desktop Audio was available and the routing response confirmed its assignment.
- Two normal speaker links remained, with two additional capture links.
- No Snapclient or microphone links entered the capture node.
- Both the destination recording and local speaker recording contained 660 Hz.
- The destination recording contained no detectable 880 Hz component. With the
  desktop application stopped, FH-only playback produced zero captured samples.
- The default output before and after capture was identical.
- Forced capture stall and PipeWire outage recovered automatically. Application
  health remained available during the checks.
- Logout stopped capture, the source explained that a local desktop login was
  needed, and a new login restored capture.
- Reboot restored application/server startup and recreated the runtime capture
  pipe; a subsequent desktop login resumed capture automatically.
- Reinstallation retained node identity, configuration, password, and remembered
  browser sessions. No identity or credential migration was needed.

The final regression run passed **72 Python tests**, including real Snapcast
control/compatibility, installer repair/rollback, persistence, authentication,
source availability, ownership, and graph safety. The vanilla JavaScript DOM
harness, Python compilation, and shell syntax checks passed.

## Verify the acceptance criterion yourself

1. On a supported Linux desktop already using PipeWire, run the standard
   `sudo ./installLinux.sh`. Sign in at the printed URL. If needed, create the
   management password with `sudo flowharmonic password` on that installed node.
2. Play a song or other audio in a normal desktop application. It must continue
   playing through the same local speakers. Record the current default output
   in the desktop sound settings and leave it unchanged.
3. In FH, select **Desktop Audio** on a destination. Confirm that destination
   plays the application's audio and the original desktop playback continues.
   Use a separate speaker destination for an easy listening comparison.
4. Change destination volume/mute, then choose **Silence** to stop routed audio.
   The desktop application's normal local playback must continue.
5. Route Desktop Audio back to Desktop Speakers if desired. Expect a delayed
   duplicate due to Snapcast buffering, but no increasing echo/feedback loop.
6. Log out of the desktop. Capture must stop; FH remains accessible and explains
   that Desktop Audio is unavailable. Log in again and allow about 15 seconds
   for automatic capture restoration.
7. Rerun the installer. Verify `flowharmonic --version` reports M4, the node
   identity and configured names remain unchanged, and valid browsers stay
   signed in. Recheck desktop playback and routing.

For diagnostics only:

```bash
flowharmonic status
sudo flowharmonic logs
journalctl -u flowharmonic-audio -b
systemctl status flowharmonic-desktop-$(id -u).service
```

Run the last command as the desktop user on the installed node. The physical
PC's `localhost:18080` test URL forwards to the remote VM; maintenance commands
belong inside that VM. The PC's temporary Snapclient is only a receiving
playback destination and does not publish the PC's own desktop audio.

## Repeat the automated measurements

The two acceptance scripts are development-only and are not shipped by the
installer. Prepare an isolated VM with a real active local desktop session,
PipeWire, an FH-owned local Snapcast server, and the installed M4 release.
Copy the scripts there, then run from `/opt/flowharmonic/current`:

```bash
PYTHONPATH=. .venv/bin/python /path/to/tests/desktop_acceptance.py
```

This creates `/tmp/fh-m4-acceptance/`, a temporary HTTP listener on loopback port
18081, a synthetic credential store, a gentle desktop tone, and recorded PCM.
It restores Desktop Speakers and the physical PC test destination to Silence,
stops its processes, and removes its own measurement client. Its JSON report and
logs remain in that temporary directory. It does not change the installed
management password or default output.

The lifecycle script intentionally stops PipeWire and terminates the desktop
session. Run it **only in the disposable prepared test VM**, never on a person's
working desktop:

```bash
sudo env PYTHONPATH=. .venv/bin/python /path/to/tests/desktop_lifecycle_acceptance.py
```

That fixture specifically uses the VM's `ubuntu` user (UID 1000), Xvfb, Openbox,
and the default local audio ports. It restores a graphical test session and
leaves its result at `/tmp/fh-m4-lifecycle-result.json`.

For the regression suite, use the commands in README and set
`SNAPSERVER_BINARY`/`SNAPCLIENT_BINARY` to working test binaries to include the
real-server compatibility test.

## Boundaries and deviations

- Capture currently supports one active primary-seat PipeWire session and
  ordinary application streams linked directly to an audio sink. PulseAudio-only
  desktops, simultaneous multi-seat capture, custom JACK/filter graphs, and
  surround channels beyond the front stereo pair are outside this implementation.
- Automatic source provisioning requires an FH-owned local server and client.
  Existing or remote servers remain controllable but are not modified to add a
  Desktop Audio source. This limits where M4's automatic capture can be published.
- X11 was tested with a real logind session; Wayland is detected by the same
  session/graph path but has not received a native Wayland acceptance run.
- Native M4 install/update and capture were demonstrated on Ubuntu 22.04 x86_64.
  Other supported installer targets, including Fedora/SELinux and ARM, still need
  native acceptance runs; command-double installer tests do not establish that
  support by themselves. A fresh M4 desktop installation and reboot/login matrix
  across distributions has not been demonstrated in this run.
- The current trusted-LAN HTTP/security boundaries described in
  [authentication.md](authentication.md) remain unchanged. No automatic HTTPS
  provisioning was added as part of M4.

## Technical references

The implementation uses PipeWire's supported
[port linking commands](https://docs.pipewire.org/page_man_pw-link_1.html) and
[stream properties](https://docs.pipewire.org/page_man_pipewire-props_7.html),
its packaged [GStreamer capture implementation](https://github.com/PipeWire/pipewire/blob/0.3.48/src/gst/gstpipewiresrc.c),
and Snapcast's [pipe source](https://github.com/snapcast/snapcast/blob/v0.30.0/doc/configuration.md#pipe).
The installer uses the distribution's GStreamer tools and PipeWire plugin
([upstream tools guide](https://gstreamer.freedesktop.org/documentation/tutorials/basic/gstreamer-tools.html),
[Fedora PipeWire plugin package](https://packages.fedoraproject.org/pkgs/pipewire/pipewire-gstreamer/)).
The older Ubuntu PipeWire tool's option limits can be checked in its
[pw-cat source](https://github.com/PipeWire/pipewire/blob/0.3.48/src/tools/pw-cat.c).
