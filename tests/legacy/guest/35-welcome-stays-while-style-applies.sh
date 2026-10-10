#!/bin/sh
# timeout: 120
# Choosing a style in the Welcome wizard must not make the Welcome window disappear while the session restarts its helpers.
. /tmp/carpatic-rust-legacy/lib/x.sh
need carpatic-welcome "welcome not installed"
cu() { sh -c "PATH=/usr/local/bin:/usr/bin:/bin HOME=/home/carpatic-rust-test DISPLAY=:98 XAUTHORITY=$XAUTHORITY CARPATIC_SESSION=1 $*"; }
orig=$(sed -n 's/^PROFILE="\(.*\)"$/\1/p' /home/carpatic-rust-test/.config/carpatic/settings.conf 2>/dev/null | tail -1); [ -n "$orig" ] || orig=tiling
setpid=
trap '[ -n "$setpid" ] && wait $setpid; pkill -u "$(id -u)" -f "[c]arpatic-welcome"; cu carpatic-profile set $orig >/dev/null 2>&1' EXIT
cu carpatic-welcome >/dev/null 2>&1 </dev/null &
i=0; while [ -z "$(xdotool search --onlyvisible --name Welcome 2>/dev/null)" ] && [ $i -lt 30 ]; do sleep 1; i=$((i+1)); done
sleep 2; [ -n "$(xdotool search --onlyvisible --name Welcome)" ] || fail "Welcome did not open"
other=ubuntu; [ "$orig" = ubuntu ] && other=windows
cu "carpatic-profile set $other" >/dev/null 2>&1 </dev/null &
setpid=$!
gone=0; i=0
while [ $i -lt 30 ]; do [ -z "$(xdotool search --onlyvisible --name Welcome 2>/dev/null)" ] && gone=$((gone+1)); sleep 0.5; i=$((i+1)); done
wait $setpid; sleep 3
[ $gone = 0 ] || fail "the Welcome window was missing in $gone of 30 samples while the style applied"
