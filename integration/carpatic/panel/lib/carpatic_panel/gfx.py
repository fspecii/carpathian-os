"""cairo/Pango drawing helpers and the Carpatic UI glyph set (24 px grid, 1.75 stroke, round caps and joins, one colour).

Everything here works on a plain cairo context, so views render identically on screen and into PNGs for the tests."""
import math, os
import cairo
import gi
gi.require_version("Pango", "1.0"); gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo

TAU = math.tau


# ----------------------------------------------------------------------------- shapes
def rrect(cr, x, y, w, h, r):
    r = max(0.0, min(r, w / 2, h / 2))
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def fill_rrect(cr, x, y, w, h, r, color):
    rrect(cr, x, y, w, h, r); cr.set_source_rgba(*color); cr.fill()


def stroke_rrect(cr, x, y, w, h, r, color, lw=1.0):
    """Border drawn *inside* the rectangle so it never gets clipped by the window edge."""
    rrect(cr, x + lw / 2, y + lw / 2, w - lw, h - lw, max(0, r - lw / 2)); cr.set_source_rgba(*color); cr.set_line_width(lw); cr.stroke()


def circle(cr, cx, cy, r, color):
    cr.new_sub_path(); cr.arc(cx, cy, r, 0, TAU); cr.set_source_rgba(*color); cr.fill()


# ----------------------------------------------------------------------------- text
_FEATURES = {}


def layout(cr, s, px, weight=400, family="Inter", tnum=False, maxw=None, markup=False):
    lay = PangoCairo.create_layout(cr)
    fd = Pango.FontDescription()
    fd.set_family(family); fd.set_absolute_size(px * Pango.SCALE)
    fd.set_weight(Pango.Weight(weight))
    lay.set_font_description(fd)
    if markup: lay.set_markup(s, -1)
    else: lay.set_text(s, -1)
    if tnum:
        al = Pango.AttrList(); al.insert(Pango.attr_font_features_new("tnum, lnum")); lay.set_attributes(al)
    if maxw is not None:
        lay.set_width(int(maxw * Pango.SCALE)); lay.set_ellipsize(Pango.EllipsizeMode.END)
    return lay


_SC = []


def _scratch():
    if not _SC: _SC.append(cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 8, 8)))
    return _SC[0]


def text_size(cr, s, px, weight=400, family="Inter", tnum=False, maxw=None):
    lay = layout(cr, s, px, weight, family, tnum, maxw)
    w, h = lay.get_pixel_size()
    return w, h


def text(cr, s, x, y, px, color, weight=400, anchor="l", maxw=None, tnum=False, family="Inter", valign="m"):
    """Draw one line. x is the left/centre/right edge by `anchor`; y is the vertical centre of the line (valign 'm') or the top ('t').
    Returns the drawn width."""
    if s is None or s == "": return 0
    lay = layout(cr, s, px, weight, family, tnum, maxw)
    w, h = lay.get_pixel_size()
    tx = x if anchor == "l" else (x - w / 2 if anchor == "c" else x - w)
    # centre on the x-height-ish middle so digits and lowercase look vertically centred in a box
    ty = y - h / 2 if valign == "m" else y
    cr.move_to(round(tx), round(ty)); cr.set_source_rgba(*color)
    PangoCairo.show_layout(cr, lay)
    return w


def wrap_text(cr, s, px, maxw, weight=400, family="Inter", max_lines=2):
    """Greedy word wrap with an ellipsis on the last line. Returns a list of lines."""
    words = s.split(); lines = []; cur = ""
    for w_ in words:
        t = (cur + " " + w_).strip()
        if text_size(cr, t, px, weight, family)[0] <= maxw or not cur: cur = t
        else:
            lines.append(cur); cur = w_
    if cur: lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and text_size(cr, last + "…", px, weight, family)[0] > maxw: last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines


# ----------------------------------------------------------------------------- glyphs
def _poly(cr, pts, close=False):
    cr.move_to(*pts[0])
    for p in pts[1:]: cr.line_to(*p)
    if close: cr.close_path()


