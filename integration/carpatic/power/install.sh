#!/bin/sh
# Install Carpatic power management into a root (default /). Idempotent.
#   sh install.sh [--root DIR] [--packages] [--no-enable] [--hibernate]
# --packages   apk add the packages in packages.txt (online)
# --hibernate  also run `carpatic-power hibernate-setup` (needs the real, running system)
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=; PKGS=; ENABLE=1; HIB=
while [ $# -gt 0 ]; do case "$1" in
  --root) ROOT=$2; shift ;; --packages) PKGS=1 ;; --no-enable) ENABLE= ;; --hibernate) HIB=1 ;;
  *) echo "unknown option $1" >&2; exit 2 ;; esac; shift; done

if [ -n "$PKGS" ]; then
  pk=$(grep -v '^[[:space:]]*#' "$HERE/packages.txt" | grep -v '^[[:space:]]*$')
  # shellcheck disable=SC2086
  if [ -n "$ROOT" ]; then apk add --root "$ROOT" --no-cache $pk; else apk add --no-cache $pk; fi
fi
d() { mkdir -p "$ROOT$1"; }
i() { d "$(dirname "$2")"; install -m "$3" "$HERE/$1" "$ROOT$2"; }   # src dst mode
i bin/carpatic-power /usr/bin/carpatic-power 755
i etc/openrc/carpatic-power /etc/init.d/carpatic-power 755
i etc/udev/99-carpatic-power.rules /etc/udev/rules.d/99-carpatic-power.rules 644
i etc/acpi/carpatic-ac /etc/acpi/events/carpatic-ac 644
i etc/tlp.d/10-carpatic.conf /etc/tlp.d/10-carpatic.conf 644
[ -e "$ROOT/etc/carpatic/power.conf" ] || i etc/power.conf /etc/carpatic/power.conf 644
# zram-init config only if the package's conf.d exists and was not customised
if [ -d "$ROOT/etc/conf.d" ] && ! grep -qs "Carpatic" "$ROOT/etc/conf.d/zram-init" 2>/dev/null; then
  [ -e "$ROOT/etc/conf.d/zram-init" ] && cp "$ROOT/etc/conf.d/zram-init" "$ROOT/etc/conf.d/zram-init.orig"
  i etc/conf.d/zram-init /etc/conf.d/zram-init 644
fi
mkdir -p "$ROOT/var/lib/carpatic-power"
# elogind lid / power-key policy + sleep hook (decides laptop vs desktop from the battery)
if [ -z "$ROOT" ]; then carpatic-power apply-config >/dev/null
else CP_ETC="$ROOT/etc" CP_SYS="$ROOT/sys" CP_NOROOT=1 sh "$HERE/bin/carpatic-power" apply-config >/dev/null; fi

if [ -n "$ENABLE" ]; then
  rc() { # rc <service> <runlevel>  (works for a chroot root too)
    if [ -n "$ROOT" ]; then
      [ -e "$ROOT/etc/init.d/$1" ] || { echo "note: service $1 not installed, skipped" >&2; return 0; }
      mkdir -p "$ROOT/etc/runlevels/$2"; ln -sf "/etc/init.d/$1" "$ROOT/etc/runlevels/$2/$1"
    else rc-update add "$1" "$2" >/dev/null 2>&1 || true; fi
  }
  rc dbus default; rc elogind boot; rc acpid default; rc tlp default; rc zram-init boot; rc carpatic-power default
fi
[ -n "$HIB" ] && carpatic-power hibernate-setup
echo "carpatic-power installed${ROOT:+ into $ROOT}"
