#!/bin/sh
# Carpatic store: provision Flatpak + Flathub on Alpine (musl/OpenRC). Run as root, idempotent.
# Does not need a running desktop. Audio/portal pieces are installed here, started per user session.
set -eu
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
log() { echo "== $*"; }

log "packages"
apk add --no-cache flatpak bubblewrap xdg-desktop-portal xdg-desktop-portal-gtk flatpak-xdg-utils \
  pipewire pipewire-pulse wireplumber pipewire-alsa \
  mesa-dri-gallium mesa-egl mesa-gl mesa-vulkan-swrast vulkan-loader \
  dbus polkit-elogind elogind eudev udev-init-scripts shadow-uidmap ca-certificates

log "services"
for s in dbus elogind; do rc-update add "$s" default >/dev/null 2>&1 || true; rc-service "$s" start >/dev/null 2>&1 || true; done
rc-update add udev sysinit >/dev/null 2>&1 || true

log "flathub remote (system-wide, so every user sees it)"
flatpak remote-add --if-not-exists flathub "$(dirname "$0")/flathub.flatpakrepo"

log "rootless containers: subuid/subgid ranges for every normal user"
# next free 65536-wide range after the existing entries (grep -c prints 0 and exits 1 on an empty file, so never chain `|| echo 0`)
next_subid_start() {
  n="$(grep -c . "$1" 2>/dev/null)"; case "$n" in ''|*[!0-9]*) n=0 ;; esac
  echo $((100000 + n * 65536))
}
awk -F: '$3>=1000 && $3<60000 {print $1}' /etc/passwd | while read -r u; do
  for f in /etc/subuid /etc/subgid; do
    grep -q "^$u:" "$f" 2>/dev/null || echo "$u:$(next_subid_start "$f"):65536" >> "$f"
  done
done

log "XDG_RUNTIME_DIR fallback (busybox login has no pam_elogind session)"
install -Dm644 "$(dirname "$0")/xdg-runtime.sh" /etc/profile.d/carpatic-xdg-runtime.sh

log "controller / gamepad udev rules (Steam Input, Xbox, PS, Switch pads)"
install -Dm644 "$(dirname "$0")/60-carpatic-controllers.rules" /etc/udev/rules.d/60-carpatic-controllers.rules
udevadm control --reload 2>/dev/null || true

log "Flatpak apps visible to launchers"
# /etc/profile.d/flatpak.sh from the flatpak package already adds the exports dirs to XDG_DATA_DIRS
ls /etc/profile.d/flatpak.sh >/dev/null

log "install the store (CLI, GUI, catalog, launcher entry)"
apk add --no-cache python3 py3-gobject3 curl adw-gtk3 librsvg gtk+3.0 adwaita-icon-theme hicolor-icon-theme
H="$(dirname "$0")/.."
install -Dm755 "$H/bin/carpatic-store" /usr/local/bin/carpatic-store
install -Dm755 "$H/bin/carpatic-store-gui" /usr/local/bin/carpatic-store-gui
install -Dm755 "$H/bin/carpatic-ai" /usr/local/bin/carpatic-ai
install -Dm755 "$H/bin/carpatic-drivers" /usr/local/bin/carpatic-drivers
for m in carpatic_store carpatic_ai carpatic_drivers carpatic_storeui; do install -Dm644 "$H/lib/$m.py" /usr/local/lib/carpatic-store/$m.py; done
install -Dm644 "$(dirname "$0")/carpatic-localbin.sh" /etc/profile.d/carpatic-localbin.sh
rm -rf /usr/local/share/carpatic/store/ai; mkdir -p /usr/local/share/carpatic/store
cp -r "$H/ai" /usr/local/share/carpatic/store/ai
rm -rf /usr/local/share/carpatic/store/gui; cp -r "$H/gui" /usr/local/share/carpatic/store/gui
install -Dm644 "$H/gui/carpatic-icon-64.png" /usr/share/icons/hicolor/64x64/apps/carpatic-store.png
install -Dm644 "$H/carpatic-store.desktop" /usr/share/applications/carpatic-store.desktop
# GTK finds an icon that was added after the cache was written only once the cache is rebuilt (else the panel shows a grey gear)
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -qft /usr/share/icons/hicolor 2>/dev/null || true
mkdir -p /usr/local/share/carpatic/store
install -Dm644 "$H/system/flathub.flatpakrepo" /usr/local/share/carpatic/store/flathub.flatpakrepo
rm -rf /usr/local/share/carpatic/store/catalog
cp -r "$H/catalog" /usr/local/share/carpatic/store/
cp "$0" /usr/local/share/carpatic/store/setup-flatpak.sh
update-desktop-database /usr/share/applications 2>/dev/null || true
echo "done"