def _arc(cr, cx, cy, r, a0, a1):
    cr.new_sub_path(); cr.arc(cx, cy, r, math.radians(a0), math.radians(a1))


def _circle_hits(c1, r1, c2, r2):
    dx, dy = c2[0] - c1[0], c2[1] - c1[1]
    d = math.hypot(dx, dy)
    a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
    h = math.sqrt(max(0, r1 * r1 - a * a))
    mx, my = c1[0] + a * dx / d, c1[1] + a * dy / d
    return (mx + h * dy / d, my - h * dx / d), (mx - h * dy / d, my + h * dx / d)


def glyph_wifi(cr, level=3, dim=0.3, color=None):
    cx, cy = 12, 19.2
    for i, r in enumerate((5.4, 10.2, 15.0), start=1):
        _set(cr, color, 1.0 if level >= i else dim)
        _arc(cr, cx, cy, r, -135, -45); cr.stroke()
    _set(cr, color, 1.0); cr.new_sub_path(); cr.arc(cx, cy, 1.6, 0, TAU); cr.fill()


def _set(cr, color, alpha=1.0):
    r, g, b, a = color
    cr.set_source_rgba(r, g, b, a * alpha)


def glyph(cr, name, cx, cy, size, color, lw=1.75, level=3, charging=False, extra=None):
    """Draw glyph `name` centred at (cx, cy) with the given pixel size. `level` is 0..3 (wifi, volume) or 0..100 (battery)."""
    fn = GLYPHS.get(name)
    if fn is None: fn = GLYPHS["dot"]
    cr.save()
    cr.translate(cx - size / 2, cy - size / 2); cr.scale(size / 24, size / 24)
    cr.set_line_width(lw); cr.set_line_cap(cairo.LINE_CAP_ROUND); cr.set_line_join(cairo.LINE_JOIN_ROUND)
    cr.set_source_rgba(*color)
    fn(cr, color, level, charging)
    cr.restore()


G = {}


def _reg(name):
    def deco(f): G[name] = f; return f
    return deco


@_reg("wifi")
def _(cr, c, level, ch): glyph_wifi(cr, level, color=c)


@_reg("wifi_off")
def _(cr, c, level, ch):
    glyph_wifi(cr, 3, dim=0.3, color=(c[0], c[1], c[2], c[3] * 0.55)); _set(cr, c); cr.move_to(4.5, 3.5); cr.line_to(19.5, 20.5); cr.stroke()


@_reg("bluetooth")
def _(cr, c, level, ch):
    _poly(cr, [(6.5, 7.5), (17, 16.5), (12, 21), (12, 3), (17, 7.5), (6.5, 16.5)]); cr.stroke()


@_reg("moon")
def _(cr, c, level, ch):
    c1, r1, c2, r2 = (11.5, 12.5), 8.6, (16.2, 8.3), 7.2
    p, q = _circle_hits(c1, r1, c2, r2)
    a1 = math.atan2(p[1] - c1[1], p[0] - c1[0]); a2 = math.atan2(q[1] - c1[1], q[0] - c1[0])
    b1 = math.atan2(q[1] - c2[1], q[0] - c2[0]); b2 = math.atan2(p[1] - c2[1], p[0] - c2[0])
    cr.new_sub_path(); cr.arc(c1[0], c1[1], r1, a1, a2 if a2 > a1 else a2 + TAU)
    cr.arc_negative(c2[0], c2[1], r2, b1, b2 if b2 < b1 else b2 - TAU)
    cr.close_path(); cr.stroke()


@_reg("moon_fill")
def _(cr, c, level, ch):
    c1, r1, c2, r2 = (11.5, 12.5), 8.6, (16.2, 8.3), 7.2
    p, q = _circle_hits(c1, r1, c2, r2)
    a1 = math.atan2(p[1] - c1[1], p[0] - c1[0]); a2 = math.atan2(q[1] - c1[1], q[0] - c1[0])
    b1 = math.atan2(q[1] - c2[1], q[0] - c2[0]); b2 = math.atan2(p[1] - c2[1], p[0] - c2[0])
    cr.new_sub_path(); cr.arc(c1[0], c1[1], r1, a1, a2 if a2 > a1 else a2 + TAU)
    cr.arc_negative(c2[0], c2[1], r2, b1, b2 if b2 < b1 else b2 - TAU)
    cr.close_path(); cr.fill_preserve(); cr.stroke()


