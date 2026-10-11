#!/bin/sh
# Native build from a fresh source tree; only Cargo's target cache is reused.
set -eu
cd "$(dirname "$0")/.."
vm=${CARPATIC_TEST_VM:?Select a disposable VM}
results=${CARPATIC_RESULTS_DIR:?Select a results directory}
scripts/vm-test.sh --name "$vm" wait
build_dir=$(scripts/vm-test.sh --name "$vm" ssh 'test -f /etc/alpine-release; mktemp -d /var/tmp/carpatic-native-source-XXXXXX')
case "$build_dir" in /var/tmp/carpatic-native-source-??????) :;; *) echo 'Invalid native source path' >&2; exit 1;; esac
case "$build_dir" in *[!a-zA-Z0-9/-]*) echo 'Invalid native source characters' >&2; exit 1;; esac
cleanup() { scripts/vm-test.sh --name "$vm" ssh "rm -rf '$build_dir'" >/dev/null 2>&1 || :; }
trap cleanup EXIT
trap 'exit 130' INT TERM
tar --exclude=__pycache__ -cf "$results/source.tar" Cargo.toml Cargo.lock crates config scripts alpine tests integration/carpatic
scripts/vm-test.sh --name "$vm" put "$results/source.tar" "$build_dir/source.tar"
rc=0
scripts/vm-test.sh --name "$vm" ssh "set -eu; cd '$build_dir'; tar -xf source.tar; export CARGO_TARGET_DIR=/var/tmp/carpatic-native-target CARGO_BUILD_JOBS=2; cargo build --release --locked; sh tests/host.sh; sh tests/daily.sh" || rc=$?
# Preserve private-Xvfb WM logs even when a regression fails, before cleanup.
if ! scripts/vm-test.sh --name "$vm" ssh "tar -C '$build_dir/artifacts' -cf - ." >"$results/native-artifacts.tar"; then
    printf 'Native diagnostic artifact retrieval failed\n' >&2
    [ "$rc" -ne 0 ] || rc=1
fi
[ "$rc" -eq 0 ] || exit "$rc"
scripts/vm-test.sh --name "$vm" get /var/tmp/carpatic-native-target/release/carpatic-wm "$results/carpatic-wm-alpine"
