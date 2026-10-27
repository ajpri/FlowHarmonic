# FlowHarmonic

## Technical Specification

**Version:** Pre-release (milestone phase)
**Versioning:** During development, builds are identified by milestone (M1–M10), so work can be directed as "build milestone X." After M10 (V1 release), versioning switches to date-based (YY.MM.DD). No semantic versions, ever.
**Status:** Initial development specification
**Target:** V1
**Initial platform:** Linux

---

## 1. Overview

### 1.1 Purpose

FlowHarmonic (FH) is a simple, self configuring multizone audio system built on Snapcast.

FH abstracts audio infrastructure into two concepts:

- **Sources:** Where audio comes from.
- **Destinations:** Where audio plays.

Users install FlowHarmonic on supported devices and manage audio through a web interface.

FH automatically handles the underlying services, configuration, audio transport, device discovery, and routing.

Users should not need to understand Snapcast, audio protocols, configuration files, or Linux service management.

### 1.2 Product Promise

Install FlowHarmonic. Connect your devices. Route audio anywhere.

### 1.3 Primary Design Philosophy

Best part is no part.

Follow this order when designing features:

1. Question the requirement.
2. Remove unnecessary components or processes.
3. Simplify what remains.
4. Optimize only when necessary.
5. Accelerate development and execution.
6. Automate last.

User facing complexity is considered a product defect unless it is unavoidable.

The software should make complex audio infrastructure feel simple and predictable.

---

## 2. Design Principles

### 2.1 Sources and Destinations

The primary interface exposes only sources and destinations.

Users select which source plays through each destination.

FH internally manages Snapcast streams, clients, groups, and routing.

Snapcast terminology should not appear in the primary interface.

### 2.2 Automatic Configuration

FH should discover and configure supported hardware and services automatically.

The user should only make decisions that FH cannot safely make itself.

### 2.3 One Installation

Every device uses the same FlowHarmonic software distribution.

Depending on its capabilities, a device may function as:

- An audio source
- An audio destination
- Both
- A central coordinator
- Any supported combination of these capabilities

Users do not choose an installation type.

### 2.4 Local Independence

Every FH installation includes a local web interface.

A node can be configured and diagnosed without a coordinator.

Nodes should continue their existing audio operation when the coordinator becomes unavailable, where technically possible.

### 2.5 Optional Central Management

Multiple FH nodes can join a centrally managed system.

FH discovers nearby systems and suggests joining.

Joining never occurs without explicit user approval.

### 2.6 No Reinvention of Audio Transport

FH does not implement its own audio transport, synchronization, or encoding engine.

Snapcast remains responsible for synchronized playback and audio distribution.

FH controls and provisions existing audio infrastructure.

### 2.7 Minimal Dependencies

Avoid unnecessary frameworks, services, databases, containers, and processes.

Prefer existing operating system functionality.

### 2.8 Existing Snapcast Compatibility

FH must support existing Snapcast installations.

An existing installation should be controllable through FH without requiring replacement or reinstallation.

FH must distinguish infrastructure it owns from infrastructure it merely connects to.

---

## 3. User Experience

### 3.1 Main Interface

The primary dashboard displays:

**Sources** — Available audio sources across the FH system. Examples:

- Desktop Audio
- Phone
- Lofi Music
- Microphone

**Destinations** — Available playback devices. Examples:

- Office
- Kitchen
- Bedroom
- Desk Speakers

Each destination exposes:

- Name
- Current source
- Source selection
- Volume
- Mute
- Availability status

Multiple destinations may select the same source.

Each destination may select only one source at a time in V1.

### 3.2 Interface Rules

- The primary dashboard must remain simple.
- Source selection should require one obvious action.
- Routing changes should not require navigating configuration screens.
- Do not expose Snapcast groups or internal stream identifiers.
- Show errors in understandable language.
- Hide advanced settings from normal workflows.
- Avoid configuration wizards unless genuinely necessary.
- Do not show controls for unsupported capabilities.
- Prefer automatic discovery over manual entry.
- Use a separate sign-in page and remember authenticated browsers; do not require control keys or a lock/unlock workflow.
- Connected destinations expose ordinary source, volume, and mute controls.
- Disconnected destinations show last known settings and an understandable reason instead of inactive, greyed-out controls. Restore controls automatically when connectivity returns.

