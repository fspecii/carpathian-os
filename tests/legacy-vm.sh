#!/bin/sh
# Optional existing-preview adapter. All tests use an isolated VM account and Xvfb :98.
set -eu
cd "$(dirname "$0")/.."
vm=${CARPATIC_TEST_VM:?Select a disposable VM with tests/run.sh --vm NAME}
scripts/vm-test.sh --name "$vm" wait
cases=${CARPATIC_LEGACY_CASES:-}
case "$cases" in *[!a-z0-9,-]*) echo 'Invalid legacy case list' >&2; exit 2;; esac
ssh_vm() { scripts/vm-test.sh --name "$vm" ssh "$@"; }
ssh_vm 'test -f /etc/alpine-release; test -x /usr/local/bin/carpatic-wm; id carpatic-rust-test >/dev/null 2>&1 || adduser -D -h /home/carpatic-rust-test carpatic-rust-test; mkdir -p /tmp/carpatic-rust-legacy /usr/share/carpatic-rust/config'
tar -C tests/legacy -cf - . | ssh_vm 'tar -xf - -C /tmp/carpatic-rust-legacy; chown -R carpatic-rust-test:carpatic-rust-test /tmp/carpatic-rust-legacy'
tar -C config -cf - . | ssh_vm 'tar -xf - -C /usr/share/carpatic-rust/config'
cleanup() { ssh_vm 'uid=$(id -u carpatic-rust-test); [ "$uid" -ge 1000 ] && pkill -u "$uid" 2>/dev/null || :; test ! -f /tmp/carpatic-rust-legacy-xvfb.pid || kill "$(cat /tmp/carpatic-rust-legacy-xvfb.pid)" 2>/dev/null; true' >/dev/null 2>&1 || :; }
trap cleanup EXIT
ssh_vm 'test ! -e /tmp/.X11-unix/X98; nohup Xvfb :98 -screen 0 1280x800x24 -noreset -ac -nolisten tcp >/tmp/carpatic-rust-legacy-xvfb.log 2>&1 </dev/null & echo $! >/tmp/carpatic-rust-legacy-xvfb.pid; sleep 1'
out=${CARPATIC_RESULTS_DIR:-$PWD/artifacts/legacy-vm}
mkdir -p "$out/desktop-cases"
set +e
ssh_vm "su carpatic-rust-test -c 'mkdir -p /tmp/carpatic-rust-legacy-runtime; chmod 700 /tmp/carpatic-rust-legacy-runtime; DISPLAY=:98 GDK_BACKEND=x11 CARPATIC_SESSION=1 CARPATIC_FULLSCREEN_SPACES=0 CARPATIC_LEGACY_CASES=$cases XDG_RUNTIME_DIR=/tmp/carpatic-rust-legacy-runtime dbus-run-session -- sh /tmp/carpatic-rust-legacy/run-guest.sh'" > "$out/runner.log" 2>&1
rc=$?
ssh_vm 'tar -C /tmp/carpatic-rust-legacy/results -cf - .' | tar -xf - -C "$out/desktop-cases"
cat "$out/desktop-cases/results.tap"
exit "$rc"
