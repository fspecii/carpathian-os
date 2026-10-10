#!/bin/sh
# timeout: 420
# Every window-button style: hit areas exist where dwm says, close closes, maximise toggles (exact restore), minimise hides and Super+Shift+m brings it back;
# macOS puts the buttons on the left, 'none' has no buttons, "only close" leaves one hit area.
. /tmp/carpatic-rust-legacy/lib/tb.sh
STYLES="windows macos gnome kde minimal ring squircle contrast omarchy kylin nothing classic98 luna"
rng() { # rng <win> -> "min0 min1 max0 max1 close0 close1"
  i=$(tbinfo "$1"); set -- $i; xprop -id "$1" _CARPATIC_BUTTONS | sed 's/.*= //; s/,//g'; }
for st in $STYLES; do
  tbcfg "button_style=\"$st\"" 'button_side="auto"' 'buttons_shown="all"' 'button_order=""'
  closeall; a=$(spawn_st); b=$(spawn_st)
  r=$(rng $b); set -- $r
  [ "$2" -gt "$1" ] && [ "$4" -gt "$3" ] && [ "$6" -gt "$5" ] || fail "$st: a button has no hit area ($r)"
  tw=$(tbinfo $b | cut -d' ' -f4)
  case $st in macos) [ "$5" -lt $((tw/2)) ] || fail "macos close button not on the left ($r)";; *) [ "$5" -gt $((tw/2)) ] || fail "$st: close button not on the right ($r)";; esac
  g0=$(geom $b)
  tbclick $b max; g1=$(geom $b); [ "$g0" != "$g1" ] || fail "$st: maximise did nothing"
  tbclick $b max; g2=$(geom $b); [ "$g2" = "$g0" ] || fail "$st: restore not exact (before: $g0; after: $g2)"
  tbclick $b min; mapped $b && fail "$st: minimise left the window on screen"
  xdotool key super+shift+m; sleep 1.2; mapped $b || fail "$st: Super+Shift+m did not restore"
  tbclick $b close; [ -z "$(xdotool search --class '^XTerm$' | grep -x $b)" ] || fail "$st: close did not close"
  echo "ok $st"
done
# only close: one hit area
tbcfg 'button_style="gnome"' 'buttons_shown="close"'; closeall; a=$(spawn_st)
r=$(rng $a); set -- $r; [ "$2" = 0 ] && [ "$4" = 0 ] && [ "$6" -gt "$5" ] || fail "buttons_shown=close should leave only the close button ($r)"
tbclick $a close; [ -z "$(stwins)" ] || fail "close-only: close did not close"
# none: title bar without buttons
tbcfg 'button_style="none"' 'buttons_shown="all"'; closeall; a=$(spawn_st)
r=$(rng $a); set -- $r; [ "$1$2$3$4$5$6" = 000000 ] || fail "style none still has buttons ($r)"
# custom order and side override
tbcfg 'button_style="windows"' 'button_side="left"' 'button_order="close,max,min"'; closeall; a=$(spawn_st)
r=$(rng $a); set -- $r; [ "$5" -lt "$3" ] && [ "$3" -lt "$1" ] || fail "button_order close,max,min not honoured ($r)"
exit 0
