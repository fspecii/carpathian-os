"""Carpathian theme picker: the card (header, large live preview, option strip, row list, key hints). Pure drawing + hit regions, driven by a
tp_model.Session; the GTK shell (bin/carpatic-theme-picker-ui) only forwards events and keeps time. Renders to a PNG on the host for tests."""
import math, os
import gi
gi.require_version("Pango", "1.0")
import cairo
from gi.repository import Pango
import tp_render as R
from tp_render import rgb, mix, rrect, FONTS
from tp_data import lum, profile_defaults, label_for, default_for, theme_accent

CW, CH = 1040, 640            # design size of the card
PAD = 24
LX, LW = PAD, 620             # left column: header, preview, option strip
PV_Y, PV_H = 84, 349          # large preview (620 x 349 = 16:9)
STRIP_Y, STRIP_H = 449, 118
RX, RW = 668, 348             # right column: the rows
ROW_Y, ROW_H = 24, 34
FOOT_Y = CH - 52
RADIUS = 14


def palette(colors, accent):
    surf = colors.get("dark_background", colors.get("background", "#171c25"))
    bg = colors.get("background", "#11151c")
    fg = colors.get("foreground", "#e7ecf3")
    acc = accent or colors.get("accent", "#5cc8a8")
    light = colors.get("mode", "dark") == "light"
    return {"surf": surf, "bg": bg, "fg": fg, "accent": acc, "accent_fg": "#08241d" if lum(acc) > 140 else "#ffffff",
            "muted": mix(fg, surf, .38), "subtle": mix(fg, surf, .58), "inset": mix(surf, fg, .07), "border": mix(surf, fg, .15),
            "border_strong": mix(surf, fg, .26), "soft": mix(surf, acc, .17), "light": light, "danger": colors.get("red", "#f0707a")}


def ease(t): return 1 - (1 - t) ** 3


def _ui_scale():
    """The display scale (1.0 .. 3.0) from carpatic_scale when it is installed."""
    try:
        import sys
        for p in ("/usr/local/lib/carpatic", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "configurator", "lib")):
            if os.path.isdir(p) and p not in sys.path: sys.path.append(p)
        import carpatic_scale
        return carpatic_scale.factor()
    except Exception:
        return 1.0


