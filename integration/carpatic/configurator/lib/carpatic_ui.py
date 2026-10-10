"""Shared helpers for the Carpatic GTK front ends (carpatic-welcome, carpatic-settings). All real work is done by the CLI tools."""
import os, re, subprocess, glob
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib

SHARE = os.environ.get("CARPATIC_SHARE", "/usr/local/share/carpatic/configurator")
CFG = os.path.expanduser("~/.config/carpatic")
ACCENTS = ["#e06c75", "#e5a050", "#e5c07b", "#98c379", "#56b6c2", "#61afef", "#c678dd", "#ff79c6"]
PROFILES = [  # (id, glyph, title, blurb)
    ("windows", "\u229e", "Windows", "A taskbar at the bottom with a Start button, like Windows."),
    ("macos", "\u2318", "macOS", "A menu bar on top and a dock at the bottom. Super works like Cmd."),
    ("ubuntu", "\u25c9", "Ubuntu", "A top bar, a dock on the left and an Activities overview."),
    ("tiling", "\u25a6", "I know Linux (tiling)", "Windows tile themselves and the keyboard does the rest."),
    ("beginner", "\u263a", "I'm new to computers", "A taller taskbar with bigger icons and window names, larger text and a bigger pointer."),
]

def stylepack_profiles():
    """style packs (stylepacks/) register a profile with STYLEPACK=<id>: they appear in Settings > Style next to the built-in styles"""
    out = []
    for f in sorted(glob.glob(f"{SHARE}/profiles/*.conf")):
        kv = {}
        try:
            for line in open(f):
                m = re.match(r'([A-Z_]+)="?([^"\n]*?)"?\s*(?:#.*)?$', line.rstrip("\n"))
                if m and m.group(1) in ("STYLEPACK", "DEFAULT_THEME", "LABEL", "DESC", "GLYPH"): kv[m.group(1)] = m.group(2)
        except OSError:
            continue
        pid = os.path.basename(f)[:-5]
        if kv.get("STYLEPACK") == pid or (kv.get("DEFAULT_THEME") and os.path.isfile(f"{SHARE}/themes/{kv['DEFAULT_THEME']}/colors.toml")): out.append((pid, (kv.get("GLYPH", "\\u2726").encode().decode("unicode_escape")), kv.get("LABEL", pid), kv.get("DESC", "")))
    return out
PROFILES += stylepack_profiles()

