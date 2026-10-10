"""Reject foreign desktops; GUI tests use isolated displays."""
import os


def session_ok():
    e = os.environ
    if e.get("CARPATIC_FORCE") == "1" or e.get("CARPATIC_SESSION") == "1": return True
    if e.get("WAYLAND_DISPLAY"): return False
    return os.path.isdir("/usr/local/share/carpatic/configurator") or os.path.isdir("/usr/share/carpatic")


def require_session(name):
    if not session_ok():
        import sys
        sys.stderr.write(f"{name}: not inside a Carpatic session, nothing to do. (Set CARPATIC_FORCE=1 to run anyway.)\n")
        raise SystemExit(0)
