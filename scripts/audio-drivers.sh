# Load standard drivers only for currently unbound playback-capable hardware.
# Ubuntu cloud/minimal images may omit sound modules from the running kernel.
install_audio_drivers() {
    local device value need_hda=0 need_usb=0 module
    for device in /sys/bus/pci/devices/*; do
        [[ -r $device/class && ! -L $device/driver ]] || continue
        value=$(cat "$device/class")
        [[ $value != 0x040300 ]] || need_hda=1
    done
    for device in /sys/bus/usb/devices/*:*; do
        [[ -r $device/bInterfaceClass && ! -L $device/driver ]] || continue
        value=$(cat "$device/bInterfaceClass")
        [[ $value != 01 ]] || need_usb=1
    done
    local modules=()
    [[ $need_hda == 0 ]] || modules+=(snd_hda_intel)
    [[ $need_usb == 0 ]] || modules+=(snd_usb_audio)
    for module in "${modules[@]}"; do
        if ! modinfo "$module" >/dev/null 2>&1; then
            if [[ $ID == ubuntu ]]; then
                local package="linux-modules-extra-$(uname -r)"
                if apt-cache show "$package" >/dev/null 2>&1; then
                    DEBIAN_FRONTEND=noninteractive apt-get install -y "$package"
                fi
            elif [[ $ID == fedora ]]; then
                dnf install -y "kernel-modules-$(uname -r)"
            fi
        fi
        if ! modprobe "$module"; then
            printf 'Audio driver %s is unavailable; the dashboard will report unavailable outputs.\n' "$module" >&2
        fi
    done
}
