# M7: Central Coordination — verification

Validated 2026-10-26. Application version is **M7**. No M8 source types,
scenes, automatic coordinator election or M9 recovery engine were added.

## What was built

Creating an approved system activates its host as coordinator. Signed node
reports build one inventory of actual sources and destinations. The coordinator
owns routing requests, sends bounded authenticated commands, and confirms the
result through Snapcast. Members retain their own dashboard, settings,
diagnostics and leave operation; member audio commands affect only that member's
destinations. The coordinator dashboard controls all joined destinations.

FH-owned hardware and desktop players can connect to another node's audio
server automatically. Existing infrastructure is never retargeted. Existing
Snapcast clients retain same-server RPC control. Visibility is saved per source,
independent of capture and playback; hidden sources disappear from new choices
while current routes and controls remain. A selected hidden source remains
labelled in its current destination. Node connection and source errors use
readable status messages. A source outage leaves ready destinations selectable
so another source can be chosen.

The protected schema-1 `coordination.db` stores visibility, observed inventory,
coordinator route intent and accepted player targets. Installer SQLite backups
include it. The unprivileged app writes bounded target data; the existing root
provisioner validates identity, current system, private numeric IP and port before
changing an FH-owned player. Unknown database schemas are refused, not reset.

## Demonstrated acceptance

Native tests used the existing Ubuntu 22.04 x86_64 VM and Fedora 43 Cloud x86_64
VM on the authorized remote host. Fedora SELinux stayed enforcing. Both installed
through the normal installer, retained their existing UUIDs and credentials, and
were explicitly enrolled in a temporary approved system. An isolated virtual LAN
connected them; no host LAN configuration was changed.

| Criterion | Demonstration | Repeatable check |
| --- | --- | --- |
| One dashboard routes desktop audio across nodes | A normal PipeWire application played a continuous 440 Hz tone on Ubuntu. The coordinator dashboard's actual source-select event routed Desktop Audio to Fedora's automatically provisioned HDA destination. Both QEMU output recordings contained 440 Hz simultaneously. | Join two supported nodes; play a normal desktop application; select that desktop source on the other node's destination in the coordinator dashboard. Listen at both outputs. |
| Normal local output continues | Ubuntu's normal desktop sink stayed selected and its recording continued while Fedora received the same signal. | Check the desktop default output before/after routing and listen locally. |
| Destination-only presentation | Hiding all five actual Fedora sources removed them from new selections while its HDA destination stayed available and playing. The inventory test also covers a node with zero sources; enrollment never fabricates a source. | Under Node settings, hide that speaker node's published sources. Its destinations must remain. |
| Desktop visibility independent of speakers | Hiding Ubuntu Desktop Audio kept both its own destination and the active Fedora route. New selections excluded it; showing restored it. | Hide the playing desktop source, confirm current playback, then show it. |
| Visibility persistence | Hidden Desktop Audio and Fedora source preferences survived coordinator restart, Fedora reboot, coordinator reconnection and reinstall of both nodes. The active route also retained playback. | Repeat those operations with a hidden active source; inspect source choices and current destination. |
| Coordinator disconnection recovery | Paused only the coordinator's FH process for over 20 seconds. Both recordings continued. Member dashboard reported the coordinator unavailable; local settings remained readable. Resuming recovered reports without resetting the route. | Stop only the coordination process while keeping the source audio services running; reconnect it and inspect status/playback. |
| Volume and mute | Dashboard events set Fedora to volume 37, muted and unmuted it. During a three-second muted interval QEMU wrote zero new audio bytes; unmute restored the waveform. | Adjust volume and mute on the routed destination. |
| Installable and persistent | Normal final M7 reinstall succeeded on both distributions while joined, retaining identity, membership, visibility, source and volume. Fedora reboot recovered the player automatically. | Run `sudo ./installLinux.sh` again, then reboot. |

Final post-reinstall PCM measurements (44,100 Hz recording, first channel, two
seconds): Ubuntu peak 1196, 440 Hz amplitude 1194.974, 880 Hz amplitude 0.010;
Fedora peak 195, 440 Hz amplitude 195.043, 880 Hz amplitude 0.003. These are
recorded VM outputs, not physical speaker or synchronization certification.
Sanitized final inventory and measurements: [M7-acceptance.json](M7-acceptance.json).

UI testing used the shipped JavaScript in a minimal DOM/event-handler harness
against real installed HTTP services. It was not visual browser automation.
The ordinary dashboard regression harness additionally covers authentication,
offline/reconnect behavior, focused controls and sign-out.

All **106** Python tests passed (74.016 seconds), along with the dashboard
JavaScript checks, Python compilation and installer shell syntax checks.

Automated regression command:

```sh
SNAPSERVER_BINARY=/path/to/snapserver SNAPCLIENT_BINARY=/path/to/snapclient \
  .venv/bin/python -m unittest discover -s tests -v
node tests/test_dashboard.js
bash -n installLinux.sh
```

M7-specific tests cover real signed membership authorization, source/destination
independence, source hiding, route persistence, coordinator outage, deduplication,
remote volume/mute, ready destination recovery, concurrent retry generations,
external infrastructure ownership and root target validation.

## Limits and deviations

No intentional M7 scope deviations. Snapcast streaming is unencrypted and expects
a trusted LAN. Joined controls are signed; FH-owned management listeners remain
loopback. Existing servers must already expose an accessible stream listener;
FH preserves their configuration and firewall. Cross-server retargeting requires
FH-provisioned destinations. Active firewalld policy was not tested; rules are
never automatically changed. Other distribution releases/architectures remain
unvalidated.

Existing audio survives loss of the coordinator process, not loss of the machine
or server supplying that audio. New routing waits for coordinator reconnection;
there is no automatic failover. Source hiding is not an authorization mechanism.
Test tones and temporary membership were removed after testing; all published
source visibility preferences were restored and Fedora returned to local Silence.