@_reg("sun")
def _(cr, c, level, ch):
    cr.new_sub_path(); cr.arc(12, 12, 4.2, 0, TAU); cr.stroke()
    for i in range(8):
        a = i * math.pi / 4
        cr.move_to(12 + 7.4 * math.cos(a), 12 + 7.4 * math.sin(a)); cr.line_to(12 + 10 * math.cos(a), 12 + 10 * math.sin(a))
    cr.stroke()


@_reg("nightlight")
def _(cr, c, level, ch):
    # half-filled sun: warm light
    cr.new_sub_path(); cr.arc(12, 12, 4.4, 0, TAU); cr.stroke()
    cr.new_sub_path(); cr.arc(12, 12, 4.4, math.pi / 2, 3 * math.pi / 2); cr.close_path(); cr.fill()
    for i in range(8):
        a = i * math.pi / 4
        cr.move_to(12 + 7.6 * math.cos(a), 12 + 7.6 * math.sin(a)); cr.line_to(12 + 10 * math.cos(a), 12 + 10 * math.sin(a))
    cr.stroke()


@_reg("contrast")
def _(cr, c, level, ch):
    cr.new_sub_path(); cr.arc(12, 12, 8.5, 0, TAU); cr.stroke()
    cr.new_sub_path(); cr.arc(12, 12, 8.5, -math.pi / 2, math.pi / 2); cr.close_path(); cr.fill()


@_reg("bell")
def _(cr, c, level, ch):
    cr.new_sub_path(); cr.arc(12, 10.5, 6, math.pi, TAU)
    cr.line_to(18, 16.5); cr.line_to(19.6, 18.2); cr.line_to(4.4, 18.2); cr.line_to(6, 16.5); cr.close_path(); cr.stroke()
    cr.new_sub_path(); cr.arc(12, 19.6, 2.1, 0.15 * math.pi, 0.85 * math.pi); cr.stroke()
    cr.move_to(12, 3.2); cr.line_to(12, 4.6); cr.stroke()


@_reg("bell_off")
def _(cr, c, level, ch):
    G["bell"](cr, (c[0], c[1], c[2], c[3] * 0.6), level, ch); _set(cr, c); cr.move_to(4, 3.5); cr.line_to(20, 20.5); cr.stroke()


@_reg("airplane")
def _(cr, c, level, ch):
    _poly(cr, [(12, 2.8), (13.4, 4.4), (13.4, 9.2), (21, 14), (21, 16.2), (13.4, 13.8), (13.4, 17.6), (15.8, 19.4), (15.8, 20.8),
               (12, 19.7), (8.2, 20.8), (8.2, 19.4), (10.6, 17.6), (10.6, 13.8), (3, 16.2), (3, 14), (10.6, 9.2), (10.6, 4.4)], True); cr.stroke()


@_reg("battery")
def _(cr, c, level, ch):
    rrect(cr, 2.5, 7, 17.5, 10, 2.6); cr.stroke()
    cr.move_to(22.2, 10.6); cr.line_to(22.2, 13.4); cr.stroke()
    lv = max(0, min(100, level))
    if lv > 0:
        w = max(1.6, 12.5 * lv / 100)
        rrect(cr, 5, 9.5, w, 5, 1.3); cr.fill()
    if ch:
        # bolt cut out look: draw a small bolt in the surface-contrasting way (outline only)
        pass


@_reg("bolt")
def _(cr, c, level, ch):
    _poly(cr, [(13.2, 2.8), (5.6, 13.4), (11.4, 13.4), (10.6, 21.2), (18.4, 10.2), (12.6, 10.2)], True); cr.stroke()


