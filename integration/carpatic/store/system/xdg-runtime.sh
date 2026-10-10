# Carpatic: make sure XDG_RUNTIME_DIR exists even without an elogind PAM session
# (Alpine tty autologin through busybox login). Needed by dbus, pipewire, flatpak portals.
if [ -z "${XDG_RUNTIME_DIR:-}" ] && [ "$(id -u)" -ne 0 ]; then
  XDG_RUNTIME_DIR="/tmp/runtime-$(id -u)"
  if [ ! -d "$XDG_RUNTIME_DIR" ]; then mkdir -p "$XDG_RUNTIME_DIR" 2>/dev/null && chmod 700 "$XDG_RUNTIME_DIR"; fi
  export XDG_RUNTIME_DIR
fi
