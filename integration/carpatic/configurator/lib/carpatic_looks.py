"""Shared "look" components used by Carpatic Settings (Appearance) and the Welcome wizard, so the style gallery and the theme gallery are the
same widgets with the same previews everywhere. The previews are drawn by the theme picker's renderer (themepicker/lib/tp_render.draw_mock: the
real wallpaper, the style's bars, windows with borders, gaps and buttons), which is also what the keyboard picker (Super+Ctrl+Shift+Space) shows.
Without the picker's library a plain palette swatch is drawn instead. License: MIT."""
import os, sys, glob, math
import cairo
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0"); gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(_HERE, "..", "..", "themepicker", "lib"), "/usr/local/lib/carpatic-themepicker", "/usr/lib/carpatic-themepicker", "/usr/local/lib/carpatic", "/usr/lib/carpatic"):
    if os.path.isdir(_p) and _p not in sys.path: sys.path.append(_p)
try:
    import tp_render, tp_data
except Exception:   # picker library not installed: swatch previews
    tp_render = tp_data = None

_catalog = None
def catalog():
    global _catalog
    if _catalog is None and tp_data is not None:
        try: _catalog = tp_data.Catalog()
        except Exception: _catalog = False
    return _catalog or None

def hex_rgb(h):
    h = (h or "#888888").lstrip("#")
    if len(h) == 3: h = "".join(c * 2 for c in h)
    try: return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError: return (0.5, 0.5, 0.5)

def mix(a, b, t):
    ca, cb = hex_rgb(a), hex_rgb(b)
    return "#%02x%02x%02x" % tuple(round((ca[i] * (1 - t) + cb[i] * t) * 255) for i in range(3))

def palette_from_colors(c, accent=""):
    """GUI palette (card, border, fg, muted, accent...) from a theme's colors.toml dict: for windows that do not have their own (the Welcome)"""
    bg, fg = c.get("background", "#11151c"), c.get("foreground", "#e7ecf3"); acc = accent or c.get("accent", "#5cc8a8")
    dark = c.get("mode", "dark") == "dark"
    lum = lambda h: 0.299 * hex_rgb(h)[0] * 255 + 0.587 * hex_rgb(h)[1] * 255 + 0.114 * hex_rgb(h)[2] * 255
    return {"mode": "dark" if dark else "light", "bg": bg, "fg": fg, "accent": acc, "accent_fg": "#08241d" if lum(acc) > 150 else "#ffffff",
            "card": mix(bg, fg, 0.06) if dark else mix(bg, "#ffffff", 0.85), "card_hover": mix(bg, fg, 0.10) if dark else mix(bg, "#000000", 0.035),
            "border": mix(bg, fg, 0.16) if dark else mix(bg, "#000000", 0.12), "muted": mix(bg, fg, 0.66) if dark else mix(bg, fg, 0.72)}

# ---------------------------------------------------------------- choices
def style_choices():
    """[(id, title, description)]: the built-in desktop styles plus installed style packs (same list as the Welcome question)"""
    import carpatic_ui as cu
    return [(pid, title, blurb) for pid, glyph, title, blurb in cu.PROFILES]

def theme_choices(mode=None):
    """[(id, title, colors)] of every theme, optionally only the light or the dark ones"""
    cat = catalog(); out = []
    if cat is not None:
        for n in cat.theme_names():
            c = cat.colors(n)
            if mode and c.get("mode", "dark") != mode: continue
            out.append((n, tp_data.label_for(n), c))
        return out
    import carpatic_ui as cu
    for n in cu.theme_names():
        c = cu.read_colors(n)
        if mode and c.get("mode", "dark") != mode: continue
        out.append((n, n.replace("-", " ").title(), c))
    return out

# ---------------------------------------------------------------- painters
def _rounded(cr, w, h, r):
    cr.new_sub_path(); cr.arc(w - r, r, r, -math.pi / 2, 0); cr.arc(w - r, h - r, r, 0, math.pi / 2); cr.arc(r, h - r, r, math.pi / 2, math.pi); cr.arc(r, r, r, math.pi, 1.5 * math.pi); cr.close_path()

def _swatch(cr, w, h, colors):
    cr.set_source_rgb(*hex_rgb(colors.get("background"))); cr.paint()
    cr.set_source_rgb(*hex_rgb(colors.get("dark_background"))); cr.rectangle(0, h - h * .16, w, h * .16); cr.fill()
    cr.set_source_rgb(*hex_rgb(colors.get("accent"))); cr.rectangle(w * .05, h - h * .12, w * .18, h * .08); cr.fill()
    cr.set_source_rgb(*hex_rgb(colors.get("foreground"))); cr.rectangle(w * .08, h * .14, w * .55, h * .05); cr.fill(); cr.rectangle(w * .08, h * .26, w * .35, h * .05); cr.fill()
    for i, k in enumerate(("red", "green", "yellow", "blue", "magenta", "cyan")):
        cr.set_source_rgb(*hex_rgb(colors.get(k))); cr.arc(w * (.11 + i * .1), h * .52, h * .045, 0, 6.3); cr.fill()

def mock_look(theme, profile="tiling", state=None):
    """the `look` dict tp_render.draw_mock wants: colours of THEME, the bars of PROFILE, the user's own border/gap/button choices when STATE (settings.conf) has them"""
    cat = catalog(); st = state or {}
    c = cat.colors(theme) if cat is not None else {}
    wp = ""
    if cat is not None:
        try:
            w = cat.wallpapers(theme); wp = w[0][0] if w else ""
        except Exception: wp = ""
    def num(k, d):
        try: return int(st.get(k) or d)
        except ValueError: return d
    return {"colors": c, "accent": st.get("ACCENT") or c.get("accent"), "wallpaper": wp, "profile": profile, "bar": "tint2", "border_px": num("BORDER_WIDTH", 2),
            "buttons": st.get("WINDOW_BUTTONS") or "macos", "titlebars": profile != "tiling", "tiled": profile == "tiling",
            "radius": num("CORNER_RADIUS", 0), "gap": num("INNER_GAP", 8)}