### 3.3 Local Interface

Every installation serves a web interface for:

- Local sources
- Local destinations
- Device settings
- Connection status
- Updates
- Diagnostics
- Joining or leaving a managed system

When the device is a coordinator, the same interface additionally exposes systemwide management.

A separate coordinator frontend is not required.

---

## 4. Functional Requirements

### 4.1 Audio Sources

FH must support the following source types by V1.

| Source | Behavior |
|---|---|
| Desktop audio | Capture an existing computer audio output |
| Bluetooth | Receive audio from a paired phone or device |
| Local music | Play audio from a configured local music folder |
| Microphone | Capture a supported audio input |
| Line-in and USB audio inputs | Capture a supported physical input, including audio supplied by another computer through an audio interface |
| Existing Snapcast | Display and route existing streams |

Sources should be created and managed automatically when possible.

Source specific controls may include:

- Start
- Stop
- Play
- Pause
- Pair
- Unpair

Only display controls supported by the source.

For physical audio inputs, allow selection of the supported input device and channel or channel pair. Publish each configured input as a distinct, independently named source; inputs and speaker destinations on the same device remain independent. Do not enable microphone monitoring or route a captured input to speakers automatically. Report disconnected or unavailable inputs in understandable language and recover when the configured device returns, without silently selecting a different input.

FH does not integrate directly with streaming services.

Applications such as YouTube Music or Spotify remain responsible for playback.

### 4.2 Destinations

FH discovers available audio output devices.

Examples include:

- Built in audio outputs
- USB audio interfaces
- Supported external sound cards
- Existing Snapcast clients
- Remote FH nodes

Users may rename destinations.

FH manages the underlying Snapclient configuration.

### 4.3 Routing

FH supports:

- One source per destination
- One source routed to multiple destinations
- Independent destination volume
- Independent destination mute
- Switching sources without manually editing configuration files

FH translates user routing decisions into supported Snapcast operations.

Where necessary, FH creates or modifies Snapcast groups internally.

Routing must be based on observed system state rather than assumptions about group membership.

### 4.4 Desktop Audio Capture

On supported Linux desktop systems, FH should automatically expose system audio as an available source.

Requirements:

- Capture audio through the supported Linux audio stack.
- Preserve normal local desktop playback.
- Do not change the system default output without permission.
- Avoid capturing audio generated by FH itself in a feedback loop.
- Handle desktop login and logout appropriately.
- Indicate when desktop capture is unavailable.

PipeWire is the preferred Linux integration.

Where required, a user session component may operate alongside the primary FH system service.

Remote playback latency must be treated as a known limitation for interactive applications.

### 4.5 Local Music

FH supports playback from a user selected music folder.

Required capabilities:

- Select music folder
- Play
- Pause
- Stop
- Basic track selection
- Publish audio as a source

Mopidy is an initial candidate, not a mandatory dependency.

Use a simpler player if it satisfies the requirements with fewer moving parts.

### 4.6 Bluetooth

FH supports Bluetooth audio reception through the local Linux Bluetooth stack.

Requirements:

- Enable pairing from the web interface.
- Display pairing status.
- Identify connected devices.
- Receive supported Bluetooth audio.
- Publish received audio as a source.
- Handle disconnection and reconnection.

Bluetooth support depends on hardware and operating system capabilities.

Unavailable hardware must not prevent FH from operating.

### 4.7 Scenes

Scenes save routing configurations.

A scene may contain:

- Source assignments
- Destination selections
- Destination volumes
- Mute states

Applying a scene restores the saved configuration.

Scenes do not require a separate audio engine.

### 4.8 Discovery

FH discovers other FH installations on the local network.

Discovery requirements:

- Identify available nodes.
- Identify available managed systems.
- Avoid automatic system enrollment.
- Suggest joining an existing system.
- Support manual connection when discovery is unavailable.

Local network discovery may use mDNS or another appropriate open mechanism.

