"""Palette and CSS of Carpatic Settings. Colours come from the active theme (configurator/themes/<name>/colors.toml, the same file
design/tokens/out/ is generated into), so the app follows the user's theme and accent. Sizes come from docs/DESIGN-SYSTEM.md:
4 px spacing grid, radii 4/6/10/14, type scale 11/12/14/16/20/24/32."""
import os, re
from . import sysutil as su

# ---- design tokens (px) ----
SP = {"2": 2, "4": 4, "8": 8, "12": 12, "16": 16, "24": 24, "32": 32, "48": 48}
RADIUS = {"xs": 4, "sm": 6, "md": 10, "lg": 14}
TYPE = {"caption": 11, "small": 12, "body": 14, "lead": 16, "h3": 20, "h2": 24, "h1": 32}

def norm_hex(h):
    """#rgb -> #rrggbb; anything that is not a colour -> neutral grey (a theme file can be missing or hand-written)"""
    h = (h or "").strip().lstrip("#")
    if len(h) == 3: h = "".join(ch * 2 for ch in h)
    try:
        int(h, 16)
        if len(h) == 6: return "#" + h.lower()
    except ValueError: pass
    return "#888888"

def _rgb(h):
    h = norm_hex(h).lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def _hex(c):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v))) for v in c)

def mix(a, b, t):
    """a*(1-t) + b*t, colours as #rrggbb"""
    ca, cb = _rgb(a), _rgb(b)
    return _hex([ca[i] * (1 - t) + cb[i] * t for i in range(3)])

def lum(h):
    r, g, b = _rgb(h); return 0.299 * r + 0.587 * g + 0.114 * b

def rgba(h, a):
    r, g, b = _rgb(h); return "rgba(%d,%d,%d,%.3f)" % (r, g, b, a)

def theme_dir(theme):
    u = os.path.join(su.CFG, "themes", theme)
    return u if os.path.isfile(os.path.join(u, "colors.toml")) else os.path.join(su.SHARE, "themes", theme)

def read_colors(theme):
    c = {}
    try:
        with open(os.path.join(theme_dir(theme), "colors.toml")) as f:
            for line in f:
                m = re.match(r'\s*(\w+)\s*=\s*"([^"]*)"', line)
                if m: c[m.group(1)] = m.group(2)
    except OSError:
        pass
    return c

FALLBACK = {"dark": {"background": "#11151c", "foreground": "#e7ecf3", "accent": "#5cc8a8", "red": "#f0707a", "green": "#7bd389", "yellow": "#f2c25a", "blue": "#6cb4f0"},
            "light": {"background": "#f6f7f9", "foreground": "#172029", "accent": "#16806a", "red": "#c8323f", "green": "#1f8f4e", "yellow": "#a86a00", "blue": "#1e6fb8"}}

