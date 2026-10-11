#!/bin/sh
# Shared Carpathian desktop tools; deliberately no C dwm build.
set -eu
[ "$(id -u)" = 0 ] && [ -f /etc/alpine-release ] || { echo 'Run inside Alpine as root.' >&2; exit 1; }
cd "$(dirname "$0")/.."
SRC=$PWD/integration/carpatic
U=${CARPATIC_USER:-root}
H=$(getent passwd "$U" | cut -d: -f6)
[ -n "$H" ] || { echo "Unknown user: $U" >&2; exit 1; }
mkdir -p /usr/local/share/carpatic-rust
install -m755 "$SRC/desktop/session/autostart.sh" /usr/local/share/carpatic-rust/autostart.sh
install -m755 "$SRC/desktop/session/carpatic-status" /usr/local/share/carpatic-rust/carpatic-status
mkdir -p "$H/.local/share/dwm-titus/config" "$H/.local/share/dwm-titus/scripts" "$H/.config/dwm-titus"
for f in config/*.toml; do
    install -m644 "$f" "$H/.local/share/dwm-titus/config/"
    [ -e "$H/.config/dwm-titus/$(basename "$f")" ] || install -m644 "$f" "$H/.config/dwm-titus/"
done
if [ "${CARPATIC_SKIP_PACKAGES:-0}" != 1 ]; then
    apk add gtk+3.0-dev libxext-dev 'picom>=13' mesa-dri-gallium mesa-utils xfdesktop xdg-user-dirs xrandr xprop dmenu xautolock i3lock-color playerctl \
        pipewire pipewire-pulse wireplumber alsa-utils firefox xdg-utils \
        libinput-tools xinput xset setxkbmap libxtst flatpak util-linux \
        elogind elogind-openrc polkit-elogind polkit-gnome dbus-openrc polkit-openrc
fi
sh alpine/desktop-services.sh
install -m755 "$SRC/desktop/session/carpatic-status" "$H/.local/share/dwm-titus/scripts/"
SKIP_PACKAGES=${CARPATIC_SKIP_PACKAGES:-0} SKIP_DWM=1 CARPATIC_USER="$U" DESKTOP_SRC="$SRC/desktop" sh "$SRC/configurator/install.sh"
for f in "$SRC"/desktop/bin/*; do [ -f "$f" ] || continue; install -m755 "$f" /usr/local/bin/; done
sh "$SRC/settings/install.sh"
SKIP_PACKAGES=1 sh "$SRC/themepicker/install.sh"
for component in wallpapers stylepacks widgets motion reminders notes; do sh "$SRC/$component/install.sh"; done
SKIP_PACKAGES=${CARPATIC_SKIP_PACKAGES:-0} sh "$SRC/geek/install.sh"
SKIP_PACKAGES=${CARPATIC_SKIP_PACKAGES:-0} CARPATIC_USER="$U" sh "$SRC/quicklook/install.sh"
# Input/display integration is shared; installing these does not enable compatibility containers.
mkdir -p /usr/local/lib/carpatic /usr/local/lib/carpatic-store /usr/local/share/applications
for helper in "$SRC"/compat/bin/*; do [ -f "$helper" ] || continue; install -m755 "$helper" /usr/local/bin/; done
install -m644 "$SRC/compat/gui/carpatic_system_pages.py" /usr/local/lib/carpatic/
# Helpers exposed by Settings need their authentication policies even when the
# optional compatibility/container installer is not used.
for policy in "$SRC"/compat/share/*.policy; do
    install -Dm644 "$policy" "/usr/share/polkit-1/actions/$(basename "$policy")"
done
for f in "$SRC"/store/bin/*; do [ -f "$f" ] || continue; install -m755 "$f" /usr/local/bin/; done
for f in "$SRC"/store/lib/*.py; do install -m644 "$f" /usr/local/lib/carpatic-store/; done
mkdir -p /usr/local/share/carpatic/store/catalog /usr/share/icons/hicolor/64x64/apps
install -m644 "$SRC"/store/catalog/*.toml /usr/local/share/carpatic/store/catalog/
cp -R "$SRC/store/ai" "$SRC/store/gui" /usr/local/share/carpatic/store/
install -m644 "$SRC/store/system/carpatic-localbin.sh" /etc/profile.d/
install -m644 "$SRC/store/system/flathub.flatpakrepo" /usr/local/share/carpatic/store/
install -m755 "$SRC/store/system/setup-flatpak.sh" /usr/local/share/carpatic/store/
install -m644 "$SRC/store/gui/carpatic-icon-64.png" /usr/share/icons/hicolor/64x64/apps/carpatic-store.png
install -m644 "$SRC/store/carpatic-store.desktop" /usr/local/share/applications/
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || :
[ -e "$H/.local/share/dwm-titus/scripts/autostart.sh" ] || install -m755 "$SRC/desktop/session/autostart.sh" "$H/.local/share/dwm-titus/scripts/autostart.sh"
# Default profile without first-login wizard; users can select any profile in Settings.
mkdir -p "$H/.config/carpatic"
if [ ! -f "$H/.config/carpatic/settings.conf" ]; then
    printf 'PROFILE="windows"\nTHEME="carpatic"\nLAYOUT="tile"\n' > "$H/.config/carpatic/settings.conf"
fi
chown -R "$U:$(id -gn "$U")" "$H/.config/carpatic" "$H/.config/dwm-titus" "$H/.local/share/dwm-titus"
sh alpine/branding.sh
printf 'Carpathian theme/profile tools installed.\n'