@_reg("bolt_fill")
def _(cr, c, level, ch):
    _poly(cr, [(13.2, 2.8), (5.6, 13.4), (11.4, 13.4), (10.6, 21.2), (18.4, 10.2), (12.6, 10.2)], True); cr.fill_preserve(); cr.stroke()


@_reg("power")
def _(cr, c, level, ch):
    cr.new_sub_path(); cr.arc(12, 13, 7.6, math.radians(-52), math.radians(232)); cr.stroke()
    cr.move_to(12, 3.4); cr.line_to(12, 12); cr.stroke()


@_reg("lock")
def _(cr, c, level, ch):
    rrect(cr, 4.8, 10.6, 14.4, 10.2, 2.6); cr.stroke()
    cr.new_sub_path(); cr.move_to(8, 10.6); cr.line_to(8, 8); cr.arc(12, 8, 4, math.pi, TAU); cr.line_to(16, 10.6); cr.stroke()
    cr.new_sub_path(); cr.arc(12, 15.7, 1.3, 0, TAU); cr.fill()


@_reg("unlock")
def _(cr, c, level, ch):
    rrect(cr, 4.8, 10.6, 14.4, 10.2, 2.6); cr.stroke()
    cr.new_sub_path(); cr.move_to(8, 10.6); cr.line_to(8, 8); cr.arc(12, 8, 4, math.pi, 1.8 * math.pi); cr.stroke()


@_reg("gear")
def _(cr, c, level, ch):
    n = 8; pts = []
    for i in range(n):
        a = i * TAU / n
        for da, r in ((-0.30, 7.6), (-0.19, 9.8), (0.19, 9.8), (0.30, 7.6)):
            pts.append((12 + r * math.cos(a + da), 12 + r * math.sin(a + da)))
    _poly(cr, pts, True); cr.stroke()
    cr.new_sub_path(); cr.arc(12, 12, 3.1, 0, TAU); cr.stroke()


@_reg("sliders")
def _(cr, c, level, ch):
    for y, kx in ((6, 9), (12, 15.5), (18, 8)):
        cr.move_to(3.5, y); cr.line_to(20.5, y); cr.stroke()
        cr.new_sub_path(); cr.arc(kx, y, 2.6, 0, TAU); cr.stroke()


@_reg("volume")
def _(cr, c, level, ch):
    _poly(cr, [(3.5, 9.4), (7.6, 9.4), (12.4, 5.2), (12.4, 18.8), (7.6, 14.6), (3.5, 14.6)], True); cr.stroke()
    if level >= 1: _arc(cr, 12.4, 12, 4.6, -52, 52); cr.stroke()
    if level >= 2: _arc(cr, 12.4, 12, 8.4, -52, 52); cr.stroke()


@_reg("volume_mute")
def _(cr, c, level, ch):
    _poly(cr, [(3.5, 9.4), (7.6, 9.4), (12.4, 5.2), (12.4, 18.8), (7.6, 14.6), (3.5, 14.6)], True); cr.stroke()
    cr.move_to(16.2, 9.4); cr.line_to(21, 14.6); cr.move_to(21, 9.4); cr.line_to(16.2, 14.6); cr.stroke()


@_reg("headphones")
def _(cr, c, level, ch):
    cr.new_sub_path(); cr.arc(12, 13, 8, math.pi, TAU); cr.stroke()
    rrect(cr, 3.6, 13, 4.2, 6.6, 2); cr.stroke(); rrect(cr, 16.2, 13, 4.2, 6.6, 2); cr.stroke()


@_reg("mic")
def _(cr, c, level, ch):
    rrect(cr, 9, 3, 6, 11.4, 3); cr.stroke()
    cr.new_sub_path(); cr.arc(12, 11, 6.6, 0, math.pi); cr.stroke()
    cr.move_to(12, 17.6); cr.line_to(12, 21); cr.move_to(8.6, 21); cr.line_to(15.4, 21); cr.stroke()


