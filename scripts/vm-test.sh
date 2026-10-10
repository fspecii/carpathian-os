#!/bin/sh
# Disposable Alpine fixtures; this script never operates on the host display.
set -eu
exec python3 "$(dirname "$0")/vm-test.py" "$@"
