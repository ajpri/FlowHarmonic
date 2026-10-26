# Sign-in and installed maintenance

FlowHarmonic has one management password. Credentials are created, changed and
recovered only from the command line on the installed machine. There are no
accounts, setup links, browser password-management screens, or control keys.

## First use and password changes

The installer installs `/usr/local/bin/flowharmonic`, which follows the active
release. An interactive first installation offers hidden, confirmed password
entry. An unattended installation leaves the password unset; the sign-in page
explains the command to run:

```bash
sudo flowharmonic password
```

Use this same command to change a password or recover a forgotten one. Enter it
twice; typing displays no password characters. Passwords must contain 12–128
characters. Arguments, environment variables, piped input and an echoing fallback
are not accepted for password entry. A mismatch permits correction. Cancellation
or invalid input leaves credentials unchanged.

A password change atomically replaces the hash and revokes all existing browser
sessions. Device identity, application configuration, names, routing and other
settings are retained. No service restart is needed. The command requires a local
administrator, then drops to the application's service account before writing
SQLite so credentials and recovery journals retain the correct ownership.

## Browser behavior

Open the normal dashboard URL. A signed-out browser gets a separate sign-in
page. Enter the management password once to open the dashboard. Reloads, new
tabs, service restarts and reinstalls retain the remembered browser session.
Another browser signs in separately. Sign out revokes that browser's token,
including its other tabs and copied cookies; other browsers remain signed in.
Cookies and server-side sessions last up to one year. Clearing cookies or using
private browsing requires sign-in again.

The dashboard and audio inventory APIs require sign-in. `/health` and the small
`/api/auth` sign-in-status endpoint remain public. Signed-in, connected destinations
have ordinary controls. Offline destinations display last known settings and an
explanation; controls return automatically after reconnection, even if a stale
control retained keyboard focus. Audio connection loss also presents readable
status instead of a block of greyed-out controls.

## Maintenance commands

```bash
flowharmonic                 # same as status
flowharmonic status          # health, identity, URL, and password-setup status
flowharmonic --version
sudo flowharmonic password   # first setup, change, or recovery
sudo flowharmonic logs       # latest 50 application journal entries
sudo flowharmonic restart    # restart the application and verify health
flowharmonic --help
```

The wrapper resolves imports from the root-owned active release rather than the
caller's working directory. Installation repairs the wrapper and refuses to
replace an unrelated command with the same name. Restart affects the application
service only; it does not restart unrelated audio infrastructure. These privileged
maintenance operations are never exposed through the web API. Application code,
units and configuration remain protected from web-service writes.

For a development checkout, `python -m flowharmonic` (or `serve`) still runs the
server. Development tests set passwords directly only inside their isolated
synthetic state. The installed `password` command expects the installed service
account and directory ownership; do not point it at an unrelated user's data.

## Storage and request protection

No additional runtime packages are needed. The protected
`/var/lib/flowharmonic/authentication.db` (mode 0600, schema 1) contains a salted
scrypt password hash and SHA-256 hashes of random 256-bit session tokens. The
identity database remains schema 1, preserving earlier-release rollback
compatibility. The installer creates consistent SQLite credential backups and
never resets credentials simply because it runs again. Unknown schemas are
refused. Legacy `control.key` files are retained for old-release rollback only;
current code neither creates nor uses them.

Password hashing uses Python's standard library with scrypt N=2^14, r=8, p=5,
a random 16-byte salt and dklen=32: an [OWASP low-memory configuration](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html#scrypt).
Hashing is serialized within the service to bound memory. Eight failed sign-ins
within a minute trigger a retry response. Password verification and session
creation also serialize with CLI password resets across processes, preventing
an old-password login from surviving a concurrent reset.

Session cookies are HttpOnly, SameSite=Strict, host-only and named per node.
HTTPS responses set Secure. Credentials are not stored in local/session storage.
Existing remembered cookies from the older `/api` path migrate to `/` so page
requests can authenticate without forcing sign-in again. Writes require a custom
request header, validate Origin when supplied and reject cross-origin browser
preflights. No username, role system, or general shell/RPC proxy is introduced.
See [OWASP session guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).

The default installer still serves HTTP on a trusted LAN. HTTP does not encrypt
passwords or cookies; the current VM test uses an SSH tunnel. Automatic HTTPS
provisioning remains unresolved. Proxy headers are not implicitly trusted. Public
internet deployment is unsupported.

## Verified behavior

The final Python suite passed **62 tests** (46.581 seconds). It includes
confirmed/hidden terminal input, cancellation, noninteractive and unprivileged
refusal, password/session atomicity, concurrent login/reset protection, protected
pages/API reads, remembered-cookie migration, installer repair and rollback,
PATH command execution outside the checkout, and existing real Snapcast control.
The in-memory JavaScript checks cover sign-in redirects, remembered sessions,
focused-control disconnection, readable offline/outage state and reconnection.

[Real terminal evidence](maintenance-acceptance.json) was recorded in the
Ubuntu 22.04 VM using isolated synthetic state. A native PTY exercised the
installed command's hidden first-password setup and reset, verified no password
was echoed, verified service-account file ownership/mode 0600, and confirmed
session revocation, cancellation, noninteractive refusal and status output.
The real demo password was not chosen by this test, and no audio routing changed.
The installed demo's status, logs and restart commands also passed; its identity,
configuration and silent playback were retained.

For the current disposable VM only, from the testing PC an interactive command
can be reached through the saved test SSH configuration:

```bash
ssh -t -F /tmp/fh-m3-vm/remote-ssh-config fh-m3-remote-vm sudo flowharmonic password
```

This SSH wrapper is test infrastructure. On a normal installed machine, use
`sudo flowharmonic password` directly.