@_reg("search")
def _(cr, c, level, ch):
    cr.new_sub_path(); cr.arc(10.5, 10.5, 6.6, 0, TAU); cr.stroke()
    cr.move_to(15.4, 15.4); cr.line_to(20.6, 20.6); cr.stroke()


@_reg("winlogo")
def _(cr, c, level, ch):
    for x, y in ((3.2, 3.2), (13.1, 3.2), (3.2, 13.1), (13.1, 13.1)):
        rrect(cr, x, y, 7.7, 7.7, 1.5); cr.fill()


@_reg("apps")
def _(cr, c, level, ch):
    for i in range(3):
        for j in range(3):
            cr.new_sub_path(); cr.arc(5 + i * 7, 5 + j * 7, 1.9, 0, TAU); cr.fill()


@_reg("grid")
def _(cr, c, level, ch):
    for x, y in ((3.5, 3.5), (13.5, 3.5), (3.5, 13.5), (13.5, 13.5)):
        rrect(cr, x, y, 7, 7, 2); cr.stroke()


@_reg("chevron_r")
def _(cr, c, level, ch): _poly(cr, [(9, 5), (16, 12), (9, 19)]); cr.stroke()


@_reg("chevron_l")
def _(cr, c, level, ch): _poly(cr, [(15, 5), (8, 12), (15, 19)]); cr.stroke()


@_reg("chevron_u")
def _(cr, c, level, ch): _poly(cr, [(5, 15), (12, 8), (19, 15)]); cr.stroke()


@_reg("chevron_d")
def _(cr, c, level, ch): _poly(cr, [(5, 9), (12, 16), (19, 9)]); cr.stroke()


@_reg("plus")
def _(cr, c, level, ch): cr.move_to(12, 5); cr.line_to(12, 19); cr.move_to(5, 12); cr.line_to(19, 12); cr.stroke()


@_reg("minus")
def _(cr, c, level, ch): cr.move_to(5, 12); cr.line_to(19, 12); cr.stroke()


@_reg("close")
def _(cr, c, level, ch): cr.move_to(6, 6); cr.line_to(18, 18); cr.move_to(18, 6); cr.line_to(6, 18); cr.stroke()


@_reg("check")
def _(cr, c, level, ch): _poly(cr, [(5, 12.6), (10, 17.4), (19, 7)]); cr.stroke()


@_reg("record")
def _(cr, c, level, ch):
    cr.new_sub_path(); cr.arc(12, 12, 8.6, 0, TAU); cr.stroke(); cr.new_sub_path(); cr.arc(12, 12, 4.2, 0, TAU); cr.fill()


@_reg("capture")
def _(cr, c, level, ch):
    for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
        x, y = 12 + sx * 8.6, 12 + sy * 8.6
        cr.move_to(x - sx * 5, y); cr.line_to(x, y); cr.line_to(x, y - sy * 5); cr.stroke()
    cr.new_sub_path(); cr.arc(12, 12, 2.2, 0, TAU); cr.fill()


@_reg("folder")
def _(cr, c, level, ch):
    _poly(cr, [(3.5, 6.5), (3.5, 18.5), (20.5, 18.5), (20.5, 8.5), (11, 8.5), (9.2, 5.5), (3.5, 5.5)], True); cr.stroke()


@_reg("home")
def _(cr, c, level, ch):
    _poly(cr, [(3.5, 11), (12, 3.8), (20.5, 11)]); cr.stroke()
    _poly(cr, [(5.8, 9.4), (5.8, 20), (18.2, 20), (18.2, 9.4)]); cr.stroke()
    _poly(cr, [(10, 20), (10, 14.2), (14, 14.2), (14, 20)]); cr.stroke()


@_reg("user")
def _(cr, c, level, ch):
    cr.new_sub_path(); cr.arc(12, 8.2, 4, 0, TAU); cr.stroke()
    cr.new_sub_path(); cr.arc(12, 21.2, 8, math.radians(215), math.radians(325)); cr.stroke()


