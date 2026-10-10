#!/bin/sh
# Keep a real Xorg desktop running inside an isolated Alpine VM for inspection.
set -eu
[ "${CARPATIC_VM_TEST:-}" = 1 ] && [ -f /etc/alpine-release ] || {
    printf 'This check runs only inside an explicitly marked Alpine test VM.\n' >&2; exit 1;
}
unset WAYLAND_DISPLAY XDG_CURRENT_DESKTOP DBUS_SESSION_BUS_ADDRESS
desktop_home=$(getent passwd "$(id -u)" | cut -d: -f6)
[ -n "$desktop_home" ] && [ -d "$desktop_home" ] || exit 1
export HOME="$desktop_home" DISPLAY=:0 GDK_BACKEND=x11 CARPATIC_DEBUG_SESSION=1
modprobe virtio_gpu 2>/dev/null || :
Xorg :0 vt7 -nolisten tcp -noreset -logfile /tmp/carpatic-xorg.log >/tmp/carpatic-xorg-console.log 2>&1 &
echo $! >/tmp/carpatic-xorg.pid
tries=0
while ! xprop -root >/dev/null 2>&1; do
    tries=$((tries + 1)); [ "$tries" -lt 40 ] || { cat /tmp/carpatic-xorg.log; exit 1; }
    sleep 0.25
done
/usr/local/bin/carpatic-rust-session >/tmp/carpatic-rust-session.log 2>&1 &
echo $! >/tmp/carpatic-rust-session.pid
tries=0
while ! xprop -root _NET_SUPPORTING_WM_CHECK 2>/dev/null | grep -q 'window id'; do
    tries=$((tries + 1)); [ "$tries" -lt 40 ] || { cat /tmp/carpatic-rust-session.log; exit 1; }
    sleep 0.25
done
for label in 'Master terminal' 'Stack terminal 1' 'Stack terminal 2'; do
    xterm -fa 'DejaVu Sans Mono' -fs 12 -bg '#111c2b' -fg '#d6e3ef' -title "$label" \
        -e sh -c 'printf "Carpathian OS — native Alpine desktop\n\nSuper + Shift + Space: toggle floating\nSuper + drag: move\nSuper + right drag: resize\nSuper + 1–4: workspaces\n\n"; exec sh' \
        >/tmp/carpatic-xterm.log 2>&1 &
    sleep 0.4
done
xprop -root _NET_CLIENT_LIST _NET_NUMBER_OF_DESKTOPS _NET_CURRENT_DESKTOP
pid=$(pidof carpatic-wm)
printf '\nWindow manager memory (not the whole desktop):\n'
cat "/proc/$pid/smaps_rollup" | grep -E 'Rss:|Pss:|Private_Clean:|Private_Dirty:'
printf '\nWindow manager binary:\n'
ls -lh /usr/local/bin/carpatic-wm