def palette(theme=None, accent=None):
    s = su.settings()
    theme = theme or s.get("THEME") or "carpatic"
    c = read_colors(theme)
    mode = c.get("mode") or ("light" if lum(c.get("background", "#000000")) > 140 else "dark")
    f = FALLBACK[mode]
    bg = c.get("background", f["background"]); fg = c.get("foreground", f["foreground"])
    acc = accent or s.get("ACCENT") or c.get("accent", f["accent"])
    dark = mode == "dark"
    p = {"mode": mode, "theme": theme, "bg": bg, "fg": fg, "accent": acc,
         "accent_fg": "#08241d" if lum(acc) > 150 else "#ffffff",
         "red": c.get("red", f["red"]), "green": c.get("green", f["green"]), "yellow": c.get("yellow", f["yellow"]), "blue": c.get("blue", f["blue"])}
    if dark:
        p.update(content=bg, card=mix(bg, fg, 0.06), card_hover=mix(bg, fg, 0.10), sidebar=mix(bg, "#000000", 0.28), field=mix(bg, fg, 0.09),
                 border=mix(bg, fg, 0.14), border_strong=mix(bg, fg, 0.24), muted=mix(bg, fg, 0.66), subtle=mix(bg, fg, 0.42), btn=mix(bg, fg, 0.14), btn_hover=mix(bg, fg, 0.20),
                 track=mix(bg, fg, 0.22), sidebar_hover=mix(bg, fg, 0.08), knob="#ffffff", switch_off=mix(bg, fg, 0.28))
    else:
        p.update(content=mix(bg, "#000000", 0.015), card=mix(bg, "#ffffff", 0.85), card_hover=mix(bg, "#000000", 0.035), sidebar=mix(bg, "#000000", 0.045),
                 field=mix(bg, "#ffffff", 0.85), border=mix(bg, "#000000", 0.10), border_strong=mix(bg, "#000000", 0.20), muted=mix(bg, fg, 0.72),
                 subtle=mix(bg, fg, 0.50), btn=mix(bg, "#ffffff", 0.9), btn_hover=mix(bg, "#000000", 0.04), track=mix(bg, "#000000", 0.14),
                 sidebar_hover=mix(bg, "#000000", 0.06), knob="#ffffff", switch_off=mix(bg, "#000000", 0.18))
    p["accent_soft"] = mix(p["content"], acc, 0.16)
    p["accent_hover"] = mix(acc, "#ffffff" if dark else "#000000", 0.10)
    p["sel_fg"] = p["accent_fg"]
    return p

