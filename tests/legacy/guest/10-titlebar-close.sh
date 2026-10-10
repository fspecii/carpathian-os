#!/bin/sh
# Close button closes tiled and floating windows; the other window survives.
. /tmp/carpatic-rust-legacy/lib/tb.sh
a=$(spawn_st); b=$(spawn_st)
tbclick $b close
[ -z "$(xdotool search --class '^XTerm$' | grep -x $b)" ] || fail "tiled window not closed by close button"
[ -n "$(xdotool search --class '^XTerm$' | grep -x $a)" ] || fail "close button closed the wrong window"
xdotool key super+shift+space; sleep 1   # float the survivor
tbclick $a close
[ -z "$(stwins)" ] || fail "floating window not closed by close button"