### 4.9 Coordinator

A coordinator provides centralized management of connected nodes.

Responsibilities:

- Maintain system membership.
- Collect available sources and destinations.
- Manage systemwide routing.
- Store scenes.
- Display node status.
- Coordinate supported remote operations.

Coordinator functionality is included in the standard FH application.

It is activated when a system is created or managed.

V1 assumes one authoritative coordinator per managed system.

Automatic coordinator election and high availability are not required.

### 4.10 Node Management

Each node manages its local hardware and services.

The coordinator issues desired operations.

Nodes report their actual state and errors.

Nodes must not independently overwrite coordinator owned routing decisions while centrally managed.

Local controls for systemwide routing should direct requests through the coordinator when connected.

Local device recovery and diagnostics remain accessible.

---

## 5. Technical Architecture

### 5.1 Initial Technology Stack

| Component | Technology |
|---|---|
| Backend | Python 3 |
| Web API | FastAPI |
| Frontend | HTML, CSS, vanilla JavaScript |
| Audio transport | Snapcast |
| Linux desktop audio | PipeWire |
| Bluetooth | BlueZ |
| Service management | systemd |
| Persistence | SQLite |
| Installation | Shell scripts |
| Discovery | Local network discovery |

Technology choices may change when testing demonstrates a clear benefit.

### 5.2 Application Architecture

FH is one backend application with internally separated responsibilities:

- Web interface and API
- Audio source management
- Destination management
- Snapcast control
- Device discovery
- Local node operations
- Coordinator operations
- Persistent state

These are logical modules.

They should not become separate services unless necessary.

### 5.3 Audio Responsibility

Snapcast owns:

- Audio transport
- Audio synchronization
- Stream encoding
- Stream distribution
- Client playback
- Snapcast group management primitives

FH owns:

- User interactions
- Source and destination discovery
- Source lifecycle
- Routing intent
- Service provisioning
- Device orchestration
- Scenes
- User configuration

FH may manage capture processes, but it must not implement a replacement audio pipeline.

### 5.4 Snapcast Integration

FH communicates with Snapcast using supported JSON RPC interfaces.

An existing Snapcast installation must remain usable independently of FH.

FH must not assume that every connected Snapcast server permits operating system level management.

### 5.5 State Management

SQLite stores persistent FH state.

Persistent data includes:

- Node identity
- User assigned names
- System membership
- Managed source definitions
- Scenes
- Application settings
- Infrastructure ownership metadata
- Management password hash and remembered browser sessions

Current audio and connection status should be obtained from the underlying systems where possible.

Do not maintain unnecessary duplicate state.

---

## 6. Installation

### 6.1 Installer

The initial installer is:

`installLinux.sh`

It must support compatible Debian and Fedora family distributions.

Initial targets:

- Debian
- Ubuntu
- Raspberry Pi OS
- Fedora

Support is validated by distribution release and architecture, not assumed solely from distro family.

### 6.2 Installer Responsibilities

The installer must:

1. Detect the operating system and architecture.
2. Validate compatibility.
3. Install required packages.
4. Install FH into an isolated application environment.
5. Install required Snapcast components.
6. Create necessary directories and permissions.
7. Configure systemd.
8. Start the FH service.
9. Verify application health.
10. Install the `flowharmonic` maintenance command into the system PATH.
11. Offer password creation during an interactive first installation, using hidden, confirmed terminal entry.
12. Display the local dashboard URL and any remaining password setup instruction.

A fresh installation provisions a local Snapcast server by default.

FH may subsequently disable unnecessary local components when a node joins a managed system.

### 6.3 Installation Experience

One installer should result in a functioning FH dashboard.

The user should not have to:

- Install Python packages manually.
- Configure Snapcast manually.
- Edit systemd services.
- Create configuration files.
- Configure a database.
- Select a device role.

An unattended installation must not generate or display a default management password. The administrator completes password setup with `sudo flowharmonic password`. Until then, the sign-in page explains this command and management access remains unavailable.

### 6.4 Application Storage

Separate application releases from persistent data.

Filesystem layout:

