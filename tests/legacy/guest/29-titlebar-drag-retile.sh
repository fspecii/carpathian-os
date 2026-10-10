#!/bin/sh
# timeout: 240
# Auto-tiling: dragging a window by its TITLE BAR (no Super key) pulls it out so it floats freely; dropping it on another tile snaps it back into the tiling.
. /tmp/carpatic-rust-legacy/lib/x.sh
neutral_set drag_tiled '"float"'; neutral_set default_layout '"tile"'; sleep 2.5
a=$(spawn_st); b=$(spawn_st); c=$(spawn_st)
src=$a; for w in $a $b $c; do [ "$(gv $w X)" -lt "$(gv $src X)" ] && src=$w; done
dst=$a; for w in $a $b $c; do [ "$w" != "$src" ] && { [ "$dst" = "$src" ] || [ "$(gv $w Y)" -gt "$(gv $dst Y)" ]; } && dst=$w; done
[ "$dst" != "$src" ] || dst=$b
sx=$(gv $src X); sy=$(gv $src Y); sw=$(gv $src WIDTH); dx=$(gv $dst X); dy=$(gv $dst Y); dw=$(gv $dst WIDTH); dh=$(gv $dst HEIGHT)
echo "src $src at $sx,$sy ${sw}w   dst $dst at $dx,$dy ${dw}x$dh"
# title bar sits above the client area: grab it 12 px above the client's top edge, in the middle
tx=$((sx + sw / 2)); ty=$((sy - 12))
xdotool mousemove $tx $ty mousedown 1; sleep 0.3
xdotool mousemove_relative -- 40 40; sleep 0.3; xdotool mousemove_relative -- 40 40; sleep 0.3; xdotool mousemove_relative -- 10 10; sleep 0.8
nx=$(gv $src X); ny=$(gv $src Y)
[ $((nx-sx)) -ge 20 ] && [ $((ny-sy)) -ge 10 ] || { xdotool mouseup 1; fail "title-bar drag did not pull the window out ($sx,$sy -> $nx,$ny)"; }
echo "floating at $nx,$ny"
xdotool mousemove $((dx + dw / 2)) $((dy + dh / 2)); sleep 0.3; xdotool mousemove_relative -- 3 3; sleep 0.8
xdotool mouseup 1; sleep 1.5
fx=$(gv $src X); fy=$(gv $src Y)
dist=$(( (fx-dx) * (fx-dx) + (fy-dy) * (fy-dy) )); [ "$dist" -lt $((40*40)) ] || fail "drop on a tile did not snap the window into it ($fx,$fy vs $dx,$dy)"
echo "snapped back to $fx,$fy"