def sh(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()

def run(*cmd, done=None):
    """Run a command in the background; call done(returncode) on the GTK main loop when it ends."""
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if done:
        GLib.child_watch_add(GLib.PRIORITY_DEFAULT, p.pid, lambda pid, status: done(os.waitstatus_to_exitcode(status)))
    return p

def theme_dir(theme):
    """System themes live in the share dir; themes the user imported (carpatic theme import) in ~/.config/carpatic/themes."""
    u = os.path.join(os.environ.get("CARPATIC_CONFIG", os.path.expanduser("~/.config/carpatic")), "themes", theme)
    return u if os.path.isfile(os.path.join(u, "colors.toml")) else f"{SHARE}/themes/{theme}"

def theme_names():
    names = set(os.listdir(f"{SHARE}/themes")) if os.path.isdir(f"{SHARE}/themes") else set()
    ud = os.path.join(os.environ.get("CARPATIC_CONFIG", os.path.expanduser("~/.config/carpatic")), "themes")
    if os.path.isdir(ud):
        names |= {d for d in os.listdir(ud) if os.path.isfile(os.path.join(ud, d, "colors.toml"))}
    return sorted(names, key=lambda x: (not x.startswith("carpatic"), x))

def read_colors(theme):
    c = {}
    try:
        for line in open(f"{theme_dir(theme)}/colors.toml"):
            m = re.match(r'\s*(\w+)\s*=\s*"([^"]*)"', line)
            if m: c[m.group(1)] = m.group(2)
    except OSError:
        pass
    return c

def read_env(path):
    d = {}
    try:
        for line in open(path):
            m = re.match(r'\s*(\w+)="?(.*?)"?\s*$', line)
            if m: d[m.group(1)] = m.group(2)
    except OSError:
        pass
    return d

def settings():
    return read_env(f"{CFG}/settings.conf")

def lum(h):
    h = h.lstrip("#"); r, g, b = (int(h[i:i+2], 16) for i in (0, 2, 4)); return 0.299*r + 0.587*g + 0.114*b

# Accent picker: the six accents of the design tokens (dark value, light value)
ACCENT_SETS = [("Spruce", "#5cc8a8", "#16806a"), ("Glacier", "#6cb4f0", "#1e6fb8"), ("Dusk", "#a99bf0", "#6a4fd0"),
               ("Rose", "#f08aa8", "#c2386a"), ("Ember", "#f2a65a", "#b8640f"), ("Moss", "#a3d36b", "#4f8a1c")]
SCENES = [("bucegi", "Bucegi"), ("retezat", "Retezat"), ("fagaras", "F\u0103g\u0103ra\u015f"), ("rodna", "Rodna"), ("apuseni", "Apuseni"),
          ("piatra", "Piatra Craiului"), ("ceahlau", "Ceahl\u0103u"), ("tatra", "Tatra")]

def gtk_style():
    """The GTK style family in use (gtktheme/): user setting, then the profile's GTK_STYLE, then carpatic; the nothing themes force 'nothing'."""
    st = settings()
    if st.get("GTK_STYLE"): return st["GTK_STYLE"]
    if st.get("THEME", "") in ("nothing", "nothing-light"): return "nothing"
    return profile_value(st.get("PROFILE", "tiling"), "GTK_STYLE") or "carpatic"

def style_geometry(style=None):
    """Radii (px) of the style from share/gtktheme/geometry.conf: card, ctl, row, pop, search. Defaults = the carpatic style."""
    g = {"card": 12, "ctl": 8, "row": 8, "pop": 14, "search": 8}
    try:
        for line in open(f"{SHARE}/gtktheme/geometry.conf"):
            f = line.split()
            if len(f) > 1 and f[0] == (style or gtk_style()):
                g.update({k: int(v) for k, v in (x.split("=") for x in f[1:])})
    except (OSError, ValueError):
        pass
    return g

def card_css(theme, accent=""):
    """Widget CSS from the design tokens: radius 10 cards, 1 px border (2 px accent when selected), h1 32 px / 600, caption 11 px, pills and swatches fully round."""
    c = read_colors(theme)
    fg = c.get("foreground", "#e7ecf3"); acc = accent or c.get("accent", "#5cc8a8"); card = c.get("dark_background", "#171c25")
    bd = c.get("lighter_background", "#1e2430"); muted = c.get("light_foreground", "#a3aec0")
    accfg = "#08241d" if lum(acc) > 140 else "#ffffff"
    g = style_geometry(); rc = g["card"]; rp = min(g["search"], 999)
    return f"""
    .h1 {{ font-size: 32px; font-weight: 600; }}
    .sub {{ color: {muted}; font-size: 14px; }}
    .card {{ background-color: {card}; border: 1px solid alpha({fg}, 0.14); border-radius: {rc}px; padding: 16px; color: {fg}; background-image: none; box-shadow: none; }}
    .card:hover {{ background-color: alpha({fg}, 0.06); }}
    .card:checked, .card.selected {{ border: 2px solid {acc}; padding: 15px; background-color: alpha({acc}, 0.12); }}
    .glyph {{ font-size: 28px; color: {acc}; }}
    .ctitle {{ font-weight: 600; font-size: 14px; color: {fg}; }}
    .cdesc {{ color: {muted}; font-size: 11px; font-weight: normal; }}
    .badge {{ background-color: {acc}; color: {accfg}; border-radius: 999px; padding: 1px 10px; font-size: 11px; font-weight: 600; }}
    .swatch {{ border-radius: 999px; min-width: 28px; min-height: 28px; padding: 0; border: 2px solid transparent; background-image: none; }}
    button.swatch:checked, button.swatch.selected {{ border: 2px solid {fg}; }}
    .pill {{ border-radius: {rp}px; padding: 6px 16px; }}
    button.pill:checked, button.pill:checked:hover {{ background-color: {acc}; color: {accfg}; background-image: none; }}
    button.pill:checked label {{ color: {accfg}; }}
    """

def draw_theme_swatch(w, cr, c):
    def rgb(h): h = h.lstrip("#"); return tuple(int(h[i:i+2], 16)/255 for i in (0, 2, 4))
    W, H = w.get_allocated_width(), w.get_allocated_height()
    cr.set_source_rgb(*rgb(c.get("background", "#000000"))); cr.rectangle(0, 0, W, H); cr.fill()
    cr.set_source_rgb(*rgb(c.get("dark_background", "#000000"))); cr.rectangle(0, H-16, W, 16); cr.fill()
    cr.set_source_rgb(*rgb(c.get("accent", "#888888"))); cr.rectangle(8, H-12, 28, 8); cr.fill()
    cr.set_source_rgb(*rgb(c.get("foreground", "#ffffff"))); cr.rectangle(12, 12, 90, 5); cr.fill(); cr.rectangle(12, 24, 60, 5); cr.fill()
    for i, k in enumerate(("red", "green", "yellow", "blue", "magenta", "cyan")):
        cr.set_source_rgb(*rgb(c.get(k, "#888888"))); cr.arc(18 + i*16, 50, 5, 0, 6.3); cr.fill()

def install_css(provider):
    # above the user's gtk.css (USER priority) so the app's cards/pills keep their selected look
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)

def profile_value(profile, key):
    """Value of KEY in profiles/<profile>.conf (quoted or bare)."""
    try:
        for line in open(f"{SHARE}/profiles/{profile}.conf"):
            m = re.match(rf'{key}="([^"]*)"|{key}=(\S+)', line)
            if m: return m.group(1) if m.group(1) is not None else m.group(2)
    except OSError:
        pass
    return ""
