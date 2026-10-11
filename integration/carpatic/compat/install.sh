#!/bin/sh
# Install the daily-driver layer into the running system (idempotent). Run as root from a checkout of the repo.
#   sh compat/install.sh            carpatic-compat only (the heavy Podman parts are fetched on first use)
#   sh compat/install.sh --daily    also the daily-driver package set (installer/packages/daily.txt) and its configuration
#   sh compat/install.sh --i18n     also fonts and input methods for CJK/RTL/Indic (installer/packages/daily-i18n.txt, ~150 MB)
set -eu
SRC=$(cd "$(dirname "$0")" && pwd)
REPO=$(dirname "$SRC")
DAILY=no; I18N=no
for a in "$@"; do case "$a" in --daily) DAILY=yes;; --i18n) DAILY=yes; I18N=yes;; *) echo "unknown option $a" >&2; exit 2;; esac; done

install -Dm755 "$SRC/bin/carpatic-compat"            /usr/local/bin/carpatic-compat
install -Dm755 "$SRC/bin/carpatic-update"            /usr/local/bin/carpatic-update
install -Dm755 "$SRC/bin/carpatic-a11y"             /usr/local/bin/carpatic-a11y
install -Dm755 "$SRC/bin/carpatic-touchpad"         /usr/local/bin/carpatic-touchpad
install -Dm755 "$SRC/bin/carpatic-gestures"         /usr/local/bin/carpatic-gestures
install -Dm755 "$SRC/gui/carpatic-system"           /usr/local/bin/carpatic-system
install -Dm644 "$SRC/gui/carpatic_system_pages.py"  /usr/local/lib/carpatic/carpatic_system_pages.py
rm -f /usr/share/applications/carpatic-system.desktop   # one Settings entry only
install -Dm644 "$SRC/share/org.carpatic.system.policy" /usr/share/polkit-1/actions/org.carpatic.system.policy
install -Dm755 "$SRC/bin/carpatic-display"          /usr/local/bin/carpatic-display
install -Dm755 "$SRC/bin/carpatic-input-method"    /usr/local/bin/carpatic-input-method
install -Dm644 "$SRC/system/carpatic-im.sh"        /etc/profile.d/carpatic-im.sh
install -Dm644 "$SRC/share/udiskie.yml"             /etc/carpatic/udiskie.yml
install -Dm755 "$SRC/bin/carpatic-rollback"          /usr/local/bin/carpatic-rollback
install -Dm644 "$REPO/compatibility/blueman-passkey.py" /usr/libexec/carpatic/blueman-passkey.py
install -Dm755 "$SRC/system/apk-commit-hook"         /etc/apk/commit_hooks.d/carpatic-fixups
install -Dm755 "$SRC/system/brand-os"                /usr/libexec/carpatic/brand-os
install -Dm755 "$SRC/system/periodic-update-check"   /etc/periodic/daily/carpatic-update-check
install -Dm755 "$SRC/system/periodic-auto-update"    /etc/periodic/daily/carpatic-auto-update
install -Dm755 "$SRC/bin/carpatic-security"          /usr/local/bin/carpatic-security
install -Dm755 "$SRC/system/compat-boot"             /usr/libexec/carpatic/compat-boot
install -Dm755 "$SRC/system/carpatic-compat.initd"   /etc/init.d/carpatic-compat
install -Dm644 "$SRC/share/carpatic-compat.desktop"  /usr/share/applications/carpatic-compat.desktop
install -Dm644 "$SRC/share/carpatic-compat.svg"      /usr/share/icons/hicolor/scalable/apps/carpatic-compat.svg
install -Dm644 "$SRC/share/carpatic-compat-open.desktop" /usr/share/applications/carpatic-compat-open.desktop
install -Dm644 "$SRC/share/org.carpatic.compat.policy" /usr/share/polkit-1/actions/org.carpatic.compat.policy
rc-update add carpatic-compat boot >/dev/null 2>&1 || true
rc-service carpatic-compat start >/dev/null 2>&1 || true

pkgs() { grep -v '^[[:space:]]*#' "$1" | grep -v '^[[:space:]]*$'; }
if [ "$DAILY" = yes ]; then
  echo "daily-driver packages..."
  # shellcheck disable=SC2046
  apk add --no-cache $(pkgs "$REPO/installer/packages/daily.txt")
  sh "$SRC/system/daily-config.sh"
fi
if [ "$I18N" = yes ]; then
  echo "language and font packages..."
  # shellcheck disable=SC2046
  apk add --no-cache $(pkgs "$REPO/installer/packages/daily-i18n.txt")
fi
# apply the menu branding (plain app names, hidden tools) now: the apps may have been installed before the hook existed
sh "$SRC/system/brand-os" || true
sh "$SRC/system/apk-commit-hook" post-commit >/dev/null 2>&1 || true
echo "carpatic-compat installed. Try: carpatic-compat help"