def painter_mock(theme, profile="tiling", state=None, preview_png=None):
    """-> painter(cr, w, h) drawing the mock desktop (or a style pack's own screenshot when PREVIEW_PNG exists)"""
    pix = {}
    def draw(cr, w, h):
        cr.save(); _rounded(cr, w, h, 8); cr.clip()
        try:
            if preview_png and os.path.isfile(preview_png):
                if "pb" not in pix: pix["pb"] = GdkPixbuf.Pixbuf.new_from_file(preview_png)
                pb = pix["pb"]; k = max(w / pb.get_width(), h / pb.get_height()); cr.scale(k, k)
                Gdk.cairo_set_source_pixbuf(cr, pb, (w / k - pb.get_width()) / 2, (h / k - pb.get_height()) / 2); cr.paint()
            elif tp_render is not None:
                look = pix.get("look") or pix.setdefault("look", mock_look(theme, profile, state))
                tp_render.draw_mock(cr, 0, 0, w, h, look, detail=w > 150)
            else:
                import carpatic_ui as cu; _swatch(cr, w, h, cu.read_colors(theme))
        except Exception:
            import carpatic_ui as cu; _swatch(cr, w, h, cu.read_colors(theme))
        cr.restore()
    def paint(cr, w, h):
        if w <= 0 or h <= 0: return
        size = (int(math.ceil(w)), int(math.ceil(h)))
        if pix.get("size") != size:
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, *size)
            draw(cairo.Context(surface), w, h)
            pix["surface"], pix["size"] = surface, size
        # Hover, focus and scrolling redraw the gallery frequently. Reuse the
        # finished thumbnail rather than rendering its wallpaper/windows/text
        # again on every input event. Each painter retains only one size.
        cr.save(); cr.set_source_surface(pix["surface"], 0, 0); cr.paint(); cr.restore()
    return paint

def painter_swatch(colors):
    def paint(cr, w, h):
        cr.save(); _rounded(cr, w, h, 8); cr.clip(); _swatch(cr, w, h, colors); cr.restore()
    return paint

# ---------------------------------------------------------------- the gallery widget
_CSS = """
button.lk-card { padding: 8px; border-radius: 10px; background-image: none; background-color: %(card)s; border: 2px solid %(border)s; box-shadow: none; min-height: 0; color: %(fg)s; }
button.lk-card:hover { background-color: %(card_hover)s; }
button.lk-card.selected { border-color: %(accent)s; }
button.lk-card:focus { outline: 2px solid %(accent)s; outline-offset: 2px; -gtk-outline-radius: 12px; }
button.lk-card label.lk-title { font-size: 12px; font-weight: 600; color: %(fg)s; }
button.lk-card label.lk-sub { font-size: 11px; font-weight: 400; color: %(muted)s; }
"""

class LookGallery(Gtk.FlowBox):
    """Grid of selectable look cards (a preview, a title, an optional sentence). add_item(id, title, sub, painter); select(id); on_pick(id) on click.
    The palette keys: card, card_hover, border, fg, muted, accent."""
    def __init__(self, palette, cols=3, preview_w=200, on_pick=None):
        super().__init__(); self.set_selection_mode(Gtk.SelectionMode.NONE); self.set_homogeneous(True)
        self.set_min_children_per_line(1); self.set_max_children_per_line(cols); self.set_row_spacing(12); self.set_column_spacing(12); self.set_valign(Gtk.Align.START)
        self.pw = preview_w; self.on_pick = on_pick; self.items = {}; self.value = None; self.guard = False
        self.provider = Gtk.CssProvider(); self.set_palette(palette)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), self.provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 5)
    def set_palette(self, p):
        self.palette = dict(p); self.provider.load_from_data((_CSS % self.palette).encode())
    def add_item(self, iid, title, sub="", painter=None):
        b = Gtk.Button(); b.set_relief(Gtk.ReliefStyle.NONE); b.get_style_context().add_class("lk-card")
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        if painter is not None:
            da = Gtk.DrawingArea(); da.set_size_request(self.pw, int(self.pw * 9 / 16)); da.set_halign(Gtk.Align.CENTER)
            da.connect("draw", lambda w, cr, p=painter: (p(cr, w.get_allocated_width(), w.get_allocated_height()), False)[1]); v.pack_start(da, False, False, 0)
        t = Gtk.Label(label=title); t.get_style_context().add_class("lk-title"); t.set_line_wrap(True); t.set_justify(Gtk.Justification.CENTER); v.pack_start(t, False, False, 0)
        if sub:
            s = Gtk.Label(label=sub); s.get_style_context().add_class("lk-sub"); s.set_line_wrap(True); s.set_max_width_chars(max(18, self.pw // 9)); s.set_justify(Gtk.Justification.CENTER); v.pack_start(s, False, False, 0)
        b.add(v); b.connect("clicked", lambda _b, i=iid: self.on_pick and not self.guard and self.on_pick(i)); b.title_text = title
        try:
            a = b.get_accessible(); a.set_name(title); a.set_description(sub or "")
        except Exception: pass
        self.items[iid] = b; self.add(b); b.show_all(); return b
    def select(self, iid):
        self.value = iid
        for k, b in self.items.items():
            c = b.get_style_context(); (c.add_class if k == iid else c.remove_class)("selected")
    def clear(self):
        for c in self.get_children(): self.remove(c)
        self.items = {}
