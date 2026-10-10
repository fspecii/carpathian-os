#!/bin/sh
# Install the Carpathian widgets (host, CLI, tips, Settings page) into a running system or a target tree. Idempotent. Usage: install.sh [--root DIR]
# Paths: program -> /usr/local/bin, python package + Settings page -> /usr/local/lib/carpatic, shared files -> /usr/local/share/carpatic/widgets.
# Installing does NOT turn widgets on: the user does that in Settings > Widgets or with `carpatic widgets enable`.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd); ROOT=; [ "${1:-}" = --root ] && ROOT=$2
r() { echo "$ROOT$1"; }
mkdir -p "$(r /usr/local/bin)" "$(r /usr/local/lib/carpatic/cwidgets)" "$(r /usr/local/share/carpatic/widgets)"
install -m 755 "$HERE/bin/carpatic-widgets" "$(r /usr/local/bin/carpatic-widgets)"
for f in "$HERE"/lib/cwidgets/*.py; do install -m 644 "$f" "$(r /usr/local/lib/carpatic/cwidgets/$(basename "$f"))"; done
install -m 644 "$HERE/gui/carpatic_widgets_pages.py" "$(r /usr/local/lib/carpatic/carpatic_widgets_pages.py)"
echo "carpatic-widgets installed${ROOT:+ into $ROOT} (off until the user enables it)"
