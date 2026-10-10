# Sourced by desktop title-bar guest tests (on top of lib/x.sh).
. /tmp/carpatic-rust-legacy/lib/x.sh
need xwininfo "apk add xwininfo"; need xprop "apk add xprop"
# tbinfo <win>: prints "id x y w h" of the title bar directly above content window <win> (empty if none)
tbinfo() {
  for id in $(xwininfo -root -tree | awk '/(has no name)/{print $1}'); do
    client=$(xprop -id "$id" _CARPATIC_CLIENT 2>/dev/null | sed -n 's/.*# *//p')
    [ -n "$client" ] || continue
    [ "$((client))" = "$1" ] || continue
    eval "$(xdotool getwindowgeometry --shell "$id")"
    printf '%s %s %s %s %s\n' "$id" "$X" "$Y" "$WIDTH" "$HEIGHT"; return
  done
}
# tbclick <win> <min|max|close> [ignored]: click that button wherever the active style put it
tbclick() {
  _tw=$1; _tb=$2
  _ti=$(tbinfo "$_tw"); [ -n "$_ti" ] || fail "no title bar above window $_tw"
  set -- $_ti; _tid=$1; _tx=$2; _ty=$3; _th=$5
  _tp=$(xprop -id "$_tid" _CARPATIC_BUTTONS 2>/dev/null | sed 's/.*= //; s/,//g'); [ -n "$_tp" ] || fail "no _CARPATIC_BUTTONS on title bar $_tid"
  set -- $_tp
  case "$_tb" in min) _x0=$1; _x1=$2;; max) _x0=$3; _x1=$4;; close) _x0=$5; _x1=$6;; esac
  [ "$_x1" -gt "$_x0" ] || fail "button $_tb is not visible (range $_x0-$_x1)"
  clear_toasts
  xdotool mousemove $(( _tx + (_x0 + _x1) / 2 )) $(( _ty + _th / 2 )); sleep 0.4; xdotool click 1; sleep 1
}
# tbcfg key=value ...: edit [titlebar] in the user's themes.toml (live reload)
tbcfg() {
  mkdir -p "$UCFG"; [ -f "$UCFG/themes.toml" ] || cp "$DCFG" "$UCFG/themes.toml"
  for kv in "$@"; do k=${kv%%=*}; v=${kv#*=}
    if sed -n '/^\[titlebar\]/,/^\[/p' "$UCFG/themes.toml" | grep -q "^$k *="; then
      sed -i "/^\[titlebar\]/,/^\[/ s|^$k *=.*|$k = $v|" "$UCFG/themes.toml"
    else sed -i "s|^\[titlebar\]|[titlebar]\n$k = $v|" "$UCFG/themes.toml"; fi
  done
  chown -R carpatic-rust-test "$UCFG"; sleep 2.5
}
mapped() { xwininfo -id "$1" 2>/dev/null | grep -q "Map State: IsViewable" && [ "$(gv "$1" X)" -ge 0 ]; }