```
/opt/flowharmonic/
    releases/
    current/
/etc/flowharmonic/
    config.toml
/var/lib/flowharmonic/
    flowharmonic.db
    authentication.db
    network.db
    coordination.db
    sources.db
    scenes.db
    identity/
    backups/
/usr/local/bin/flowharmonic
```

Application releases may be replaced without deleting persistent data.

### 6.5 Repeatable Installation

Running `installLinux.sh` repeatedly must be safe.

The installer should recognize:

- Fresh installation
- Existing installation
- Required update
- Missing application files
- Broken service configuration

It must not reset the system merely because the installer runs again. Preserve the management password and unexpired browser sessions, repair the installed maintenance command, and refuse to overwrite an unrelated command at the same path.

### 6.6 Local Maintenance

Password management and the following node maintenance actions are available through the installed `flowharmonic` command:

| Command | Behavior |
|---|---|
| `flowharmonic` or `sudo flowharmonic` | Show command help and maintenance examples |
| `flowharmonic status` | Report health, identity, dashboard URL, and whether a password is configured |
| `flowharmonic --version` | Report the milestone version |
| `flowharmonic --help` | Show command usage |
| `sudo flowharmonic password` | Create, change, or recover the management password |
| `sudo flowharmonic diagnostics` | Report local configuration, audio, and service status without changing them |
| `sudo flowharmonic name ["New name"]` | Show or change the persistent node display name, shared with the dashboard, without restarting services |
| `sudo flowharmonic connections [command]` | Discover nodes and manage system creation, join requests, approval, confirmation, membership checks, and leaving from a terminal |
| `sudo flowharmonic logs` | Show recent FH service logs |
| `sudo flowharmonic restart` | Restart FH and verify application health |

Privileged commands require local administrator access, including an administrator connected through SSH. The command must work outside the application checkout and follow the active installed release.

Connection management must be possible entirely through the CLI for nodes with terminal-only access. Use the same persistent membership and authentication protocol as the dashboard. Sudo authorizes local actions without browser sign-in; joining still requires approval on the system host and matching-code confirmation on the joining node. Codes may be compared between terminals or between a terminal and dashboard. Concurrent CLI and dashboard operations must not overwrite one another's membership decisions.

Password entry must be hidden and confirmed, accept 12–128 characters, and preserve spaces. Do not accept passwords through command arguments, environment variables, piped input, or an echoing fallback. Cancellation must leave credentials unchanged.

Password replacement and revocation of all browser sessions must be atomic. Changing the password requires no service restart and must preserve identity, configuration, names, and audio state.

Do not expose password setup, change, recovery, or these privileged maintenance commands through web endpoints. Restarting FH must not restart unrelated audio infrastructure.

---

## 7. Updates, Recovery, and Removal

### 7.1 Update Behavior

FH supports updating without manual reinstallation.

Requirements:

- Check available versions.
- Preserve persistent configuration.
- Download and verify update artifacts.
- Install updates separately from the active release.
- Restart the service.
- Verify successful startup.
- Restore the previous working application release if the update fails.

Automatic update installation is not required for V1.

### 7.2 Reinstallation

Reinstalling FH preserves:

- Device identity
- Existing configuration
- Scenes
- Managed system membership
- Source and destination names
- Management password and unexpired remembered browser sessions

Reinstallation should repair missing application files, the maintenance command, and service configuration.

### 7.3 Recovery

Application recovery must not depend on manually recreating system configuration.

Persistent data should remain outside replaceable application directories.

Database changes require versioned migrations and a backup before destructive changes.

Application rollback does not imply automatic database rollback. Recovery must account for database compatibility.

### 7.4 Uninstall

Uninstallation must distinguish FH owned resources from existing user infrastructure.

Uninstalling FH must not automatically delete a preexisting Snapcast installation.

The normal uninstall process should offer:

- Remove application while preserving configuration.
- Completely remove FH managed data and identity.

Destructive removal requires explicit confirmation.

M10 must provide the following administrator-only CLI commands:

