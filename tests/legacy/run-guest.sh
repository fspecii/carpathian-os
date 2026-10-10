#!/bin/sh
# Run adapted legacy regression cases in an isolated account/display, never the preview.
set -u
export DISPLAY=:98 GDK_BACKEND=x11 CARPATIC_SESSION=1 XDG_CURRENT_DESKTOP=CarpaticRust
unset WAYLAND_DISPLAY XAUTHORITY
export XDG_RUNTIME_DIR=/tmp/carpatic-rust-legacy-runtime
mkdir -p "$XDG_RUNTIME_DIR" "$HOME/.config/dwm-titus" "$HOME/.local/share/dwm-titus/config" "$HOME/.config/carpatic"
chmod 700 "$XDG_RUNTIME_DIR"
cp /usr/share/carpatic-rust/config/*.toml "$HOME/.local/share/dwm-titus/config/"
cp /usr/share/carpatic-rust/config/*.toml "$HOME/.config/dwm-titus/"
printf 'PROFILE="windows"\nTHEME="carpatic"\nLAYOUT="tile"\n' > "$HOME/.config/carpatic/settings.conf"
touch "$HOME/.config/carpatic/welcome-done"
carpatic-apply >/tmp/carpatic-rust-legacy-apply.log 2>&1
carpatic-wm >/tmp/carpatic-rust-legacy-wm.log 2>&1 &
wm_pid=$!
cleanup() { kill "$wm_pid" 2>/dev/null || :; pkill -u "$(id -u)" -x xterm 2>/dev/null || :; }
trap cleanup EXIT
for i in 1 2 3 4 5 6 7 8 9 10; do xprop -root _NET_SUPPORTING_WM_CHECK | grep -q 'window id' && break; sleep 1; done
out=/tmp/carpatic-rust-legacy/results
rm -rf "$out"
mkdir -p "$out"
echo 'TAP version 13' > "$out/results.tap"
n=0; failed=0
for file in /tmp/carpatic-rust-legacy/guest/*.sh; do
    name=$(basename "$file" .sh)
    if [ -n "${CARPATIC_LEGACY_CASES:-}" ]; then
        case ",$CARPATIC_LEGACY_CASES," in *",$name,"*) :;; *) continue;; esac
    fi
    n=$((n+1))
    timeout 420 sh "$file" > "$out/$name.log" 2>&1; rc=$?
    case $rc in
        0) line="ok $n - $name";;
        77) line="ok $n - $name # SKIP";;
        *) line="not ok $n - $name"; failed=$((failed+1));;
    esac
    echo "$line"; echo "$line" >> "$out/results.tap"
    [ "$rc" = 0 ] || tail -5 "$out/$name.log"
done
echo "1..$n" >> "$out/results.tap"
echo "$n legacy cases, $failed failed"
[ "$n" -gt 0 ] || { echo 'No matching legacy cases' >&2; exit 2; }
[ "$failed" = 0 ]