@_reg("hotspot")
def _(cr, c, level, ch):
    cr.new_sub_path(); cr.arc(12, 12, 1.9, 0, TAU); cr.fill()
    for r in (5.2, 9.2):
        _arc(cr, 12, 12, r, -48, 48); cr.stroke(); _arc(cr, 12, 12, r, 132, 228); cr.stroke()


@_reg("play")
def _(cr, c, level, ch): _poly(cr, [(7, 4.6), (19, 12), (7, 19.4)], True); cr.fill_preserve(); cr.stroke()


@_reg("pause")
def _(cr, c, level, ch):
    rrect(cr, 6.4, 4.6, 3.8, 14.8, 1.3); cr.fill(); rrect(cr, 13.8, 4.6, 3.8, 14.8, 1.3); cr.fill()


@_reg("next")
def _(cr, c, level, ch):
    _poly(cr, [(5, 5.6), (15.4, 12), (5, 18.4)], True); cr.fill_preserve(); cr.stroke(); cr.move_to(19, 5.6); cr.line_to(19, 18.4); cr.stroke()


@_reg("prev")
def _(cr, c, level, ch):
    _poly(cr, [(19, 5.6), (8.6, 12), (19, 18.4)], True); cr.fill_preserve(); cr.stroke(); cr.move_to(5, 5.6); cr.line_to(5, 18.4); cr.stroke()


@_reg("music")
def _(cr, c, level, ch):
    cr.new_sub_path(); cr.arc(7.6, 17.4, 3.1, 0, TAU); cr.fill()
    cr.move_to(10.7, 17.4); cr.line_to(10.7, 5.4); cr.line_to(19, 3.6); cr.line_to(19, 14.6); cr.stroke()
    cr.new_sub_path(); cr.arc(16.1, 14.6, 2.9, 0, TAU); cr.fill()


@_reg("globe")
def _(cr, c, level, ch):
    cr.new_sub_path(); cr.arc(12, 12, 8.6, 0, TAU); cr.stroke()
    cr.save(); cr.translate(12, 12); cr.scale(0.42, 1); cr.new_sub_path(); cr.arc(0, 0, 8.6, 0, TAU); cr.restore(); cr.stroke()
    cr.move_to(3.4, 12); cr.line_to(20.6, 12); cr.stroke()


@_reg("ethernet")
def _(cr, c, level, ch):
    rrect(cr, 9, 3.6, 6, 5, 1.2); cr.stroke(); rrect(cr, 3, 15.4, 6, 5, 1.2); cr.stroke(); rrect(cr, 15, 15.4, 6, 5, 1.2); cr.stroke()
    _poly(cr, [(12, 8.6), (12, 12), (6, 12), (6, 15.4)]); cr.stroke(); _poly(cr, [(12, 12), (18, 12), (18, 15.4)]); cr.stroke()


@_reg("refresh")
def _(cr, c, level, ch):
    _arc(cr, 12, 12, 7.8, -30, 250); cr.stroke(); _poly(cr, [(15.6, 3.6), (17.2, 7.2), (13.4, 8.4)]); cr.stroke()


@_reg("trash")
def _(cr, c, level, ch):
    cr.move_to(4, 6.6); cr.line_to(20, 6.6); cr.move_to(9.4, 6.6); cr.line_to(9.4, 4); cr.line_to(14.6, 4); cr.line_to(14.6, 6.6); cr.stroke()
    _poly(cr, [(6, 6.6), (7, 20), (17, 20), (18, 6.6)]); cr.stroke()


@_reg("calendar")
def _(cr, c, level, ch):
    rrect(cr, 3.5, 5, 17, 15.5, 3); cr.stroke(); cr.move_to(3.5, 10.2); cr.line_to(20.5, 10.2); cr.move_to(8, 3); cr.line_to(8, 6.6)
    cr.move_to(16, 3); cr.line_to(16, 6.6); cr.stroke()


@_reg("clock")
def _(cr, c, level, ch):
    cr.new_sub_path(); cr.arc(12, 12, 8.6, 0, TAU); cr.stroke(); _poly(cr, [(12, 7), (12, 12), (15.6, 14)]); cr.stroke()