class Card:
    def __init__(self, cat, session, ui_font="Inter", mono_font="JetBrains Mono", ui_size=10):
        self.cat, self.s = cat, session
        self.ui, self.mono, self.uis = ui_font, mono_font, ui_size
        self.status = ""                 # right side of the footer
        self.strip_x = None              # animated scroll offset of the option strip (px, design space)
        self.row_scroll = 0.0
        self.regions = []                # (kind, (x, y, w, h), payload) in design space, rebuilt by every draw
        self.scale = 1.0; self.ox = self.oy = 0
        self.thumbs = {}                 # look key -> surface
        self.mode_flip = 0.0
        self.toast = ""

    # ---------------------------------------------------------------- looks
    def eff_colors(self, theme=None):
        st = self.s.state
        return self.cat.colors(theme or st.get("THEME") or "carpatic")

    def look(self, theme=None, wallpaper=None, detail=True):
        st = self.s.state; cur = st.get("THEME") or "carpatic"; theme = theme or cur
        colors = self.cat.colors(theme); mode = colors.get("mode", "dark")
        profile = st.get("PROFILE") or "tiling"
        pd = profile_defaults(self.cat, profile, mode)
        acc = theme_accent(self.cat, st, theme)
        # for another theme (a thumbnail) the look rows still apply, but its own look file and palette decide the defaults
        probe = dict(st, THEME=theme)
        E = lambda key: st.get(key) or default_for(self.cat, probe, key)
        bcol = (st.get("BORDER_ACTIVE") if theme == cur else "") or acc
        if wallpaper is None:
            wallpaper = (st.get("WALLPAPER") if theme == cur else "") or self.cat.default_wallpaper(theme)
        return {"colors": colors, "accent": acc, "wallpaper": wallpaper, "profile": profile, "border_px": E("BORDER_WIDTH"),
                "border_color": bcol, "gap": E("INNER_GAP"), "outer_gap": E("OUTER_GAP"), "radius": E("CORNER_RADIUS"),
                "buttons": E("WINDOW_BUTTONS"), "side": "auto", "titlebars": (pd["titlebars"] and profile != "tiling") or self.s.row.id == "buttons",   # the Window buttons row shows them even on a style that hides title bars
                "ui_font": E("UI_FONT") or pd["ui_font"], "ui_size": E("UI_SIZE"), "mono_font": E("MONO_FONT") or pd["mono"],
                "icons": E("ICON_THEME") or pd["icons"], "layout": pd["layout"], "tiled": profile == "tiling"}

    def thumb(self, theme=None, wallpaper=None, w=148, h=83, make=True):
        lk = self.look(theme, wallpaper, detail=False)
        key = (w, h, lk["wallpaper"], lk["accent"], lk["profile"], lk["border_px"], lk["border_color"], lk["gap"], lk["outer_gap"], lk["radius"], lk["buttons"],
               tuple(sorted(lk["colors"].items())))
        t = self.thumbs.get(key)
        if t is None and make:
            path = self._thumb_path(key)
            try: t = cairo.ImageSurface.create_from_png(path)
            except Exception: t = None
            if t is None or t.get_width() != w:
                t = cairo.ImageSurface(cairo.FORMAT_RGB24, w, h)
                c = cairo.Context(t); R.draw_mock(c, 0, 0, w, h, lk, detail=False)
                try:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    tmp = "%s.%d" % (path, os.getpid()); t.write_to_png(tmp); os.replace(tmp, path)
                except OSError:
                    pass
            if len(self.thumbs) > 200: self.thumbs.pop(next(iter(self.thumbs)))
            self.thumbs[key] = t
        return t

    def _thumb_path(self, key):
        import hashlib
        wp = key[2]
        try: mt = os.path.getmtime(wp)
        except OSError: mt = 0
        h = hashlib.sha1(repr((key, mt, "v3")).encode()).hexdigest()[:24]
        return os.path.join(os.path.expanduser("~/.cache/carpatic/themepicker"), h + ".png")

    def prefetch_paths(self):
        """Wallpapers the next Left/Right press will want (the two neighbours each way of the focused theme or wallpaper row)."""
        row = self.s.row; out = []
        if row.id not in ("theme", "wallpaper", "mode"): return out
        opts = self.s.visible_options(row)
        cur = row.current(self.s.state)
        pos = next((n for n, (i, _) in enumerate(opts) if i == cur), 0)
        for d in (1, -1, 2, -2):
            if not opts: break
            o = opts[(pos + d) % len(opts)][1]
            if row.id == "wallpaper": p = o.meta.get("path")
            elif row.id == "theme": p = self.cat.default_wallpaper(o.value)
            else: p = self.cat.default_wallpaper(self.cat.counterpart(self.s.state.get("THEME") or "carpatic", o.value))
            if p and p not in out: out.append(p)
        return out

    # ---------------------------------------------------------------- drawing
    def fit(self, w, h, margin=24):
        s = min(1.0, (w - margin) / CW, (h - margin) / CH)
        if margin and w >= 1500 and h >= 960: s = min(max(1.25, _ui_scale()), (w - 200) / CW, (h - 200) / CH)   # roomy screens get a bigger card (1.25, or the display scale when that is larger)
        self.scale = max(.5, s); self.ox = (w - CW * self.scale) / 2; self.oy = (h - CH * self.scale) / 2
        return self.scale

    def draw(self, cr, w, h, margin=0, scale=None):
        """Draws the card centred in a w x h window (the window is exactly the card, or larger for tests)."""
        st = self.s.state; colors = self.eff_colors(); pal = palette(colors, st.get("ACCENT"))
        self.pal = pal; self.regions = []
        if scale: self.scale = scale; self.ox = (w - CW * scale) / 2; self.oy = (h - CH * scale) / 2     # on screen: the window was sized for exactly this scale (1.25 on big screens)
        else: self.fit(w, h, margin)
        cr.save(); cr.translate(self.ox, self.oy); cr.scale(self.scale, self.scale)
        # card
        rrect(cr, 0, 0, CW, CH, RADIUS); cr.set_source_rgba(*rgb(pal["surf"])); cr.fill_preserve()
        cr.set_source_rgba(*rgb(pal["border_strong"])); cr.set_line_width(1); cr.stroke()
        cr.save(); rrect(cr, 0, 0, CW, CH, RADIUS); cr.clip()
        import time as _t
        self.timing = {}
        for name, fn in (("header", self._header), ("preview", self._preview), ("strip", self._strip), ("rows", self._rows), ("footer", self._footer)):
            t0 = _t.perf_counter(); fn(cr, pal); self.timing[name] = round((_t.perf_counter() - t0) * 1000, 1)
        s = self.s
        if s.hex_entry is not None:
            e = {"title": "Your own colour", "text": s.hex_entry, "hint": "Type six digits, like ff8800. Enter keeps it, Esc cancels.", "swatch": s.hex_entry if len(s.hex_entry) == 7 else None}
            self._entry(cr, pal, e)
        elif s.save_entry is not None:
            self._entry(cr, pal, {"title": "Save as my theme", "text": s.save_entry, "hint": "Give it a name and press Enter. It joins your theme list."})
        cr.restore(); cr.restore()

    def _t(self, cr, x, y, s, size, color, **kw):
        return FONTS.text(cr, x, y, s, kw.pop("family", self.ui), size, color, **kw)

    def _header(self, cr, pal):
        row = self.s.row; st = self.s.state
        opts = row.options(st); ci = row.current(st)
        name = opts[ci].label if 0 <= ci < len(opts) else (opts[0].label if opts else "")
        if row.id == "theme": name = label_for(st.get("THEME") or "carpatic")
        self._t(cr, LX, PAD, row.label.upper(), 11, pal["subtle"], weight=Pango.Weight.SEMIBOLD)
        self._t(cr, LX, PAD + 17, name, 24, pal["fg"], weight=Pango.Weight.SEMIBOLD, width=LW - 150)
        if 0 <= ci < len(opts) and len(opts) > 1:
            self._t(cr, LX + LW, PAD + 26, "%d of %d" % (ci + 1, len(opts)), 12, pal["muted"], align="r")

    def _preview(self, cr, pal):
        lk = self.look()
        key = (round(self.scale, 3),) + tuple(sorted((k, str(v)) for k, v in lk.items() if k != "colors")) + (lk["colors"].get("background"), lk["colors"].get("accent"), lk["colors"].get("foreground"), lk["colors"].get("dark_background"))
        pw, ph = int(round(LW * self.scale)), int(round(PV_H * self.scale))
        if getattr(self, "_pv_key", None) != key:
            surf = cairo.ImageSurface(cairo.FORMAT_RGB24, pw, ph); c = cairo.Context(surf)
            R.draw_mock(c, 0, 0, pw, ph, lk, detail=True)
            self._pv_key, self._pv = key, surf
        cr.save(); rrect(cr, LX, PV_Y, LW, PV_H, 10); cr.clip()
        cr.translate(LX, PV_Y); cr.scale(1 / self.scale, 1 / self.scale); cr.set_source_surface(self._pv, 0, 0); cr.paint()
        cr.restore()
        rrect(cr, LX + .5, PV_Y + .5, LW - 1, PV_H - 1, 10); cr.set_source_rgba(*rgb(pal["border"])); cr.set_line_width(1); cr.stroke()
        self.regions.append(("preview", (LX, PV_Y, LW, PV_H), None))

    # option strip --------------------------------------------------------
    def _strip_items(self, cr, row):
        """[(option index, option, width, kind)] for the focused row, filtered."""
        out = []
        kind = {"theme": "thumb", "wallpaper": "thumb", "accent": "dot", "bordercolor": "dot"}.get(row.id, "pill")
        for i, o in self.s.visible_options(row):
            if kind == "pill":
                fam = o.value if row.id in ("font", "mono") and o.value else self.ui
                tw = FONTS.measure(cr, o.label, fam, 13)[0]
                out.append((i, o, max(64, tw + 32), kind))
            elif kind == "thumb": out.append((i, o, 148, kind))
            else: out.append((i, o, 72, kind))
        return out

    def _strip(self, cr, pal):
        row = self.s.row; st = self.s.state
        cr.save(); cr.rectangle(LX, STRIP_Y, LW, STRIP_H); cr.clip()
        items = self._strip_items(cr, row)
        if not items:
            self._t(cr, LX + LW / 2, STRIP_Y + 40, "Nothing matches “%s”" % self.s.filter, 14, pal["muted"], align="c")
            cr.restore(); return
        gap = 12; cur = row.current(st)
        x = 0; xs = []
        for i, o, w, kind in items:
            xs.append((x, w)); x += w + gap
        total = x - gap
        centre_idx = next((n for n, it in enumerate(items) if it[0] == cur), 0)
        cx = xs[centre_idx][0] + xs[centre_idx][1] / 2
        target = max(0, min(total + 12 - LW, cx - LW / 2)) if total + 12 > LW else -(LW - total - 12) / 2
        if self.strip_x is None or getattr(self, "_strip_row", None) != row.id: self.strip_x = target
        self._strip_row = row.id; self._strip_target = target
        base = LX + 6 - self.strip_x
        for n, (i, o, w, kind) in enumerate(items):
            x0 = base + xs[n][0]
            if x0 > LX + LW or x0 + w < LX: continue
            sel = (i == cur)
            if kind == "thumb":
                th = 83; y0 = STRIP_Y + 8
                rrect(cr, x0, y0, w, th, 8)
                cr.save(); cr.clip()
                if row.id == "theme": t = self.thumb(o.value, None, 148, 83)
                else: t = self.thumb(None, o.meta.get("path") or None, 148, 83)
                if t: cr.set_source_surface(t, x0, y0); cr.paint()
                cr.restore()
                if not sel:
                    rrect(cr, x0, y0, w, th, 8); cr.set_source_rgba(*rgb(pal["surf"], .30)); cr.fill()
                rrect(cr, x0 - (1.5 if sel else 0) + .5, y0 - (1.5 if sel else 0) + .5, w + (3 if sel else 0) - 1, th + (3 if sel else 0) - 1, 9 if sel else 8)
                cr.set_source_rgba(*rgb(pal["accent"] if sel else pal["border"])); cr.set_line_width(2.5 if sel else 1); cr.stroke()
                self._t(cr, x0 + w / 2, y0 + th + 8, o.label, 12, pal["fg"] if sel else pal["muted"], align="c", width=w, weight=Pango.Weight.SEMIBOLD if sel else None)
            elif kind == "dot":
                d = 36; y0 = STRIP_Y + 14; mx = x0 + w / 2
                col = o.meta.get("color", "#888888")
                if sel:
                    cr.new_sub_path(); cr.arc(mx, y0 + d / 2, d / 2 + 5, 0, 6.3); cr.set_source_rgba(*rgb(pal["accent"] if row.id != "accent" else col)); cr.set_line_width(2); cr.stroke()
                cr.new_sub_path(); cr.arc(mx, y0 + d / 2, d / 2 - (0 if sel else 2), 0, 6.3); cr.set_source_rgba(*rgb(col)); cr.fill()
                cr.new_sub_path(); cr.arc(mx, y0 + d / 2, d / 2 - (0 if sel else 2), 0, 6.3); cr.set_source_rgba(*rgb(pal["fg"], .18)); cr.set_line_width(1); cr.stroke()
                self._t(cr, mx, y0 + d + 12, o.label if len(o.label) < 12 else o.label[:11] + "…", 11, pal["fg"] if sel else pal["muted"], align="c")
            else:
                h = 34; y0 = STRIP_Y + 30
                fam = o.value if row.id in ("font", "mono") and o.value else self.ui
                R.draw_chip(cr, x0, y0, w, h, o.label, sel, pal, size=13, family=self.ui, font_for_label=fam)
            self.regions.append(("opt", (x0, STRIP_Y, w, STRIP_H), (self.s.focus, i)))
        cr.restore()
        # fade the strip edges into the card
        for side in ((0,) if self.strip_x > 2 else ()) + ((1,) if self.strip_x < total + 12 - LW - 2 else ()):
            g = cairo.LinearGradient(LX if side == 0 else LX + LW, 0, LX + 36 if side == 0 else LX + LW - 36, 0)
            g.add_color_stop_rgba(0, *rgb(pal["surf"], 1)); g.add_color_stop_rgba(1, *rgb(pal["surf"], 0))
            cr.rectangle(LX, STRIP_Y, 36, STRIP_H) if side == 0 else cr.rectangle(LX + LW - 36, STRIP_Y, 36, STRIP_H)
            cr.set_source(g); cr.fill()

    # rows ---------------------------------------------------------------
    def _rows(self, cr, pal):
        st = self.s.state; rows = self.s.rows
        avail = FOOT_Y - ROW_Y - 54               # leave room for the hint under the rows
        visible = max(5, int(avail // ROW_H))
        first = max(0, min(len(rows) - visible, self.s.focus - visible // 2)) if len(rows) > visible else 0
        cr.save(); cr.rectangle(RX - 6, ROW_Y - 4, RW + 12, visible * ROW_H + 8); cr.clip()
        for n in range(first, min(len(rows), first + visible)):
            r = rows[n]; y = ROW_Y + (n - first) * ROW_H; foc = (n == self.s.focus)
            self.regions.append(("row", (RX, y, RW, ROW_H), n))
            if foc:
                rrect(cr, RX, y + 1, RW, ROW_H - 2, 8); cr.set_source_rgba(*rgb(pal["soft"])); cr.fill()
                rrect(cr, RX, y + 7, 3, ROW_H - 14, 1.5); cr.set_source_rgba(*rgb(pal["accent"])); cr.fill()
            self._t(cr, RX + 14, y + 8, r.label, 14, pal["fg"] if foc else pal["muted"], weight=Pango.Weight.SEMIBOLD if foc else None)
            opts = r.options(st); ci = r.current(st)
            if r.id == "theme": val = label_for(st.get("THEME") or "carpatic")
            elif 0 <= ci < len(opts): val = opts[ci].label
            else: val = opts[0].label if opts else ""
            vx = RX + RW - 14
            if foc:
                # chevrons: clickable
                self._t(cr, RX + RW - 12, y + 7, "›", 18, pal["accent"], align="r"); vx -= 16
                self._t(cr, vx - FONTS.measure(cr, val, self.ui, 13)[0] - 8 - 0, y + 7, "‹", 18, pal["accent"], align="r")
                self.regions.append(("chev", (RX + RW - 30, y, 30, ROW_H), 1))
                self.regions.append(("chev", (RX + RW - 160, y, 30, ROW_H), -1))
            sw = None
            if r.id in ("accent", "bordercolor") and 0 <= ci < len(opts): sw = opts[ci].meta.get("color")
            tw = FONTS.measure(cr, val, self.ui, 13)[0]
            maxw = RW - 28 - (self.s.rows and FONTS.measure(cr, r.label, self.ui, 14)[0]) - 40
            if sw:
                cr.new_sub_path(); cr.arc(vx - min(tw, maxw) - 12, y + ROW_H / 2, 6, 0, 6.3); cr.set_source_rgba(*rgb(sw)); cr.fill()
                cr.new_sub_path(); cr.arc(vx - min(tw, maxw) - 12, y + ROW_H / 2, 6, 0, 6.3); cr.set_source_rgba(*rgb(pal["fg"], .25)); cr.set_line_width(1); cr.stroke()
            self._t(cr, vx - (0 if foc else 0), y + 9, val, 13, pal["fg"] if foc else pal["muted"], align="r", width=max(40, maxw), ellipsize=True)
            if r.marks and not r.at_default(st) and not foc:
                cr.new_sub_path(); cr.arc(RX + 5, y + ROW_H / 2, 2.2, 0, 6.3); cr.set_source_rgba(*rgb(pal["accent"], .9)); cr.fill()
        cr.restore()
        # hint of the focused row
        hy = ROW_Y + visible * ROW_H + 10
        self._t(cr, RX + 14, hy, self.s.row.hint, 12, pal["muted"], width=RW - 28)
        if len(rows) > visible:
            self._t(cr, RX + RW - 14, hy + 18, "%d of %d" % (self.s.focus + 1, len(rows)), 11, pal["subtle"], align="r")

    def _footer(self, cr, pal):
        cr.set_source_rgba(*rgb(pal["border"])); cr.rectangle(0, FOOT_Y, CW, 1); cr.fill()
        x = PAD
        hints = [("← →", "change"), ("↑ ↓", "row"), ("Enter", "keep"), ("Esc", "revert"), ("Del", "reset row"), ("Ctrl S", "save as mine")]
        if self.s.row.id == "accent": hints.insert(2, ("#", "your colour"))
        for k, v in hints:
            kw = FONTS.measure(cr, k, self.ui, 11)[0] + 12
            rrect(cr, x, FOOT_Y + 15, kw, 22, 5); cr.set_source_rgba(*rgb(pal["fg"], .09)); cr.fill()
            self._t(cr, x + kw / 2, FOOT_Y + 19, k, 11, pal["fg"], align="c")
            w = self._t(cr, x + kw + 6, FOOT_Y + 19, v, 12, pal["muted"])[0]
            x += kw + 6 + w + 14
        if self.s.filter:
            self._t(cr, x, FOOT_Y + 18, "Filter: " + self.s.filter, 12, pal["accent"], weight=Pango.Weight.SEMIBOLD)
        else:
            self._t(cr, x, FOOT_Y + 19, "Type to search", 12, pal["subtle"])
        # buttons
        bx = CW - PAD - 84
        rrect(cr, bx, FOOT_Y + 11, 84, 30, 15); cr.set_source_rgba(*rgb(pal["accent"])); cr.fill()
        self._t(cr, bx + 42, FOOT_Y + 17, "Keep", 13, pal["accent_fg"], align="c", weight=Pango.Weight.SEMIBOLD)
        self.regions.append(("keep", (bx, FOOT_Y + 11, 84, 30), None))
        bx2 = bx - 90
        rrect(cr, bx2, FOOT_Y + 11, 80, 30, 15); cr.set_source_rgba(*rgb(pal["fg"], .09)); cr.fill()
        self._t(cr, bx2 + 40, FOOT_Y + 17, "Revert", 13, pal["fg"], align="c")
        self.regions.append(("cancel", (bx2, FOOT_Y + 11, 80, 30), None))
        msg = self.toast or self.status
        if msg:      # top right of the card, above the counter: the footer is already full on rows with extra hints
            self._t(cr, LX + LW, PAD - 2, msg, 12, pal["accent"] if self.toast else pal["muted"], align="r")

    def _entry(self, cr, pal, e):
        cr.set_source_rgba(*rgb(pal["surf"], .82)); cr.rectangle(0, 0, CW, CH); cr.fill()
        w, h = 420, 150; x, y = (CW - w) / 2, (CH - h) / 2 - 20
        rrect(cr, x, y, w, h, 12); cr.set_source_rgba(*rgb(pal["surf"])); cr.fill_preserve(); cr.set_source_rgba(*rgb(pal["border_strong"])); cr.set_line_width(1); cr.stroke()
        self._t(cr, x + 24, y + 20, e["title"], 16, pal["fg"], weight=Pango.Weight.SEMIBOLD)
        rrect(cr, x + 24, y + 56, w - 48, 38, 8); cr.set_source_rgba(*rgb(pal["inset"])); cr.fill_preserve(); cr.set_source_rgba(*rgb(pal["accent"])); cr.set_line_width(2); cr.stroke()
        tw = self._t(cr, x + 38, y + 64, e["text"], 15, pal["fg"], family=self.mono)[0]
        cr.set_source_rgba(*rgb(pal["accent"])); cr.rectangle(x + 38 + tw + 1, y + 64, 2, 20); cr.fill()
        if e.get("swatch"):
            cr.new_sub_path(); cr.arc(x + w - 24 - 19, y + 75, 9, 0, 6.3); cr.set_source_rgba(*rgb(e["swatch"])); cr.fill()
        self._t(cr, x + 24, y + 108, e["hint"], 12, pal["muted"])

    # ---------------------------------------------------------------- hit testing
    def to_design(self, px, py): return (px - self.ox) / self.scale, (py - self.oy) / self.scale

    def hit(self, px, py):
        x, y = self.to_design(px, py)
        for kind, (rx, ry, rw, rh), payload in reversed(self.regions):
            if rx <= x < rx + rw and ry <= y < ry + rh: return kind, payload
        if 0 <= x < CW and 0 <= y < CH: return "card", None
        return "outside", None
