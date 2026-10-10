#!/bin/sh
# Carpathian dwm autostart. Installed to ~/.local/share/dwm-titus/scripts/autostart.sh
# Each helper is optional; missing programs are skipped.
once() { command -v "$1" >/dev/null 2>&1 || return 0; pgrep -u "$(id -u)" -x "$1" >/dev/null 2>&1 || "$@" >/dev/null 2>&1 & }

xset s off -dpms 2>/dev/null
# Thunar's zoom, icon sizes and first window size follow the display scale. They live in xfconf, which needs the session bus: the early sync in ~/.xinitrc has none yet.
if command -v carpatic-thunar >/dev/null 2>&1 && command -v carpatic-scale >/dev/null 2>&1; then
  _ts=$(carpatic-scale effective 2>/dev/null)
  [ "$(cat "$HOME/.config/carpatic/thunar-scale" 2>/dev/null)" = "$_ts" ] || { carpatic-thunar >/dev/null 2>&1 && echo "$_ts" > "$HOME/.config/carpatic/thunar-scale"; } &
fi
# display scale: older ~/.xinitrc files do not call this; it is a no-op when the scale is already right (configurator/bin/carpatic-scale)
command -v carpatic-scale >/dev/null 2>&1 && carpatic-scale sync >/dev/null 2>&1
xsetroot -solid '#0b0e13' 2>/dev/null
# login animation (motion/): waits (max 1.5 s) until its first frame (the colour of the line above) covers the screen, so the wallpaper loads UNDER it; skips itself when off / reduced motion / slow screen
command -v carpatic-intro >/dev/null 2>&1 && carpatic-intro auto --wait >/dev/null 2>&1
# wallpaper via feh (sets _XROOTPMAP_ID, which picom needs; plain xsetroot -solid shows black under picom)
WP=/usr/share/backgrounds/carpatic/bucegi-dark.jpg
[ -f "$WP" ] || WP=/usr/local/share/carpatic/wallpaper.png
[ -f "$HOME/.config/carpatic/wallpaper" ] && WP=$(cat "$HOME/.config/carpatic/wallpaper")
[ -f "$WP" ] && feh --no-fehbg --bg-fill "$WP" 2>/dev/null
# The Rust session owns its compositor and animation settings.
if [ "${CARPATIC_SESSION:-0}" = 1 ] && command -v carpatic-animations >/dev/null 2>&1; then
  carpatic-animations apply >/dev/null 2>&1
else
  [ -f "$HOME/.config/carpatic/compositor" ] && once picom
fi
# This foreground helper becomes the file desktop; the session bus owns its
# lifetime. Wait for WM publication rather than racing an early login.
if command -v carpatic-desktop >/dev/null 2>&1 && [ ! -e "$HOME/.config/carpatic/desktop-files-disabled" ]; then
  (
    tries=0
    while ! xprop -root _NET_SUPPORTING_WM_CHECK 2>/dev/null | grep -q 'window id'; do
      tries=$((tries+1)); [ "$tries" -lt 50 ] || exit 1
      sleep .1
    done
    exec carpatic-desktop
  ) &
fi
once dunst
# One per-store notifier lock serializes overlapping starts. The private login
# bus closes on logout, including when the reminder queue is empty.
if [ "${CARPATIC_SESSION:-0}" = 1 ] && [ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ] && command -v carpatic-reminders >/dev/null 2>&1; then
  carpatic-reminders notify-service &
fi
# authentication dialogs for pkexec / udisks / NetworkManager / Settings (without an agent they fail silently)
for agent in /usr/lib/polkit-gnome/polkit-gnome-authentication-agent-1 /usr/libexec/polkit-mate-authentication-agent-1 /usr/bin/lxqt-policykit-agent; do
  [ -x "$agent" ] || continue
  pgrep -u "$(id -u)" -f "$agent" >/dev/null 2>&1 || "$agent" >/dev/null 2>&1 &
  break
