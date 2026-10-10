#!/bin/sh
# Carpathian Quick Look provisioning (run as root on a box that already has the desktop + configurator; idempotent).
# Usage: sh quicklook/install.sh        Env: CARPATIC_USER (default carpatic)
set -eu
SRC=$(cd "$(dirname "$0")" && pwd)
U=${CARPATIC_USER:-carpatic}
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
echo "== quicklook: packages"
if [ "${SKIP_PACKAGES:-0}" != 1 ]; then apk add --no-cache $(grep -v '^[[:space:]]*#' "$SRC/packages.txt" | grep -v '^[[:space:]]*$') >/dev/null; fi
echo "== quicklook: files"
rm -rf /usr/local/lib/carpatic/quicklook; mkdir -p /usr/local/lib/carpatic/quicklook
cp "$SRC"/lib/*.py /usr/local/lib/carpatic/quicklook/
for f in "$SRC"/bin/*; do [ -f "$f" ] || continue; install -m755 "$f" /usr/local/bin/; done
# the user-level pieces (Thunar action + Space key) are installed by the daemon itself at its first start; do it now for the install user too
H=$(getent passwd "$U" | cut -d: -f6 || true)
if [ -n "${H:-}" ] && [ -d "$H" ]; then
  su "$U" -c "HOME=$H python3 -c \"import sys; sys.path.insert(0,'/usr/local/lib/carpatic/quicklook'); import ql_setup; ql_setup.setup(restart=False, quiet=True)\"" || true
fi
echo "== quicklook: done"
