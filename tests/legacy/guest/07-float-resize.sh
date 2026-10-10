#!/bin/sh
# Floating window resizes with Super+right-drag.
. /tmp/carpatic-rust-legacy/lib/x.sh
a=$(spawn_st); xdotool key super+shift+space; sleep 1
drag 1 400 300 20 20   # nudge so it's well inside the screen
w0=$(gv $a WIDTH); h0=$(gv $a HEIGHT)
x=$(gv $a X); y=$(gv $a Y)
drag 3 $((x+w0-30)) $((y+h0-30)) -30 -30
w1=$(gv $a WIDTH); h1=$(gv $a HEIGHT)
echo "size ${w0}x$h0 -> ${w1}x$h1"
[ "$w1" -lt "$w0" ] && [ "$h1" -lt "$h0" ] || fail "Super+right-drag did not resize window"
