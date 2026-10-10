# shellcheck shell=bash
# ttylib.sh: terminal helpers shared by the Carpathian greeter and screensaver animations (bash 4+; sourced, no side effects on load).
#   ttl_open        open the tty, hide the cursor, stop echo, remember the old settings, install the restore trap, watch for resize
#   ttl_close       restore everything (also runs on EXIT, INT, TERM, HUP): `stty sane`, attributes off, cursor on
#   ttl_sleep SEC   sleep without forking (a timed read on a pipe that never gets data)
#   ttl_key SEC     wait up to SEC seconds for one key on the tty: sets TTL_KEY ("" = Return, "other" = anything else, "eof" = tty closed), returns 0; returns 1 on timeout
#   ttl_size        sets TTL_ROWS TTL_COLS from the tty (falls back to LINES/COLUMNS/24x80)
#   TTL_RESIZED     set to 1 by SIGWINCH; the caller clears it after redrawing
TTL_RESIZED=0
TTL_OPEN=0
ttl_size() {
  local s
  s=$(stty size 2>/dev/null </dev/tty) || s=""
  TTL_ROWS=${s%% *}; TTL_COLS=${s##* }
  [[ $TTL_ROWS =~ ^[0-9]+$ && $TTL_ROWS -gt 0 ]] || TTL_ROWS=${LINES:-24}
  [[ $TTL_COLS =~ ^[0-9]+$ && $TTL_COLS -gt 0 ]] || TTL_COLS=${COLUMNS:-80}
}
ttl_open() {
  TTL_STTY=$(stty -g 2>/dev/null </dev/tty) || TTL_STTY=""
  exec {TTL_NULLFD}<> <(:)                 # a pipe nobody writes to: `read -t` on it is a sleep builtin
  exec {TTL_TTYFD}</dev/tty 2>/dev/null || TTL_TTYFD=
  stty -echo -icanon min 1 time 0 </dev/tty 2>/dev/null || true
  printf '\033[?25l' >/dev/tty 2>/dev/null || printf '\033[?25l'
  TTL_OPEN=1
  trap 'TTL_RESIZED=1' WINCH
  trap 'ttl_close; exit 130' INT TERM HUP
  trap 'ttl_close' EXIT
  ttl_size
}
ttl_close() {
  [[ $TTL_OPEN == 1 ]] || return 0
  TTL_OPEN=0
  # a killed animation can leave the tty raw / without echo: put it back (this once broke the gum prompts after the greeter in Omarchy)
  stty sane </dev/tty 2>/dev/null || true
  [[ -n ${TTL_STTY:-} ]] && stty "$TTL_STTY" </dev/tty 2>/dev/null || true
  printf '\033[0m\033[?25h' >/dev/tty 2>/dev/null || printf '\033[0m\033[?25h'
}
ttl_sleep() { read -r -t "$1" -u "$TTL_NULLFD" _ 2>/dev/null || true; }
ttl_key() {   # wait up to $1 s (sleeping on the null pipe, so a key never gets swallowed by a timed tty read); Return -> TTL_KEY="", other -> "other"
  local k="" rc fd=${TTL_TTYFD:-0}
  if ! read -r -t 0 -u "$fd" 2>/dev/null; then
    ttl_sleep "$1"
    read -r -t 0 -u "$fd" 2>/dev/null || return 1
  fi
  IFS= read -rsn1 -t 1 -u "$fd" k; rc=$?
  if [[ -n $k ]]; then TTL_KEY=other; elif (( rc == 0 )); then TTL_KEY=""; else TTL_KEY=eof; fi   # eof: the tty went away (treated like Return)
  return 0
}

# ttl_awk: pick the fastest awk (sets AWK, AWK_OPTS, AWK_SLOW). Alpine's default awk is busybox's, which is 10 to 30 times slower than mawk on these frame generators
# (measured: 400 saver frames cost 3 to 9 s of CPU there, 0.2 s with mawk). Sets AWK and AWK_SLOW (1 = busybox: callers lower their frame rate).
ttl_awk() {
  AWK=; AWK_SLOW=0; AWK_OPTS=
  local c
  for c in mawk gawk awk; do command -v "$c" >/dev/null 2>&1 && { AWK=$c; break; }; done
  [[ -n $AWK ]] || AWK=awk
  [[ $(basename "$(readlink -f "$(command -v "$AWK")")") == busybox* ]] && AWK_SLOW=1
  [[ $AWK == mawk ]] && AWK_OPTS='-W interactive'      # mawk otherwise waits for a full input block before it sees a frame tick
  return 0
}
