#!/bin/sh
# Install program files only; never open or change a user's notes database.
set -eu
SRC=$(cd "$(dirname "$0")" && pwd)
DEST=${DESTDIR:-}
case "$DEST" in ''|/*) ;; *) echo 'DESTDIR must be absolute' >&2; exit 1;; esac
if [ -z "$DEST" ] && [ "$(id -u)" != 0 ]; then
    echo 'run as root, or provide an absolute DESTDIR for staging' >&2
    exit 1
fi
LIB="$DEST/usr/local/lib/carpatic-notes/carpatic_notes"
mkdir -p "$LIB" "$DEST/usr/local/bin" "$DEST/usr/local/share/applications"
for file in "$SRC"/lib/carpatic_notes/*.py; do install -m644 "$file" "$LIB/"; done
install -m755 "$SRC/bin/carpatic-notes" "$DEST/usr/local/bin/carpatic-notes"
install -m644 "$SRC/org.carpathian.Notes.desktop" "$DEST/usr/local/share/applications/"
echo 'Carpathian Notes installed; no user data changed or service started'
