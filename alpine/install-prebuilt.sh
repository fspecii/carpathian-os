#!/bin/sh
# Fresh-installer handoff: install a checksum-verified native Alpine build.
# No disk partitioning or password changes happen in this script.
set -eu
[ "$(id -u)" = 0 ] && [ -f /etc/alpine-release ] || exit 1
cd "$(dirname "$0")/.."
project=$PWD
CARPATIC_USER=${CARPATIC_USER:?Select the installed desktop user}
export CARPATIC_USER
desktop_home=$(getent passwd "$CARPATIC_USER" | cut -d: -f6)
[ -n "$desktop_home" ] && [ -d "$desktop_home" ] || exit 1
[ "$(uname -m)" = x86_64 ] || { echo 'This image contains an x86_64 build.' >&2; exit 1; }
( cd prebuilt; sha256sum -c SHA256SUMS )
# The original signed desktop packages supply the shared runtime dependencies.
# xterm is the Rust port's terminal; no Rust or C build toolchain is required.
if [ -f packages/SHA256SUMS ]; then
    ( cd packages; sha256sum -c SHA256SUMS )
    apk add --no-network --no-progress "$project"/packages/*.apk
else
    apk add --no-progress xterm
fi
for required in xfdesktop xdg-user-dir xprop xterm python3 dbus-run-session; do
    command -v "$required" >/dev/null 2>&1 || {
        echo "Required desktop runtime is missing: $required" >&2
        exit 1
    }
done
python3 -c 'import gi; gi.require_version("Gtk", "3.0"); from gi.repository import Gtk, Gio'
mkdir -p /usr/share/licenses/carpathian-os
install -m644 LICENSE NOTICE /usr/share/licenses/carpathian-os/
install -m755 prebuilt/carpatic-wm /usr/local/bin/
install -m755 scripts/carpatic-rust-session /usr/local/bin/
mkdir -p /etc/X11/xorg.conf.d
install -m644 alpine/20-carpatic-virtio-cursor.conf /etc/X11/xorg.conf.d/
mkdir -p /usr/share/carpatic-rust/config
if [ "$(readlink -f config)" != "$(readlink -f /usr/share/carpatic-rust/config)" ]; then
    install -m644 config/*.toml /usr/share/carpatic-rust/config/
fi
install -m755 prebuilt/carpatic-intro-play integration/carpatic/motion/src/
install -m755 prebuilt/carpatic-clipwatch /usr/local/bin/
export CARPATIC_PREBUILT_DIR="$project/prebuilt" CARPATIC_SKIP_PACKAGES=1
sh alpine/desktop-tools.sh
# A fresh install uses the adapted autostart, not the package's dwm hook.
install -m755 integration/carpatic/desktop/session/autostart.sh "$desktop_home/.local/share/dwm-titus/scripts/autostart.sh"
mkdir -p /usr/share/xsessions /usr/local/share/carpatic/lightdm /usr/share/carpatic/lightdm
cat > /usr/share/xsessions/carpatic-rust.desktop <<'EOF'
[Desktop Entry]
Name=Carpathian OS
Comment=Tiling and floating desktop
Exec=/usr/local/bin/carpatic-rust-session
Type=Application
DesktopNames=CarpaticRust
EOF
# Existing greeter/autologin entry points all select the Rust session.
cp /usr/share/xsessions/carpatic-rust.desktop /usr/share/xsessions/carpatic.desktop
for location in /usr/local/share/carpatic /usr/share/carpatic; do
    mkdir -p "$location/lightdm"
    cp integration/carpatic/desktop/etc/lightdm/* "$location/lightdm/"
    cp /usr/share/xsessions/carpatic-rust.desktop "$location/lightdm/xsession-carpatic.desktop"
    printf '#!/bin/sh\nexec /usr/local/bin/carpatic-rust-session\n' > "$location/xinitrc"
    printf '#!/bin/sh\nexec /usr/local/bin/carpatic-rust-session\n' > "$location/xsession"
    chmod 755 "$location/xinitrc" "$location/xsession"
done
for name in .xinitrc .xsession; do
    printf '#!/bin/sh\nexec /usr/local/bin/carpatic-rust-session\n' > "$desktop_home/$name"
    chmod 755 "$desktop_home/$name"
done
mkdir -p /etc/lightdm/lightdm.conf.d
printf '[Seat:*]\nuser-session=carpatic-rust\n' > /etc/lightdm/lightdm.conf.d/99-carpatic-rust.conf
chown -R "$CARPATIC_USER:$(id -gn "$CARPATIC_USER")" "$desktop_home/.local/share/dwm-titus" "$desktop_home/.config/carpatic" "$desktop_home/.config/dwm-titus"
chown "$CARPATIC_USER:$(id -gn "$CARPATIC_USER")" "$desktop_home/.xinitrc" "$desktop_home/.xsession"
# Generate profile bindings/themes as the desktop user, without starting apps.
su "$CARPATIC_USER" -c 'carpatic-apply'
mkdir -p /etc/carpatic /var/lib/carpatic
printf 'rust\n' > /etc/carpatic/window-manager
cp prebuilt/SHA256SUMS /var/lib/carpatic/rust-build.sha256
echo 'Carpathian OS desktop installed.'
