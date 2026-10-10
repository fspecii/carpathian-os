#!/bin/sh
# Install program files only. User reminder data is never touched.
set -eu
SRC=$(cd "$(dirname "$0")" && pwd)
DEST=${DESTDIR:-}
if [ -z "$DEST" ] && [ "$(id -u)" -ne 0 ]; then
    echo 'run as root, or provide an absolute DESTDIR for staging' >&2
    exit 1
fi
case "$DEST" in ''|/*) ;; *) echo 'DESTDIR must be absolute' >&2; exit 1 ;; esac
LIB="$DEST/usr/local/lib/carpatic-reminders/carpatic_reminders"
mkdir -p "$LIB" "$DEST/usr/local/bin" "$DEST/usr/local/share/applications"
for file in "$SRC"/lib/carpatic_reminders/*.py; do install -m644 "$file" "$LIB/"; done
install -m755 "$SRC/bin/carpatic-reminders" "$DEST/usr/local/bin/carpatic-reminders"
cat > "$DEST/usr/local/share/applications/org.carpatic.Reminders.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Reminders
Comment=Manage local reminders and due dates
Exec=carpatic-reminders
Icon=view-task-symbolic
Terminal=false
Categories=Office;Utility;
StartupNotify=true
EOF
echo 'Carpathian Reminders program files installed; notifier not started, no autostart added'
