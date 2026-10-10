#!/bin/sh
# Tests for scripts/list-themes.sh using temporary fixtures. No writes outside mktemp.

set -u

script="$(cd "$(dirname "$0")/.." && pwd)/scripts/list-themes.sh"
pass=0
fail=0

ok() { echo "PASS: $1"; pass=$((pass + 1)); }
ko() { echo "FAIL: $1"; fail=$((fail + 1)); }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# Fixture 1: mixed content with themes, other tables, comments, blank lines
cat > "$tmp/f1.toml" <<'EOF'
# comment with [theme.fake] inside
[active]
theme = "carpatic"

[appearance]
borderpx = 2

[theme.alpha]
normfgcolor = "#111111"

   [theme.beta-2]
normbgcolor = "#222222"

[tray]
enabled = 1

[theme.gamma_x]
selbgcolor = "#333333"

[not_theme.z]
x = 1
EOF
expected1='alpha
beta-2
gamma_x'

# Test 1: --file listing
out="$("$script" --file "$tmp/f1.toml")"
[ "$out" = "$expected1" ] && ok "--file lists theme names" || ko "--file lists theme names (got: $out)"

# Fixture 2: project themes.toml default listing (non-empty, no theme on active)
# Test 2: default file, run from a different cwd
out="$(cd "$tmp" && "$script")"
[ -n "$out" ] && ok "default run produces output" || ko "default run empty"
echo "$out" | grep -qx carpatic && ok "default includes carpatic" || ko "default missing carpatic"
echo "$out" | grep -qx tokyonight-day && ok "default includes tokyonight-day" || ko "default missing tokyonight-day"
echo "$out" | grep -q carpatic-light && echo "$out" | grep -q "^carpatic-light$" && ok "dotted names parsed" || ko "dotted names wrong"

# Test 3: --help exits 0 and shows usage
out="$("$script" --help)" ; rc=$?
[ $rc -eq 0 ] && ok "--help exit 0" || ko "--help rc=$rc"
echo "$out" | grep -q -- "--file" && ok "--help mentions --file" || ko "--help missing usage"

# Test 4: missing file exits nonzero with plain error
out="$("$script" --file "$tmp/nope.toml" 2>&1 >/dev/null)"; rc=$?
[ $rc -ne 0 ] && ok "missing file nonzero exit (rc=$rc)" || ko "missing file rc=0"
[ -n "$out" ] && ok "missing file prints error" || ko "missing file silent"

# Test 5: bad option exits nonzero
out="$("$script" --bogus 2>&1 >/dev/null)"; rc=$?
[ $rc -ne 0 ] && ok "bad option nonzero exit (rc=$rc)" || ko "bad option rc=0"
[ -n "$out" ] && ok "bad option prints error" || ko "bad option silent"

# Test 6: --file without argument exits nonzero
"$script" --file >/dev/null 2>&1; rc=$?
[ $rc -ne 0 ] && ok "--file without arg nonzero exit" || ko "--file without arg rc=0"

echo ""
echo "passed=$pass failed=$fail"
[ $fail -eq 0 ]