CSS = """
window.cset, .cset-bg { background-color: %(content)s; color: %(fg)s; font-family: Inter, "Noto Sans", "Ubuntu Sans", "Cantarell", sans-serif; font-size: 14px; }
.cset label { color: %(fg)s; }
.cset .muted, .cset .row-sub, .cset .group-footer { color: %(muted)s; }
.cset *:disabled label { color: %(subtle)s; }

/* ---- sidebar ---- */
.sidebar-pane { background-color: %(sidebar)s; border-right: 1px solid %(border)s; }
.sidebar-search { padding: 12px 12px 8px 12px; }
.cset .sb-entry { min-height: 32px; padding: 0 8px; border-radius: 8px; background-color: %(field)s; background-image: none; border: 1px solid %(border)s; box-shadow: none; color: %(fg)s; caret-color: %(accent)s; }
.cset .sb-entry:focus { border-color: %(accent)s; box-shadow: 0 0 0 2px %(accent_a)s; }
.cset .sb-entry image { color: %(subtle)s; }
.sidebar-list { background-color: transparent; }
.sidebar-list row { background-color: transparent; margin: 0 8px; border-radius: 6px; padding: 0; min-height: 36px; }
.sidebar-list row:hover { background-color: %(sidebar_hover)s; }
.sidebar-list row:selected, .sidebar-list row:selected:hover { background-color: %(accent)s; }
.sidebar-list row:selected label { color: %(accent_fg)s; }
.sidebar-list row:focus { outline: 2px solid %(accent)s; outline-offset: -2px; -gtk-outline-radius: 6px; }
.sidebar-list row:selected:focus { outline-color: %(fg)s; }
.cset .sb-row-title { font-size: 14px; }
.cset .sb-row-sub { font-size: 12px; color: %(muted)s; }
.cset .cset .cset .cset .cset .cset .cset .cset .cset .cset .cset .cset .cset .cset .cset .cset .cset .cset .sidebar-list row:selected .sb-row-sub { color: %(accent_fg)s; }
.sb-gap { min-height: 8px; }
.cset button.user-card { background: none; border: none; box-shadow: none; border-radius: 8px; margin: 0 8px 4px 8px; padding: 8px; min-height: 0; }
.cset button.user-card:hover { background-color: %(sidebar_hover)s; }
.cset .user-name { font-size: 14px; font-weight: 600; }
.cset .user-card label { font-weight: 400; }
.cset .user-card .user-name { font-weight: 600; }
.cset .user-sub { font-size: 12px; color: %(muted)s; }
.cset .sb-empty { padding: 32px 16px; color: %(muted)s; }

/* icon tile (coloured rounded square, white glyph) */
.tile { border-radius: 6px; min-width: 28px; min-height: 28px; }
.cset .tile image { color: #ffffff; }
.card row image { color: %(muted)s; }
.cset .tile image, .card row .tile image { color: #ffffff; }
.tile-sm { border-radius: 5px; min-width: 24px; min-height: 24px; }
.tile-lg { border-radius: 10px; min-width: 40px; min-height: 40px; }

/* ---- toolbar (sticky header) ---- */
.toolbar { min-height: 56px; background-color: %(content)s; border-bottom: 1px solid transparent; padding: 0 16px; }
.toolbar.scrolled { border-bottom-color: %(border)s; background-color: %(content_a)s; }
.cset .toolbar-title { font-size: 16px; font-weight: 600; }
.cset button.nav-btn { min-width: 32px; min-height: 32px; padding: 0; border-radius: 6px; background-image: none; background-color: transparent; border: none; box-shadow: none; }
.cset button.nav-btn:hover { background-color: %(card_hover)s; }
.cset button.nav-btn:disabled { opacity: 0.35; }
.cset button.nav-btn image { color: %(fg)s; }

/* ---- page ---- */
.cset .page-title { font-size: 32px; font-weight: 600; letter-spacing: -0.3px; }
.cset .page-sub { font-size: 14px; color: %(muted)s; }
.cset .group-title { font-size: 12px; font-weight: 600; color: %(muted)s; }
.cset .group-footer { font-size: 12px; }
.card { background-color: %(card)s; border: 1px solid %(border)s; border-radius: 10px; }
list.card, .card list { background-color: transparent; }
.card row { background-color: transparent; padding: 0; min-height: 48px; border-radius: 0; }
.card row:first-child .row-sep { opacity: 0; }
.cset separator.row-sep { background-color: %(border)s; min-height: 1px; }
.card row:first-child { border-top-left-radius: 9px; border-top-right-radius: 9px; }
.card row:last-child { border-bottom-left-radius: 9px; border-bottom-right-radius: 9px; }
.card row.activatable:hover { background-color: %(card_hover)s; }
.card row.activatable:active { background-color: %(border)s; }
.card row:focus { outline: 2px solid %(accent)s; outline-offset: -2px; -gtk-outline-radius: 8px; }
.card row.flash { background-color: %(accent_soft)s; }
.cset .row-title { font-size: 14px; font-weight: 500; }
.cset .row-sub { font-size: 12px; }
.cset .row-value { font-size: 14px; color: %(muted)s; }
.cset .row-chevron { color: %(subtle)s; }
.card.custom { padding: 16px; }
.banner { background-color: %(accent_soft)s; border: 1px solid %(accent_b)s; border-radius: 10px; padding: 12px 16px; }
.banner.warn { background-color: %(yellow_a)s; border-color: %(yellow_b)s; }
.banner.bad { background-color: %(red_a)s; border-color: %(red_b)s; }
.status-dot { border-radius: 5px; min-width: 10px; min-height: 10px; }
.status-ok { background-color: %(green)s; } .status-warn { background-color: %(yellow)s; } .status-bad { background-color: %(red)s; } .status-off { background-color: %(subtle)s; }

/* ---- controls ---- */
.cset button { min-height: 28px; padding: 0 12px; border-radius: 6px; border: 1px solid %(border_strong)s; background-image: none; background-color: %(btn)s; box-shadow: none; color: %(fg)s; text-shadow: none; -gtk-icon-shadow: none; }
.cset button:hover { background-color: %(btn_hover)s; }
.cset button:active, .cset button:checked { background-color: %(border)s; }
.cset button:disabled { color: %(subtle)s; opacity: 0.7; }
.cset button:focus { outline: 2px solid %(accent)s; outline-offset: 1px; -gtk-outline-radius: 7px; }
.cset button.suggested-action { background-color: %(accent)s; border-color: transparent; color: %(accent_fg)s; }
.cset button.suggested-action label { color: %(accent_fg)s; }
.cset button.suggested-action:hover { background-color: %(accent_hover)s; }
.cset button.destructive-action { background-color: transparent; border-color: %(red)s; color: %(red)s; }
.cset button.destructive-action label { color: %(red)s; }
.cset button.destructive-action:hover { background-color: %(red_a)s; }
.cset button.link-btn { background: none; border: none; color: %(accent)s; padding: 0 4px; }
.cset button.link-btn label { color: %(accent)s; }
.cset button.popup-btn { padding: 0 8px 0 12px; min-width: 96px; }
.cset button.pill { border-radius: 999px; padding: 0 16px; }
.cset button.pill:checked { background-color: %(accent)s; color: %(accent_fg)s; border-color: transparent; }
.cset button.pill:checked label { color: %(accent_fg)s; }
.cset entry, .cset spinbutton { min-height: 28px; padding: 0 8px; border-radius: 6px; background-color: %(field)s; background-image: none; border: 1px solid %(border_strong)s; box-shadow: none; color: %(fg)s; caret-color: %(accent)s; }
.cset entry:focus, .cset spinbutton:focus-within { border-color: %(accent)s; box-shadow: 0 0 0 2px %(accent_a)s; }
.cset spinbutton button { min-height: 0; border: none; background: none; border-radius: 0; }
.cset switch { min-width: 40px; min-height: 24px; border-radius: 12px; border: none; background-image: none; background-color: %(switch_off)s; box-shadow: none; padding: 0; margin: 0; }
.cset switch:checked { background-color: %(accent)s; }
.cset switch:focus { outline: 2px solid %(accent)s; outline-offset: 2px; -gtk-outline-radius: 14px; }
.cset switch slider { min-width: 20px; min-height: 20px; margin: 2px; border-radius: 10px; border: none; background-image: none; background-color: %(knob)s; box-shadow: 0 1px 2px rgba(0,0,0,0.30); }
.cset switch:disabled { opacity: 0.5; }
.cset switch label, .cset switch image { font-size: 0; color: transparent; opacity: 0; min-width: 0; min-height: 0; -gtk-icon-source: none; }
.stepper { background-color: %(btn)s; border: 1px solid %(border_strong)s; border-radius: 6px; }
.cset .stepper-val { font-size: 14px; padding: 0 4px; }
.cset button.step-btn { min-width: 28px; min-height: 26px; border: none; border-left: 1px solid %(border_strong)s; border-radius: 0; background: none; padding: 0; }
.cset button.step-btn:hover { background-color: %(btn_hover)s; }
.cset button.step-btn:last-child { border-top-right-radius: 5px; border-bottom-right-radius: 5px; }
.cset scale trough { min-height: 4px; border-radius: 2px; background-color: %(track)s; background-image: none; border: none; }
.cset scale highlight { background-color: %(accent)s; background-image: none; border: none; border-radius: 2px; }
.cset scale slider { min-width: 20px; min-height: 20px; margin: -8px; border-radius: 10px; background-color: %(knob)s; background-image: none; border: 1px solid %(border_strong)s; box-shadow: 0 1px 3px rgba(0,0,0,0.25); }
.cset scale:focus slider { outline: 2px solid %(accent)s; outline-offset: 1px; -gtk-outline-radius: 12px; }
.cset scale value { color: %(muted)s; }
.cset progressbar trough { min-height: 8px; border-radius: 4px; background-color: %(track)s; border: none; background-image: none; }
.cset progressbar progress { min-height: 8px; border-radius: 4px; background-color: %(accent)s; background-image: none; border: none; }
.cset progressbar.warn progress { background-color: %(yellow)s; } .cset progressbar.bad progress { background-color: %(red)s; }
.cset popover { background-color: %(card)s; border: 1px solid %(border_strong)s; border-radius: 10px; box-shadow: 0 8px 24px rgba(0,0,0,0.30); padding: 0; }
.cset popover.background { background-color: %(card)s; }
.cset popover modelbutton, .cset .pop-item { min-height: 32px; padding: 0 12px; border-radius: 6px; background: none; border: none; box-shadow: none; }
.cset .pop-item:hover { background-color: %(accent)s; }
.cset .pop-item:hover label, .cset .pop-item:hover image { color: %(accent_fg)s; }
.cset .pop-item:focus { outline: none; background-color: %(accent)s; }
.cset .pop-item:focus label { color: %(accent_fg)s; }
.cset scrolledwindow undershoot, .cset scrolledwindow overshoot { background: none; }
.cset scrollbar { background: none; border: none; }
.cset scrollbar slider { min-width: 6px; min-height: 6px; border-radius: 3px; background-color: %(border_strong)s; border: none; }
.cset scrollbar.overlay-indicator:hover slider { background-color: %(subtle)s; }
.cset separator { background-color: %(border)s; min-height: 1px; min-width: 1px; }
.cset spinner { color: %(muted)s; }

/* ---- galleries (style, themes, icons...) ---- */
.cset button.gallery { padding: 8px; border-radius: 10px; background-color: %(card)s; border: 2px solid %(border)s; box-shadow: none; min-height: 0; }
.cset button.gallery:hover { background-color: %(card_hover)s; }
.cset button.gallery:checked, .cset button.gallery.selected { border-color: %(accent)s; background-color: %(card)s; }
.cset button.gallery:focus { outline: 2px solid %(accent)s; outline-offset: 2px; -gtk-outline-radius: 12px; }
.cset .gallery-title { font-size: 12px; font-weight: 600; }
.cset .gallery-sub { font-size: 11px; color: %(muted)s; }
.cset button.gallery:checked .gallery-sub { color: %(muted)s; }
.badge { background-color: %(accent)s; color: %(accent_fg)s; border-radius: 999px; padding: 0 8px; font-size: 11px; font-weight: 600; }
.badge label { color: %(accent_fg)s; font-size: 11px; font-weight: 600; }
.swatch { min-width: 28px; min-height: 28px; border-radius: 14px; padding: 0; border: 2px solid transparent; box-shadow: inset 0 0 0 1px rgba(0,0,0,0.18); }
.cset button.swatch { padding: 0; min-width: 28px; min-height: 28px; border-radius: 14px; border: 2px solid transparent; }
.cset button.swatch.selected { border-color: %(fg)s; }
.cset button.swatch:focus { outline: 2px solid %(accent)s; outline-offset: 2px; -gtk-outline-radius: 16px; }
.seg { background-color: %(btn)s; border: 1px solid %(border_strong)s; border-radius: 8px; padding: 2px; }
.cset button.seg-btn { border: none; background: none; min-height: 24px; border-radius: 6px; padding: 0 12px; box-shadow: none; }
.cset button.seg-btn:checked { background-color: %(accent)s; color: %(accent_fg)s; }
.cset button.seg-btn:checked label { color: %(accent_fg)s; }
.cset .big-num { font-size: 24px; font-weight: 600; }
.legacy-page .h1 { font-size: 20px; font-weight: 600; margin-top: 8px; }
.legacy-page .sub, .legacy-page .cdesc { color: %(muted)s; font-size: 12px; }
.legacy-page .ctitle { font-weight: 500; }
"""

def css(p=None):
    p = p or palette()
    d = dict(p)
    d["accent_a"] = rgba(p["accent"], 0.30); d["accent_b"] = rgba(p["accent"], 0.45)
    d["yellow_a"] = rgba(p["yellow"], 0.16); d["yellow_b"] = rgba(p["yellow"], 0.45)
    d["red_a"] = rgba(p["red"], 0.14); d["red_b"] = rgba(p["red"], 0.45)
    d["content_a"] = rgba(p["content"], 0.96)
    return CSS % d
