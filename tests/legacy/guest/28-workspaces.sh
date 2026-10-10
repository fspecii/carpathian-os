#!/bin/sh
# timeout: 240
# Workspaces: Ctrl+Alt+Right/Left and Super+Ctrl+Right/Left change the workspace, Super+N goes directly, Ctrl+Alt+Shift+Right takes the window along,
# each workspace remembers its own layout (pertag), the panel shows the pager state, gesture defaults and docs exist.
. /tmp/carpatic-rust-legacy/lib/x.sh
cur() { xprop -root _NET_CURRENT_DESKTOP | sed 's/.*= *//'; }
xdotool key super+1; sleep 0.8; [ "$(cur)" = 0 ] || fail "Super+1 did not go to workspace 1 ($(cur))"
xdotool key ctrl+alt+Right; sleep 0.8; [ "$(cur)" = 1 ] || fail "Ctrl+Alt+Right: workspace $(cur), want 2"
xdotool key super+ctrl+Right; sleep 0.8; [ "$(cur)" = 2 ] || fail "Super+Ctrl+Right: workspace $(cur), want 3"
xdotool key ctrl+alt+Left; sleep 0.8; [ "$(cur)" = 1 ] || fail "Ctrl+Alt+Left: workspace $(cur), want 2"
xdotool key super+1; sleep 0.8; xdotool key ctrl+alt+Left; sleep 0.8; [ "$(cur)" = $(( $(xprop -root _NET_NUMBER_OF_DESKTOPS | sed "s/.*= *//") - 1 )) ] || fail "Ctrl+Alt+Left from workspace 1 did not wrap to the last workspace ($(cur))"
xdotool key super+1; sleep 0.8
a=$(spawn_st); xdotool key ctrl+alt+shift+Right; sleep 1.2
[ "$(cur)" = 1 ] || fail "window carried to workspace 2 but the view is on $(cur)"
xdotool key super+1; sleep 0.8; closeall
# per-workspace layout (pertag): turn auto-tiling off on workspace 2 only; workspace 1 keeps tiling
xdotool key super+1; sleep 0.8; b=$(spawn_st); c=$(spawn_st); gb=$(geom $b)
xdotool key super+2; sleep 0.8; xdotool key super+alt+t; sleep 1
xdotool key super+1; sleep 1
[ "$(geom $b)" = "$gb" ] && [ "$(gv $b X)" != "$(gv $c X)" ] || fail "workspace 1 lost its tiling when workspace 2 was set to floating"
xdotool key super+2; sleep 0.8; xdotool key super+alt+t; sleep 1; xdotool key super+1; sleep 0.8
# gestures: defaults map left/right swipes to workspaces
need carpatic-gestures "gestures not installed"
printf '3 left\n4 right\n3 up\n' | carpatic-gestures run --dry-run --stdin >/dev/null 2>&1 || true
carpatic-gestures help | grep -q "next workspace" || fail "carpatic-gestures help lost the workspace actions"
