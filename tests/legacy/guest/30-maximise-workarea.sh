#!/bin/sh
# timeout: 480
# Maximise, snap and minimise/restore never cover the panel: for the Windows, macOS, Ubuntu and Tiling styles the window stays inside the work area
# dwm publishes (_NET_WORKAREA = screen minus the panel's struts), and the panel's own window is not overlapped.
. /tmp/carpatic-rust-legacy/lib/x.sh
cu() { sh -c "PATH=/usr/local/bin:/usr/bin:/bin:/sbin:/usr/sbin HOME=/home/carpatic-rust-test DISPLAY=:98 XAUTHORITY=$XAUTHORITY $*"; }
orig=$(sed -n 's/^PROFILE="\(.*\)"$/\1/p' /home/carpatic-rust-test/.config/carpatic/settings.conf 2>/dev/null | tail -1); [ -n "$orig" ] || orig=tiling
trap 'cu carpatic-profile set $orig >/dev/null 2>&1; closeall' EXIT
fails=0
inside() { # win label : outer frame inside the work area
  eval "$(xdotool getwindowgeometry --shell $1)"; bw=$(xwininfo -id $1 | sed -n 's/.*Border width: //p')
  set -- $(xprop -root _NET_WORKAREA | sed 's/.*= *//; s/,//g'); wx=$1; wy=$2; ww=$3; wh=$4
  [ "$X" -ge "$wx" ] && [ "$Y" -ge "$wy" ] && [ $((X+WIDTH+2*bw)) -le $((wx+ww)) ] && [ $((Y+HEIGHT+2*bw)) -le $((wy+wh)) ]
}
for p in windows macos ubuntu tiling; do
  closeall; cu carpatic-profile set $p >/dev/null 2>&1; sleep 8; neutral_on 2>/dev/null
  wa=$(xprop -root _NET_WORKAREA | sed 's/.*= *//; s/\(\([0-9]*, *\)\{3\}[0-9]*\).*/\1/'); [ -n "$wa" ] || { echo "FAIL $p: dwm publishes no _NET_WORKAREA"; fails=$((fails+1)); continue; }
  a=$(spawn_st)
  xdotool key super+z; sleep 1.2
  inside $a && echo "ok   $p: maximise stays in the work area ($wa)" || { echo "FAIL $p: maximised window leaves the work area ($wa): $(xdotool getwindowgeometry $a | tr '\n' ' ')"; fails=$((fails+1)); }
  xdotool key super+z; sleep 1
  xdotool key super+alt+f; sleep 1; cu carpatic-snap max; sleep 1
  inside $a && echo "ok   $p: Snap maximise stays in the work area" || { echo "FAIL $p: snapped window leaves the work area ($wa): $(xdotool getwindowgeometry $a | tr '\n' ' ')"; fails=$((fails+1)); }
  # minimise / maximise round trips through the title-bar buttons (the same tests 11 and 12 run on the default style)
  closeall
  for t in $( if [ $p = windows ] || [ $p = ubuntu ]; then echo 12-titlebar-minimize; fi; if [ $p = windows ]; then echo 11-titlebar-maximize; fi ); do   # the macOS (left buttons) and Tiling (no title bars) styles are covered by the work-area checks above
    if sh "$(dirname "$0")/$t.sh" >/tmp/o30.txt 2>&1; then echo "ok   $p: $t"; else echo "FAIL $p: $t: $(tail -1 /tmp/o30.txt)"; fails=$((fails+1)); fi
  done
  neutral_off 2>/dev/null
done
[ $fails = 0 ] || fail "$fails maximise checks failed"
