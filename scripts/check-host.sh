#!/bin/sh
# check-host.sh - read-only host dependency check for Carpathian OS.
#
# POSIX sh (Alpine busybox ash compatible). Verifies that the commands
# required to build and test the workspace are present in PATH:
#
#   cargo rustc Xvfb xdotool python3
#
# Prints each missing command plainly and exits nonzero if any are
# missing. Performs no installs, no network access, no GUI, no VM.

set -u

# Note: this script uses only shell builtins (printf, command, [) so it
# works even when PATH is restricted, e.g. in tests with a fake PATH.
usage() {
    printf 'Usage: check-host.sh [-h | --help]\n'
    printf '\n'
    printf 'Read-only check for commands required by Carpathian OS:\n'
    printf '\n'
    printf '    cargo rustc Xvfb xdotool python3\n'
    printf '\n'
    printf 'Prints each missing command plainly and exits nonzero if any are\n'
    printf 'missing. No installs, no network, no GUI, no VM.\n'
    printf '\n'
    printf 'Options:\n'
    printf '    -h, --help    Show this help and exit 0.\n'
}

# Option handling: only no arguments or --help/-h are accepted.
for arg in "$@"; do
    case $arg in
        -h|--help)
            usage
            exit 0
            ;;
        *)
            printf 'check-host.sh: unknown argument: %s\n' "$arg" >&2
            usage >&2
            exit 2
            ;;
    esac
done

missing=0
for cmd in cargo rustc Xvfb xdotool python3; do
    if command -v "$cmd" >/dev/null 2>&1; then
        printf 'found:   %s\n' "$cmd"
    else
        printf 'missing: %s\n' "$cmd"
        missing=$((missing + 1))
    fi
done

if [ "$missing" -eq 0 ]; then
    printf 'check-host: all required commands found\n'
    exit 0
fi

printf 'check-host: %d required command(s) missing\n' "$missing"
exit 1
