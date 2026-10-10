#!/bin/sh
# Maximise button / double-click: fills the work area (below bar, inside gaps), restore returns exact geometry.
. /tmp/carpatic-rust-legacy/lib/tb.sh
sw=$(xprop -root _NET_WORKAREA 2>/dev/null | sed -n 's/.*= *[0-9]*, *[0-9]*, *\([0-9]*\),.*/\1/p'); wx=$(xprop -root _NET_WORKAREA 2>/dev/null | sed -n 's/.*= *\([0-9]*\),.*/\1/p'); [ -n "$sw" ] || sw=$(xdotool getdisplaygeometry | cut -d' ' -f1)   # work area width: a side dock (Ubuntu style) narrows it
a=$(spawn_st); b=$(spawn_st)
g0=$(geom $b); t0=$(geom $a)
tbclick $b max; g1=$(geom $b)
echo "tiled before: $g0  maximised: $g1"
[ "$g0" != "$g1" ] || fail "maximise did not change geometry"
w=$(gv $b WIDTH); x=$(gv $b X); y=$(gv $b Y)
[ "$w" -ge $((sw-30)) ] && [ "$w" -le $((sw-14)) ] || fail "maximised width $w not ~screen width (gaps) $sw"
[ "$x" -ge $((${wx:-0}+4)) ] && [ "$x" -le $((${wx:-0}+16)) ] || fail "maximised window not inset by gap (x=$x)"
# content starts below the title bar (28) and the outer gap (8); a top bar (dwm bar, panel menu bar) only pushes it further down
[ "$y" -ge 36 ] || fail "maximised content overlaps bar/title (y=$y)"
[ -n "$(tbinfo $b)" ] || fail "maximised window lost its title bar"
tbclick $b max; g2=$(geom $b)
[ "$g2" = "$g0" ] || fail "restore did not return exact geometry: [$g0] -> [$g2]"
[ "$(geom $a)" = "$t0" ] || fail "other tiled window moved after maximise/restore"
# still tiled after restore: float toggle must change geometry
xdotool key super+shift+space; sleep 1; [ "$(geom $b)" != "$g0" ] || fail "window was not tiled after restore"
xdotool key super+shift+space; sleep 1
# double-click on the title (left part) toggles maximise
i=$(tbinfo $b); set -- $i; xdotool mousemove $(( $2 + 30 )) $(( $3 + $5/2 )); sleep 0.4
xdotool click --repeat 2 --delay 80 1; sleep 1
g3=$(geom $b); [ "$g3" != "$g0" ] || fail "double-click did not maximise"
xdotool click --repeat 2 --delay 80 1; sleep 1
[ "$(geom $b)" = "$g0" ] || fail "double-click did not restore"
# floating window: maximise + restore keeps exact geometry
xdotool key super+shift+space; sleep 1; f0=$(geom $b)
tbclick $b max; [ "$(geom $b)" != "$f0" ] || fail "floating maximise no-op"
tbclick $b max; [ "$(geom $b)" = "$f0" ] || fail "floating restore not exact"