- `sudo flowharmonic uninstall`: show the removal plan and require confirmation, then stop and remove the FH application, maintenance command, and FH-owned service units. Preserve configuration, node identity, names, credentials, and system membership by default so a later reinstall can restore the node.
- `sudo flowharmonic uninstall --purge`: additionally remove FH-managed persistent data, identity, credentials, and backups, with a separate explicit confirmation that these cannot be restored by reinstalling.
- `sudo flowharmonic uninstall --dry-run`: show the plan without stopping services, notifying other nodes, or changing any files. Support combining this with `--purge` to preview complete removal.

The plan must identify FH-owned audio components and explain which playback or capture services will stop. Remove only resources FH provisioned; preserve preexisting Snapcast installations, unrelated configuration and services, and shared distribution packages.

After confirmation, attempt to notify the system host when uninstalling a member. If the host is unreachable, explain that its stale member entry may need manual removal without preventing local uninstall. Default uninstall must preserve the local membership and trust credentials for reinstall; any successful departure notification must be reconciled through explicit enrollment when the node returns. When uninstalling a system host, explain the loss of central management and its effect on other members before confirmation. Do not stop unrelated playback services.

### 7.5 Backup and Restore

Before V1 release, FH must support exporting and restoring configuration.

Backups should include the configuration and state necessary to reconstruct a node or managed system.

Secrets and device trust credentials must be protected appropriately.

---

## 8. Security

### 8.1 Local Service Privileges

The web application must not run with unrestricted root privileges.

Privileged operations should be isolated and limited to approved system management actions.

### 8.2 Network Access

Node discovery does not grant management access.

Joining a coordinator requires approval.

Management commands must be authenticated once nodes are joined.

The system must not trust arbitrary LAN devices merely because they are discoverable.

### 8.3 Web Security

The management interface must protect configuration changing operations from unauthorized access.

Each installation has one management password. No username, account registration, or role system is required for this local interface. Password creation, changes, and forgotten-password recovery use the administrator-only command described in section 6.6.

Signed-out browsers are directed to a separate sign-in page. The dashboard and audio inventory APIs require authentication. The health endpoint and a minimal sign-in-status endpoint remain public.

Remembered browser sessions last up to one year and survive reloads, new tabs, service restarts, updates, and reinstallation while valid. Signing out revokes that browser session, including other tabs sharing it; other browser sessions remain valid. A password change revokes every session.

Store salted password hashes and hashes of random session tokens in a protected persistent credential store outside application releases. Do not store plaintext passwords or session credentials in browser local storage. Credential backups must receive equivalent protection.

Session cookies must be HttpOnly, host-only, and SameSite=Strict, with Secure enabled over HTTPS. State-changing browser requests require cross-origin request protection. Rate-limit failed sign-ins.

The current installer serves HTTP for trusted local-network use. HTTP does not encrypt passwords or cookies. Use encrypted transport, such as HTTPS or an SSH tunnel, when the network cannot be trusted. Automatic HTTPS provisioning is not yet implemented.

Remote access over the public internet is outside V1 scope.

### 8.4 Updates

Update artifacts must be verified before installation.

Untrusted remote requests must not be allowed to execute arbitrary shell commands.

### 8.5 Existing Infrastructure

FH must not modify unrelated services or delete configurations it does not own without explicit authorization.

---

## 9. V1 Non Goals

The following are outside V1:

- Mixing multiple sources into one destination
- Automatic ducking
- Doorbell overlays
- Proprietary streaming service integrations
- Native mobile applications
- Automatic coordinator failover
- Multi coordinator clustering
- Cloud accounts
- Mandatory cloud services
- Audio processing or encoding implemented by FH
- Advanced audio effects
- Complex automation rules
- Windows and macOS production support

Windows and macOS remain future platform targets.

The V1 architecture should avoid unnecessary Linux specific assumptions in its user facing API, but it does not need speculative cross platform abstractions.

---

## 10. Development Milestones

Every milestone must remain installable, accessible through the web interface, and upgradable without losing persistent data.

### M1: Application Foundation

Goal: Establish a repeatably installable FH application with a working web interface.

Requirements:

