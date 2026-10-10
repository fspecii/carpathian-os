#!/bin/sh
# tests/check-host.sh - tests for scripts/check-host.sh.
#
# POSIX sh, read-only with respect to the repository: all fixtures live
# in a temp directory. Uses an isolated fake PATH with fake executables
# so it never depends on the host having cargo (or any other dependency).

set -u

here=$(cd "$(dirname "$0")" && pwd)
script="$here/../scripts/check-host.sh"

failures=0
pass() { printf 'ok:   %s\n' "$1"; }
fail() { printf 'FAIL: %s\n' "$1"; failures=$((failures + 1)); }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT INT TERM

ALL_DEPS='cargo rustc Xvfb xdotool python3'

# make_fake DIR NAME... - create fake executable NAME in DIR.
make_fake() {
    _dir=$1
    shift
    mkdir -p "$_dir"
    for _name in "$@"; do
        printf '#!/bin/sh\nexit 0\n' > "$_dir/$_name"
        chmod +x "$_dir/$_name"
    done
}

# run_check PATHDIR ARGS... -> sets rc_out and out_out.
run_check() {
    _dir=$1
    shift
    out_out=$(PATH="$_dir" "$script" "$@" 2>&1)
    rc_out=$?
}

# Fixture directories.
make_fake "$tmp/all" $ALL_DEPS
mkdir -p "$tmp/none"
make_fake "$tmp/partial" cargo

# 1. All dependencies present (isolated fake PATH, no host toolchain).
run_check "$tmp/all"
[ "$rc_out" -eq 0 ] && pass 'all deps: exit 0' || fail "all deps: expected exit 0, got $rc_out"
case $out_out in
    *missing:*) fail 'all deps: output claims a missing command' ;;
    *) pass 'all deps: no missing lines' ;;
esac

# 2. No dependencies present.
run_check "$tmp/none"
[ "$rc_out" -ne 0 ] && pass 'no deps: nonzero exit' || fail "no deps: expected nonzero exit, got $rc_out"
for cmd in $ALL_DEPS; do
    case $out_out in
        *"missing: $cmd"*) pass "no deps: reports missing $cmd" ;;
        *) fail "no deps: does not report missing $cmd" ;;
    esac
done

# 3. Partial: only cargo present; others must be reported, cargo must not.
run_check "$tmp/partial"
[ "$rc_out" -ne 0 ] && pass 'partial: nonzero exit' || fail "partial: expected nonzero exit, got $rc_out"
case $out_out in
    *"missing: cargo"*) fail 'partial: wrongly reports cargo missing' ;;
    *) pass 'partial: cargo not reported missing' ;;
esac
for cmd in rustc Xvfb xdotool python3; do
    case $out_out in
        *"missing: $cmd"*) pass "partial: reports missing $cmd" ;;
        *) fail "partial: does not report missing $cmd" ;;
    esac
done

# 4. --help exits 0 even with an empty PATH (no deps installed).
run_check "$tmp/none" --help
[ "$rc_out" -eq 0 ] && pass '--help: exit 0' || fail "--help: expected exit 0, got $rc_out"
case $out_out in
    *Usage*) pass '--help: prints usage' ;;
    *) fail '--help: no usage text' ;;
esac

# 5. -h behaves like --help.
run_check "$tmp/none" -h
[ "$rc_out" -eq 0 ] && pass '-h: exit 0' || fail "-h: expected exit 0, got $rc_out"

# 6. Unknown argument is rejected.
run_check "$tmp/all" --bogus
[ "$rc_out" -ne 0 ] && pass 'bad arg: nonzero exit' || fail "bad arg: expected nonzero exit, got $rc_out"

if [ "$failures" -eq 0 ]; then
    printf 'check-host tests: all passed\n'
    exit 0
fi
printf 'check-host tests: %d failure(s)\n' "$failures"
exit 1
