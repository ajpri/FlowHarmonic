# Sourced by installLinux.sh and installer tests.
fail() { printf 'FlowHarmonic: %s\n' "$*" >&2; exit 1; }

platform_supported() {
    local distro=$1 release=$2 arch=$3
    case "$distro:$release" in
        debian:12|debian:13|raspbian:12|raspbian:13)
            case "$arch" in x86_64|aarch64) return 0;; esac ;;
        ubuntu:22.04|ubuntu:24.04|fedora:42|fedora:43)
            case "$arch" in x86_64|aarch64) return 0;; esac ;;
    esac
    return 1
}

atomic_link() {
    local target=$1 link=$2
    local temporary="$link.next.$BASHPID"
    ln -s "$target" "$temporary"
    mv -Tf "$temporary" "$link"
}

wait_health() {
    local url=$1 expected_build=$2 expected_identity=$3 attempt
    for attempt in {1..30}; do
        if curl --noproxy '*' --fail --silent --max-time 2 "$url/health" > "$work/health.json" &&
            python3 - "$work/health.json" "$expected_build" "$expected_identity" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1]))
    valid = data['status'] == 'ok' and data['version'] == 'M6' and data['build'] == sys.argv[2]
    valid = valid and (not sys.argv[3] or data['identity'] == sys.argv[3])
    sys.exit(0 if valid else 1)
except (ValueError, KeyError):
    sys.exit(1)
PY
        then return 0; fi
        sleep 1
    done
    return 1
}
