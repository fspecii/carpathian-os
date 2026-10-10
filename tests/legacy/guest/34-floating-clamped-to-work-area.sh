#!/bin/sh
# timeout: 120
# A floating window (Settings, taller than the screen on small displays) is shrunk and moved inside the work area: never under the taskbar, menu bar or dock.
. /tmp/carpatic-rust-legacy/lib/x.sh
need carpatic-settings "settings not installed"
cu() { sh -c "PATH=/usr/local/bin:/usr/bin:/bin HOME=/home/carpatic-rust-test DISPLAY=:98 XAUTHORITY=$XAUTHORITY CARPATIC_SESSION=1 $*"; }
cu carpatic-settings >/dev/null 2>&1 </dev/null &
i=0; while [ -z "$(xdotool search --class 'arpatic-settings' 2>/dev/null)" ] && [ $i -lt 40 ]; do sleep 1; i=$((i+1)); done
sleep 3; w=$(xdotool search --class 'arpatic-settings' | tail -1); [ -n "$w" ] || fail "Settings did not open"
eval "$(xdotool getwindowgeometry --shell $w)"; bw=$(xwininfo -id $w | sed -n 's/.*Border width: //p')
set -- $(xprop -root _NET_WORKAREA | sed 's/.*= *//; s/,//g'); wx=$1; wy=$2; ww=$3; wh=$4
pkill -u "$(id -u)" -f "[c]arpatic-settings/carpatic-settings" 2>/dev/null
echo "settings at $X,$Y ${WIDTH}x$HEIGHT, work area $wx,$wy ${ww}x$wh"
[ "$X" -ge "$wx" ] && [ "$Y" -ge "$wy" ] && [ $((X + WIDTH + 2*bw)) -le $((wx + ww)) ] && [ $((Y + HEIGHT + 2*bw)) -le $((wy + wh)) ] || fail "Settings is outside the work area (under a bar)"
