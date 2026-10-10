"""Mini desktop previews drawn with cairo from the real state files: the style's bar/dock layout, window title buttons, fonts, icon theme.
Used by the Appearance style gallery, the live preview and the window look pages."""
import os, math
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Pango", "1.0"); gi.require_version("PangoCairo", "1.0"); gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, Gdk, Pango, PangoCairo, GdkPixbuf
from . import sysutil as su, theme

def rgb(h):
    return tuple(v / 255 for v in theme._rgb(h))

def profile_conf(prof, key, default=""):
    try:
        with open(os.path.join(su.SHARE, "profiles", f"{prof}.conf")) as f:
            for line in f:
                if line.startswith(key + "="): return line.split("=", 1)[1].split("#")[0].strip().strip('"')
    except OSError: pass
    return default

def is_pack(prof):
    return profile_conf(prof, "STYLEPACK") == prof

_wp_cache = {}
def wallpaper(path, w, h):
    key = (path, w, h)
    if key not in _wp_cache:
        try: _wp_cache[key] = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, w, h, False) if path else None
        except Exception: _wp_cache[key] = None
    return _wp_cache[key]

def current_wallpaper():
    try:
        with open(os.path.join(su.CFG, "wallpaper")) as f: return f.read().strip()
    except OSError: return ""

# (the mock desktops of the style and theme galleries come from configurator/lib/carpatic_looks.py, the same renderer as the keyboard theme picker)
