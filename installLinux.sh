#!/usr/bin/env bash
set -Eeuo pipefail
umask 022
SOURCE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
VERSION=$(sed -n 's/^VERSION = "\([^"]*\)"$/\1/p' "$SOURCE/flowharmonic/__init__.py")
# shellcheck source=scripts/install-common.sh
source "$SOURCE/scripts/install-common.sh"

main() {
    [[ $# -le 1 ]] || fail 'Usage: installLinux.sh [--check]'
    [[ $# == 0 || $1 == --check ]] || fail 'Usage: installLinux.sh [--check]'
    # Only explicit release/architecture combinations, never ID_LIKE guesses.
    source /etc/os-release
    local arch
    arch=$(uname -m)
    platform_supported "$ID" "$VERSION_ID" "$arch" || fail "Unsupported platform: $ID $VERSION_ID $arch. See docs/verification.md."
    printf 'Platform: %s %s (%s)\n' "$ID" "$VERSION_ID" "$arch"
    if platform_validated "$ID" "$VERSION_ID" "$arch"; then
        printf 'Validation: tested release/architecture; see docs/verification.md for scope.\n'
    else
        printf 'Validation: implemented target, not yet verified on this release/architecture. See docs/verification.md.\n'
    fi
    [[ -d /run/systemd/system ]] || fail 'A booted systemd system is required.'
    [[ ${1:-} != --check ]] || return 0
    [[ $EUID == 0 ]] || fail 'Run with sudo: sudo ./installLinux.sh'
    command -v flock >/dev/null || fail 'flock (util-linux) is required.'
    if [[ -e /usr/local/bin/flowharmonic || -L /usr/local/bin/flowharmonic ]]; then
        [[ -f /usr/local/bin/flowharmonic && ! -L /usr/local/bin/flowharmonic ]] &&
            [[ $(sed -n '2p' /usr/local/bin/flowharmonic) == '# Managed by FlowHarmonic installer' ]] ||
            fail 'An unrelated /usr/local/bin/flowharmonic command already exists; it was retained.'
    fi
    exec 9>/run/lock/flowharmonic-install.lock
    flock -n 9 || fail 'Another installation is running.'
    export FLOWHARMONIC_CONFIG=/etc/flowharmonic/config.toml
    export FLOWHARMONIC_DATA_DIR=/var/lib/flowharmonic
    work=$(mktemp -d /tmp/flowharmonic-install.XXXXXXXX)
    rollback_needed=0
    previous=''
    had_unit=0
    was_enabled=0
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM

    if [[ $ID == fedora ]]; then
        dnf install -y python3 python3-pip curl ca-certificates tar gzip shadow-utils alsa-utils pipewire-utils pipewire-gstreamer gstreamer1 bluez wireplumber pipewire-libs ffmpeg-free
    else
        apt-get update
        DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv curl ca-certificates tar gzip alsa-utils pipewire-bin gstreamer1.0-tools gstreamer1.0-pipewire bluez wireplumber libspa-0.2-bluetooth ffmpeg
    fi
    source "$SOURCE/scripts/audio-drivers.sh"
    install_audio_drivers
    python3 -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ required"'
    if ! id flowharmonic >/dev/null 2>&1; then
        useradd --system --user-group --home-dir /var/lib/flowharmonic --shell /usr/sbin/nologin flowharmonic
    fi
    if ! getent group audio >/dev/null; then groupadd --system audio; fi
    if ! id flowharmonic-audio >/dev/null 2>&1; then
        useradd --system --user-group --groups audio --home-dir /nonexistent --shell /usr/sbin/nologin flowharmonic-audio
    else
        usermod -a -G audio flowharmonic-audio
    fi
    install -d -o root -g root -m 0755 /var/lib/flowharmonic-audio
    install -d -m 0755 /opt/flowharmonic/releases /etc/flowharmonic
    install -d -o flowharmonic -g flowharmonic -m 0750 /var/lib/flowharmonic
    install -d -o root -g root -m 0700 /var/lib/flowharmonic/backups
    if [[ ! -f /etc/flowharmonic/config.toml ]]; then
        install -m 0644 "$SOURCE/packaging/config.toml" /etc/flowharmonic/config.toml
    fi

    # Save ownership BEFORE package installation so interrupted installs stay owned.
    server_owner=flowharmonic
    client_owner=flowharmonic
    if command -v snapserver >/dev/null || systemctl cat snapserver.service >/dev/null 2>&1; then server_owner=existing; fi
    if command -v snapclient >/dev/null || systemctl cat snapclient.service >/dev/null 2>&1; then client_owner=existing; fi
    read -r server_owner client_owner < <(python3 "$SOURCE/scripts/install-state.py" ownership \
        /etc/flowharmonic/infrastructure.json "$server_owner" "$client_owner")
    if [[ $ID == fedora ]]; then
        if [[ $server_owner == flowharmonic || $client_owner == flowharmonic ]]; then
            source "$SOURCE/scripts/snapcast-fedora.sh"
            install_fedora_snapcast
        fi
    else
        local packages=()
        [[ $server_owner != flowharmonic ]] || packages+=(snapserver)
        [[ $client_owner != flowharmonic ]] || packages+=(snapclient)
        if ((${#packages[@]})); then
            DEBIAN_FRONTEND=noninteractive apt-get install -y "${packages[@]}"
        fi
    fi

    # Each attempt gets a distinct path. venv paths must never move after creation.
    build="$VERSION-$(date -u +%Y%m%dT%H%M%SZ)-$(basename "$work" | cut -d. -f2)"
    release="/opt/flowharmonic/releases/$build"
    install -d -m 0755 "$release"
    cp -R "$SOURCE/flowharmonic" "$release/"
    find "$release" -name __pycache__ -type d -exec rm -rf {} +
    install -m 0644 "$SOURCE/requirements.txt" "$release/requirements.txt"
    printf '%s\n' "$build" > "$release/BUILD"
    python3 -m venv "$release/.venv"
    "$release/.venv/bin/python" -m pip install --only-binary=:all: --require-hashes -r "$release/requirements.txt"
    chown -R root:root "$release"
    chmod -R go-w "$release"
    (cd "$release" && "$release/.venv/bin/python" -m flowharmonic --version)
    # Validate preserved configuration before interrupting the running application.
    health_url=$(cd "$release" && "$release/.venv/bin/python" - <<'PY'
from flowharmonic.config import load_config
config = load_config()
host = config['host']
if host in ('0.0.0.0', '::'):
    host = '127.0.0.1' if host == '0.0.0.0' else '::1'
if ':' in host:
    host = f'[{host}]'
print(f"http://{host}:{config['port']}")
PY
    )
    if [[ -e /opt/flowharmonic/current || -L /opt/flowharmonic/current ]]; then
        [[ -L /opt/flowharmonic/current ]] || fail 'current must be a release symlink; refusing to replace a directory.'
        previous=$(readlink -f /opt/flowharmonic/current)
        [[ $previous == /opt/flowharmonic/releases/* ]] || fail 'current points outside releases.'
    fi
    if [[ -n $previous && ! -f /var/lib/flowharmonic/flowharmonic.db ]]; then
        fail "Existing installation has no database. Restore its backup before reinstalling; identity will not be reset."
    fi
    if [[ -f /etc/systemd/system/flowharmonic.service ]]; then
        cp -p /etc/systemd/system/flowharmonic.service "$work/previous.service"
        had_unit=1
    fi
    if systemctl is-enabled --quiet flowharmonic.service; then was_enabled=1; fi
    # From here every failure restores the previous application and service unit.
    rollback_needed=1
    systemctl stop flowharmonic.service || {
        local load_state
        load_state=$(systemctl show --property=LoadState --value flowharmonic.service 2>/dev/null || true)
        [[ $load_state == not-found ]] || fail 'Could not stop the previous application safely.'
    }
    backup_dir="/var/lib/flowharmonic/backups/$build"
    install -d -m 0700 "$backup_dir"
    cp -p /etc/flowharmonic/config.toml "$backup_dir/config.toml"
    for audio_config in local-audio.json local-snapserver.conf; do
        if [[ -f /etc/flowharmonic/$audio_config ]]; then cp -p "/etc/flowharmonic/$audio_config" "$backup_dir/$audio_config"; fi
    done
    if [[ -f /var/lib/flowharmonic/control.key ]]; then
        cp -p /var/lib/flowharmonic/control.key "$backup_dir/control.key"
    fi
    if [[ -f /var/lib/flowharmonic/authentication.db ]]; then
        python3 "$SOURCE/scripts/install-state.py" backup-auth \
            /var/lib/flowharmonic/authentication.db "$backup_dir/authentication.db"
    fi
    if [[ -f /var/lib/flowharmonic/network.db ]]; then
        python3 "$SOURCE/scripts/install-state.py" backup-network \
            /var/lib/flowharmonic/network.db "$backup_dir/network.db"
    fi
    if [[ -f /var/lib/flowharmonic/coordination.db ]]; then
        python3 "$SOURCE/scripts/install-state.py" backup-coordination \
            /var/lib/flowharmonic/coordination.db "$backup_dir/coordination.db"
    fi
    if [[ -f /var/lib/flowharmonic/sources.db ]]; then
        python3 "$SOURCE/scripts/install-state.py" backup-sources \
            /var/lib/flowharmonic/sources.db "$backup_dir/sources.db"
    fi
    if [[ -f /var/lib/flowharmonic/scenes.db ]]; then
        python3 "$SOURCE/scripts/install-state.py" backup-scenes \
            /var/lib/flowharmonic/scenes.db "$backup_dir/scenes.db"
    fi
    expected_identity=$(python3 "$SOURCE/scripts/install-state.py" backup \
        /var/lib/flowharmonic/flowharmonic.db "$backup_dir/flowharmonic.db")
    atomic_link "$release" /opt/flowharmonic/current
    install -m 0644 "$SOURCE/packaging/flowharmonic.service" /etc/systemd/system/flowharmonic.service
    if command -v restorecon >/dev/null; then
        restorecon -RF /opt/flowharmonic /etc/flowharmonic /var/lib/flowharmonic /etc/systemd/system/flowharmonic.service
    fi
    systemctl daemon-reload
    systemctl enable flowharmonic.service
    systemctl restart flowharmonic.service
    wait_health "$health_url" "$build" "$expected_identity" || fail 'Startup health check failed.'
    systemctl is-active --quiet flowharmonic.service
    rollback_needed=0
    install -d -m 0755 /usr/local/bin
    install -m 0755 "$SOURCE/packaging/flowharmonic" /usr/local/bin/flowharmonic
    # Audio provisioning runs only after the application has passed activation.
    # A failed hardware/service setup leaves the working dashboard available.
    install -m 0644 "$SOURCE/packaging/flowharmonic-audio.service" /etc/systemd/system/flowharmonic-audio.service
    install -m 0644 "$SOURCE/packaging/flowharmonic-audio.timer" /etc/systemd/system/flowharmonic-audio.timer
    if command -v restorecon >/dev/null; then
        restorecon -RF /var/lib/flowharmonic-audio /etc/systemd/system/flowharmonic-audio.service /etc/systemd/system/flowharmonic-audio.timer
    fi
    systemctl daemon-reload
    systemctl enable flowharmonic-audio.service flowharmonic-audio.timer
    if [[ -f /etc/systemd/system/flowharmonic-bluetooth.service ]] &&
        ! grep -qxF '# Managed by FlowHarmonic Bluetooth' /etc/systemd/system/flowharmonic-bluetooth.service &&
        ! grep -qxF 'Description=FlowHarmonic Bluetooth pairing window' /etc/systemd/system/flowharmonic-bluetooth.service; then
        fail 'An unrelated Bluetooth service occupies the FH service name; it was retained.'
    fi
    install -m 0644 "$SOURCE/packaging/flowharmonic-bluetooth.service" /etc/systemd/system/flowharmonic-bluetooth.service
    if command -v restorecon >/dev/null; then restorecon /etc/systemd/system/flowharmonic-bluetooth.service; fi
    systemctl daemon-reload
    systemctl enable flowharmonic-bluetooth.service
    systemctl restart flowharmonic-bluetooth.service
    systemctl start flowharmonic-audio.timer
    systemctl start flowharmonic-audio.service || fail 'Application installed; local audio setup needs attention. The dashboard remains available and setup retries automatically. Inspect journalctl -u flowharmonic-audio.'
    (cd "$release" && "$release/.venv/bin/python" -m flowharmonic password --if-needed) ||
        printf 'Password setup was not completed. Run sudo flowharmonic password when ready.\n'
    printf '\nFlowHarmonic %s installed. Dashboard: %s/\n' "$VERSION" "$health_url"
    printf 'Maintenance: flowharmonic status | sudo flowharmonic password | sudo flowharmonic logs | sudo flowharmonic restart\n'
    printf 'Your browser remembers sign-in across reloads and tabs. Use Sign out on shared devices.\n'
    printf 'Configuration and identity are preserved in /etc/flowharmonic and /var/lib/flowharmonic.\n'
}

cleanup() {
    local status=$?
    trap - EXIT INT TERM
    if [[ $rollback_needed == 1 ]]; then
        printf 'Installation failed; restoring the previous application and service.\n' >&2
        systemctl stop flowharmonic.service || true
        if [[ -n $previous ]]; then
            atomic_link "$previous" /opt/flowharmonic/current || true
        else
            rm -f /opt/flowharmonic/current
        fi
        if [[ $had_unit == 1 ]]; then
            cp -p "$work/previous.service" /etc/systemd/system/flowharmonic.service
        else
            rm -f /etc/systemd/system/flowharmonic.service
        fi
        systemctl daemon-reload || true
        if [[ $was_enabled == 0 ]]; then systemctl disable flowharmonic.service || true; fi
        if [[ -n $previous ]]; then
            if ! systemctl restart flowharmonic.service; then
                printf 'Previous service could not restart; inspect journalctl -u flowharmonic.\n' >&2
            fi
        fi
        printf 'Persistent data retained. Failed release retained at %s for diagnosis.\n' "${release:-unknown}" >&2
    fi
    rm -rf -- "$work"
    exit "$status"
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then main "$@"; fi
