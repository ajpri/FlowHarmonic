# Milestone 10: release validation

M10 remains a milestone build, not v1 or a semantic version. Tests ran on the
remote host's disposable Linux VMs on 2026-10-27. No host desktop installation
was made. [SPEC §7 and M10](../SPEC.md) govern the acceptance checks.

## Implemented

- Administrator CLI uninstall with read-only dry-run, default state preservation,
  separately confirmed purge, ownership-aware resource removal and authenticated
  member-departure notification. Host/member consequences appear before removal.
- Explicit local/HTTPS checksum-pinned update checks and installation through the
  existing staged installer, health check and code/service rollback. Production
  archives are reproducible and exclude runtime state.
- Backup reconstruction with an explicit identity-replacement option that requires
  the original identity to be offline and unchanged infrastructure ownership.
  Recovery retains a private diagnostic snapshot when current data is damaged,
  and starts the application even if damage had stopped it.
- Additive departure tracking preserves local membership/trust after removal;
  successful departure requires explicit leave/re-enrollment when reinstalled.
- Current platform labeling, CLI help and basic install, two-node web setup,
  update, removal and recovery documentation in [README](../README.md).

## Acceptance evidence

| Check | Evidence |
| --- | --- |
| Clean supported installation | Official SHA512-verified Debian 13 x86_64 cloud image, initially no FH; installer installed dependencies, enabled systemd services, detected HDA output, exposed sources/destination and opened M10 sign-in/dashboard. |
| Native platform coverage | Ubuntu 22.04.5 x86_64 and Fedora 43 x86_64 upgraded to M10; Fedora retained SELinux enforcing. Clean installs of these retained guests were demonstrated in earlier milestones. |
| Verified update | Local archive check/install succeeded on all three guests. Wrong SHA256 was rejected on Ubuntu with healthy installation unchanged. |
| Activation rollback | Intentionally failing app artifact passed its supplied digest but failed startup. Installer restored the previous active release and service; same UUID and working dashboard returned. Failed release retained for diagnosis. |
| Default member uninstall | Fedora showed its plan, required UNINSTALL, notified host with signed departure and removed only owned app/audio resources. Reinstall retained original UUID and configured password. Regression covers preserving membership even during background refresh after notification. |
| Host removal | Debian plan explained loss of central management and source/playback effects. Default uninstall/reinstall retained UUID, source definition, scene, membership, credentials and remembered browser session. User music remained. |
| Unreachable host | Ubuntu member removed while Debian host was down; CLI warned that stale host entry might need removal and still completed. Reinstall retained original UUID, management password and membership. |
| Purge isolation | Fedora required UNINSTALL then PURGE. FH DBs, backups and CLI disappeared. Unrelated data remained. An independent Snapcast service kept its exact PID and unchanged config; installed RPM list was byte-identical. External protected backup survived. |
| Identity reconstruction | Fedora fresh post-purge UUID differed; explicit `--replace-identity` restore recovered original UUID and credential state with unchanged ownership. A discovered running-player ownership issue was fixed; automatic provisioning then restored the original client ID and cross-node route. |
| Native dry-run | Both modes preserved all 21 inspected persistent/configuration/unit/launcher files (hash and mtime) and stopped service states; original active services resumed after the test harness finished. |
| Backup repair | Debian scene DB deliberately corrupted with FH stopped. Restore retained a mode-0600 raw recovery ZIP, restored the saved M10 multizone scene, started FH and verified health with the same UUID. |
| Reboot recovery | Debian guest rebooted through systemd; FH returned automatically with its UUID, sign-in and scene retained. |
| Enrollment security | Real two-sided web enrollment with matching code. Automated cases reject tampering, wrong key/audience, replay, stale timestamps, unauthenticated and cross-origin control, public/link-local/rebinding targets. Discovery never grants access. |
| Existing Snapcast | Real independent Snapcast TCP and HTTP fixtures passed control/restart compatibility without config modification. Native purge retained an independently managed Snapcast process/config and shared packages. |
| Entire web audio workflow | Debian created system; Fedora requested join; matching codes approved/confirmed on both dashboards. A local WAV folder was read, named, added and played through Local source setup. Host dashboard routed it to both VM outputs and exercised volume/mute and saved/applied a two-destination scene. No manual Snapcast edits. |
| Actual audio reception | Remote QEMU sound-card recordings measured 660.0 Hz on both nodes. Debian RMS 2576.94, Fedora RMS 3532.91 before changing volume/mute. VM recordings establish electrical playback, not physical speaker audibility or synchronization precision. |

