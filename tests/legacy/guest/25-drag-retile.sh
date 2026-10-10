#!/bin/sh
# Drag a tiled window out (floats), hover over another tile (drop-zone ring appears), release = swap/insert back into the tile;
# release over empty space keeps it floating; Esc cancels and returns it to its tile.
. /tmp/carpatic-rust-legacy/lib/x.sh
neutral_set drag_tiled '"float"'; neutral_set default_layout '"tile"'; sleep 2.5   # this test is about tiles: the Windows profile starts floating
a=$(spawn_st); b=$(spawn_st); c=$(spawn_st)
xdotool key super+Return >/dev/null 2>&1   # no-op safety
cx() { echo $(( $(gv $1 X) + $(gv $1 WIDTH) / 2 )); }
cy() { echo $(( $(gv $1 Y) + $(gv $1 HEIGHT) / 2 )); }
# pick src = leftmost window (master), dst = bottom-right one
src=$a; dst=$a
for w in $a $b $c; do [ "$(gv $w X)" -lt "$(gv $src X)" ] && src=$w; done
for w in $a $b $c; do [ "$w" != "$src" ] && { [ "$dst" = "$a" ] && [ "$src" = "$a" ] && dst=$w; [ "$(gv $w Y)" -gt "$(gv $dst Y)" ] && dst=$w; }; done
[ "$dst" != "$src" ] || fail "could not pick distinct windows"
sx0=$(gv $src X); sy0=$(gv $src Y); dx0=$(gv $dst X); dy0=$(gv $dst Y)
dw=$(gv $dst WIDTH); dh=$(gv $dst HEIGHT)
echo "src $src at $sx0,$sy0   dst $dst at $dx0,$dy0 ${dw}x$dh"
# 1) pull out: Super+drag a bit -> floating (geometry no longer a tile slot) and ring shown over the destination
xdotool mousemove $(cx $src) $(cy $src) keydown super mousedown 1
xdotool mousemove_relative -- 30 30; sleep 0.3; xdotool mousemove_relative -- 30 30; sleep 0.3; xdotool mousemove_relative -- 8 8; sleep 1
dw=$(gv $dst WIDTH); dh=$(gv $dst HEIGHT)   # the remaining tiles re-flow once the window is pulled out
xdotool mousemove $(cx $dst) $(cy $dst); sleep 0.3; xdotool mousemove_relative -- 2 2; sleep 1
ring=$(xwininfo -root -tree | grep -c " ${dw}x[0-9]*+" )
dbw=$(xwininfo -id $dst | sed -n 's/.*Border width: //p')
big=$(xwininfo -root -tree | awk -v w=$((dw+2*dbw)) -v h=$dh '{ if (match($0,/ [0-9]+x[0-9]+\+/)) { g=substr($0,RSTART+1,RLENGTH-2); split(g,a,"x"); if (a[1]==w && a[2]>h) n++ } } END{print n+0}')
echo "ring candidates: $big"
xdotool mouseup 1 keyup super; sleep 1.5
nsx=$(gv $src X); nsy=$(gv $src Y)
[ $((nsx-dx0)) -lt 30 ] && [ $((dx0-nsx)) -lt 30 ] && [ $((nsy-dy0)) -lt 30 ] && [ $((dy0-nsy)) -lt 30 ] || fail "swap did not land in the destination slot ($nsx,$nsy vs $dx0,$dy0)"
ndx=$(gv $dst X); ndy=$(gv $dst Y)
[ $((ndx-sx0)) -lt 30 ] && [ $((sx0-ndx)) -lt 30 ] && [ $((ndy-sy0)) -lt 30 ] && [ $((sy0-ndy)) -lt 30 ] || fail "destination did not take the source slot ($ndx,$ndy vs $sx0,$sy0)"
[ "$big" -ge 1 ] || fail "no drop-zone ring window seen while hovering over the target tile"
# 2) Esc cancels: window returns to its tile
bx=$(gv $src X); by=$(gv $src Y)
xdotool mousemove $(cx $src) $(cy $src) keydown super mousedown 1
xdotool mousemove_relative -- 40 40; sleep 0.3; xdotool mousemove_relative -- 40 40; sleep 0.3; xdotool mousemove_relative -- 8 8; sleep 0.5
xdotool key Escape; sleep 0.5; xdotool mouseup 1 keyup super; sleep 1.5
ex=$(gv $src X); ey=$(gv $src Y)
[ $((ex-bx)) -lt 8 ] && [ $((bx-ex)) -lt 8 ] && [ $((ey-by)) -lt 8 ] && [ $((by-ey)) -lt 8 ] || fail "Esc did not return the window to its tile ($ex,$ey vs $bx,$by)"
# 3) release over empty space (the bar's right edge / screen gap) leaves it floating
xdotool mousemove $(cx $src) $(cy $src) keydown super mousedown 1
xdotool mousemove_relative -- 40 40; sleep 0.3; xdotool mousemove_relative -- 40 40; sleep 0.3; xdotool mousemove_relative -- 8 8
sh_=$(xdotool getdisplaygeometry | cut -d' ' -f2)
for st in 1 2 3 4 5; do xdotool mousemove 800 $((700 - st*135)); sleep 0.3; done; # empty space = the top bar when the profile has one, else the outer gap above the tiles (y=12 would hover over a tile and re-tile the window)
bt=$(sed -n 's/^BAR_TOP=//p' /home/carpatic-rust-test/.config/carpatic/profile.env 2>/dev/null); if [ "${bt:-0}" -gt 12 ]; then ey_=12; else ey_=3; fi
xdotool mousemove 800 $ey_; sleep 0.5
xdotool mouseup 1 keyup super; sleep 1.5
fx=$(gv $src X); fy=$(gv $src Y); echo "after empty-space drop: $fx,$fy $(gv $src WIDTH)x$(gv $src HEIGHT)"
[ "$fy" -lt $((by - 100)) ] || fail "window did not stay floating where dropped ($fx,$fy)"
# 4) keyboard path: toggling float back puts it in its former tile slot
xdotool mousemove $(cx $src) $(cy $src); sleep 0.5; xdotool mousemove_relative -- 3 3; sleep 0.5; xdotool key super+shift+space; sleep 1.5
kx=$(gv $src X); ky=$(gv $src Y)
[ $((kx-bx)) -lt 30 ] && [ $((bx-kx)) -lt 30 ] && [ $((ky-by)) -lt 30 ] && [ $((by-ky)) -lt 30 ] || fail "keyboard re-tile did not restore the tile slot ($kx,$ky vs $bx,$by)"
neutral_set drag_tiled '"float"'
