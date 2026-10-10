# shellcheck shell=sh
# motionconf.sh: settings and theme colours shared by carpatic-intro and carpatic-screensaver (POSIX sh, sourced).
# Settings live in the configurator's settings.conf (KEY="value"), written only through carpatic-lib's set_setting when it exists.
#   INTRO=first-login-only|every-login|off     (default first-login-only)
#   SCREENSAVER=on|off  SCREENSAVER_MIN=<minutes>  SAVER_EFFECT=random|brand|rain|sunrise|stars   SAVER_ON_BATTERY=yes|no
#   MOTION=full|reduced        (reduced: no intro, no animated greeter, static screensaver screen)
CFG_DIR=${CARPATIC_CONFIG:-$HOME/.config/carpatic}
STATE_DIR=${CARPATIC_STATE:-$HOME/.local/state/carpatic}
SETTINGS=${SETTINGS:-$CFG_DIR/settings.conf}
CARPATIC_SHARE=${CARPATIC_SHARE:-/usr/local/share/carpatic/configurator}

m_get() { # key [default]   (pure shell: no sed/fork, this runs at every login)
  v=
  if [ -r "$SETTINGS" ]; then
    while IFS= read -r l; do case $l in "$1=\""*\") v=${l#*=\"}; v=${v%\"} ;; esac; done < "$SETTINGS"
  fi
  [ -n "$v" ] && printf '%s' "$v" || printf '%s' "${2:-}"
}
m_set() { # key value
  mkdir -p "$CFG_DIR"; tmp=$SETTINGS.$$
  { grep -v "^$1=" "$SETTINGS" 2>/dev/null; printf '%s="%s"\n' "$1" "$2"; } > "$tmp" && mv "$tmp" "$SETTINGS"
}
# Is motion reduced? settings, flag file, kernel command line (the same switch the boot splash obeys), or the accessibility setting
m_reduced() {
  [ "$(m_get MOTION full)" = reduced ] && return 0
  [ -e "$CFG_DIR/reduced-motion" ] && return 0
  grep -qw carpatic.reduced-motion /proc/cmdline 2>/dev/null && return 0
  return 1
}
# On battery? (no mains adapter reports online). Desktops without a battery are never "on battery".
m_on_battery() {
  bat=0; ac=0
  for p in ${CARPATIC_POWER_SUPPLY:-/sys/class/power_supply}/*; do
    [ -r "$p/type" ] || continue
    case $(cat "$p/type") in
      Battery) bat=1 ;;
      Mains|USB) [ "$(cat "$p/online" 2>/dev/null)" = 1 ] && ac=1 ;;
    esac
  done
  [ "$bat" = 1 ] && [ "$ac" = 0 ]
}
# Battery saver active? carpatic-power's profile "power-saver" (powerprofilesctl) when present
m_power_saver() {
  command -v powerprofilesctl >/dev/null 2>&1 && [ "$(powerprofilesctl get 2>/dev/null)" = power-saver ] && return 0
  [ "$(cat "$STATE_DIR/power-profile" 2>/dev/null)" = power-saver ] && return 0
  return 1
}
# Theme colours: sets M_ACCENT M_EMBER M_BG M_BGDEEP M_FG M_MUTED from the active theme (colors.toml), with the user's accent override.
m_theme_colors() {
  t=$(m_get THEME carpatic); f=
  for d in "${CARPATIC_THEME_DIR:-}" "$CFG_DIR/themes/$t" "$CARPATIC_SHARE/themes/$t" "$(dirname "$0")/../../configurator/themes/$t"; do
    [ -n "$d" ] && [ -f "$d/colors.toml" ] && { f=$d/colors.toml; break; }
  done
  tv() { [ -n "$f" ] && sed -n "s/^$1 *= *\"\(#[0-9a-fA-F]\{6\}\)\".*/\1/p" "$f" | head -1; }
  M_ACCENT=$(m_get ACCENT); [ -n "$M_ACCENT" ] || M_ACCENT=$(tv accent); [ -n "$M_ACCENT" ] || M_ACCENT='#5cc8a8'
  M_EMBER=$(tv orange);  [ -n "$M_EMBER" ]  || M_EMBER='#f2a65a'
  M_BG=$(tv background); [ -n "$M_BG" ]     || M_BG='#11151c'
  M_BGDEEP=$(tv darker_background); [ -n "$M_BGDEEP" ] || M_BGDEEP='#0b0e13'
  M_FG=$(tv foreground); [ -n "$M_FG" ]     || M_FG='#e7ecf3'
  M_MUTED=$(tv muted);   [ -n "$M_MUTED" ]  || M_MUTED='#6b778c'
  M_MODE=$(sed -n 's/^mode *= *"\(.*\)"/\1/p' "${f:-/dev/null}" | head -1); [ -n "$M_MODE" ] || M_MODE=dark
}
# m_lighten #rrggbb PERCENT : mix a colour toward white (for accents of light themes shown on a dark screen)
m_lighten() {
  c=${1#\#}; p=$2; r=$((0x${c%????})); g=$((0x$(echo "$c" | cut -c3-4))); b=$((0x${c#????}))
  printf '#%02x%02x%02x' $((r + (255 - r) * p / 100)) $((g + (255 - g) * p / 100)) $((b + (255 - b) * p / 100))
}
