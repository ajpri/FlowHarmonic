# M6 Fedora smoke test

Tested the committed M6 source `b9d2aaa31484f1c8eb3c822daa7b2bdf4bde4393`
on Fedora 43 Cloud x86_64 in a KVM VM on the authorized remote host.
The official Fedora image's SHA-256 checksum was verified. SELinux remained
**Enforcing** throughout. No application or installer fixes were needed.

Passed:

- Normal clean installation, including the Fedora Snapcast build.
- Authenticated dashboard HTML and audio/connection API checks.
- Real two-way mDNS discovery between independent Fedora and Ubuntu VMs.
- CLI join request, matching-code approval on both sides, and authenticated communication.
- Identity and membership persistence after service restart, reinstall, and reboot.
- Enabled FH application and owned audio server recovered after reboot.
- Leave and system dissolution; original Ubuntu node restored to independent operation.

This was a focused smoke test, not a full Fedora certification or desktop-audio test.
The Cloud image's firewalld was inactive. Joining used the explicit private LAN
address because both VMs had identical addresses on their separate NAT networks;
mDNS node detection was verified, but automatic address selection across those
multiple interfaces was not validated. No desktop or host firewall changes were made.

The Fedora VM was shut down and the temporary test network removed. Its disk and
installation logs remain in `/tmp/flowharmonic-fedora-m6` on the remote host for reuse.
Sanitized results: [M6-fedora-smoke.json](M6-fedora-smoke.json).
