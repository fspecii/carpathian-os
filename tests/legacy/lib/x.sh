# Sourced by desktop guest tests (run as root; talks to carpatic's X session).
. /tmp/carpatic-rust-legacy/lib/guest.sh
need Xorg "desktop not installed"; need carpatic-wm "desktop not installed"; need xdotool "apk add xdotool"; need xterm "terminal not installed"
running Xorg || fail "Xorg installed but not running (session did not start)"
running carpatic-wm || fail "dwm installed but not running"
export DISPLAY=:98 GDK_BACKEND=x11 CARPATIC_SESSION=1
unset WAYLAND_DISPLAY XAUTHORITY
stwins() { xdotool search --class '^XTerm$' 2>/dev/null; }
geom() { xdotool getwindowgeometry --shell "$1" | tr '\n' ' '; }
# gv <win> <X|Y|WIDTH|HEIGHT>
gv() { xdotool getwindowgeometry --shell "$1" | sed -n "s/^$2=//p"; }
# clear_toasts: dismiss notification pop-ups (the "Connection Established" toast right after boot sits in the top-right corner, over the title-bar buttons, and swallows clicks)
clear_toasts() { command -v dunstctl >/dev/null 2>&1 && dunstctl close-all >/dev/null 2>&1 || :; }
closeall() { pkill -x xterm; i=0; while [ -n "$(stwins)" ] && [ $i -lt 10 ]; do sleep 0.5; i=$((i+1)); done; }
# spawn_st: Super+Shift+Return, wait for a new st window, echo its id
spawn_st() {
  before=$(stwins | wc -l)
  xdotool key super+shift+Return
  i=0; while [ "$(stwins | wc -l)" -le "$before" ] && [ $i -lt 20 ]; do sleep 0.5; i=$((i+1)); done
  [ "$(stwins | wc -l)" -gt "$before" ] || fail "Super+Shift+Return did not open a terminal"
  sleep 1; xdotool getwindowfocus
}
drag() { # drag <button> <x> <y> <dx> <dy> with Super held
  xdotool mousemove "$2" "$3" keydown super mousedown "$1"
  xdotool mousemove_relative -- "$4" "$5"; xdotool mousemove_relative -- "$4" "$5"
  xdotool mouseup "$1" keyup super; sleep 1
}
[ -f /tmp/carpatic-rust-legacy/lib/neutral.sh ] && { . /tmp/carpatic-rust-legacy/lib/neutral.sh; neutral_on; trap 'neutral_off; closeall' EXIT; } || trap closeall EXIT
closeall
clear_toasts
