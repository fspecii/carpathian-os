"""Window-button previews for Carpatic Settings (cairo). Mirrors desktop/dwm window-button styles (same geometry in u = bar height / 32,
same colour roles) so the picker shows what dwm will draw. All colours come from a theme palette dict (read_colors)."""
import math

STYLES = [  # id, label, one-line description
    ("windows", "Windows", "Flat glyph buttons, close turns red"),
    ("macos", "macOS", "Traffic lights on the left"),
    ("gnome", "GNOME / Ubuntu", "Round, subtle, symbolic"),
    ("kde", "KDE Breeze", "Flat icons, hover plate"),
    ("minimal", "Minimal dots", "Small dots, colour on hover"),
    ("ring", "Rings", "Thin outline circles"),
    ("squircle", "Squircles", "Rounded squares"),
    ("contrast", "High contrast", "Big outlined squares"),
    ("omarchy", "Omarchy", "Bare thin glyphs"),
    ("kylin", "Kylin", "Rounded plates, red close"),
    ("nothing", "Nothing", "Square, dot-matrix glyphs"),
    ("classic98", "Classic 98", "Silver bevels and a navy title"),
    ("luna", "Luna", "Blue title gradient and gel buttons"),
    ("none", "None", "Title bar only"),
]
# side (1 right), cell width, gap, margin, centred title, nominal   (all in u)
DEF = {"windows": (1, 46, 0, 0, 0), "macos": (0, 12, 8, 14, 1), "gnome": (1, 24, 6, 8, 1), "kde": (1, 24, 2, 6, 0), "minimal": (1, 10, 10, 14, 0),
       "ring": (1, 14, 9, 14, 0), "squircle": (1, 22, 6, 8, 0), "contrast": (1, 28, 6, 6, 0), "omarchy": (1, 12, 16, 14, 0), "kylin": (1, 30, 4, 4, 0), "nothing": (1, 24, 4, 10, 0), "classic98": (1, 18, 0, 3, 0), "luna": (1, 22, 2, 4, 0), "none": (1, 0, 0, 0, 0)}

def rgb(h, a=1.0):
    h = h.lstrip("#"); return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255, a)

def _glyph(cr, idx, cx, cy, g, s, restore=False, mac=False):
    h = g / 2; cr.set_line_width(s); cr.set_line_cap(1)   # round caps
    if idx == "min":
        cr.move_to(cx - h, cy); cr.line_to(cx + h, cy)
    elif idx == "close":
        cr.move_to(cx - h, cy - h); cr.line_to(cx + h, cy + h); cr.move_to(cx - h, cy + h); cr.line_to(cx + h, cy - h)
    elif mac:
        o = g * 0.36
        cr.move_to(cx - h, cy + h); cr.line_to(cx + h, cy - h)
        cr.move_to(cx + h, cy - h); cr.rel_line_to(-o, 0); cr.move_to(cx + h, cy - h); cr.rel_line_to(0, o)
        cr.move_to(cx - h, cy + h); cr.rel_line_to(o, 0); cr.move_to(cx - h, cy + h); cr.rel_line_to(0, -o)
    else:
        r = g * 0.1
        cr.new_sub_path(); cr.rectangle(cx - h, cy - h, g, g)
    cr.stroke()

def _rr(cr, x0, y0, x1, y1, r):
    r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
    cr.new_sub_path(); cr.arc(x1 - r, y0 + r, r, -math.pi / 2, 0); cr.arc(x1 - r, y1 - r, r, 0, math.pi / 2)
    cr.arc(x0 + r, y1 - r, r, math.pi / 2, math.pi); cr.arc(x0 + r, y0 + r, r, math.pi, 1.5 * math.pi); cr.close_path()

def _mix(a, b, amount):
    left, right = rgb(a)[:3], rgb(b)[:3]
    return "#" + "".join(f"{round((l + (r-l)*amount)*255):02x}" for l, r in zip(left, right))


def _gradient(cr, x, y, w, h, first, last, vertical=True):
    import cairo
    ramp = cairo.LinearGradient(x, y, x if vertical else x+w, y+h if vertical else y)
    ramp.add_color_stop_rgb(0, *rgb(first)[:3]); ramp.add_color_stop_rgb(1, *rgb(last)[:3])
    cr.set_source(ramp); cr.rectangle(x, y, w, h); cr.fill()


