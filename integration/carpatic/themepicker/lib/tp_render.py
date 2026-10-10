"""Carpathian theme picker: drawing. A mock desktop (wallpaper, the desktop style's bars, windows with border / gaps / rounded corners /
title-bar buttons, fonts, icons) and the picker card around it. Cairo + Pango only; no widgets, so it also renders to a PNG on the host.

Everything is drawn in a fixed 960x540 reference space and scaled, so thumbnails and the large preview share one code path."""
import math, os, sys
import gi
gi.require_version("Pango", "1.0"); gi.require_version("PangoCairo", "1.0"); gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Pango, PangoCairo, GdkPixbuf
import cairo
try:
    gi.require_foreign("cairo"); PANGO_OK = True
except ImportError:          # no gi/cairo bridge (python3-gi-cairo): fall back to cairo's own text so the card still renders
    PANGO_OK = False

for _p in ("/usr/local/lib/carpatic", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "configurator", "lib")):
    if os.path.isdir(_p) and _p not in sys.path: sys.path.append(_p)
try:
    from carpatic_buttons import draw_titlebar
except Exception:          # the Settings app's library is missing: windows get a plain title bar
    draw_titlebar = None

REF_W, REF_H = 960, 540


def rgb(h, a=1.0):
    h = (h or "#888888").lstrip("#")
    if len(h) < 6: h = "888888"
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255, a)


def mix(a, b, t):
    ra, rb = rgb(a), rgb(b)
    return "#%02x%02x%02x" % tuple(int((ra[i] * (1 - t) + rb[i] * t) * 255) for i in range(3))


def rrect(cr, x, y, w, h, r):
    r = max(0, min(r, w / 2, h / 2))
    cr.new_sub_path()
    if r <= 0:
        cr.rectangle(x, y, w, h); return
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0); cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi); cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi); cr.close_path()


class Fonts:
    """Pango layouts with a tiny cache of font descriptions."""
    def __init__(self): self.fd = {}
    def desc(self, family, size, weight=None):
        k = (family, size, weight)
        if k not in self.fd:
            d = Pango.FontDescription(); d.set_family(family); d.set_absolute_size(size * Pango.SCALE)
            if weight: d.set_weight(weight)
            self.fd[k] = d
        return self.fd[k]
    def text(self, cr, x, y, s, family, size, color, alpha=1.0, weight=None, width=None, align="l", ellipsize=True):
        """Draws s with its top-left at x,y (x is the right edge for align 'r', the centre for 'c'). Returns (w, h) in pixels."""
        if not PANGO_OK: return self._toy(cr, x, y, s, family, size, color, alpha, weight, width, align)
        lay = PangoCairo.create_layout(cr)
        lay.set_font_description(self.desc(family, size, weight)); lay.set_text(s, -1)
        if width is not None:
            lay.set_width(int(width * Pango.SCALE))
            if ellipsize: lay.set_ellipsize(Pango.EllipsizeMode.END)
        w, h = lay.get_pixel_size()
        if align == "r": x -= w
        elif align == "c": x -= w / 2
        cr.set_source_rgba(*rgb(color, alpha)); cr.move_to(x, y); PangoCairo.show_layout(cr, lay)
        return w, h
    def _toy(self, cr, x, y, s, family, size, color, alpha, weight, width, align):
        cr.select_font_face(family, 0, 1 if weight and int(weight) >= 600 else 0); cr.set_font_size(size)
        w = cr.text_extents(s).x_advance
        while width is not None and w > width and len(s) > 2:
            s = s[:-2] + "\u2026"; w = cr.text_extents(s).x_advance
        if align == "r": x -= w
        elif align == "c": x -= w / 2
        cr.set_source_rgba(*rgb(color, alpha)); cr.move_to(x, y + size * .85); cr.show_text(s)
        return w, size * 1.2
    def measure(self, cr, s, family, size, weight=None):
        if not PANGO_OK:
            cr.select_font_face(family); cr.set_font_size(size); return cr.text_extents(s).x_advance, size * 1.2
        lay = PangoCairo.create_layout(cr); lay.set_font_description(self.desc(family, size, weight)); lay.set_text(s, -1)
        return lay.get_pixel_size()