- Python application
- FastAPI backend
- Basic sources and destinations dashboard
- installLinux.sh
- Debian and Fedora installation support
- systemd service
- Automatic service startup
- Application health endpoint
- Persistent application identity
- Basic version reporting
- Safe reinstall and update foundation
- Automatic local Snapcast installation

Acceptance criteria:

A clean supported Linux system can install FH, open its dashboard, reboot, reinstall FH, and retain its identity and configuration.

The initial dashboard may show empty sources and destinations when no usable endpoints have been configured.

### M2: Snapcast Control

Goal: Control an existing Snapcast installation through FH.

Requirements:

- Connect to local or remote Snapcast servers
- Enumerate streams
- Enumerate clients
- Display available sources and destinations
- Change routing
- Change volume and mute
- Handle connection errors

Acceptance criteria:

A user can select between multiple test sources for a destination through the web UI without editing Snapcast configuration.

An existing Snapcast system remains compatible.

### M3: Local Audio Provisioning

Goal: Automatically configure the local machine as an audio device.

Requirements:

- Detect local audio output hardware
- Configure the local Snapcast components
- Expose local playback destinations
- Provision test audio sources
- Manage required services automatically

Acceptance criteria:

A fresh Linux installation exposes usable local destinations and can play a test source through the web UI without manual audio configuration.

Agreed M3 usability and security follow-up:

- Provide the sign-in and CLI-only password management described in sections 6.6 and 8.3.
- Demonstrate hidden password setup and recovery, remembered sign-in, sign-out, and revocation of all sessions after a password change.
- Demonstrate that reinstalling retains identity, configuration, credentials, and valid browser sessions.
- Demonstrate readable disconnected-destination status and automatic restoration of controls after reconnection.

### M4: Desktop Audio

Goal: Make desktop system audio an FH source.

Requirements:

- Detect supported desktop audio environments
- Integrate PipeWire capture
- Preserve normal desktop playback and do not change the system default output without permission
- Publish desktop audio as a source
- Handle capture availability and failures in understandable language
- Exclude FH playback from capture to avoid feedback loops
- Handle desktop login and logout

Acceptance criteria:

Audio playing on a Linux desktop appears as a selectable FH source and can be routed to a destination without interrupting normal desktop output.

### M5: Standalone Node

Goal: Complete the independently usable FH node.

Requirements:

- Local sources and destinations
- Source switching
- Volume and mute
- Local configuration persistence
- Service recovery
- Reboot recovery
- Basic local diagnostics

Acceptance criteria:

A supported Linux machine functions as an independently manageable FH audio node through its local web interface.

### M6: Discovery and Enrollment

Goal: Connect independently installed FH nodes.

Requirements:

- LAN node discovery
- Existing system discovery
- Suggested enrollment
- Explicit join approval
- Persistent node identity
- Join and leave operations
- Basic authenticated communication
- Terminal-only discovery, joining, approval, confirmation, and leaving through `sudo flowharmonic connections`

Acceptance criteria:

Two independent FH nodes discover one another and can join the same managed system with user approval.

### M7: Central Coordination

Goal: Route audio across multiple FH nodes.

Requirements:

- Coordinator activation
- Central source and destination inventory
- List actual audio sources and destinations independently. A node with speakers must not appear as a source merely because it is enrolled.
- Allow users to show or hide each source in the systemwide source list without disabling the node's destinations or normal local playback.
- Persist source visibility across service restarts, reboot, and coordinator reconnection. Hiding a source removes it from new routing selections; it does not stop existing routes or act as an access-control boundary.
- Systemwide routing
- Remote node status
- Coordinator ownership of routing state
- Local node management
- Recovery from coordinator disconnection

Acceptance criteria:

A desktop source on one FH node can play through a destination on another FH node, controlled from one web dashboard.

A destination-only node such as Living Room speakers appears under destinations without a corresponding source entry. A user can hide and show a node's desktop audio source independently of its speakers. Hidden sources are omitted from new source selections, existing routes continue to work, and the visibility setting survives service restarts, reboot, and coordinator reconnection.

### M8: Additional Sources

Goal: Complete the planned V1 source types.

Requirements:

