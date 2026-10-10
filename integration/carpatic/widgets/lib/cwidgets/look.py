"""Palette and style ("look") of the cards, derived from the active Carpathian theme and desktop style. Pure Python, no GTK."""
import os, re
from . import conf

SYS_THEMES = os.environ.get("CARPATIC_SHARE", "/usr/local/share/carpatic/configurator") + "/themes"


def hex2rgb(h):
    h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def rgb2hex(c):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v * 255))) for v in c)


def mix(a, b, t):
    """t = 0 gives a, t = 1 gives b (both '#rrggbb')."""
    x, y = hex2rgb(a), hex2rgb(b); return rgb2hex(tuple(p + (q - p) * t for p, q in zip(x, y)))


def luminance(h):
    def f(v): return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (f(v) for v in hex2rgb(h)); return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = luminance(a), luminance(b); hi, lo = max(la, lb), min(la, lb); return (hi + 0.05) / (lo + 0.05)


def ensure_contrast(fg, bg, ratio=4.5):
    """Move fg away from bg (towards black or white) until the WCAG ratio holds."""
    if contrast(fg, bg) >= ratio: return fg
    target = "#ffffff" if luminance(bg) < 0.4 else "#000000"
    for i in range(1, 21):
        c = mix(fg, target, i / 20)
        if contrast(c, bg) >= ratio: return c
    return target


def read_toml_colors(path):
    c = {}
    try:
        for line in open(path):
            m = re.match(r'\s*(\w+)\s*=\s*"([^"]*)"', line)
            if m: c[m.group(1)] = m.group(2)
    except OSError: pass
    return c


def read_env(path):
    d = {}
    try:
        for line in open(path):
            m = re.match(r'\s*(\w+)="?(.*?)"?\s*$', line)
            if m: d[m.group(1)] = m.group(2)
    except OSError: pass
    return d


def theme_file(theme):
    for base in (os.path.join(conf.CFG, "themes"), SYS_THEMES):
        p = os.path.join(base, theme, "colors.toml")
        if os.path.isfile(p): return p
    return ""


FALLBACK = {"mode": "dark", "background": "#11151c", "dark_background": "#171c25", "lighter_background": "#1e2430", "foreground": "#e7ecf3",
            "accent": "#5cc8a8", "green": "#7bd389", "yellow": "#f2c25a", "red": "#f0707a", "blue": "#6cb4f0"}


def palette(theme, accent=""):
    """Roles used by every card. Text roles are forced to AA contrast against the card, whatever the theme says."""
    c = dict(FALLBACK); c.update(read_toml_colors(theme_file(theme)) if theme_file(theme) else {})
    card = c["dark_background"]; fg = c["foreground"]
    acc = accent if re.fullmatch(r"#[0-9a-fA-F]{6}", accent or "") else c["accent"]
    acc = ensure_contrast(acc, card, 3.0)
    p = dict(mode=c.get("mode", "dark"), bg=c["background"], card=card, card2=c["lighter_background"], fg=ensure_contrast(fg, card, 7.0),
             accent=acc, accent_fg=("#0b0e13" if contrast("#0b0e13", acc) >= contrast("#ffffff", acc) else "#ffffff"))
    p["muted"] = ensure_contrast(mix(p["fg"], card, 0.32), card, 4.5)
    p["subtle"] = ensure_contrast(mix(p["fg"], card, 0.5), card, 3.0)    # decoration and large figures only, never small text
    p["border"] = mix(card, p["fg"], 0.16 if luminance(card) < 0.4 else 0.28)    # light cards need a clearer edge against bright wallpapers
    p["ok"], p["warn"], p["bad"] = (ensure_contrast(c.get(k, FALLBACK[k]), card, 3.0) for k in ("green", "yellow", "red"))
    p["info"] = ensure_contrast(c.get("blue", FALLBACK["blue"]), card, 3.0)
    return p


# radius, card opacity with a compositor (1 without), border, header style, shadow, font role
LOOKS = {
    "macos":   dict(radius=18, alpha=0.78, border=0.10, pad=16, head="plain", shadow=True,  caps=False, flat=False, font="Inter", head_font="Inter", elev=0.05),
    "windows": dict(radius=8,  alpha=0.88, border=0.12, pad=14, head="icon",  shadow=True,  caps=False, flat=False, font="Inter", head_font="Inter", elev=0.06),
    "ubuntu":  dict(radius=12, alpha=0.94, border=0.08, pad=14, head="bar",   shadow=False, caps=False, flat=True,  font="Cantarell", head_font="Cantarell"),
    "tiling":  dict(radius=0,  alpha=1.0,  border=0.40, pad=10, head="mono",  shadow=False, caps=False, flat=True,  font="JetBrains Mono", head_font="JetBrains Mono"),
    "nothing": dict(radius=22, alpha=1.0,  border=0.20, pad=16, head="dots",  shadow=False, caps=True,  flat=True,  font="Noto Sans Mono", head_font="Doto"),
}
PROFILE_LOOK = {"macos": "macos", "windows": "windows", "beginner": "windows", "ubuntu": "ubuntu", "tiling": "tiling"}


def pick_look(setting, theme, profile):
    if setting in LOOKS: return setting
    if (theme or "").startswith("nothing"): return "nothing"
    return PROFILE_LOOK.get(profile, "windows")


def current(layout=None):
    """Everything the host needs to paint: palette, look parameters, ui font. Reads settings.conf fresh each call (cheap, only on change)."""
    s = read_env(os.path.join(conf.CFG, "settings.conf"))
    theme = s.get("THEME", "carpatic"); name = pick_look((layout or {}).get("look", "auto"), theme, s.get("PROFILE", ""))
    lk = dict(LOOKS[name]); lk["name"] = name; lk.setdefault("elev", 0)
    if s.get("FONT_UI") and name not in ("nothing",): lk["font"] = s["FONT_UI"]
    if name == "tiling" and s.get("FONT_MONO"): lk["font"] = lk["head_font"] = s["FONT_MONO"]
    if name == "nothing" and s.get("FONT_UI"): lk["font"] = s["FONT_UI"]
    return palette(theme, s.get("ACCENT", "")), lk, s
