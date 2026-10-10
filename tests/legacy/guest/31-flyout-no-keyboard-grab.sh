#!/bin/sh
# timeout: 300
# A flyout (quick settings, calendar, start menu) and the workspace overview never take the keyboard away from dwm: while one is open, hotkeys still work
# (Super+2 changes workspace), Esc closes it, calling it again closes it, and nothing is left running.
. /tmp/carpatic-rust-legacy/lib/x.sh
cu() { sh -c "PATH=/usr/local/bin:/usr/bin:/bin:/sbin:/usr/sbin HOME=/home/carpatic-rust-test DISPLAY=:98 XAUTHORITY=$XAUTHORITY CARPATIC_SESSION=1 $*"; }
cur() { xprop -root _NET_CURRENT_DESKTOP | sed 's/.*= *//'; }
need carpatic-flyout "panel flyouts not installed"
xdotool key super+1; sleep 0.8
fails=0
for f in "carpatic-flyout quick" "carpatic-flyout calendar" "carpatic-flyout start" "carpatic-overview"; do
  pat="^python3 /usr/(local/)?bin/$f\$"
  cu "$f" >/dev/null 2>&1 &
  sleep 3
  pgrep -u "$(id -u)" -f "$pat" >/dev/null || { echo "FAIL $f did not start"; fails=$((fails+1)); continue; }
  xdotool key super+2; sleep 1
  [ "$(cur)" = 1 ] && echo "ok   $f: Super+2 still works while it is open" || { echo "FAIL $f: Super+2 ignored while open (workspace $(cur))"; fails=$((fails+1)); }
  xdotool key super+1; sleep 0.8
  # the second call closes it (the key that opened it closes it)
  cu "$f" >/dev/null 2>&1; sleep 1.5
  if pgrep -u "$(id -u)" -f "$pat" >/dev/null; then
    # still there: Esc must close it
    xdotool key Escape; sleep 1.5
    pgrep -u "$(id -u)" -f "$pat" >/dev/null && { echo "FAIL $f: neither the second call nor Esc closed it"; fails=$((fails+1)); pkill -u "$(id -u)" -f "$pat"; } || echo "ok   $f: Esc closes it"
  else echo "ok   $f: second call closes it"; fi
  # Esc closes it (keys reach it through X input focus, not a grab)
  cu "$f" >/dev/null 2>&1 &
  sleep 3; pgrep -u "$(id -u)" -f "$pat" >/dev/null || { echo "FAIL $f: did not reopen"; fails=$((fails+1)); }
  xdotool key Escape; sleep 1.5
  pgrep -u "$(id -u)" -f "$pat" >/dev/null && { echo "FAIL $f: Esc did not close it"; fails=$((fails+1)); pkill -u "$(id -u)" -f "$pat"; } || echo "ok   $f: Esc closes it"
  # keyboard is free afterwards
  xdotool key super+2; sleep 0.8; [ "$(cur)" = 1 ] || { echo "FAIL $f: hotkeys dead after closing"; fails=$((fails+1)); }; xdotool key super+1; sleep 0.5
done
[ $fails = 0 ] || fail "$fails flyout checks failed"