FONTS = Fonts()


class Pictures:
    """Wallpaper and icon cache. Wallpapers are decoded once, scaled on load (libjpeg scales while decoding, which is the fast path),
    and kept as cairo surfaces; the cache is small and least-recently-used."""
    def __init__(self, limit=8):
        self.limit = limit; self.walls = {}; self.order = []; self.icons = {}; self.icon_themes = {}
    def wallpaper(self, path, w, h):
        """A cover-fit surface of exactly w x h (ints) for the file, or None."""
        k = (path, w, h)
        if k in self.walls:
            self.order.remove(k); self.order.append(k); return self.walls[k]
        surf = self._load(path, w, h)
        if surf is None: return None
        self.walls[k] = surf; self.order.append(k)
        while len(self.order) > self.limit:
            del self.walls[self.order.pop(0)]
        return surf
    def _load(self, path, w, h):
        if not PANGO_OK: return None            # host without the gi/cairo bridge: the card falls back to a palette gradient
        try:
            gi.require_version("Gdk", "3.0")
            from gi.repository import Gdk
            info = GdkPixbuf.Pixbuf.get_file_info(path)       # gdk-pixbuf scales while decoding: the fast path
            iw, ih = (info[1], info[2]) if info and info[0] else (w, h)
            sc = max(w / iw, h / ih)
            tw, th = max(w, int(math.ceil(iw * sc))), max(h, int(math.ceil(ih * sc)))
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, tw, th, False)
            surf = cairo.ImageSurface(cairo.FORMAT_RGB24, w, h); c = cairo.Context(surf)
            Gdk.cairo_set_source_pixbuf(c, pb, (w - pb.get_width()) / 2, (h - pb.get_height()) / 2); c.paint()
            return surf
        except Exception:
            return None
    def icon(self, theme, name, size):
        k = (theme, name, size)
        if k in self.icons: return self.icons[k]
        surf = None
        try:
            gi.require_version("Gtk", "3.0")
            from gi.repository import Gtk, Gdk
            it = self.icon_themes.get(theme)
            if it is None:
                it = Gtk.IconTheme.new(); it.set_custom_theme(theme); self.icon_themes[theme] = it
            pb = it.load_icon(name, size, 0)
            surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, pb.get_width(), pb.get_height())
            c = cairo.Context(surf); Gdk.cairo_set_source_pixbuf(c, pb, 0, 0); c.paint()
        except Exception:
            surf = None
        self.icons[k] = surf
        return surf


PICS = Pictures()


def pick_font(look, key, fallback):
    return look.get(key) or fallback