@_reg("desktop")
def _(cr, c, level, ch):
    rrect(cr, 3, 4.6, 18, 12, 2.2); cr.stroke(); cr.move_to(8.4, 20); cr.line_to(15.6, 20); cr.stroke()


@_reg("taskview")
def _(cr, c, level, ch):
    rrect(cr, 3.4, 7.4, 13, 10.6, 2.2); cr.stroke(); _poly(cr, [(8, 4.6), (19, 4.6), (20.6, 6.2), (20.6, 14.6)]); cr.stroke()


@_reg("widgets")
def _(cr, c, level, ch):
    for x, y in ((3.6, 3.6), (13.4, 3.6), (3.6, 13.4), (13.4, 13.4)):
        rrect(cr, x, y, 7, 7, 1.8); cr.stroke()


@_reg("keyboard")
def _(cr, c, level, ch):
    rrect(cr, 2.5, 6, 19, 12, 2.4); cr.stroke()
    for x in (6.4, 10, 13.6, 17.2): cr.new_sub_path(); cr.arc(x, 10, 0.7, 0, TAU); cr.fill()
    cr.move_to(8, 14.2); cr.line_to(16, 14.2); cr.stroke()


@_reg("leaf")
def _(cr, c, level, ch):
    cr.move_to(5, 19); cr.curve_to(4, 10, 10, 4, 20, 4); cr.curve_to(20.6, 13, 15, 19.6, 6.6, 18.6); cr.stroke()
    cr.move_to(4.6, 20.4); cr.line_to(13, 11.6); cr.stroke()


@_reg("gauge")
def _(cr, c, level, ch):
    _arc(cr, 12, 14, 8.6, 180, 360); cr.stroke(); cr.move_to(12, 14); cr.line_to(16.2, 9.4); cr.stroke()
    cr.move_to(3.4, 14); cr.line_to(3.4, 14.01); cr.move_to(20.6, 14); cr.line_to(20.6, 14.01); cr.stroke()


@_reg("more")
def _(cr, c, level, ch):
    for x in (5.5, 12, 18.5): cr.new_sub_path(); cr.arc(x, 12, 1.7, 0, TAU); cr.fill()


@_reg("pin")
def _(cr, c, level, ch):
    _poly(cr, [(9, 3.6), (15, 3.6), (14.2, 9.4), (17.6, 13), (6.4, 13), (9.8, 9.4)], True); cr.stroke(); cr.move_to(12, 13); cr.line_to(12, 20.6); cr.stroke()


@_reg("edit")
def _(cr, c, level, ch):
    _poly(cr, [(4, 20), (4.8, 15.4), (16.4, 3.8), (20.2, 7.6), (8.6, 19.2)], True); cr.stroke(); cr.move_to(13.8, 6.4); cr.line_to(17.6, 10.2); cr.stroke()


@_reg("signal")
def _(cr, c, level, ch):
    for i, h in enumerate((5, 9, 13, 17)):
        _set(cr, c, 1.0 if level > i else 0.3); rrect(cr, 4 + i * 4.6, 20 - h, 3, h, 1.2); cr.fill()


@_reg("eye")
def _(cr, c, level, ch):
    cr.move_to(2.6, 12); cr.curve_to(6, 5.6, 18, 5.6, 21.4, 12); cr.curve_to(18, 18.4, 6, 18.4, 2.6, 12); cr.stroke()
    cr.new_sub_path(); cr.arc(12, 12, 3.2, 0, TAU); cr.stroke()


@_reg("star")
def _(cr, c, level, ch):
    pts = []
    for i in range(10):
        r = 9.2 if i % 2 == 0 else 4.1; a = -math.pi / 2 + i * math.pi / 5
        pts.append((12 + r * math.cos(a), 12.6 + r * math.sin(a)))
    _poly(cr, pts, True); cr.stroke()


@_reg("cloud")
def _(cr, c, level, ch):
    cr.move_to(7.4, 18.6); cr.curve_to(3.4, 18.6, 3, 12.6, 7.6, 12.2); cr.curve_to(8, 7.6, 15.6, 6.8, 16.6, 12); cr.curve_to(21.6, 11.8, 21.8, 18.6, 17, 18.6); cr.close_path(); cr.stroke()