def draw_titlebar(cr, x, y, w, h, style, c, focused=True, hover=None, pressed=None, side="auto", shown="all", title="Terminal", layout=None):
    """Draws a title bar of height h at x,y. hover/pressed: 'min'|'max'|'close'|None. Returns nothing."""
    u = h / 32.0
    side_d, cw, gap, margin, center = DEF[style]
    right = side_d if side == "auto" else (1 if side == "right" else 0)
    bar = c.get("dark_background", "#171c25"); fg = c.get("foreground", "#e7ecf3"); acc = c.get("accent", "#5cc8a8")
    red, yel, grn = c.get("red", "#f0707a"), c.get("yellow", "#f2c25a"), c.get("green", "#7bd389")
    muted = c.get("muted", "#6b778c"); bgc = c.get("background", "#11151c")
    cr.save(); cr.rectangle(x, y, w, h); cr.clip()
    cr.set_source_rgba(*rgb(bar)); cr.paint()
    if style in ("classic98", "luna"):
        bar = acc if focused else bar
        fg = "#ffffff" if focused and sum(v*k for v,k in zip(rgb(bar)[:3], (.299,.587,.114))) < .55 else fg
        if style == "classic98":
            cr.set_source_rgba(*rgb("#c0c0c0")); cr.paint()
            _gradient(cr, x+3*u, y+3*u, w-6*u, h-5*u, bar, _mix(bar,"#ffffff",.35), False)
        else:
            _gradient(cr, x, y, w, h, _mix(bar,"#ffffff",.28 if focused else .12), _mix(bar,"#000000",.16 if focused else .06))
    cr.set_source_rgba(*rgb(acc if focused else c.get("lighter_background", "#1e2430"))); cr.rectangle(x, y, w, 1.5); cr.fill()
    order = ["close"] if shown == "close" else (["min", "max", "close"] if right else ["close", "min", "max"])
    cwp, gp, mp = cw * u, gap * u, margin * u
    n = len(order) if style != "none" else 0
    total = n * cwp + max(0, n - 1) * gp
    start = (x + w - mp - total) if right else (x + mp)
    cy = y + h / 2 + 0.5
    fa = 1.0 if focused else 0.6
    def col(hexs, a=1.0): cr.set_source_rgba(*rgb(hexs, a))
    for i, name in enumerate(order[:n] if n else []):
        cx = start + i * (cwp + gp) + cwp / 2
        hov = hover == name; prs = pressed == name; grp = hover is not None
        cc = {"close": red, "min": yel, "max": grn}[name]
        if style == "classic98":
            face = _mix("#c0c0c0", "#000000", .15) if prs else _mix("#c0c0c0", acc, .28) if hov else "#c0c0c0"
            bx, by = cx-cwp/2, cy-cwp/2
            col(face); cr.rectangle(bx,by,cwp,cwp); cr.fill()
            col("#808080" if prs else "#ffffff"); cr.rectangle(bx,by,cwp,u); cr.rectangle(bx,by,u,cwp); cr.fill()
            col("#ffffff" if prs else "#808080"); cr.rectangle(bx,by+cwp-u,cwp,u); cr.rectangle(bx+cwp-u,by,u,cwp); cr.fill()
            col("#000000" if focused else "#808080"); _glyph(cr,name,cx,cy+(3*u if name=="min" else 0),8*u,max(1,1.2*u))
        elif style == "luna":
            base = red if name == "close" else bar
            if prs: base=_mix(base,"#000000",.2)
            elif hov: base=_mix(base,"#ffffff",.15)
            bx, by = cx-cwp/2, cy-cwp/2
            cr.save(); _rr(cr,bx,by,bx+cwp,by+cwp,3.5*u); cr.clip()
            _gradient(cr,bx,by,cwp,cwp,_mix(base,"#ffffff",.35),_mix(base,"#000000",.2)); cr.restore()
            col("#ffffff",.75); cr.set_line_width(u); _rr(cr,bx,by,bx+cwp,by+cwp,3.5*u); cr.stroke()
            col("#ffffff",fa); _glyph(cr,name,cx,cy,9*u,max(1,1.2*u))
        elif style == "windows":
            if hov or prs:
                col(red if name == "close" else fg, (0.78 if prs else 1.0) if name == "close" else (0.16 if prs else 0.10)); cr.rectangle(cx - cwp / 2, y + 1.5, cwp, h - 1.5); cr.fill()
            col("#ffffff" if (name == "close" and (hov or prs)) else fg, fa); _glyph(cr, name, cx, cy, 10 * u, max(1, u))
        elif style == "macos":
            col(cc if focused else muted); cr.arc(cx, cy, 6 * u, 0, 6.3); cr.fill()
            if prs: cr.set_source_rgba(0, 0, 0, .25); cr.arc(cx, cy, 6 * u, 0, 6.3); cr.fill()
            cr.set_source_rgba(0, 0, 0, .18); cr.set_line_width(.8 * u); cr.arc(cx, cy, 5.6 * u, 0, 6.3); cr.stroke()
            if grp:
                cr.set_source_rgba(0, 0, 0, .62); _glyph(cr, name, cx, cy, (6.2 if name == "max" else 5.6) * u, max(1, 1.15 * u), mac=name == "max")
        elif style == "gnome":
            if name == "close" and (hov or prs): col(red, .45 if prs else .30)
            else: col(fg, .22 if prs else .14 if hov else .07)
            cr.arc(cx, cy, 12 * u, 0, 6.3); cr.fill(); col(fg, fa); _glyph(cr, name, cx, cy, 8 * u, max(1.2, 1.6 * u))
        elif style == "kde":
            if hov or prs:
                col(red if name == "close" else acc, (1.0 if prs else .88) if name == "close" else (.38 if prs else .22)); _rr(cr, cx - 11 * u, cy - 11 * u, cx + 11 * u, cy + 11 * u, 4 * u); cr.fill()
            col("#ffffff" if name == "close" and (hov or prs) else fg, fa); _glyph(cr, name, cx, cy, 10 * u, max(1, 1.3 * u))
        elif style == "minimal":
            if hov or prs: col(cc)
            else: col(fg, .55 * fa)
            cr.arc(cx, cy, 5 * u, 0, 6.3); cr.fill()
        elif style == "ring":
            st = max(1.1, 1.5 * u)
            if hov or prs: col(cc, .6 if prs else .3); cr.arc(cx, cy, 7 * u - st / 2, 0, 6.3); cr.fill()
            if hov or prs: col(cc)
            else: col(fg, .6 * fa)
            cr.set_line_width(st); cr.arc(cx, cy, 7 * u - st / 2, 0, 6.3); cr.stroke()
        elif style == "squircle":
            if hov or prs: col(red if name == "close" else acc, .7 if prs else .92)
            else: col(fg, .10)
            _rr(cr, cx - 11 * u, cy - 11 * u, cx + 11 * u, cy + 11 * u, 7 * u); cr.fill()
            col("#ffffff" if name == "close" and (hov or prs) else (bgc if hov or prs else fg), 1.0 if hov or prs else .85 * fa); _glyph(cr, name, cx, cy, 9 * u, max(1.1, 1.5 * u))
        elif style == "contrast":
            st = max(1.5, 2.2 * u)
            if hov or prs: col(fg, .8 if prs else 1.0); _rr(cr, cx - 14 * u, cy - 14 * u, cx + 14 * u, cy + 14 * u, 3 * u); cr.fill()
            col(fg); cr.set_line_width(st); _rr(cr, cx - 14 * u + st / 2, cy - 14 * u + st / 2, cx + 14 * u - st / 2, cy + 14 * u - st / 2, 3 * u); cr.stroke()
            col(bgc if hov or prs else fg); _glyph(cr, name, cx, cy, 12 * u, st * 1.1)
        elif style == "kylin":
            if hov or prs:
                if name == "close": col("#C21B24" if prs else "#E7202B")
                else: col(fg, .24 if prs else .16)
                _rr(cr, cx - 14 * u, cy - 14 * u, cx + 14 * u, cy + 14 * u, 6 * u); cr.fill()
            hot = (hov or prs) and name == "close"
            col("#ffffff" if hot else fg, (.75 if prs else 1.0) if hot else (1.0 if focused else .4)); _glyph(cr, name, cx, cy, 10 * u, max(1, 1.1 * u))
        elif style == "nothing":
            st = max(1.0, u); hh = 9 * u; hi = hov or prs
            if hi:
                if name == "close": col(acc, .7 if prs else 1.0)
                else: col(fg, .22 if prs else .12)
                cr.rectangle(cx - hh, cy - hh, 2 * hh, 2 * hh); cr.fill()
            col(fg, fa); cr.set_line_width(st); cr.rectangle(cx - hh + st / 2, cy - hh + st / 2, 2 * hh - st, 2 * hh - st); cr.stroke()
            col(bgc if hi and name == "close" else fg, fa)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if name == "min": on = dy == 1
                    elif name == "max": on = not (dx == 0 and dy == 0)
                    else: on = (dx != 0 and dy != 0) or (dx == 0 and dy == 0)
                    if on: cr.arc(cx + dx * 4.2 * u, cy + dy * 4.2 * u, max(.9, 1.15 * u), 0, 6.3); cr.fill()
        elif style == "omarchy":
            if hov or prs: col(red if name == "close" else acc, .7 if prs else 1.0)
            else: col(fg, .55 * fa)
            _glyph(cr, name, cx, cy, 12 * u, max(1, 1.4 * u))
    # title
    cr.select_font_face("Inter"); cr.set_font_size(max(9, 11 * u * 0.9))
    ext = cr.text_extents(title)
    if n == 0 or right:
        tx = x + 10 * u; room_r = start - 8 * u if n else x + w - 10 * u
        if center and n: tx = x + ((room_r - x) - ext.width) / 2
        elif center: tx = x + (w - ext.width) / 2
    else:
        tx = start + total + 8 * u + 4
        if center: tx = start + total + 8 * u + ((x + w - 10 * u) - (start + total + 8 * u) - ext.width) / 2
    col(fg, fa); cr.move_to(tx, cy + ext.height / 2 - 1); cr.show_text(title)
    cr.restore()

def draw_card(cr, w, h, style, colors_dark, colors_light, side="auto", shown="all"):
    """Two mini windows (dark above, light below) for the picker card."""
    th = 28
    for i, c in enumerate((colors_dark, colors_light)):
        oy = 6 + i * (th + 22)
        body = c.get("background", "#11151c")
        cr.set_source_rgba(*rgb(body)); cr.rectangle(8, oy, w - 16, th + 12); cr.fill()
        draw_titlebar(cr, 8, oy, w - 16, th, style, c, True, None, None, side, shown)
        cr.set_source_rgba(*rgb(c.get("foreground", "#fff"), .35)); cr.rectangle(16, oy + th + 4, w - 70, 3); cr.fill()
