#!/bin/sh
# stylepacks/install.sh : register the style packs (Zen, Kylin) in an installed configurator. Idempotent.
# Copies profiles, themes and taskbar templates into the configurator share (that is what makes `carpatic-profile list` and Settings > Style show them),
# the helpers into /usr/local/bin and the GTK libs into /usr/local/lib/carpatic. DESTDIR=... stages instead (packaging).
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
D=${DESTDIR:-}
SHARE=${SHARE_DIR:-$D/usr/local/share/carpatic/configurator}
SP=$D/usr/local/share/carpatic/stylepacks
mkdir -p "$D/usr/local/bin" "$D/usr/local/lib/carpatic" "$SHARE/profiles" "$SHARE/themes" "$SHARE/templates/tint2" "$SHARE/packs.d" "$D/usr/local/share/applications" "$SP"
for f in carpatic-startmenu carpatic-sidebar carpatic-stylepack carpatic-showdesktop carpatic-taskpreview; do
  [ -f "$HERE/bin/$f" ] && install -m 755 "$HERE/bin/$f" "$D/usr/local/bin/$f"
done
install -m 644 "$HERE"/lib/*.py "$D/usr/local/lib/carpatic/"
for s in zen kylin; do
  install -m 644 "$HERE/$s"/profile/* "$SHARE/profiles/"
  install -m 644 "$HERE/$s"/tint2/*.tpl "$SHARE/templates/tint2/"
  for t in "$HERE/$s"/themes/*; do mkdir -p "$SHARE/themes/$(basename "$t")"; install -m 644 "$t"/* "$SHARE/themes/$(basename "$t")/"; done
  mkdir -p "$SP/$s"; install -m 644 "$HERE/$s"/assets/*.svg "$SP/$s/"
  for pv in "$HERE/$s"/preview-*.png; do [ -f "$pv" ] && install -m 644 "$pv" "$SHARE/profiles/$s.$(basename "$pv")"; done
  install -m 644 "$HERE/$s"/assets/*.desktop "$D/usr/local/share/applications/"
done
install -m 644 "$HERE/zen/accents.list" "$SP/zen/accents.list"
install -m 644 "$HERE/packs.list" "$SHARE/packs.d/stylepacks.list"; install -m 644 "$HERE/packs.list" "$SP/packs.list"
install -m 644 "$HERE/RESEARCH.md" "$SP/RESEARCH.md"
echo "style packs registered: $(ls "$HERE" | grep -c '^\(zen\|kylin\)$') (zen, kylin)"
