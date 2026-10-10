#!/bin/sh
# Two terminals must tile: side by side, not overlapping, inside the screen.
. /tmp/carpatic-rust-legacy/lib/x.sh
a=$(spawn_st); b=$(spawn_st)
[ "$a" != "$b" ] || fail "both spawns gave the same window"
ax=$(gv $a X); aw=$(gv $a WIDTH); ay=$(gv $a Y); ah=$(gv $a HEIGHT)
bx=$(gv $b X); bw=$(gv $b WIDTH); by=$(gv $b Y); bh=$(gv $b HEIGHT)
echo "a: $ax,$ay ${aw}x$ah  b: $bx,$by ${bw}x$bh"
[ $((ax+aw)) -le "$bx" ] || [ $((bx+bw)) -le "$ax" ] || [ $((ay+ah)) -le "$by" ] || [ $((by+bh)) -le "$ay" ] || fail "windows overlap while tiled"
sw=$(xdotool getdisplaygeometry | cut -d' ' -f1)
[ $((ax+aw)) -le "$sw" ] && [ $((bx+bw)) -le "$sw" ] || fail "window extends beyond screen"
[ "$ax" -ge 0 ] && [ "$ay" -ge 15 ] || fail "window overlaps the bar (y=$ay)"
