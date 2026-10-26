# M1 verification results · October 25, 2026

**Status: implemented; full acceptance pending real clean-system/reboot tests.**

Environment: Pop!_OS 22.04 host, x86_64, Python 3.10.12. This host is intentionally
not in the installer's explicit OS matrix. No host packages, accounts, services,
or system configuration were changed. Application dependencies live in `.venv`;
preview state lives in `.flowharmonic`.

| Check | Result | Evidence / limitation |
| --- | --- | --- |
| Production dependency install | Passed | Pinned packages installed with `--require-hashes` in the project venv |
| Application + installer suite | Passed | `python -m unittest discover -s tests -v`: 17 tests, 20.655 seconds |
| Python compilation | Passed | `compileall` on application, scripts, and tests |
| Shell syntax | Passed | `bash -n` on installer and shell helpers |
| systemd directive validation | Passed with host warning | `systemd-analyze verify` on temporary copies with ExecStart replaced by `/usr/bin/true` and WorkingDirectory by `/tmp`; exit 0. Host netplan unit was unreadable. Actual installed executable paths, permissions and sandbox operation still require target-system testing. |
| Live dashboard | Passed | Real HTTP server and in-app browser: Device online, Sources/Destinations empty, M1 footer; [screenshot](dashboard.png) |
| Browser outage recovery | Passed | Stopping the preview displayed Device unavailable, readable error and retry button; restarting automatically restored Device online |
| Reinstall/config/UUID retention | Passed in harness | Actual app processes and SQLite; package/account/systemd commands simulated |
| Missing asset and damaged/missing unit repair | Passed in harness | Isolated filesystem; real copied application assets and unit contents |
| Failed candidate rollback | Passed in harness | Actual candidate process failed; previous release restored, restarted and served the retained node state |
| Existing Snapcast preservation | Passed in harness | No Snapcast package or service mutations when marked existing |
| Fedora ownership/service repair | Passed in harness | Simulated package/system commands and cached binary stand-ins; no native compilation performed |
| Unsupported OS rejection | Passed | Real host `--check` rejects `pop 22.04 x86_64`; test rejects unsupported Fedora release before mutation |
| Clean Debian/Fedora-family installation | Pending | No disposable VM/container runtime available in this session |
| Actual Snapcast install/build and service readiness | Pending | Distribution packages and Fedora native build not executed on target systems |
| Reboot/autostart retention | Pending | No disposable supported system rebooted |

The explicit release/architecture matrix and the commands needed to finish
acceptance are in [verification.md](verification.md). The automated suite must
not be interpreted as validating distribution support or real reboot behavior.

M1 scope decisions: identity has one SQLite representation; name/listener settings
are in preserved TOML; updates use trusted local source and staged reinstall;
remote update distribution and functional audio are deferred. No M2+ behavior was
implemented. See README for recovery boundaries and storage locations.
