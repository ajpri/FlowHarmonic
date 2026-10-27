# Current validation: 26.10.27 Preview Release

See [preview release checks](preview-verification.md),
[M10 acceptance evidence and repeatable checks](M10-verification.md),
[maintenance and two-node setup](../README.md#maintenance), and
[the specification](../SPEC.md).

| Platform | Implemented targets | Native VM validation |
| --- | --- | --- |
| Debian | 12/13, x86_64/aarch64 | Debian 13 x86_64: M10 clean install, reinstall and reboot |
| Ubuntu | 22.04/24.04, x86_64/aarch64 | Ubuntu 22.04 x86_64: clean install in M3; M10 update, rollback and reinstall |
| Fedora | 42/43, x86_64/aarch64 | Fedora 43 x86_64, SELinux enforcing: installation and M10 maintenance |
| Raspberry Pi OS | 12/13, aarch64 | Not verified on Pi hardware |

The installer checks explicit OS/release/architecture, never guesses from ID_LIKE,
and labels unverified targets. Remaining releases and ARM hardware are implemented
but unvalidated; do not treat this as an all-platform release certification.
Debian's cloud image was SHA512-verified against its official manifest. The VM
harness uses that image's kernel/initrd directly because its GRUB did not boot
under the remote host's QEMU. Guest reboot, systemd and FH startup still run.

Older milestone reports are historical evidence. Some M8/M9 prose labels the
Fedora guest as 42; its actual /etc/os-release is Fedora 43. M10 uses the verified
OS identification. The M8 physical Bluetooth A2DP reception gap remains open.
