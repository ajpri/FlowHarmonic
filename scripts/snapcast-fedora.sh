# Build only missing components from a checksum-pinned upstream archive.
install_fedora_snapcast() {
    local build_client=OFF build_server=OFF
    [[ $client_owner == flowharmonic ]] && build_client=ON
    [[ $server_owner == flowharmonic ]] && build_server=ON
    dnf install -y gcc-c++ cmake make pkgconf-pkg-config boost-devel openssl-devel \
        alsa-lib-devel avahi-devel libvorbis-devel opus-devel pulseaudio-libs-devel \
        flac-devel soxr-devel expat-devel
    local snaproot=/opt/flowharmonic/snapcast/0.30.0
    if [[ ! -x "$snaproot/bin/snapserver" && $build_server == ON ]] ||
       [[ ! -x "$snaproot/bin/snapclient" && $build_client == ON ]]; then
        curl --proto '=https' --tlsv1.2 -fL --retry 3 \
            https://codeload.github.com/snapcast/snapcast/tar.gz/refs/tags/v0.30.0 -o "$work/snapcast.tar.gz"
        printf '%s  %s\n' c1e7f745275526a92b4797ca63bb5a8b8b558f8cb35c200e13097244db6c8a1c "$work/snapcast.tar.gz" | sha256sum -c -
        tar --no-same-owner -xzf "$work/snapcast.tar.gz" -C "$work"
        cmake -S "$work/snapcast-0.30.0" -B "$work/snap-build" \
            -DCMAKE_BUILD_TYPE=Release -DBUILD_CLIENT="$build_client" -DBUILD_SERVER="$build_server" \
            -DBUILD_WITH_JACK=OFF -DBUILD_WITH_TREMOR=OFF
        # Bound memory consumption on small nodes.
        cmake --build "$work/snap-build" --parallel 2
        install -d -m 0755 "$snaproot/bin"
        for component in snapserver snapclient; do
            [[ ! -f "$work/snapcast-0.30.0/bin/$component" ]] || install -m 0755 "$work/snapcast-0.30.0/bin/$component" "$snaproot/bin/$component"
        done
        command -v restorecon >/dev/null && restorecon -RF /opt/flowharmonic/snapcast || true
    fi
    if [[ $server_owner == flowharmonic ]]; then
        if ! id flowharmonic-snapcast >/dev/null 2>&1; then
            useradd --system --user-group --home-dir /var/lib/flowharmonic-snapcast --shell /usr/sbin/nologin flowharmonic-snapcast
        fi
        if [[ ! -f /etc/flowharmonic/snapserver.conf ]]; then
            install -m 0644 "$SOURCE/packaging/snapserver.conf" /etc/flowharmonic/snapserver.conf
        fi
    fi
}
