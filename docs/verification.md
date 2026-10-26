# Foundation installation/reboot verification (current M2 build)

The M1 foundation is retained in the current M2 build. **Full milestone acceptance is pending** clean
supported-distribution installations and reboot tests. Per SPEC §11.3,
implementation and mocked installer checks alone do not establish completion.

## Implemented platform matrix

| Distribution | Releases | Architectures | Installation/reboot validation |
| --- | --- | --- | --- |
| Debian | 12, 13 | x86_64, aarch64 | Pending |
| Ubuntu | 22.04, 24.04 | x86_64, aarch64 | Pending |
| Raspberry Pi OS | 12, 13, 64-bit | aarch64 | Pending |
| Fedora | 42, 43 | x86_64, aarch64 | Pending |

The installer uses exact OS ID/release/architecture checks, never `ID_LIKE`.
Raspberry Pi OS 64-bit commonly identifies as Debian; either explicit matching
ID is accepted. 32-bit ARM is not in the matrix. Do not claim validated support
for a row until the real procedure below has passed on that release/architecture.
Fedora SELinux enforcing mode must be included in validation.

## Automated checks

Run the test command in README. Tests cover:

- HTML, assets, inventory, health, node information, and milestone reporting.
- Persistent UUID and administrator configuration across application restarts.
- Concurrent initialization, missing identity, unknown schema, future schema,
  database health failure, and consistent SQLite backup.
- Installer platform rejection, ownership metadata preservation, fresh install,
  repeated install, missing application asset repair, broken unit replacement,
  configuration retention, and rollback after an actual candidate process fails.
- Preexisting Snapcast binaries/units: no package installation or service mutation.
- Fedora ownership and service repair with cached binary stand-ins (no native build).

In installer tests only, absolute paths are rebased into a temporary directory;
account/package/systemd commands are doubles. Per-release code, configuration,
database, startup, HTTP checks, and rollback files are real. Thus these tests do
not demonstrate package names/availability, service permissions/sandboxing,
Snapcast source compilation, SELinux behavior, or reboot startup.

## Real acceptance procedure (each matrix combination)

Use a fresh VM or device booted with systemd, working distribution repositories,
DNS/network access, and a non-root administrator with sudo. Do not run this on an
unrelated production audio system. Copy the whole trusted source tree.

1. **Clean install**

   ```bash
   ./installLinux.sh --check
   sudo ./installLinux.sh
   systemctl is-enabled flowharmonic
   systemctl is-active flowharmonic
   systemctl show flowharmonic -p User -p Group
   curl --fail http://127.0.0.1:8080/health
   curl --fail http://127.0.0.1:8080/api/node | tee /tmp/fh-before.json
   ```

   Expect enabled/active, user/group `flowharmonic`, health `ok`, version `M2`,
   schema 1, a UUID identity, and an installation fingerprint beginning `M2-`.
   Verify Snapcast automatically installed: Debian family
   `systemctl is-active snapserver` and `command -v snapclient`; Fedora
   `systemctl is-active flowharmonic-snapserver` and
   `/opt/flowharmonic/snapcast/0.30.0/bin/snapclient --version`.
   Confirm newly owned clients are not playing audio.

2. **Working dashboard**

   Open `http://<device-IP>:8080` in a browser. Allow TCP 8080 on the trusted LAN
   using the administrator's firewall policy if needed. Expect “Device online”,
   Sources and Destinations panels with real inventory, or an audio connection error/empty state if no endpoints are available, and `M2`.
   Check a narrow/mobile viewport. Stop FH, wait 15 seconds, and confirm the
   readable unavailable/retry state; start FH and confirm recovery.

3. **Persistent non-default configuration**

   Change only the `name` entry in `/etc/flowharmonic/config.toml` to
   `Acceptance Room`, restart FH, and confirm that name in the footer and
   `/api/node`. Capture the expected state and configuration checksum:

   ```bash
   curl --fail http://127.0.0.1:8080/api/node > /tmp/fh-expected.json
   sudo sha256sum /etc/flowharmonic/config.toml > /tmp/fh-config.sha256
   sudo cp /tmp/fh-expected.json /var/tmp/fh-expected.json
   sudo cp /tmp/fh-config.sha256 /var/tmp/fh-config.sha256
   ```

4. **Reboot and automatic startup**

   ```bash
   sudo reboot
   # Reconnect after boot:
   systemctl is-enabled flowharmonic
   systemctl is-active flowharmonic
   curl --fail http://127.0.0.1:8080/api/node > /tmp/fh-after.json
   diff /var/tmp/fh-expected.json /tmp/fh-after.json
   sudo sha256sum -c /var/tmp/fh-config.sha256
   ```

   Expect no differences and a working dashboard without manually starting FH.
   Also verify the owned Snapcast server is active after reboot.

5. **Reinstall and repair**

   Run `sudo ./installLinux.sh` again. Repeat identity/config comparisons and
   dashboard checks. Record `readlink -f /opt/flowharmonic/current`. Delete only
   the installed `flowharmonic/static/style.css` and damage the installed FH
   service unit in this disposable system. Rerun the installer; both must be
   repaired, while `/api/node` and the config checksum remain identical.

6. **Failed update and rollback**

   Copy the trusted source tree to a separate test directory. In that copy,
   prepend `raise RuntimeError("M1 rollback acceptance test")` to
   `flowharmonic/app.py`. Run its installer. It must exit nonzero after startup
   fails, restore the prior current symlink/unit, and restart the previous app.
   Verify health, the expected node JSON, unchanged config checksum, and the
   pre-activation database/config backup. The failed release stays for diagnosis.
   Restore normal source and rerun the installer to prove recovery.

7. **Existing infrastructure** (separate fresh VM snapshot)

   Preinstall/configure Snapcast before installing FH. Record package versions,
   unit enablement/activity, and hashes of Snapcast configs. Install/reinstall FH.
   Verify those records are unchanged and `infrastructure.json` marks those
   components `existing`. Repeat with the existing server intentionally stopped.

Record distribution release, architecture, Python version, SELinux state (Fedora),
commands/output, browser evidence, and any failure for every run. Keep records
outside the replaceable application directory.

## M1 scope decisions and limitations

- UUID is stored in SQLite rather than a duplicate `identity/` file; the spec's
  filesystem layout is proposed and SQLite is its stated persistence mechanism.
- Device name/listener settings use preserved `/etc/flowharmonic/config.toml`.
  M2 protects audio mutations with a persisted control key; see README.
- Updates currently mean rerunning the installer from trusted local source.
  Remote version checks, downloadable FH artifacts, signature distribution,
  uninstall, and configuration export remain deferred.
- Installer success verifies application startup and the newly owned server's
  systemd activity. The separate M2 real-server acceptance checks do not validate clean installation/reboot.
- Full package rollback, transaction recovery after sudden power loss, and
  automatic old-release pruning are not implemented. Persistent state is retained
  and rerun repair is available; ordinary activation failures restore the app/unit.


M3 validation update: Ubuntu 22.04.5 x86_64 has now passed actual clean install,
reboot, and reinstall in a virtual HDA-equipped KVM guest. See
[M3 verification](M3-verification.md) for current evidence and remaining targets.
