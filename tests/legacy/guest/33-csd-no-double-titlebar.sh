#!/bin/sh
# timeout: 120
# A GTK3 app that draws its own header bar (Eye of GNOME, Evince: _MOTIF_WM_HINTS decorations=0) gets NO second, dwm title bar; a plain terminal still gets one.
. /tmp/carpatic-rust-legacy/lib/x.sh
need eog "eog not installed"
cu() { sh -c "PATH=/usr/local/bin:/usr/bin:/bin HOME=/home/carpatic-rust-test DISPLAY=:98 XAUTHORITY=$XAUTHORITY $*"; }
tbabove() {
  # Rust owns a separate decoration window identified by its client property.
  # Its bottom overlaps the client border by two pixels; a geometry-only dwm
  # heuristic therefore misses a correctly attached Rust titlebar.
  client_hex=$(printf '0x%x' "$1")
  for candidate in $(xwininfo -root -tree | awk '/^[[:space:]]*0x[0-9a-f]+ / { print $1 }'); do
    owner=$(xprop -id "$candidate" _CARPATIC_CLIENT 2>/dev/null)
    case "$owner" in *"window id # $client_hex")
      info=$(xwininfo -id "$candidate")
      case "$info" in *"Map State: IsViewable"*) printf '%s\n' "$info" | sed -n 's/^[[:space:]]*Height: //p'; return;; esac
      ;;
    esac
  done
  echo 0
}

neutral_set drag_tiled '"float"'; sleep 2
t=$(spawn_st); [ "$(tbabove $t)" -gt 0 ] || fail "a terminal has no dwm title bar (is [titlebar] enabled?)"
img=$(find /usr/share -name '*.png' -size +10k 2>/dev/null | head -1)
cu "eog $img" >/dev/null 2>&1 &
i=0; while [ -z "$(xdotool search --class '^eog$' 2>/dev/null)" ] && [ $i -lt 30 ]; do sleep 1; i=$((i+1)); done
sleep 2; w=$(xdotool search --class '^eog$' | tail -1); [ -n "$w" ] || fail "eog did not open"
h=$(tbabove $w); pkill -x eog
[ "$h" = 0 ] || fail "eog got a dwm title bar ($h px) on top of its own header bar"
echo "ok   eog: no second title bar; terminal: title bar present"
