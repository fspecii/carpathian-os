# Sourced by guest tests. Exit codes: 0 pass, 77 skip, other fail.
skip() { echo "SKIP: $*"; exit 77; }
fail() { echo "FAIL: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || skip "$1 not installed ($2)"; }
running() { ps -o comm= | grep -qx "$1"; }   # busybox pgrep -x is unreliable for names started via full path
