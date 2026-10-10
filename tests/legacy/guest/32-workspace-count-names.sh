#!/bin/sh
# timeout: 240
# Number of workspaces and their names (Settings > Desktop & Dock > Workspaces, carpatic-appearance set workspaces / workspace-names): dwm applies them live,
# next/previous wraps at the new count, windows from removed workspaces move to the last one, the pager follows.
. /tmp/carpatic-rust-legacy/lib/x.sh
cu() { sh -c "PATH=/usr/local/bin:/usr/bin:/bin:/sbin:/usr/sbin HOME=/home/carpatic-rust-test DISPLAY=:98 XAUTHORITY=$XAUTHORITY $*"; }
cur() { xprop -root _NET_CURRENT_DESKTOP | sed 's/.*= *//'; }
n() { xprop -root _NET_NUMBER_OF_DESKTOPS | sed 's/.*= *//'; }
trap 'cu carpatic-appearance set workspaces default workspace-names default >/dev/null 2>&1; closeall' EXIT
xdotool key super+1; sleep 0.8
cu carpatic-appearance set workspaces 3 workspace-names Web,Code,Music >/dev/null 2>&1; sleep 5
[ "$(n)" = 3 ] || fail "workspaces=3 not applied (dwm reports $(n))"
xprop -root _NET_DESKTOP_NAMES | grep -q '"Web", "Code", "Music"' || fail "names not published: $(xprop -root _NET_DESKTOP_NAMES)"
xdotool key ctrl+alt+Left; sleep 0.8; [ "$(cur)" = 2 ] || fail "Ctrl+Alt+Left from workspace 1 should wrap to 3 (is $(cur)+1)"
xdotool key ctrl+alt+Right; sleep 0.8; [ "$(cur)" = 0 ] || fail "Ctrl+Alt+Right from workspace 3 should wrap to 1"
xdotool key super+7; sleep 0.8; [ "$(cur)" = 0 ] || fail "Super+7 should do nothing with 3 workspaces"
# a window on workspace 9 (created while 9 existed) is not lost when the count drops: it moves to the last workspace
cu carpatic-appearance set workspaces 9 >/dev/null 2>&1; sleep 4; xdotool key super+8; sleep 0.8
w=$(spawn_st); [ "$(xprop -id $w _NET_WM_DESKTOP | sed 's/.*= *//')" = 7 ] || fail "test window is not on workspace 8"
cu carpatic-appearance set workspaces 3 >/dev/null 2>&1; sleep 4
[ "$(xprop -id $w _NET_WM_DESKTOP | sed 's/.*= *//')" = 2 ] || fail "window from a removed workspace did not move to workspace 3 ($(xprop -id $w _NET_WM_DESKTOP))"
xdotool key super+1; sleep 0.5