- Bluetooth audio reception
- Bluetooth pairing interface
- Local music folder playback
- Basic play and pause controls
- Microphone capture
- Supported line-in and USB audio input capture, with input device and channel selection
- Independent naming and lifecycle controls for configured physical input sources
- Input disconnect reporting and recovery without changing the selected input or automatically enabling speaker monitoring
- Source lifecycle management

Acceptance criteria:

A user can configure, start, and route each supported source through FH without editing underlying service configuration.

A user can select a supported microphone, line-in, or USB audio input and route it as a named source independently of the node's speaker destinations. Disconnecting the input produces an understandable unavailable state; reconnecting the configured input restores capture when it was enabled. Input setup does not automatically play the captured audio through local speakers.

### M9: Scenes and Reliability

Goal: Make daily use dependable.

Requirements:

- Save routing scenes
- Restore scenes
- Persist source and destination assignments
- Recover interrupted services
- Report disconnected devices
- Display meaningful errors
- Provide configuration backup and restore

Acceptance criteria:

A multizone configuration can be saved, restored, and recovered after normal service or device restarts without manual infrastructure configuration.

### M10: V1 Release Candidate

Goal: Deliver a reproducible, maintainable, user ready system.

Requirements:

- Validate supported Linux distributions
- Test clean installation
- Test update and rollback
- Test repair and reinstall
- Test uninstall behavior
- Implement and validate `sudo flowharmonic uninstall`, `--purge`, and `--dry-run` as described in section 7.4
- Test configuration backup and restore
- Validate node enrollment security
- Validate existing Snapcast compatibility
- Complete basic user documentation
- Complete end to end multizone testing

Acceptance criteria:

A new user can install FH on two supported Linux devices, connect them, configure sources and destinations, and operate a multizone audio system entirely through the web interface.

No manual Snapcast configuration is required for the supported installation path.

Default CLI uninstall removes FH application services while preserving persistent state; reinstall restores the same identity and saved configuration. Dry-run changes nothing. Purge removes only FH-managed data after explicit destructive confirmation. Both modes preserve preexisting Snapcast installations and shared packages, and clearly report membership and system-host consequences, including an unreachable host.

---

## 11. Development Rules

### 11.1 Keep It Small

Do not introduce architectural components until they solve a demonstrated problem.

Avoid premature abstraction.

### 11.2 Preserve Usability

Every milestone must retain:

- Working installation
- Working web interface
- Persistent configuration
- Service startup
- Update compatibility

### 11.3 Test Real Behavior

A milestone is complete only when its acceptance criteria are demonstrated.

Implementation alone does not constitute completion.

### 11.4 Preserve Existing Systems

Never assume FH owns infrastructure it did not provision.

### 11.5 Avoid Unnecessary Dependencies

Before adding a dependency, determine whether standard Python, existing Linux tools, or Snapcast already solve the problem.

### 11.6 Prefer Repair Over Reset

Updates and reinstalls should restore operation without destroying user state.

### 11.7 Do Not Expose Infrastructure Complexity

The interface should focus on sources, destinations, and audio control.

Advanced infrastructure details may appear in diagnostics, not normal operation.

---

## 12. Open Technical Questions

These are implementation decisions, not blockers for M1.

1. Exact Python and supported distribution version matrix.
2. Local Snapcast packaging differences between distributions.
3. Whether PipeWire capture requires a separate user session helper.
4. Bluetooth receiver implementation and pairing behavior.
5. Mopidy versus a simpler local music player.
6. Coordinator to node authentication and enrollment mechanism.
7. Reliable restoration of routing when nodes reconnect.
8. Supported Snapcast server topology when combining existing and FH managed installations.
9. Update distribution, version compatibility, and release verification.
10. Practical latency and recovery behavior across supported devices.

Resolve each question at the milestone where it becomes relevant.

---

## 13. Final Product Constraint

FlowHarmonic exists to eliminate complexity, not relocate it into another interface.

A user should be able to install FH, see the audio sources and destinations available to them, and choose where audio plays.

Every feature, dependency, screen, and abstraction must justify its existence against that goal.

Best part is no part.