done
# network + bluetooth tray applets (shown by tint2's systray or dwm's built-in systray)
# (carpatic-applets keeps them alive and re-docks them whenever the tray appears or restarts)
pgrep -u "$(id -u)" -f 'carpatic-applets watch' >/dev/null 2>&1 || carpatic-applets watch >/dev/null 2>&1 &
# removable media: mount USB sticks, SD cards, phones when plugged in, tell the user, offer eject from the tray
command -v udiskie >/dev/null 2>&1 && { pgrep -u "$(id -u)" -f '/udiskie( |$)' >/dev/null 2>&1 || udiskie --automount --notify --smart-tray --file-manager thunar $( [ -f /etc/carpatic/udiskie.yml ] && echo "--config /etc/carpatic/udiskie.yml" ) >/dev/null 2>&1 & }
# tell the user when updates are waiting or a restart is needed (reads what carpatic-update left in /run; never installs)
command -v carpatic-update >/dev/null 2>&1 && { pgrep -u "$(id -u)" -f 'carpatic-update watch' >/dev/null 2>&1 || carpatic-update watch >/dev/null 2>&1 & }
# accessibility switches the user turned on (sticky keys, screen reader, on-screen keyboard) come back at every login
# touchpad: saved tap/scroll settings and gestures, re-applied when a pad is plugged in
command -v carpatic-touchpad >/dev/null 2>&1 && { carpatic-touchpad apply >/dev/null 2>&1; pgrep -u "$(id -u)" -f 'carpatic-touchpad watch' >/dev/null 2>&1 || carpatic-touchpad watch >/dev/null 2>&1 & }
# monitors: set up screens when they are plugged in or removed
command -v carpatic-display >/dev/null 2>&1 && { pgrep -u "$(id -u)" -f 'carpatic-display watch' >/dev/null 2>&1 || carpatic-display watch >/dev/null 2>&1 & }
# input method (fcitx5/ibus) when the user chose one
command -v carpatic-input-method >/dev/null 2>&1 && carpatic-input-method session &
command -v carpatic-a11y >/dev/null 2>&1 && carpatic-a11y session >/dev/null 2>&1 &
# idle lock (10 min) and screen blanking
if [ "${CARPATIC_DEBUG_SESSION:-0}" = 1 ]; then
    xset s off 2>/dev/null || :
    xset -dpms 2>/dev/null || :
else
    carpatic-idle start >/dev/null 2>&1 &
fi
# screensaver (motion/): starts before the lock timeout, ends when the lock screen appears
[ "${CARPATIC_DEBUG_SESSION:-0}" = 1 ] || { command -v carpatic-screensaver >/dev/null 2>&1 && carpatic-screensaver watch >/dev/null 2>&1 & }
# audio: pipewire graph, session manager, PulseAudio compatibility (needed by Flatpak apps)
once pipewire
once wireplumber
once pipewire-pulse
# wireplumber exits when it starts before PipeWire's socket exists (seen on a fresh install: no default sound device, volume keys dead): look again once
( sleep 6; once pipewire; once wireplumber; once pipewire-pulse ) >/dev/null 2>&1 &
# When a configurator profile uses an external bar (tint2), carpatic-session owns the tray and status text
BAR=dwm
[ -f "$HOME/.config/carpatic/profile.env" ] && BAR=$(. "$HOME/.config/carpatic/profile.env" >/dev/null 2>&1; echo "${BAR:-dwm}")
# system tray: dwm's built-in systray (nothing to start); tint2 profiles use tint2's own tray
# status text in dwm's bar (root window name)
[ "$BAR" = tint2 ] || [ "$BAR" = panel ] || pgrep -u "$(id -u)" -f "^(/bin/)?sh [^ ]*carpatic-status\$" >/dev/null 2>&1 || "$(dirname "$0")/carpatic-status" >/dev/null 2>&1 &
# Carpathian configurator: per-profile bars, hotkey daemon, first-run Welcome wizard
command -v carpatic-session >/dev/null 2>&1 && carpatic-session start >/dev/null 2>&1 &
