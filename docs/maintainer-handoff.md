# Maintainer handoff: 26.10.27 preview

This file preserves technical continuity independently of a workstation, temporary
VM, chat history or local development database. Read it with SPEC.md and README.md
before continuing work. Do not infer production readiness from the preview label.

## Saved state

- Release identifier: `26.10.27`; date format YY.MM.DD, never semantic versions.
- Product scope: implemented through historical M10, including uninstall, verified
  updates and backup reconstruction. There is no authorized next milestone here.
- UI: sources/destinations first, plain styling, no logo or column icons; ordinary
  remembered password sign-in. Password management is terminal-only.
- All remote disposable test VMs, images, recordings, cloud-init seeds and their
  extracted runtime were deleted. Temporary remote SSH authorization was revoked.
  No existing VM, SSH key, address, tunnel, `/tmp` path or local browser cookie is
  a prerequisite for resuming. Create new disposable VMs and fresh test identities.
- The repository contains source, documentation and sanitized test evidence, not
  an installed node's state. A new installation intentionally creates a new UUID.
  Actual node recovery needs that node's separately protected backup.

## Start on a fresh computer

1. Clone this private repository using your own GitHub authentication. Keep the
   repository private unless its owner explicitly changes that decision.
2. Read SPEC.md for product scope, README.md for operation and
   docs/verification.md for evidence and limitations.
3. Install Python 3.10+ with venv support. Create a development environment:

   ```bash
   python3 -m venv .venv
   .venv/bin/python -m pip install --only-binary=:all: --require-hashes -r requirements.txt
   .venv/bin/python -m pip install httpx==0.28.1
   cp packaging/config.toml .flowharmonic-config.toml
   ```

4. Run tests and a local development server:

   ```bash
   .venv/bin/python -m unittest discover -s tests -v
   node tests/test_dashboard.js
   node tests/test_scenes_ui.js
   bash -n installLinux.sh scripts/*.sh
   FLOWHARMONIC_CONFIG="$PWD/.flowharmonic-config.toml" \
     FLOWHARMONIC_DATA_DIR="$PWD/.flowharmonic" .venv/bin/python -m flowharmonic
   ```

   Node is only needed for JavaScript tests; the product has no frontend build.
   Local tests require loopback sockets. Use an installed disposable Linux VM to
   verify systemd, audio provisioning and password setup; a development server is
   not an installed node. Do not provision the workstation just to run unit tests.
5. Build a reproducible source artifact when needed:

   ```bash
   python3 scripts/package-release.py /tmp/FlowHarmonic-26.10.27.tar.gz
   ```

   Only trust archives from reviewed source and independently trusted checksums.
   Older M10 updaters cannot parse the first date release; upgrade them with the
   trusted source installer once. This preview's updater understands both formats.

## Architecture map

- `flowharmonic/app.py`: FastAPI application, health, authenticated dashboard APIs.
- `flowharmonic/security.py`, `cli.py`: remembered sign-in and local maintenance.
- `state.py`, `network.py`: persistent identity, explicit enrollment and signed
  node communication. Discovery is not authorization.
- `coordination.py`, `scenes.py`: inventory, routes, saved assignments and recovery.
- `snapcast.py`: bounded JSON-RPC adapter; Snapcast owns transport/synchronization.
- `provision.py`, `desktop.py`, `source_provision.py`, `source_worker.py`: owned
  hardware, PipeWire capture and additional source lifecycle.
- `backup.py`, `update.py`, `uninstall.py`, `versioning.py`: maintenance and release
  handling. Keep privileged actions out of the web application.
- `flowharmonic/static/`: HTML, CSS and vanilla JavaScript, no frontend framework.
- `installLinux.sh`, `scripts/`, `packaging/`: Linux installation and systemd.

Production stores live under `/var/lib/flowharmonic`; root-owned configuration
and ownership metadata live under `/etc/flowharmonic`. Releases live separately
under `/opt/flowharmonic`. Do not put runtime stores, backups, credentials or VM
images in Git. Database identity/schema versions remain 1; the product date is
not a database schema number.

## Verification baseline and remaining work

The historical M10 baseline passed 147 tests with one local FFmpeg skip, and all
11 native source tests passed on Debian. Real Snapcast TCP/HTTP compatibility was
included. The preview adds date-version validation, downgrade and legacy-release
removal regressions; see docs/preview-verification.md for the final release count.

Native behavior was exercised on Debian 13, Ubuntu 22.04 and Fedora 43 x86_64
(SELinux enforcing). Those VMs were removed after testing. Other implemented OS
releases, ARM/Pi hardware and physical Bluetooth A2DP reception remain unverified.
Do not silently turn these gaps into claims of support. Some older evidence calls
Fedora 42; the guest actually ran Fedora 43, as corrected in current verification.

On new disposable machines, reproduce the two-node web workflow, actual audio,
reboot, reinstall, update rollback, backup/restore, dry-run and isolated purge.
Use real sound-card recording or listening evidence, not only selected UI values.
Supply `SNAPSERVER_BINARY` and `SNAPCLIENT_BINARY` to enable real-server tests.
Optional tests skip when native FFmpeg or Snapcast binaries are absent.

Important recovery regressions already fixed:

- Successful uninstall departure preserves local membership/key even during
  background refresh; re-enrollment is explicit.
- Restoring damaged data starts an application that had been unable to run.
- Identity reconstruction retains ownership metadata. If generated inventory is
  missing, a marked running FH player is recognized and repaired without treating
  its occupied device as foreign or resetting its hardware mixer.
- Existing independently managed Snapcast, shared packages and unrelated data
  survive both uninstall modes. Never infer ownership from discovery.

Backups exclude media files, external Snapcast stores and OS Bluetooth pairings.
There is no hosted update feed, automatic host failover, OS-package rollback or
power-loss-atomic multi-store restore. Retired Snapcast clients can remain offline
records; do not delete arbitrary records to make a dashboard look cleaner.

## Working agreement

Keep changes small and within the requested scope. Preserve installability,
persistent configuration and the web interface. Demonstrate acceptance before
claiming completion. Keep personal names, machine-specific addresses, real
credentials and personal availability notes out of product documentation and
commits. A repository snapshot cannot substitute for private installed-node
backups. Use synthetic examples and disposable test secrets only.
