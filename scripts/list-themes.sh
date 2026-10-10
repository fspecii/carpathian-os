#!/bin/sh
# list-themes.sh - list names of [theme.NAME] tables in a TOML file.
# Read-only. POSIX sh + awk.

set -u

usage() {
    echo "Usage: list-themes.sh [--file PATH]"
    echo ""
    echo "List the names of [theme.NAME] tables from a TOML file."
    echo "Defaults to the project config/themes.toml (relative to this script)."
    echo ""
    echo "Options:"
    echo "  --file PATH   TOML file to read"
    echo "  --help        show this help"
}

file="$(cd "$(dirname "$0")" && pwd)/../config/themes.toml"

while [ $# -gt 0 ]; do
    case "$1" in
        --file)
            [ $# -ge 2 ] || { echo "list-themes.sh: --file requires an argument" >&2; exit 2; }
            file="$2"
            shift 2
            ;;
        --file=*)
            file="${1#--file=}"
            shift
            ;;
        --help)
            usage
            exit 0
            ;;
        *)
            echo "list-themes.sh: unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [ ! -f "$file" ]; then
    echo "list-themes.sh: file not found: $file" >&2
    exit 1
fi
if [ ! -r "$file" ]; then
    echo "list-themes.sh: file not readable: $file" >&2
    exit 1
fi

awk '
/^[ \t]*#/ { next }
/^[ \t]*\[theme\.[A-Za-z0-9_-]+\][ \t]*(#.*)?[ \t]*$/ {
    name = $0
    sub(/^[ \t]*\[theme\./, "", name)
    sub(/\][ \t]*(#.*)?$/, "", name)
    print name
}
' "$file"
