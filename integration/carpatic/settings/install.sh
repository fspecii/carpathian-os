#!/bin/sh
# Install Carpathian Settings (run as root; idempotent). The launcher /usr/local/bin/carpatic-settings (configurator/) starts this app and
# falls back to the old Appearance-only window when it is not installed.
set -eu
SRC=$(cd "$(dirname "$0")" && pwd)
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
D=/usr/local/lib/carpatic-settings
rm -rf "$D"; mkdir -p "$D"
cp -r "$SRC/lib/cset" "$D/cset"; find "$D" -name __pycache__ -prune -exec rm -rf {} +
install -m755 "$SRC/bin/carpatic-settings" "$D/carpatic-settings"
mkdir -p /usr/local/share/carpatic-settings; rm -rf /usr/local/share/carpatic-settings/panel-previews; cp -r "$SRC/share/panel-previews" /usr/local/share/carpatic-settings/panel-previews
for f in carpatic-mouse carpatic-keyboard carpatic-nightlight carpatic-lockscreen carpatic-progress; do install -m755 "$SRC/bin/$f" /usr/local/bin/; done
# the app imports carpatic_buttons / carpatic_ui from the configurator
[ -f /usr/local/lib/carpatic/carpatic_buttons.py ] || { mkdir -p /usr/local/lib/carpatic; cp "$SRC"/../configurator/lib/*.py /usr/local/lib/carpatic/; }
install -Dm644 "$SRC/share/org.carpatic.settings.policy" /usr/share/polkit-1/actions/org.carpatic.settings.policy
echo "carpatic-settings installed in $D"
