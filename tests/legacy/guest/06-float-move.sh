#!/bin/sh
# Floating window moves with Super+left-drag; size unchanged.
. /tmp/carpatic-rust-legacy/lib/x.sh
a=$(spawn_st); xdotool key super+shift+space; sleep 1
x0=$(gv $a X); y0=$(gv $a Y); w0=$(gv $a WIDTH)
drag 1 400 300 40 30
x1=$(gv $a X); y1=$(gv $a Y); w1=$(gv $a WIDTH)
echo "pos $x0,$y0 -> $x1,$y1"
[ $((x1-x0)) -ge 40 ] && [ $((y1-y0)) -ge 30 ] || fail "Super+drag did not move window"
[ "$w0" = "$w1" ] || fail "move changed width $w0 -> $w1"
