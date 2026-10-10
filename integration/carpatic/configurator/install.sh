#!/bin/sh
# Carpatic configurator provisioning (run as root on a box that already ran desktop/install.sh; idempotent).
# Usage: sh configurator/install.sh        Env: CARPATIC_USER (default carpatic), DESKTOP_SRC (default ../desktop)
set -eu
SRC=$(cd "$(dirname "$0")" && pwd)
DESK=${DESKTOP_SRC:-$SRC/../desktop}
U=${CARPATIC_USER:-carpatic}
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
log() { echo "== configurator: $*"; }

log "packages"
if [ "${SKIP_PACKAGES:-0}" != 1 ]; then apk add --no-cache $(grep -v '^[[:space:]]*#' "$SRC/packages.txt" | grep -v '^[[:space:]]*$') >/dev/null; fi

log "files"
D=/usr/local/share/carpatic/configurator
rm -rf "$D"; mkdir -p "$D"
cp -r "$SRC/themes" "$SRC/profiles" "$SRC/templates" "$D/"
cp "$SRC"/share/applications/*.desktop /usr/local/share/applications/ 2>/dev/null || { mkdir -p /usr/local/share/applications; cp "$SRC"/share/applications/*.desktop /usr/local/share/applications/; }
for f in "$SRC"/bin/*; do [ -f "$f" ] || continue; install -m755 "$f" /usr/local/bin/; done
# carpatic-panel + carpatic-flyout (taskbar designs, Quick Settings, calendar, Start menu) live in panel/; the old configurator flyout script is gone
[ -f "$SRC/../panel/install.sh" ] && sh "$SRC/../panel/install.sh"
cp "$SRC/share/packs.list" "$D/"
mkdir -p "$D/gtktheme"; cp "$SRC/share/gtktheme/geometry.conf" "$D/gtktheme/" 2>/dev/null
cp -r "$SRC/share/wallpapers" "$D/"
mkdir -p /usr/local/lib/carpatic
cp "$SRC"/lib/*.py /usr/local/lib/carpatic/
# every Carpatic GTK app follows the display scale: a .pth in site-packages arms a tiny hook that runs carpatic_scale.install() when a carpatic-* program loads Gtk
SP=$(python3 -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])' 2>/dev/null)
if [ -n "$SP" ] && [ -d "$SP" ]; then
  install -m644 "$SRC/lib/carpatic_scale_boot.py" "$SP/carpatic_scale_boot.py"
  echo "import carpatic_scale_boot" > "$SP/carpatic-scale.pth"
fi

# new shells and the X session (xinitrc sources /etc/profile) get the palette env (fzf, bat, eza, gum, Qt style)
mkdir -p /etc/profile.d
cat > /etc/profile.d/carpatic-theme.sh <<'EOT'
[ -r "$HOME/.config/carpatic/env.sh" ] && . "$HOME/.config/carpatic/env.sh"
EOT
log "carpatic-supertap"
if [ -n "${CARPATIC_PREBUILT_DIR:-}" ] && [ -x "$CARPATIC_PREBUILT_DIR/carpatic-supertap" ]; then
  install -m755 "$CARPATIC_PREBUILT_DIR/carpatic-supertap" /usr/local/bin/
else
  gcc -O2 -o /usr/local/bin/carpatic-supertap "$SRC/share/supertap.c" -lX11 -lXi
fi
log "per-style folder colour icon themes"
[ -d /usr/share/icons/Papirus ] && python3 "$SRC/share/gtktheme/gen-folder-themes.py" /usr/share/icons /usr/share/icons 2>/dev/null
[ -f "$SRC/share/gtktheme/mimeapps.list" ] && install -Dm644 "$SRC/share/gtktheme/mimeapps.list" /etc/xdg/mimeapps.list
[ -f "$SRC/share/gtktheme/thunar.xml" ] && install -Dm644 "$SRC/share/gtktheme/thunar.xml" /etc/xdg/xfce4/xfconf/xfce-perchannel-xml/thunar.xml
log "carpatic-livecss (GTK3 module: running GTK3 apps follow theme/accent switches)"
if [ -n "${CARPATIC_PREBUILT_DIR:-}" ] && [ -f "$CARPATIC_PREBUILT_DIR/libcarpatic-livecss.so" ]; then
  mkdir -p /usr/lib/gtk-3.0/modules
  install -m755 "$CARPATIC_PREBUILT_DIR/libcarpatic-livecss.so" /usr/lib/gtk-3.0/modules/
elif pkg-config --exists gtk+-3.0 2>/dev/null && command -v gcc >/dev/null 2>&1; then
  d=$(pkg-config --variable=libdir gtk+-3.0)/gtk-3.0/modules; mkdir -p "$d"
  gcc -O2 -fPIC -shared -o "$d/libcarpatic-livecss.so" "$SRC/share/carpatic-livecss.c" $(pkg-config --cflags --libs gtk+-3.0) || echo "livecss: build failed (running GTK3 apps keep the old colours until restarted)"
else echo "livecss: gtk+3.0-dev not installed, skipped (the apk package ships the module prebuilt)"; fi

log "dwm with configurator patches (taskbar focus, secondary docks, default layout, bar fallback)"
if [ "${SKIP_DWM:-0}" = 1 ]; then echo "skipped (SKIP_DWM=1)"
elif [ -d "$DESK/dwm" ]; then
  B=$(mktemp -d); cp -r "$DESK/dwm/." "$B/"
  if ( cd "$B" && patch -p0 -N --dry-run dwm.c < "$SRC/patches/0001-carpatic-configurator.patch" >/dev/null 2>&1 ); then
    ( cd "$B" && patch -p0 -N dwm.c < "$SRC/patches/0001-carpatic-configurator.patch" >/dev/null && cp config.def.h config.h && make >/dev/null && install -Dm755 dwm /usr/local/bin/dwm )
    echo "dwm rebuilt with patch (restart the X session to use it)"
  else
    echo "patch not applicable (already merged upstream, or dwm.c changed): skipped"
  fi
  rm -rf "$B"
else
  echo "no desktop/dwm source at $DESK: skipping dwm patch"
fi

log "user hook ($U)"
H=$(getent passwd "$U" | cut -d: -f6)
A="$H/.local/share/dwm-titus/scripts/autostart.sh"
if [ -f "$A" ] && ! grep -q carpatic-session "$A"; then
  printf '\n# Carpatic configurator: per-profile bars, hotkey daemon and first-run Welcome\ncarpatic-session start >/dev/null 2>&1 &\n' >> "$A"
fi
mkdir -p "$H/.config/carpatic" "$H/Pictures"; chown -R "$U:$U" "$H"
log "done"