@_reg("dot")
def _(cr, c, level, ch):
    cr.new_sub_path(); cr.arc(12, 12, 3, 0, TAU); cr.fill()


@_reg("menu")
def _(cr, c, level, ch):
    for y in (6.5, 12, 17.5): cr.move_to(4, y); cr.line_to(20, y)
    cr.stroke()


@_reg("battery_saver")
def _(cr, c, level, ch):
    G["battery"](cr, c, 60, False); cr.move_to(12.6, 8.9); cr.line_to(12.6, 15.1); cr.move_to(9.5, 12); cr.line_to(15.7, 12); cr.stroke()


GLYPHS = G


def app_letter_icon(cr, x, y, size, letter, bg, fg, radius=None):
    """Fallback app icon: rounded square with the first letter (never a blank box)."""
    r = radius if radius is not None else size * 0.225
    fill_rrect(cr, x, y, size, size, r, bg)
    text(cr, (letter or "?")[:1].upper(), x + size / 2, y + size / 2, size * 0.5, fg, 600, "c")


# ----------------------------------------------------------------------------- app icons from the icon theme
_ICON_CACHE = {}


def load_icon(name, size, scale=1):
    """Icon-theme lookup -> cairo surface that draws `size` logical px (or None). Accepts absolute paths. The pixels are loaded at the display scale
    (size x scale x UI scale) and the surface carries the matching device scale, so icons stay sharp at 125%, 150%, 200%."""
    from . import uiscale
    f = uiscale.factor()
    key = (name, size, scale, f)
    if key in _ICON_CACHE: return _ICON_CACHE[key]
    surf = None
    try:
        import gi
        gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0")
        from gi.repository import Gtk, Gdk, GdkPixbuf
        pb = None
        n = max(1, int(math.ceil(size * scale * f - 1e-6)))        # device pixels of the icon
        if name and os.path.isabs(name) and os.path.exists(name):
            pb = GdkPixbuf.Pixbuf.new_from_file_at_size(name, n, n)
        elif name:
            th = Gtk.IconTheme.get_default()
            info = th.lookup_icon(name, n, Gtk.IconLookupFlags.FORCE_SIZE)
            if info is not None: pb = info.load_icon()
        if pb is not None:
            surf = Gdk.cairo_surface_create_from_pixbuf(pb, 1, None)
            ds = surf.get_width() / float(size)
            if ds != 1.0: surf.set_device_scale(ds, ds)
    except Exception:
        surf = None
    if len(_ICON_CACHE) > 400: _ICON_CACHE.clear()
    _ICON_CACHE[key] = surf
    return surf


def logical_w(surf):
    """Width of an icon surface in logical px (icon surfaces carry the UI scale as their device scale)."""
    return surf.get_width() / surf.get_device_scale()[0]


def draw_icon(cr, name, x, y, size, fallback_letter=None, theme=None, scale=1):
    surf = load_icon(name, size, scale)
    if surf is not None:
        cr.save(); cr.translate(x, y); cr.set_source_surface(surf, 0, 0); cr.paint(); cr.restore(); return True
    if theme is not None:
        app_letter_icon(cr, x, y, size, fallback_letter or name or "?", theme.surface2 if hasattr(theme, "surface2") else (0.3, 0.3, 0.3, 1), theme.fg)
    return False


def argb_to_surface(data, w, h):
    """_NET_WM_ICON pixels (list of ARGB uint32) -> cairo surface."""
    import array
    a = array.array("I", data[:w * h])
    surf = cairo.ImageSurface.create_for_data(bytearray(a.tobytes()), cairo.FORMAT_ARGB32, w, h, w * 4)
    return surf


def lerp(a, b, t): return a + (b - a) * t


def ease_out(t): return 1 - (1 - t) ** 3


def ease_inout(t): return 3 * t * t - 2 * t * t * t
