"""ThumbGrid: a virtualised thumbnail grid (draws only the visible rows, loads thumbnails lazily on worker threads, keyboard
navigable, rounded corners, selection ring in the accent). Built on one Gtk.DrawingArea so thousands of pictures scroll at frame rate."""
import math, queue, threading, time
from collections import OrderedDict

import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0"); gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, Gdk, GLib, GObject, GdkPixbuf, Pango, PangoCairo
import cairo

GAP = 14          # 4/8/12/16 grid: gaps are 14 here only because the label row sits inside the cell; see DESIGN-SYSTEM
RADIUS = 10       # tokens: md
LABEL_H = 42
HEADER_H = 40
MIN_CELL, MAX_CELL = 150, 230


class Cell:
    """One tile. loader() runs on a worker thread and returns a GdkPixbuf (or None). header=True makes a full-width section title."""
    def __init__(self, key, title="", subtitle="", loader=None, badges=(), warn="", header=False, data=None):
        self.key, self.title, self.subtitle, self.loader = key, title, subtitle, loader
        self.badges, self.warn, self.header, self.data = list(badges), warn, header, data


def rgba(c, a=None):
    return (c.red, c.green, c.blue, c.alpha if a is None else a)


def rounded(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0); cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi); cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi); cr.close_path()


class ThumbGrid(Gtk.DrawingArea):
    __gsignals__ = {"activated": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
                    "need-more": (GObject.SignalFlags.RUN_FIRST, None, ()),
                    "context": (GObject.SignalFlags.RUN_FIRST, None, (int, int, int))}

    def __init__(self, workers=3, cache_size=260, aspect=0.625):
        super().__init__()
        self.set_can_focus(True)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK |
                        Gdk.EventMask.KEY_PRESS_MASK | Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.get_style_context().add_class("wp-grid")
        self.cells, self.skeletons = [], 0
        self.selected_key, self.focus_idx, self.hover = None, -1, -1
        self.aspect = aspect
        self._layout, self._cw, self._ch, self._cols, self._h = [], 150, 94, 1, 0
        self._pos = {}
        self._scale = 1; self._resize_src = None
        self._surf = OrderedDict(); self._cache_size = cache_size; self._cellcache = OrderedDict()
        self._inflight, self._failed, self._loaded_at = set(), {}, {}
        self._visible = set()
        self._q = queue.LifoQueue()
        self.stats = {"loaded": 0, "draws": 0, "draw_ms_max": 0.0, "draw_ms_total": 0.0}
        for _ in range(workers): threading.Thread(target=self._worker, daemon=True).start()
        self.connect("draw", self._on_draw); self.connect("size-allocate", self._on_size); self.connect("style-updated", lambda *a: self._cellcache.clear())
        self.connect("button-press-event", self._on_press); self.connect("motion-notify-event", self._on_motion)
        self.connect("leave-notify-event", lambda *a: self._set_hover(-1)); self.connect("key-press-event", self._on_key)
        self.connect("focus-in-event", lambda *a: (self.queue_draw(), False)[1]); self.connect("focus-out-event", lambda *a: (self.queue_draw(), False)[1])
        self._more_sent = False

    # -- content
    def set_cells(self, cells, keep_scroll=False):
        self.cells = list(cells); self.skeletons = 0; self._more_sent = False
        if self.focus_idx >= len(self.cells): self.focus_idx = -1
        self._relayout(); self.queue_draw()

    def append_cells(self, cells):
        self.cells += list(cells); self.skeletons = 0; self._more_sent = False
        self._relayout(); self.queue_draw()

    def set_skeletons(self, n):
        self.cells, self.skeletons = [], n
        self._relayout(); self.queue_draw()

    def add_skeletons(self, n):
        self.skeletons = n; self._relayout(); self.queue_draw()

    def select_key(self, key):
        self.selected_key = key; self.queue_draw()

    def index_of(self, key):
        for i, c in enumerate(self.cells):
            if c.key == key: return i
        return -1

    # -- layout
    def _relayout(self):
        w = max(self.get_allocated_width(), 1)
        cols = max(1, int((w + GAP) // (MIN_CELL + GAP)))
        cw = min(MAX_CELL, (w - GAP * (cols - 1)) / cols) if cols > 1 else min(w, MAX_CELL * 1.3)
        cw = max(60.0, cw)
        ch = cw * self.aspect
        rows, y, row, self._pos = [], 0.0, [], {}
        def flush():
            nonlocal y, row
            if row:
                rows.append((y, ch + LABEL_H, row)); y += ch + LABEL_H + GAP - 4; row = []
        total = len(self.cells) + self.skeletons
        for i in range(total):
            c = self.cells[i] if i < len(self.cells) else None
            if c is not None and c.header:
                flush(); rows.append((y, HEADER_H, [("h", i)])); y += HEADER_H; continue
            row.append(("c", i))
            if len(row) == cols: flush()
        flush()
        if abs(cw - self._cw) > 1 and self._surf and not self._resize_src:
            self._resize_src = GLib.timeout_add(180, self._after_resize)   # reload thumbnails at the new size once the window stops resizing
        self._layout, self._cw, self._ch, self._cols = rows, cw, ch, cols
        for ry, rh, items in rows:
            for n, (kind, i) in enumerate(items):
                if kind == "c": self._pos[i] = (n * (cw + GAP), ry)
        self._h = int(y + 8)
        if self.get_size_request()[1] != self._h: self.set_size_request(-1, self._h)

    def _on_size(self, w, alloc):
        self._scale = self.get_scale_factor() or 1
        self._relayout()

    def _after_resize(self):
        self._resize_src = None
        self._surf.clear(); self._cellcache.clear(); self._failed.clear(); self.queue_draw()
        return False

    def _cell_at(self, x, y):
        for i, (cx, cy) in self._pos.items():
            if cx <= x <= cx + self._cw and cy <= y <= cy + self._ch + LABEL_H: return i
        return -1

    # -- thumbnails
    def _worker(self):
        while True:
            key, loader = self._q.get()
            if key not in self._visible:
                self._inflight.discard(key); continue
            pb, err = None, None
            tw, th, sc = max(1, round(self._cw * self._scale)), max(1, round(self._ch * self._scale)), self._scale
            try:
                pb = loader()
                if pb is not None:   # scale + crop to the cell here, off the main thread, so drawing is a plain blit
                    f = max(tw / pb.get_width(), th / pb.get_height())
                    nw, nh = max(tw, round(pb.get_width() * f)), max(th, round(pb.get_height() * f))
                    pb = pb.scale_simple(nw, nh, GdkPixbuf.InterpType.BILINEAR).new_subpixbuf((nw - tw) // 2, (nh - th) // 2, tw, th).copy()
            except Exception as e: err = str(e) or "failed"
            GLib.idle_add(self._loaded, key, pb, err, sc)

    def _loaded(self, key, pb, err, sc=1):
        self._inflight.discard(key)
        if pb is None:
            self._failed[key] = err or "This picture cannot be previewed."
        else:
            s = Gdk.cairo_surface_create_from_pixbuf(pb, sc, None)
            self._surf[key] = s; self._loaded_at[key] = time.monotonic(); self.stats["loaded"] += 1
            while len(self._surf) > self._cache_size: self._surf.popitem(last=False)
        self.queue_draw()
        return False

    def surface_for(self, c):
        s = self._surf.get(c.key)
        if s is not None:
            self._surf.move_to_end(c.key); return s
        if c.loader and c.key not in self._inflight and c.key not in self._failed:
            self._inflight.add(c.key); self._visible.add(c.key); self._q.put((c.key, c.loader))
        return None

    def scrolled_window(self):
        w = self.get_parent()
        while w is not None and not isinstance(w, Gtk.ScrolledWindow): w = w.get_parent()
        return w

    def forget(self, key):
        self._surf.pop(key, None); self._failed.pop(key, None); self.queue_draw()

    # -- drawing
    def _colors(self):
        sc = self.get_style_context()
        def lc(name, fb):
            ok, c = sc.lookup_color(name)
            return c if ok else Gdk.RGBA(*fb)
        return {"bg": lc("window_bg_color", (0.07, 0.08, 0.1, 1)), "fg": lc("window_fg_color", (0.9, 0.92, 0.95, 1)),
                "accent": lc("accent_bg_color", (0.36, 0.78, 0.66, 1)), "accent_fg": lc("accent_fg_color", (0.03, 0.14, 0.11, 1)),
                "card": lc("card_bg_color", (0.09, 0.11, 0.14, 1)), "warn": lc("warning_bg_color", (0.95, 0.76, 0.35, 1)), "warn_fg": lc("warning_fg_color", (0.17, 0.12, 0, 1))}

    def _on_draw(self, w, cr):
        t0 = time.thread_time()
        col = self._colors()
        clip = cr.clip_extents(); y0, y1 = clip[1] - 4, clip[3] + 4
        lay = PangoCairo.create_layout(cr)
        fd = self.get_style_context().get_font(Gtk.StateFlags.NORMAL)
        vis = set()
        now = time.monotonic(); animating = False
        for ry, rh, items in self._layout:
            if ry + rh < y0 or ry > y1: continue
            for kind, i in items:
                if kind == "h":
                    c = self.cells[i]
                    fd2 = fd.copy(); fd2.set_weight(Pango.Weight.SEMIBOLD); fd2.set_size(int(fd.get_size() * 1.05))
                    lay.set_font_description(fd2); lay.set_text(c.title, -1)
                    cr.set_source_rgba(*rgba(col["fg"], 0.9)); cr.move_to(2, ry + 12); PangoCairo.show_layout(cr, lay)
                    continue
                x, y = self._pos[i]
                c = self.cells[i] if i < len(self.cells) else None
                if c is None: self._skeleton(cr, x, y, col); continue
                vis.add(c.key)
                animating |= self._cell(cr, lay, fd, c, i, x, y, col, now)
        self._visible = vis
        # ask for more when the end is on screen
        if self._layout and not self._more_sent and y1 > self._h - 360 and self.cells:
            self._more_sent = True; GLib.idle_add(lambda: self.emit("need-more") or False)
        if animating: GLib.timeout_add(16, lambda: (self.queue_draw(), False)[1])
        dt = (time.thread_time() - t0) * 1000
        self.stats["draws"] += 1; self.stats["draw_ms_total"] += dt; self.stats["draw_ms_max"] = max(self.stats["draw_ms_max"], dt)
        return False

    def _skeleton(self, cr, x, y, col):
        rounded(cr, x, y, self._cw, self._ch, RADIUS); cr.set_source_rgba(*rgba(col["fg"], 0.07)); cr.fill()
        rounded(cr, x, y + self._ch + 10, self._cw * 0.6, 10, 5); cr.set_source_rgba(*rgba(col["fg"], 0.07)); cr.fill()

    def _body(self, cr, lay, fd, c, surf, alpha, col, cw, ch):
        """Picture, hairline, badges and label of one cell at the origin (cached as a bitmap once the fade-in is over)."""
        cr.save(); rounded(cr, 0, 0, cw, ch, RADIUS); cr.clip()
        if surf is not None:
            ds = surf.get_device_scale()[0] or 1
            sw, sh = surf.get_width() / ds, surf.get_height() / ds
            sc = max(cw / sw, ch / sh)
            cr.save(); cr.translate((cw - sw * sc) / 2, (ch - sh * sc) / 2); cr.scale(sc, sc)
            cr.set_source_surface(surf, 0, 0); cr.get_source().set_filter(cairo.FILTER_GOOD)
            cr.paint_with_alpha(alpha); cr.restore()
            if alpha < 1.0:
                cr.set_source_rgba(*rgba(col["fg"], 0.07 * (1 - alpha))); cr.paint()
        else:
            cr.set_source_rgba(*rgba(col["fg"], 0.07)); cr.paint()
            if c.key in self._failed:
                lay.set_font_description(fd); lay.set_width(int((cw - 16) * Pango.SCALE)); lay.set_alignment(Pango.Alignment.CENTER)
                lay.set_text("Preview not available", -1); cr.set_source_rgba(*rgba(col["fg"], 0.6)); cr.move_to(8, ch / 2 - 8); PangoCairo.show_layout(cr, lay)
                lay.set_width(-1); lay.set_alignment(Pango.Alignment.LEFT)
        cr.restore()
        rounded(cr, .5, .5, cw - 1, ch - 1, RADIUS); cr.set_source_rgba(*rgba(col["fg"], 0.12)); cr.set_line_width(1); cr.stroke()
        bx = 8
        fd2 = fd.copy(); fd2.set_size(int(fd.get_size() * 0.82)); fd2.set_weight(Pango.Weight.SEMIBOLD)
        lay.set_font_description(fd2)
        for b in c.badges:
            lay.set_text(b, -1); tw, th = lay.get_pixel_size()
            rounded(cr, bx, ch - th - 14, tw + 12, th + 6, (th + 6) / 2); cr.set_source_rgba(0, 0, 0, 0.55); cr.fill()
            cr.set_source_rgba(1, 1, 1, 0.95); cr.move_to(bx + 6, ch - th - 11); PangoCairo.show_layout(cr, lay); bx += tw + 18
        if c.warn:
            lay.set_text(c.warn, -1); tw, th = lay.get_pixel_size()
            rounded(cr, cw - tw - 20, 8, tw + 12, th + 6, (th + 6) / 2); cr.set_source_rgba(*rgba(col["warn"])); cr.fill()
            cr.set_source_rgba(*rgba(col["warn_fg"])); cr.move_to(cw - tw - 14, 11); PangoCairo.show_layout(cr, lay)
        lay.set_font_description(fd); lay.set_width(int(cw * Pango.SCALE)); lay.set_ellipsize(Pango.EllipsizeMode.END)
        lay.set_text(c.title, -1); cr.set_source_rgba(*rgba(col["fg"], 0.95)); cr.move_to(1, ch + 8); PangoCairo.show_layout(cr, lay)
        if c.subtitle:
            f3 = fd.copy(); f3.set_size(int(fd.get_size() * 0.88)); lay.set_font_description(f3); lay.set_text(c.subtitle, -1)
            cr.set_source_rgba(*rgba(col["fg"], 0.6)); cr.move_to(1, ch + 8 + 17); PangoCairo.show_layout(cr, lay)
        lay.set_width(-1); lay.set_ellipsize(Pango.EllipsizeMode.NONE)

    def _cell(self, cr, lay, fd, c, i, x, y, col, now):
        cw, ch = self._cw, self._ch
        x, y = round(x), round(y)
        sel = (c.key == self.selected_key)
        surf = self.surface_for(c)
        alpha = 1.0 if surf is None else min(1.0, (now - self._loaded_at.get(c.key, 0)) / 0.18)
        animating = surf is not None and alpha < 1.0
        ck = (c.key, round(cw), round(ch), surf is not None, c.key in self._failed, tuple(c.badges), c.warn, c.title, c.subtitle)
        cached = self._cellcache.get(ck)
        if cached is None or animating:
            if animating:
                cr.save(); cr.translate(x, y); self._body(cr, lay, fd, c, surf, alpha, col, cw, ch); cr.restore()
            else:
                cached = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(math.ceil(cw)) + 2, int(ch + LABEL_H))
                cc = cairo.Context(cached); clay = PangoCairo.create_layout(cc)
                self._body(cc, clay, fd, c, surf, 1.0, col, cw, ch)
                self._cellcache[ck] = cached
                while len(self._cellcache) > 400: self._cellcache.popitem(last=False)
        if cached is not None and not animating:
            self._cellcache.move_to_end(ck)
            cr.set_source_surface(cached, x, y); cr.paint()
        # ring: selection = 3 px accent with a 2 px gap; hover = faint; keyboard focus = dashed accent
        if sel:
            rounded(cr, x - 4.5, y - 4.5, cw + 9, ch + 9, RADIUS + 4); cr.set_source_rgba(*rgba(col["accent"])); cr.set_line_width(3); cr.stroke()
            ix, iy = x + cw - 26, y + 8
            cr.arc(ix + 9, iy + 9, 9, 0, 2 * math.pi); cr.set_source_rgba(*rgba(col["accent"])); cr.fill()
            cr.set_source_rgba(*rgba(col["accent_fg"])); cr.set_line_width(2); cr.set_line_cap(cairo.LINE_CAP_ROUND); cr.set_line_join(cairo.LINE_JOIN_ROUND)
            cr.move_to(ix + 5, iy + 9.5); cr.line_to(ix + 8, iy + 12.5); cr.line_to(ix + 13, iy + 6); cr.stroke()
        elif i == self.hover:
            rounded(cr, x - 2.5, y - 2.5, cw + 5, ch + 5, RADIUS + 2); cr.set_source_rgba(*rgba(col["fg"], 0.35)); cr.set_line_width(2); cr.stroke()
        if i == self.focus_idx and self.has_focus():
            rounded(cr, x - 4.5, y - 4.5, cw + 9, ch + 9, RADIUS + 4); cr.set_source_rgba(*rgba(col["accent"], 0.9)); cr.set_line_width(2); cr.set_dash([5, 4]); cr.stroke(); cr.set_dash([])
        return animating

    # -- input
    def _set_hover(self, i):
        if i != self.hover: self.hover = i; self.queue_draw()
    def _on_motion(self, w, e): self._set_hover(self._cell_at(e.x, e.y))
    def _on_press(self, w, e):
        self.grab_focus()
        i = self._cell_at(e.x, e.y)
        if i < 0 or i >= len(self.cells): return False
        self.focus_idx = i
        if e.button == 1: self.emit("activated", i)
        elif e.button == 3: self.emit("context", i, int(e.x_root), int(e.y_root))
        return True

    def _on_key(self, w, e):
        k = e.keyval
        n = len(self.cells)
        if not n: return False
        real = [i for i, c in enumerate(self.cells) if not c.header]
        if not real: return False
        cur = self.focus_idx if self.focus_idx in real else (self.index_of(self.selected_key) if self.index_of(self.selected_key) in real else real[0])
        step = None
        pos = real.index(cur) if cur in real else 0
        cols = self._cols
        if k in (Gdk.KEY_Right,): pos += 1
        elif k in (Gdk.KEY_Left,): pos -= 1
        elif k in (Gdk.KEY_Down,): pos += cols
        elif k in (Gdk.KEY_Up,): pos -= cols
        elif k == Gdk.KEY_Home: pos = 0
        elif k == Gdk.KEY_End: pos = len(real) - 1
        elif k == Gdk.KEY_Page_Down: pos += cols * 3
        elif k == Gdk.KEY_Page_Up: pos -= cols * 3
        elif k in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            self.emit("activated", cur); return True
        else: return False
        pos = max(0, min(len(real) - 1, pos)); self.focus_idx = real[pos]
        self._scroll_to(self.focus_idx); self.queue_draw(); return True

    def _scroll_to(self, i):
        if i not in self._pos: return
        x, y = self._pos[i]
        sw = self.scrolled_window()
        if sw is None: return
        adj = sw.get_vadjustment(); top, page = adj.get_value(), adj.get_page_size()
        if y - 8 < top: adj.set_value(max(0, y - 12))
        elif y + self._ch + LABEL_H + 8 > top + page: adj.set_value(y + self._ch + LABEL_H + 12 - page)


class ColorChips(Gtk.DrawingArea):
    """A row of round colour chips (Wallhaven colour filter). One selected at most; click again to clear."""
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, (str,))}
    D, GAPC = 22, 8

    def __init__(self, colors, per_row=10):
        super().__init__()
        self.colors, self.per_row, self.value = colors, per_row, ""
        self.set_can_focus(True)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.KEY_PRESS_MASK)
        rows = (len(colors) + per_row - 1) // per_row
        self.set_size_request(per_row * (self.D + self.GAPC), rows * (self.D + self.GAPC))
        self.connect("draw", self._draw); self.connect("button-press-event", self._press); self.connect("key-press-event", self._key)
        self.focus_i = 0

    def set_value(self, v):
        self.value = v; self.queue_draw()

    def _xy(self, i): return (i % self.per_row) * (self.D + self.GAPC) + 2, (i // self.per_row) * (self.D + self.GAPC) + 2

    def _draw(self, w, cr):
        sc = self.get_style_context()
        ok, acc = sc.lookup_color("accent_bg_color"); ok2, fg = sc.lookup_color("window_fg_color")
        if not ok: acc = Gdk.RGBA(.36, .78, .66, 1)
        if not ok2: fg = Gdk.RGBA(.9, .9, .9, 1)
        for i, hexv in enumerate(self.colors):
            x, y = self._xy(i); r = (self.D - 4) / 2
            cr.arc(x + self.D / 2 - 2, y + self.D / 2 - 2, r, 0, 2 * math.pi)
            cr.set_source_rgb(*(int(hexv[j:j + 2], 16) / 255 for j in (0, 2, 4))); cr.fill_preserve()
            cr.set_source_rgba(*rgba(fg, 0.25)); cr.set_line_width(1); cr.stroke()
            if hexv == self.value:
                cr.arc(x + self.D / 2 - 2, y + self.D / 2 - 2, r + 3, 0, 2 * math.pi); cr.set_source_rgba(*rgba(acc)); cr.set_line_width(2); cr.stroke()
            if i == self.focus_i and self.has_focus():
                cr.arc(x + self.D / 2 - 2, y + self.D / 2 - 2, r + 5, 0, 2 * math.pi); cr.set_source_rgba(*rgba(acc, .6)); cr.set_line_width(1); cr.set_dash([2, 2]); cr.stroke(); cr.set_dash([])
        return False

    def _toggle(self, i):
        v = self.colors[i]; self.value = "" if v == self.value else v; self.queue_draw(); self.emit("changed", self.value)

    def _press(self, w, e):
        self.grab_focus()
        for i in range(len(self.colors)):
            x, y = self._xy(i)
            if x - 4 <= e.x <= x + self.D + 2 and y - 4 <= e.y <= y + self.D + 2: self.focus_i = i; self._toggle(i); return True
        return False

    def _key(self, w, e):
        k = e.keyval
        d = {Gdk.KEY_Right: 1, Gdk.KEY_Left: -1, Gdk.KEY_Down: self.per_row, Gdk.KEY_Up: -self.per_row}.get(k)
        if d is not None: self.focus_i = max(0, min(len(self.colors) - 1, self.focus_i + d)); self.queue_draw(); return True
        if k in (Gdk.KEY_space, Gdk.KEY_Return): self._toggle(self.focus_i); return True
        return False