The WAV file is a test media fixture; its creation is not an audio configuration
step. FH provisioned every stream and player for the supported path.

## Repeatable checks

1. On two fresh supported machines run `./installLinux.sh --check` and
   `sudo ./installLinux.sh`; set passwords through the CLI and open dashboards.
   Follow README's two-node web setup; select one music source for both outputs,
   adjust volume/mute and save/apply a scene. Verify both outputs receive audio.
2. Record `flowharmonic status`, names, scene and sign-in. Reboot; verify startup
   and saved state. Reinstall from the same trusted source; verify UUID unchanged.
3. Build a release with `scripts/package-release.py`. Use `update … --sha256 …
   --check`, then install. Supply a wrong checksum and verify no activation.
   In a disposable VM only, package an intentionally broken app and verify
   activation fails, the old active release returns and health recovers.
4. Run both uninstall dry-run variants. Review plans and verify state/services
   unchanged. Test cancellation at both confirmation prompts. Default uninstall,
   reinstall and compare identity/settings. On a member, test reachable and
   unreachable host; explicitly re-enroll after successful departure.
5. Save `backup /root/private.zip` outside FH's data directory. On a disposable
   node, purge with both confirmations, verify only owned data was removed,
   reinstall, then restore with `--replace-identity` and confirm its UUID. Keep
   the original identity offline throughout. Verify unchanged ownership ledger.
6. Keep an independent Snapcast server running during removal/purge. Compare PID,
   configuration hash, package inventory and normal RPC operation afterward.

## Scope and limits

Only Debian 13, Ubuntu 22.04 and Fedora 43 x86_64 were exercised natively. Other
implemented releases and ARM/Pi hardware remain unverified; installer labels them
accordingly. Some historical M8/M9 prose incorrectly calls the Fedora guest 42;
its actual release is 43. Debian's image kernel/initrd booted directly under the
remote QEMU harness after GRUB failed; its guest reboot/systemd path was tested.

There is no hosted update feed: the administrator supplies a trusted artifact
location and checksum. Hashes detect substitution only when obtained through a
trusted channel. Updates do not roll back OS packages or audio infrastructure;
power-loss atomic recovery across several stores is not claimed. Backups are
private, unencrypted configuration/trust archives; media, independent Snapcast
state and OS Bluetooth pairings remain external. Real Bluetooth A2DP reception
and physical audio hardware retain the earlier VM-only verification gap.

See [machine-readable results](M10-acceptance.json) and the
[web-created two-zone scene](M10-multizone.jpg).


## Automated checks

Final suite: **147 tests, 146 passed, one local FFmpeg skip**, in 81.647 seconds.
The final regression suite includes real Snapcast TCP/HTTP control, enrollment
security, repair/rollback, archive validation, both uninstall confirmation gates,
foreign infrastructure preservation, departure reconciliation, damaged-state
recovery and missing-inventory player recovery. Dashboard and scene JavaScript
checks, Python compilation and shell syntax checks also passed. The native Debian
source suite passed all 11 tests, including FFmpeg decoding unavailable locally.

Reconstruction can leave a previously seen Snapcast client listed offline; FH
retains those server records rather than guessing that all old clients are safe
to delete. The current restored hardware destination is detected and usable.


## Final recovery and cleanup

After the playback-ownership correction, the web-applied scene restored the
original Fedora destination, music route, 60% volume and mute. Unmuting through
the dashboard produced 660.0 Hz at both sound-card recorders again (Debian RMS
3532.31, Fedora RMS 1169.75). A native signed departure followed by refresh kept
membership and private key byte-identical and required explicit re-enrollment.

Temporary membership was removed from every node. Test music, scene and the
independent Snapcast fixture were removed; VM speakers returned to local Silence,
100% and unmuted. Ubuntu retained its original identity/password and its isolated
test LAN interface was put down. Fedora recovered its original identity and
original unset password state from the protected backup. Existing PC listening
destinations were not changed. Protected external backups remain on the VMs.

The [dashboard during recovered cross-node playback](M10-dashboard.jpg) also
shows the conservative offline record retained by Snapcast after reconstruction.

The extra Debian guest was powered down after validation; its disk and protected
backups remain available. Ubuntu and Fedora were left running M10.
