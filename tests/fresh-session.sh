#!/bin/sh
# Run only in an isolated Alpine disposable fixture; no guest :0 use.
set -eu
[ "$(id -u)" = 0 ] && [ -f /etc/alpine-release ] && [ "${CARPATIC_VM_TEST:-}" = 1 ] || exit 1
unset WAYLAND_DISPLAY
cd "$(dirname "$0")/.."
source_root=$PWD
user=carpatic-fresh-review
work=$(mktemp -d /var/tmp/carpatic-fresh-review-XXXXXX)
xpid=
cleanup() {
    # Preserve startup failures even if the normal round log dump is not reached.
    for file in "$work"/session-*.log; do
        [ -f "$file" ] || continue
        echo "Final fixture log: ${file##*/}"; tail -80 "$file"
    done
    for file in "$work"/runtime-*/carpatic-session-*/*.log; do
        [ -f "$file" ] || continue
        echo "Final private hook log: ${file##*/}"; tail -80 "$file"
    done
    pkill -u "$user" 2>/dev/null || :
    [ -z "$xpid" ] || kill "$xpid" 2>/dev/null || :
    deluser --remove-home "$user" >/dev/null 2>&1 || :
    rm -rf "$work"
}
[ ! -e /tmp/.X193-lock ] || { echo 'Display 193 busy'; exit 1; }
if id "$user" >/dev/null 2>&1; then echo 'Refuse preexisting account'; exit 1; fi
trap cleanup EXIT HUP INT TERM
adduser -D -s /bin/sh "$user"
chmod 755 "$work" "$source_root"
CARPATIC_SKIP_PACKAGES=1 CARPATIC_USER="$user" sh alpine/desktop-tools.sh >"$work/install.log" 2>&1 || { cat "$work/install.log"; exit 1; }
install -m755 scripts/carpatic-rust-session /usr/local/bin/carpatic-rust-session
printf 'Program installation completed\n'
sha256sum /usr/local/bin/carpatic-wm /usr/local/bin/carpatic-rust-session /usr/local/bin/carpatic-desktop /usr/local/bin/carpatic-session-process /usr/local/bin/carpatic-session /usr/local/bin/carpatic-apply /usr/local/share/carpatic-rust/autostart.sh /usr/local/lib/carpatic-panel/carpatic_panel/flyout_cal.py /usr/local/lib/carpatic-reminders/carpatic_reminders/service.py /usr/local/share/carpatic/wallpapers/lib/carpatic_wallpapers/apply.py
round=1
result=0
while [ "$round" -le 2 ]; do
    printf '\nFresh login round %s\n' "$round"
    mkdir "$work/runtime-$round"; chown "$user:$user" "$work/runtime-$round"; chmod 700 "$work/runtime-$round"
    Xvfb :193 -screen 0 1360x768x24 -ac -nolisten tcp >"$work/xvfb-$round.log" 2>&1 & xpid=$!
    tries=0
    until DISPLAY=:193 xprop -root >/dev/null 2>&1; do tries=$((tries+1)); [ "$tries" -lt 50 ] || exit 1; sleep .1; done
    su - "$user" -c "unset WAYLAND_DISPLAY; export DISPLAY=:193 GDK_BACKEND=x11 CARPATIC_DEBUG_SESSION=1 CARPATIC_VM_TEST=1 XDG_RUNTIME_DIR='$work/runtime-$round'; exec carpatic-rust-session" >"$work/session-$round.log" 2>&1 & session_pid=$!
    tries=0
    bus=
    while [ -z "$bus" ]; do
        for candidate in $(pgrep -u "$user" -x carpatic-wm 2>/dev/null || :); do
            [ -r "/proc/$candidate/environ" ] || continue
            bus=$(tr '\000' '\n' <"/proc/$candidate/environ" 2>/dev/null | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p')
            [ -z "$bus" ] || { wm_pid=$candidate; break; }
        done
        tries=$((tries+1)); [ "$tries" -lt 100 ] || { cat "$work/session-$round.log"; exit 1; }
        sleep .1
    done
    # Bus value stays local to this owned fixture and is never printed.
    sleep 12
    su - "$user" -c "unset WAYLAND_DISPLAY; export DISPLAY=:193 GDK_BACKEND=x11 CARPATIC_DEBUG_SESSION=1 CARPATIC_VM_TEST=1 XDG_RUNTIME_DIR='$work/runtime-$round' DBUS_SESSION_BUS_ADDRESS='$bus'; python3 '$source_root/tests/fresh-session-probe.py'" >"$work/probe-$round.log" 2>&1 || result=1
    cat "$work/probe-$round.log"
    kill "$wm_pid"
    wait "$session_pid" || :
    sleep 5
    if pgrep -u "$user" >/dev/null; then
        echo 'FAIL: owned processes survive WM/session logout'
        uid=$(id -u "$user")
        for proc in /proc/[0-9]*; do
            [ -r "$proc/status" ] || continue
            [ "$(awk '/^Uid:/ {print $2}' "$proc/status")" = "$uid" ] || continue
            printf 'Surviving process %s state=%s: ' "${proc##*/}" "$(awk '/^State:/ {print $2}' "$proc/status")"
            tr '\000' ' ' <"$proc/cmdline"; printf '\n'
        done
        result=1
    else
        echo 'PASS: no owned processes after logout'
    fi
    for log in "$work/runtime-$round"/carpatic-session-*/*.log; do
        [ -f "$log" ] || continue
        stat -c 'Login log mode=%a owner=%u' "$log"
        cat "$log"
    done
    cat "$work/session-$round.log"
    pkill -u "$user" 2>/dev/null || :
    kill "$xpid"; wait "$xpid" || :; xpid=
    sleep .5
    round=$((round+1))
done
exit "$result"
