#!/bin/sh
# Install the Carpathian motion pieces (login animation, screensaver, installer greeter animation, boot helpers, Settings page) into a running system
# or into a target tree. Idempotent. Usage: install.sh [--root DIR]
# Paths: programs -> /usr/local/bin, shared files -> /usr/local/share/carpatic/motion, Settings page -> next to carpatic_ui.py of the configurator.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd); ROOT=; [ "${1:-}" = --root ] && ROOT=$2
r() { echo "$ROOT$1"; }
mkdir -p "$(r /usr/local/bin)" "$(r /usr/local/share/carpatic/motion)"
for b in carpatic-intro carpatic-screensaver carpatic-greeter-anim carpatic-boot carpatic-set-motion carpatic-animations; do install -m 755 "$HERE/bin/$b" "$(r /usr/local/bin/$b)"; done
for f in window_animations.py animation_preview.py; do install -m644 "$HERE/lib/$f" "$(r /usr/local/share/carpatic/motion/$f)"; done
for f in ttylib.sh motionconf.sh logo-frames.awk saver.awk logo.txt; do install -m 644 "$HERE/lib/$f" "$(r /usr/local/share/carpatic/motion/$f)"; done
# the native intro player: built here (needs gcc, libx11-dev, libxext-dev) unless a binary is already there; the apk builds it at package time
if [ ! -x "$HERE/src/carpatic-intro-play" ]; then make -C "$HERE/src" >/dev/null 2>&1 || echo "carpatic-motion: could not build carpatic-intro-play (install gcc libx11-dev libxext-dev); the login animation stays off" >&2; fi
[ -x "$HERE/src/carpatic-intro-play" ] && install -m 755 "$HERE/src/carpatic-intro-play" "$(r /usr/local/bin/carpatic-intro-play)"
# the Settings page lives where carpatic_system_pages.py is installed (the configurator's python dir); fall back to the shared dir
GUI=$(r /usr/local/lib/carpatic); for d in "$ROOT"/usr/local/lib/carpatic "$ROOT"/usr/local/share/carpatic/configurator/lib "$ROOT"/usr/local/lib/carpatic-configurator; do [ -f "$d/carpatic_ui.py" ] && GUI=$d; done
mkdir -p "$GUI"; install -m 644 "$HERE/gui/carpatic_motion_pages.py" "$GUI/carpatic_motion_pages.py"
echo "carpatic-motion installed${ROOT:+ into $ROOT}"
