#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
. scripts/rust-env.sh
scripts/check-host.sh
tests/lint.sh
tests/check-host.sh
python3 tests/window-animations.py
python3 tests/animation-matrix-policy.py
python3 tests/seam-segments.py
python3 tests/flyout-oracle.py
python3 tests/installer-branding.py
python3 tests/prebuilt-architecture.py
python3 tests/desktop-auth-install.py
python3 tests/settings-responsive.py
python3 tests/vm-arm-command.py
python3 tests/arm64-live-packaging.py
python3 tests/arm64-graphics.py
python3 tests/session-env.py
python3 tests/shared-snapshot.py
python3 tests/display-lease.py
python3 tests/debug/rendering.py --self-test
export CARPATIC_RENDER_DIR="$PWD/artifacts"
cargo test --workspace --locked
mkdir -p artifacts
temporary=$(mktemp -d)
mkdir -p "$temporary/config"
printf '[appearance]\nworkspaces=4\n[titlebar]\nenabled=0\n' >"$temporary/config/themes.toml"
export CARPATIC_CONFIG_DIR="$temporary/config"
xvfb_pid=
cleanup() {
    if [ -n "$xvfb_pid" ]; then kill "$xvfb_pid" 2>/dev/null || :; wait "$xvfb_pid" 2>/dev/null || :; fi
    rm -rf "$temporary"
}
trap cleanup EXIT
trap 'exit 130' INT TERM
number=
for candidate in 90 91 92 93 94 95 96 97 98 99; do
    if [ ! -e "/tmp/.X11-unix/X$candidate" ] && [ ! -e "/tmp/.X$candidate-lock" ]; then number=$candidate; break; fi
done
[ -n "$number" ] || { printf 'No private test display available\n' >&2; exit 1; }
Xvfb ":$number" -displayfd 3 -screen 0 1280x800x24 -noreset -nolisten tcp 3>"$temporary/display" >artifacts/xvfb.log 2>&1 &
xvfb_pid=$!
tries=0
while [ ! -s "$temporary/display" ]; do
    kill -0 "$xvfb_pid" 2>/dev/null || { cat artifacts/xvfb.log; exit 1; }
    tries=$((tries + 1)); [ "$tries" -lt 50 ] || { printf 'Xvfb did not start\n' >&2; exit 1; }
    sleep 0.1
done
export DISPLAY=":$(cat "$temporary/display")"
# Reserve real-session display numbers even if Xvfb chose an unused :0.
case "$DISPLAY" in :0|:1) printf 'Refusing a reserved display.\n' >&2; exit 1;; esac
unset WAYLAND_DISPLAY XDG_CURRENT_DESKTOP
export GDK_BACKEND=x11 CARPATIC_WM_TEST_DISPLAY=1
export CARPATIC_WM_TEST_LOG="$PWD/artifacts/wm-test.log"
python3 integration/carpatic/panel/tests/test_first_paint.py
CARPATIC_XVFB_TEST=1 CARPATIC_PRIVATE_DBUS_TEST=1 G_DEBUG=fatal-criticals dbus-run-session -- python3 tests/calendar-compact.py
# Default-app widgets use an isolated runtime and in-memory GTK settings.
mkdir -p "$temporary/default-apps-runtime"
chmod 700 "$temporary/default-apps-runtime"
XDG_RUNTIME_DIR="$temporary/default-apps-runtime" GSETTINGS_BACKEND=memory GIO_USE_VFS=local NO_AT_BRIDGE=1 CARPATIC_XVFB_TEST=1 CARPATIC_PRIVATE_DBUS_TEST=1 G_DEBUG=fatal-criticals dbus-run-session -- python3 tests/default-apps-gtk.py
XDG_RUNTIME_DIR="$temporary/default-apps-runtime" GSETTINGS_BACKEND=memory GIO_USE_VFS=local NO_AT_BRIDGE=1 CARPATIC_XVFB_TEST=1 CARPATIC_PRIVATE_DBUS_TEST=1 G_DEBUG=fatal-criticals dbus-run-session -- python3 tests/storage-trash.py --gtk
XDG_RUNTIME_DIR="$temporary/default-apps-runtime" GSETTINGS_BACKEND=memory GIO_USE_VFS=local NO_AT_BRIDGE=1 CARPATIC_XVFB_TEST=1 CARPATIC_PRIVATE_DBUS_TEST=1 G_DEBUG=fatal-criticals dbus-run-session -- python3 tests/storage-cache.py --gtk
XDG_RUNTIME_DIR="$temporary/default-apps-runtime" GSETTINGS_BACKEND=memory GIO_USE_VFS=local NO_AT_BRIDGE=1 CARPATIC_XVFB_TEST=1 CARPATIC_PRIVATE_DBUS_TEST=1 G_DEBUG=fatal-criticals dbus-run-session -- python3 tests/wifi-scan.py --gtk
XDG_RUNTIME_DIR="$temporary/default-apps-runtime" GSETTINGS_BACKEND=memory GIO_USE_VFS=local NO_AT_BRIDGE=1 CARPATIC_XVFB_TEST=1 CARPATIC_PRIVATE_DBUS_TEST=1 G_DEBUG=fatal-criticals dbus-run-session -- python3 tests/wifi-connect.py --gtk
XDG_RUNTIME_DIR="$temporary/default-apps-runtime" GSETTINGS_BACKEND=memory GIO_USE_VFS=local NO_AT_BRIDGE=1 CARPATIC_XVFB_TEST=1 CARPATIC_PRIVATE_DBUS_TEST=1 G_DEBUG=fatal-criticals dbus-run-session -- python3 tests/bluetooth-refresh.py --gtk
XDG_RUNTIME_DIR="$temporary/default-apps-runtime" GSETTINGS_BACKEND=memory GIO_USE_VFS=local NO_AT_BRIDGE=1 CARPATIC_XVFB_TEST=1 CARPATIC_PRIVATE_DBUS_TEST=1 G_DEBUG=fatal-criticals dbus-run-session -- python3 tests/bluetooth-discovery.py --gtk
XDG_RUNTIME_DIR="$temporary/default-apps-runtime" GSETTINGS_BACKEND=memory GIO_USE_VFS=local NO_AT_BRIDGE=1 CARPATIC_XVFB_TEST=1 CARPATIC_PRIVATE_DBUS_TEST=1 G_DEBUG=fatal-criticals dbus-run-session -- python3 tests/calendar-editor-gtk.py
XDG_RUNTIME_DIR="$temporary/default-apps-runtime" GSETTINGS_BACKEND=memory GIO_USE_VFS=local NO_AT_BRIDGE=1 CARPATIC_XVFB_TEST=1 CARPATIC_PRIVATE_DBUS_TEST=1 G_DEBUG=fatal-criticals dbus-run-session -- python3 tests/reminders-drafts-gtk.py
XDG_RUNTIME_DIR="$temporary/default-apps-runtime" GSETTINGS_BACKEND=memory GIO_USE_VFS=local NO_AT_BRIDGE=1 CARPATIC_XVFB_TEST=1 CARPATIC_PRIVATE_DBUS_TEST=1 G_DEBUG=fatal-criticals dbus-run-session -- python3 tests/reminders-routing-gtk.py
cargo test --locked -p carpatic-wm --test x11 -- --ignored --nocapture --test-threads=1
