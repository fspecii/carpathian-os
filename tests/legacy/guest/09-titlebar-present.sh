#!/bin/sh
# Every window (tiled and floating) has a title bar directly above it, as wide as the window frame.
. /tmp/carpatic-rust-legacy/lib/tb.sh
a=$(spawn_st); b=$(spawn_st)
for w in $a $b; do
  i=$(tbinfo $w); [ -n "$i" ] || fail "tiled window $w has no title bar"
  set -- $i; tw=$4; th=$5; cw=$(gv $w WIDTH)
  echo "win $w content ${cw}px, titlebar ${tw}x$th"
  [ "$th" -ge 16 ] || fail "title bar too thin ($th)"
  [ "$tw" -ge "$cw" ] && [ "$tw" -le $((cw+4)) ] || fail "title bar width $tw does not match window width $cw"
done
xdotool key super+shift+space; sleep 1
i=$(tbinfo $b); [ -n "$i" ] || fail "floating window has no title bar"
