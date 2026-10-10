#!/bin/sh
# Window look: border colours/width/highlight, rounded corners, gaps, smart gaps, gap hotkeys (live TOML keys, numeric + pixel checks).
. /tmp/carpatic-rust-legacy/lib/x.sh
need maim "maim not installed"
px() { maim -g 1x1+$1+$2 /tmp/look-px.bmp 2>/dev/null; dd if=/tmp/look-px.bmp bs=1 skip=54 count=3 2>/dev/null | od -An -tx1 | tr -d ' \n'; }
bwid() { xwininfo -id $1 | sed -n 's/.*Border width: //p'; }
neutral_set border_width 3; neutral_set border_highlight 2; neutral_set corner_radius 12; neutral_set inner_gap 30; neutral_set outer_gap 20; neutral_set smart_gaps 0
neutral_set border_active '"#ff8800"'; neutral_set border_inactive '"#112233"'; sleep 2.5
a=$(spawn_st); b=$(spawn_st); sleep 1
# master is left; find it
l=$a; r=$b; [ "$(gv $a X)" -lt "$(gv $b X)" ] || { l=$b; r=$a; }
foc=$(xdotool getwindowfocus); oth=$l; [ "$foc" = "$l" ] && oth=$r
[ "$(bwid $foc)" = 5 ] || fail "focused border should be 3+2 highlight, got $(bwid $foc)"
[ "$(bwid $oth)" = 3 ] || fail "unfocused border should be 3, got $(bwid $oth)"
lb=$(bwid $l); rb=$(bwid $r)
wx=$(xprop -root _NET_WORKAREA 2>/dev/null | sed -n "s/.*= *\([0-9]*\),.*/\1/p"); wx=${wx:-0}   # a side dock (Ubuntu style) moves the work area
ol=$(gv $l X); [ "$ol" = $((wx + 20)) ] || fail "outer gap: window outer edge at $ol, want $((wx + 20)) (work area starts at $wx)"
gap=$(( $(gv $r X) - ($(gv $l X) + $(gv $l WIDTH) + 2 * lb) )); # terminals snap to whole character cells, so the left window can be up to one cell (<= 14 px) narrower than its slot
[ "$gap" -ge 30 ] && [ "$gap" -le 44 ] || fail "inner gap $gap, want 30..44"
# border colours (left border pixel in the middle of each window)
pf=$(px $(( $(gv $foc X) + 1 )) $(( $(gv $foc Y) + $(gv $foc HEIGHT) / 2 ))); po=$(px $(( $(gv $oth X) + 1 )) $(( $(gv $oth Y) + $(gv $oth HEIGHT) / 2 )))
echo "border pixels focused=$pf other=$po"
if [ "$pf" != 0088ff ]; then
  echo "focused geometry: $(geom $foc); border $(bwid $foc)"
  xprop -root _NET_ACTIVE_WINDOW
  xprop -id "$foc" _NET_FRAME_EXTENTS
  maim /tmp/carpatic-rust-legacy/results/window-look-failure.png 2>/dev/null || :
fi
[ "$pf" = 0088ff ] || fail "focused border colour $pf, want ff8800 (BGR 0088ff)"
[ "$po" = 332211 ] || fail "other border colour $po, want 112233 (BGR 332211)"
# rounded corners: the bottom-left outer corner pixel is NOT the border colour; the straight edge is
cx=$(gv $oth X); cy=$(( $(gv $oth Y) + $(gv $oth HEIGHT) + 2 * $(bwid $oth) - 1 ))
pc=$(px $cx $cy); pe=$(px $((cx + 40)) $cy)
echo "corner=$pc edge=$pe"
[ "$pc" != "$pe" ] || fail "radius 12: the outer corner pixel equals the edge pixel (corner not rounded)"
neutral_set corner_radius 0; sleep 2.5
pc=$(px $cx $cy); [ "$pc" = "$pe" ] || fail "radius 0: corner pixel $pc differs from edge $pe (still rounded)"
# gap hotkeys: Super+equal grows all gaps by 2
xdotool key super+equal; sleep 1
gap2=$(( $(gv $r X) - ($(gv $l X) + $(gv $l WIDTH) + 2 * $(bwid $l)) )); [ "$gap2" -ne "$gap" ] || fail "Super+equal did not change the gap ($gap2)"
xdotool key super+minus; xdotool key super+minus; sleep 1
gap3=$(( $(gv $r X) - ($(gv $l X) + $(gv $l WIDTH) + 2 * $(bwid $l)) )); [ "$gap3" -lt "$gap" ] || fail "Super+minus x2 did not shrink the gap below $gap (got $gap3)"
# smart gaps: one window -> no gap at all
neutral_set smart_gaps 1; sleep 2.5
xdotool windowkill $r; sleep 2
one=$(stwins | head -1); edge=$(gv $one X)
[ "$edge" = 0 ] || fail "smart gaps: single window outer edge at $edge, want 0"
neutral_set smart_gaps 0
