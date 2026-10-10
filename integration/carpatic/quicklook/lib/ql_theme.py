"""Carpatic Quick Look: the look. Reads the active theme (palette), accent, corner radius and window-button style the same way the
rest of the desktop does (~/.config/carpatic/settings.conf + the theme's colors.toml). No GTK here: unit-testable."""
import os, re

CFG = os.environ.get("CARPATIC_CONFIG", os.path.expanduser("~/.config/carpatic"))
SHARE = os.environ.get("CARPATIC_SHARE", "/usr/local/share/carpatic/configurator")

DEFAULT = {"mode": "dark", "accent": "#5cc8a8", "selection": "#264743", "muted": "#6b778c", "background": "#11151c", "dark_background": "#171c25",
           "darker_background": "#0b0e13", "lighter_background": "#1e2430", "foreground": "#e7ecf3", "dark_foreground": "#6b778c",
           "light_foreground": "#a3aec0", "red": "#f0707a", "green": "#7bd389", "yellow": "#f2c25a", "blue": "#6cb4f0", "magenta": "#c39ae8",
           "cyan": "#5cc8a8", "orange": "#f2a65a"}

def _env(path):
    d = {}
    try:
        for line in open(path):
            m = re.match(r'\s*(\w+)\s*=\s*"?(.*?)"?\s*$', line)
            if m: d[m.group(1)] = m.group(2)
    except OSError:
        pass
    return d

def _toml(path):
    c = {}
    try:
        for line in open(path):
            m = re.match(r'\s*(\w+)\s*=\s*"([^"]*)"', line)
            if m: c[m.group(1)] = m.group(2)
    except OSError:
        pass
    return c

def settings():
    return _env(os.path.join(CFG, "settings.conf"))

def palette(s=None):
    s = s if s is not None else settings()
    theme = s.get("THEME", "carpatic")
    c = None
    for d in (os.path.join(CFG, "themes", theme), os.path.join(SHARE, "themes", theme)):
        if os.path.isfile(os.path.join(d, "colors.toml")):
            c = _toml(os.path.join(d, "colors.toml")); break
    p = dict(DEFAULT)
    if c: p.update(c)
    eff = ""
    try: eff = open(os.path.join(CFG, "current", "accent.effective")).read().strip()
    except OSError: pass
    acc = s.get("ACCENT") or eff
    if re.match(r"^#[0-9a-fA-F]{6}$", acc or ""): p["accent"] = acc
    return p

def lum(h):
    h = h.lstrip("#"); r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.299 * r + 0.587 * g + 0.114 * b

def look(s=None):
    """Everything the window needs: colours by role, radius, button style, whether the preview is enabled."""
    s = s if s is not None else settings()
    p = palette(s)
    dark = p.get("mode", "dark") == "dark" if "mode" in p else lum(p["background"]) < 128
    try: radius = max(0, min(20, int(s.get("CORNER_RADIUS", "0") or 0)))
    except ValueError: radius = 0
    acc = p["accent"]
    return {
        "dark": dark, "radius": radius, "buttons": s.get("WINDOW_BUTTONS", "windows") or "windows", "enabled": s.get("QUICKLOOK", "on") != "off",
        "bg": p["background"], "surface": p["dark_background"], "surface2": p["lighter_background"], "deep": p["darker_background"],
        "fg": p["foreground"], "muted": p.get("light_foreground", p["foreground"]), "subtle": p.get("muted", "#6b778c"),
        "accent": acc, "accent_fg": "#08241d" if lum(acc) > 140 else "#ffffff", "selection": p["selection"],
        "red": p["red"], "green": p["green"], "yellow": p["yellow"], "blue": p["blue"], "magenta": p["magenta"], "cyan": p.get("cyan", acc),
        "orange": p.get("orange", p["yellow"]),
        "paper": "#ffffff" if dark or True else p["background"],   # PDF pages stay white paper in both modes
    }

BUTTON_SIDE = {"macos": "left"}
def button_side(style):
    return BUTTON_SIDE.get(style, "right")
