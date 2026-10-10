#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
. scripts/rust-env.sh
scripts/check-host.sh
tests/lint.sh
tests/check-host.sh
python3 tests/window-animations.py
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
unset WAYLAND_DISPLAY
export GDK_BACKEND=x11 CARPATIC_WM_TEST_DISPLAY=1
export CARPATIC_WM_TEST_LOG="$PWD/artifacts/wm-test.log"
cargo test --locked -p carpatic-wm --test x11 -- --ignored --nocapture --test-threads=1
