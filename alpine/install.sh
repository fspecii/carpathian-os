#!/bin/sh
# Install the development desktop on an existing Alpine system. No disk formatting.
set -eu
case "${1:-}" in
    --help|-h) printf 'Usage: alpine/install.sh [--no-packages]\nInstalls the Rust WM and an X11 login entry on an existing Alpine system.\n'; exit 0;;
    ''|--no-packages) :;;
    *) printf 'Unknown option: %s\n' "$1" >&2; exit 2;;
esac
[ "$(id -u)" -eq 0 ] || { printf 'Run this installer as root inside Alpine.\n' >&2; exit 1; }
[ -f /etc/alpine-release ] || { printf 'This installer requires Alpine Linux.\n' >&2; exit 1; }
cd "$(dirname "$0")/.."
if [ "${1:-}" != --no-packages ]; then
    apk add build-base cargo rust pkgconf xorg-server xinit xf86-input-libinput \
        mesa-dri-gallium xterm xsetroot font-dejavu dbus dbus-x11 gtk+3.0-dev
fi
cargo build --release --locked
cargo test --locked --lib
install -m 755 target/release/carpatic-wm /usr/local/bin/carpatic-wm
mkdir -p /usr/share/carpatic-rust/config
install -m644 config/*.toml /usr/share/carpatic-rust/config/
install -m 755 scripts/carpatic-rust-session /usr/local/bin/carpatic-rust-session
mkdir -p /etc/X11/xorg.conf.d
install -m644 alpine/20-carpatic-virtio-cursor.conf /etc/X11/xorg.conf.d/
mkdir -p /usr/share/xsessions
cat > /usr/share/xsessions/carpatic-rust.desktop <<'EOF'
[Desktop Entry]
Name=Carpathian OS
Comment=Tiling and floating desktop
Exec=/usr/local/bin/carpatic-rust-session
Type=Application
DesktopNames=CarpaticRust
EOF
CARPATIC_SKIP_PACKAGES=0; [ "${1:-}" = --no-packages ] && CARPATIC_SKIP_PACKAGES=1
CARPATIC_SKIP_PACKAGES=$CARPATIC_SKIP_PACKAGES CARPATIC_USER=${CARPATIC_USER:-root} sh alpine/desktop-tools.sh
printf 'Installed. Choose Carpathian OS at login, or use: startx /usr/local/bin/carpatic-rust-session\n'
