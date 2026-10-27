# 26.10.27 Preview Release verification

This date-based preview carries the product implemented through M10. Native
M10 audio and lifecycle evidence remains in [M10 verification](M10-verification.md).
The release changes product documentation, release identifiers and version
handling; historical reports retain the versions they actually tested.

Date-version regressions verify calendar validity, ordering across month/year
boundaries, ordering after legacy milestones, downgrade rejection before any
installation, reproducible packaging and recognition/removal of both legacy and
date-named application releases. The installer reads the product version from
its source, and its health check verifies that version, exact build and identity.

The README and SPEC describe the product and preview boundaries. The portable
[maintainer handoff](maintainer-handoff.md) records how to recreate development
and disposable test machines. No old machine, private key or `/tmp` path is needed.

Repository privacy review includes source, evidence, image metadata and both
historical commits. A personal device label and its identifier were replaced
with synthetic test labels in history. The old desktop fixture's special-case
reference is anonymized in history and removed from the current test script.
Git author metadata uses a product identity with no personal email address.

All three disposable remote VMs, their disks, images, recordings and cloud-init
seeds were deleted at the owner's request, along with the dedicated extracted
VM runtime. Temporary remote SSH authorization was removed. Earlier reports
that say a VM was retained describe historical state, not a current test resource.

Known validation gaps remain: untested release/architecture combinations,
physical Bluetooth A2DP reception and sudden-power-loss recovery across multiple
stores. No new native VM run is claimed after the date-version change and VM
cleanup; installed-service behavior is covered by the installer harness and the
previous native M10 evidence.

## Release checks

Final regression suite: **150 tests, 149 passed, one local FFmpeg
skip**, in 79.178 seconds. The existing native Debian source test covers
that decoder. Real local Snapcast TCP/HTTP tests were enabled and passed.
Dashboard and scene JavaScript checks, Python compilation and shell syntax passed.

The date-version installer harness demonstrated clean installation, repair,
reinstall, retained identity/configuration/session and failed-activation rollback.
No semantic-version or stable-v1 claim is introduced.
