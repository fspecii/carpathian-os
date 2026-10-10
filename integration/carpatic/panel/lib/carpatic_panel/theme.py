"""Colours and metrics for every panel surface, derived from the active palette (colors.toml) and the accent.

Roles follow docs/DESIGN-SYSTEM.md (bg, surface, surface_2, fg, fg_muted, accent ...). All colours are (r, g, b, a) floats so the same
theme object feeds cairo directly. `Theme.load()` reads the configurator state; `Theme.from_palette()` is what tests use."""
import os, re

RADIUS = {"xs": 4, "sm": 6, "md": 10, "lg": 14, "full": 999}      # design system radius scale
SP = {"1": 2, "2": 4, "3": 8, "4": 12, "5": 16, "6": 24, "7": 32}  # 4 px grid
MOTION = {"fast": 120, "base": 200, "slow": 320}                    # ms

DEFAULT_DARK = dict(mode="dark", accent="#5cc8a8", background="#11151c", dark_background="#171c25", darker_background="#0b0e13",
                    lighter_background="#1e2430", foreground="#e7ecf3", light_foreground="#a3aec0", dark_foreground="#6b778c",
                    red="#f0707a", green="#7bd389", yellow="#f2c25a", blue="#6cb4f0", orange="#f2a65a")
DEFAULT_LIGHT = dict(mode="light", accent="#16806a", background="#f6f7f9", dark_background="#ffffff", darker_background="#e9ecf1",
                     lighter_background="#eef1f5", foreground="#172029", light_foreground="#4e5b6c", dark_foreground="#7a8696",
                     red="#c8323f", green="#1f8f4e", yellow="#a86a00", blue="#1e6fb8", orange="#c0661a")


def hex2rgb(h, a=1.0):
    h = h.lstrip("#")
    if len(h) == 3: h = "".join(c * 2 for c in h)
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255, a)


def with_alpha(c, a):
    return (c[0], c[1], c[2], a)


def mix(a, b, t):
    """t = 0 -> a, t = 1 -> b (opaque result)."""
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t, 1.0)


def luminance(c):
    def f(v): return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def parse_toml_colors(path):
    c = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                m = re.match(r'\s*(\w+)\s*=\s*"([^"]*)"', line)
                if m: c[m.group(1)] = m.group(2)
    except OSError:
        pass
    return c


def read_env(path):
    d = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                m = re.match(r'\s*(?:export\s+)?(\w+)="?(.*?)"?\s*(?:#.*)?$', line)
                if m: d[m.group(1)] = m.group(2)
    except OSError:
        pass
    return d


class Theme:
    """All colours a panel surface needs. `dark` is true for dark palettes."""

    def __init__(self, pal, accent=None, font="Inter", scale=1.0):
        self.pal = pal
        self.dark = pal.get("mode", "dark") != "light"
        g = lambda k, d: hex2rgb(pal.get(k, d))
        self.bg = g("background", "#11151c")
        self.deep = g("darker_background", "#0b0e13")
        self.surface = g("dark_background", "#171c25")
        self.surface2 = g("lighter_background", "#1e2430")
        self.fg = g("foreground", "#e7ecf3")
        self.fg_muted = mix(self.surface, self.fg, 0.68)
        self.fg_subtle = mix(self.surface, self.fg, 0.42)
        self.accent = hex2rgb(accent or pal.get("accent", "#5cc8a8"))
        self.accent_fg = (0.03, 0.14, 0.11, 1) if luminance(self.accent) > 0.32 else (1, 1, 1, 1)
        self.danger = g("red", "#f0707a"); self.success = g("green", "#7bd389"); self.warning = g("yellow", "#f2c25a")
        self.info = g("blue", "#6cb4f0"); self.ember = g("orange", "#f2a65a")
        self.border = with_alpha(self.fg, 0.12 if self.dark else 0.14)
        self.border_strong = with_alpha(self.fg, 0.22 if self.dark else 0.24)
        self.hover = with_alpha(self.fg, 0.07 if self.dark else 0.06)
        self.press = with_alpha(self.fg, 0.13 if self.dark else 0.11)
        self.tile_off = with_alpha(self.fg, 0.07 if self.dark else 0.055)
        self.accent_soft = with_alpha(self.accent, 0.18 if self.dark else 0.14)
        self.font = font
        self.scale = scale
        # a card on a surface: a little lighter than surface in dark mode, a little darker in light mode
        self.card = mix(self.surface, self.fg, 0.05 if self.dark else 0.035)

    # ------------------------------------------------------------------ loading
    @classmethod
    def from_palette(cls, pal, **kw):
        base = dict(DEFAULT_DARK if pal.get("mode", "dark") != "light" else DEFAULT_LIGHT)
        base.update(pal)
        return cls(base, **kw)

    @classmethod
    def load(cls, mode=None):
        cfg = os.environ.get("CARPATIC_CONFIG", os.path.expanduser("~/.config/carpatic"))
        state = os.environ.get("CARPATIC_STATE", os.path.expanduser("~/.local/state/carpatic"))
        st = read_env(f"{cfg}/settings.conf") or read_env(f"{cfg}/settings")
        theme = st.get("THEME", "carpatic")
        share = os.environ.get("CARPATIC_SHARE", "/usr/local/share/carpatic/configurator")
        pal = {}
        for d in (f"{cfg}/themes/{theme}", f"{share}/themes/{theme}", os.path.join(os.path.dirname(__file__), "..", "..", "..", "configurator", "themes", theme)):
            pal = parse_toml_colors(os.path.join(d, "colors.toml"))
            if pal: break
        if mode in ("dark", "light"):
            pal = dict(DEFAULT_LIGHT if mode == "light" else DEFAULT_DARK) if not pal or pal.get("mode") != mode else pal
        accent = st.get("ACCENT") or None
        try:
            a = open(f"{state}/current/accent.effective").read().strip()
            if re.match(r"#[0-9a-fA-F]{6}$", a): accent = a
        except OSError:
            pass
        env = read_env(f"{cfg}/profile.env")
        font = st.get("FONT_UI") or env.get("FONT_UI") or "Inter"
        return cls.from_palette(pal, accent=accent, font=font)