def draw_mock(cr, x, y, w, h, look, detail=True):
    """The mock desktop in a w x h box at x,y. `look` keys:
    colors (palette dict), accent, wallpaper (path or ''), profile, bar ('tint2'|'dwm'), border_px, border_color, gap, radius, buttons,
    side, titlebars (bool), tiled (bool), ui_font, ui_size, mono_font, icons (icon theme), fg_scale."""
    c = look["colors"]; acc = look.get("accent") or c.get("accent", "#5cc8a8")
    bg, surf, fg = c.get("background", "#111111"), c.get("dark_background", c.get("background", "#111111")), c.get("foreground", "#eeeeee")
    lighter, muted = c.get("lighter_background", "#333333"), c.get("light_foreground", "#aaaaaa")
    ui, mono, uis = look.get("ui_font", "Inter"), look.get("mono_font", "JetBrains Mono"), float(look.get("ui_size", 10) or 10)
    cr.save(); cr.translate(x, y); cr.scale(w / REF_W, h / REF_H); cr.rectangle(0, 0, REF_W, REF_H); cr.clip()
    # wallpaper (or the palette's background when the file cannot be read)
    pw, ph = max(1, int(round(w))), max(1, int(round(h)))
    wp = PICS.wallpaper(look.get("wallpaper") or "", pw, ph) if look.get("wallpaper") else None
    if wp:
        cr.save(); cr.scale(REF_W / pw, REF_H / ph); cr.set_source_surface(wp, 0, 0); cr.paint(); cr.restore()
    else:
        g = cairo.LinearGradient(0, 0, 0, REF_H); g.add_color_stop_rgba(0, *rgb(mix(bg, acc, 0.18))); g.add_color_stop_rgba(1, *rgb(bg))
        cr.set_source(g); cr.paint()
    profile = look.get("profile", "tiling")
    top = bottom = left = 0
    fs = 15 * (uis / 10.0)               # reference-space text size follows the UI font size
    def box(bx, by, bw, bh, col, a=1.0, r=0):
        rrect(cr, bx, by, bw, bh, r); cr.set_source_rgba(*rgb(col, a)); cr.fill()
    # --- bars of the desktop style
    if profile in ("windows", "beginner"):
        bottom = 36; box(0, REF_H - 36, REF_W, 36, surf)
        box(0, REF_H - 36, 44, 36, acc)
        for i, a in enumerate((1, .55, .55)):
            box(54 + i * 62, REF_H - 31, 54, 26, lighter if i else mix(lighter, acc, .35), 1, 5)
        if detail: FONTS.text(cr, REF_W - 14, REF_H - 27, "12:30", ui, fs, fg, align="r")
    elif profile == "macos":
        top = 24; box(0, 0, REF_W, 24, surf, .94)
        if detail:
            FONTS.text(cr, 14, 4, "Carpathian", ui, fs, fg, weight=Pango.Weight.SEMIBOLD); FONTS.text(cr, REF_W - 14, 4, "Wed 12:30", ui, fs, fg, align="r")
        dw = 5 * 52 + 24; box(REF_W / 2 - dw / 2, REF_H - 66, dw, 58, surf, .88, 14)
        for i in range(5): box(REF_W / 2 - dw / 2 + 14 + i * 52, REF_H - 58, 42, 42, mix(lighter, acc, .35) if i == 0 else lighter, 1, 10)
        bottom = 70
    elif profile == "ubuntu":
        top = 26; left = 58; box(0, 0, REF_W, 26, surf)
        if detail: FONTS.text(cr, REF_W / 2, 5, "Wed 12:30", ui, fs, fg, align="c")
        box(0, 26, 58, REF_H - 26, surf)
        for i in range(6): box(8, 36 + i * 50, 42, 42, mix(lighter, acc, .35) if i == 0 else lighter, 1, 10)
    else:   # tiling: dwm's own bar
        top = 28; box(0, 0, REF_W, 28, surf)
        for i in range(1, 7):
            if i == 1: box(6, 4, 30, 20, mix(surf, acc, .25), 1, 6); col = acc
            else: col = muted
            if detail: FONTS.text(cr, 21 + (i - 1) * 32 - (0 if i > 1 else 0), 5, str(i), mono, fs, col, align="c")
        if detail: FONTS.text(cr, REF_W - 12, 5, "12:30", mono, fs, fg, align="r")
    ax, ay, aw, ah = left, top, REF_W - left, REF_H - top - bottom
    # --- windows
    bw = float(look.get("border_px", 2)); bw = bw * 1.6 if bw else 0
    gap = float(look.get("gap", 8)) * 1.5
    ogap = float(look.get("outer_gap", look.get("gap", 8))) * 1.5
    rad = float(look.get("radius", 0)) * 1.6
    bcol = look.get("border_color") or acc
    ncol = mix(lighter, fg, .12)
    style = look.get("buttons") or "windows"
    tb = look.get("titlebars", True)
    ths = 34 if tb else 0
    icons = look.get("icons") or "Adwaita"
    def window(wx, wy, ww, wh, focused, title, body):
        cr.save()
        rrect(cr, wx, wy, ww, wh, rad); cr.clip_preserve()
        cr.set_source_rgba(*rgb(bg)); cr.fill()
        if ths:
            cr.save(); cr.rectangle(wx, wy, ww, ths); cr.clip()
            if draw_titlebar:
                draw_titlebar(cr, wx, wy, ww, ths, style, c, focused, None, None, look.get("side", "auto"), "all", title)
            else:
                box(wx, wy, ww, ths, surf)
            cr.restore()
        body(wx + 12, wy + ths + 10, ww - 24, wh - ths - 20)
        cr.restore()
        if bw:
            cr.save(); rrect(cr, wx + bw / 2, wy + bw / 2, ww - bw, wh - bw, max(0, rad - bw / 2)); cr.set_source_rgba(*rgb(bcol if focused else ncol))
            cr.set_line_width(bw); cr.stroke(); cr.restore()
    def term_body(bx, by, bw_, bh):
        if not detail: return
        yy = by
        for line, col in (("~ $ carpatic theme", acc), ("nord  gruvbox  tokyo-night", fg), ("~ $ ls Pictures", acc), ("Wallpapers  Screenshots", muted), ("~ $", acc)):
            if yy > by + bh - 14: break
            FONTS.text(cr, bx, yy, line, mono, fs, col, width=bw_); yy += fs * 1.55
    def files_body(bx, by, bw_, bh):
        if not detail: return
        names = ("folder", "utilities-terminal", "web-browser", "preferences-system")
        for i, n in enumerate(names):
            ic = PICS.icon(icons, n, 32)
            if ic:
                cr.save(); cr.set_source_surface(ic, bx + 4 + i * 54, by); cr.paint(); cr.restore()
            else:
                box(bx + 4 + i * 54, by, 32, 32, lighter, 1, 8)
        FONTS.text(cr, bx + 4, by + 44, "The quick brown fox", ui, fs, fg, width=bw_)
        FONTS.text(cr, bx + 4, by + 44 + fs * 1.6, "jumps over the lazy dog", ui, fs, muted, width=bw_)
    def text_body(bx, by, bw_, bh):
        if not detail: return
        for i, wd in enumerate((.9, .7, .8, .5)):
            box(bx, by + i * 14, bw_ * wd, 5, fg if i == 0 else muted, .55 if i else .8, 2)
    tiled = look.get("tiled", profile == "tiling")
    pad = gap
    if not detail:
        # thumbnail: two overlapping windows so the wallpaper (the theme's face) stays visible; border, corners and buttons still show
        ww, wh = aw * .52, ah * .50
        window(ax + aw * .10, ay + ah * .18, ww, wh, False, "", text_body)
        window(ax + aw * .34, ay + ah * .36, ww, wh, True, "", term_body)
    elif look.get("layout") == "tile" or tiled:
        mw = (aw - ogap * 2 - gap) * .56
        window(ax + ogap, ay + ogap, mw, ah - ogap * 2, True, "Terminal", term_body)
        sx = ax + ogap + mw + gap; sw = aw - ogap * 2 - gap - mw; sh = (ah - ogap * 2 - gap) / 2
        window(sx, ay + ogap, sw, sh, False, "Files", files_body)
        window(sx, ay + ogap + sh + gap, sw, sh, False, "Notes", text_body)
    else:
        # floating styles: two windows snapped side by side so border, corners, gaps and buttons all show
        cw = (aw - ogap * 2 - gap) / 2
        window(ax + ogap, ay + ogap + 20, cw, ah - ogap * 2 - 40, False, "Notes", text_body)
        window(ax + ogap + cw + gap, ay + ogap + 20, cw, ah - ogap * 2 - 40, True, "Files", files_body)
    cr.restore()


# ------------------------------------------------------------------ the picker card
def alpha_col(h, a): return rgb(h, a)


def draw_chip(cr, x, y, w, h, label, selected, pal, size=12, family="Inter", font_for_label=None, enabled=True):
    acc = pal["accent"]
    rrect(cr, x, y, w, h, h / 2)
    if selected:
        cr.set_source_rgba(*rgb(acc)); cr.fill()
        FONTS.text(cr, x + w / 2, y + (h - size * 1.25) / 2, label, font_for_label or family, size, pal["accent_fg"], align="c", weight=Pango.Weight.SEMIBOLD, width=w - 12)
    else:
        cr.set_source_rgba(*rgb(pal["fg"], .08)); cr.fill()
        FONTS.text(cr, x + w / 2, y + (h - size * 1.25) / 2, label, font_for_label or family, size, pal["fg"], alpha=.85, align="c", width=w - 12)
