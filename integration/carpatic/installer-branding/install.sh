#!/bin/sh
# Installer identity only; login, boot and screensaver assets are untouched.
set -eu
here=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
root=
if [ "${1:-}" = --root ]; then root=${2:?Missing target root}; shift 2; fi
[ "$#" -eq 0 ] || { echo 'Usage: install.sh [--root DIR]' >&2; exit 2; }
mkdir -p "$root/usr/local/bin" "$root/usr/local/share/carpatic/installer-branding/assets" "$root/usr/local/share/carpatic/installer-branding/lib"
install -m755 "$here/bin/carpathian-installer-greeter" "$root/usr/local/bin/"
install -m644 "$here/lib/greeter.py" "$root/usr/local/share/carpatic/installer-branding/lib/"
for asset in "$here"/assets/*.txt; do install -m644 "$asset" "$root/usr/local/share/carpatic/installer-branding/assets/"; done
