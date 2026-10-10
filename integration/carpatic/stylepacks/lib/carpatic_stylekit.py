"""carpatic_stylekit: tiny shared helpers of the style-pack GTK programs (carpatic-startmenu, carpatic-sidebar): config files, palette tokens, CSS recipes.
Pure python, no GTK import, so the host tests can run it without a display. MIT."""
import json, os, re, subprocess, time

HOME = os.path.expanduser("~")
SHARE = os.environ.get("CARPATIC_SHARE", "/usr/local/share/carpatic/configurator")
CFG = os.environ.get("CARPATIC_CONFIG", os.path.join(HOME, ".config/carpatic"))
STATE = os.environ.get("CARPATIC_STATE", os.path.join(HOME, ".local/state/carpatic"))

# ---------------------------------------------------------------- pure data helpers (unit-tested on the host without a display)

def read_kv(path):
    """KEY="value" (quoted values may hold # and spaces) or KEY=value, one per line; comments after an unquoted value are dropped"""
    d = {}
    try:
        for line in open(path):
            m = re.match(r'\s*([A-Za-z0-9_]+)\s*=\s*(?:"([^"]*)"|([^\s#]*))', line)
            if m:
                d[m.group(1)] = m.group(2) if m.group(2) is not None else m.group(3)
    except OSError:
        pass
    return d

def theme_colors(theme=None, accent=None):
    s = read_kv(os.path.join(CFG, "settings.conf"))
    theme = theme or s.get("THEME", "carpatic")
    accent = accent if accent is not None else s.get("ACCENT", "")
    c = {}
    for base in (os.path.join(CFG, "themes", theme), os.path.join(SHARE, "themes", theme)):
        p = os.path.join(base, "colors.toml")
        if os.path.isfile(p):
            c = read_kv(p)
            break
    if accent:
        c["accent"] = accent
    return c

def _rgb(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]

def mix(a, b, p):
    ra, rb = _rgb(a), _rgb(b)
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * p / 100) for x, y in zip(ra, rb))

def lum(h):
    r, g, b = _rgb(h)
    return 0.299 * r + 0.587 * g + 0.114 * b

def palette(c):
    """derived tokens (same recipe as carpatic-render): surface = window colour, base = panel/list colour"""
    g = lambda k, d: c.get(k) or d
    p = {
        "mode": g("mode", "dark"),
        "accent": g("accent", "#5cc8a8"),
        "surface": g("background", "#222222"),
        "base": g("dark_background", g("background", "#222222")),
        "fg": g("foreground", "#ffffff"),
        "muted": g("dark_foreground", "#888888"),
        "line": g("lighter_background", "#444444"),
    }
    p["accent_fg"] = "#08241d" if lum(p["accent"]) > 140 else "#ffffff"
    light = p["mode"] == "light"
    p["hover"] = mix(p["surface"], p["fg"], 8 if light else 10)
    p["press"] = mix(p["surface"], p["fg"], 14 if light else 18)
    p["tint"] = mix(p["surface"], p["accent"], 16 if light else 22)
    p["line"] = mix(p["surface"], p["fg"], 14 if light else 18)
    return p

