"""Quick settings flyout: toggle tiles with state colour, drill-down panes (Wi-Fi, Bluetooth, power mode, sound output), volume and brightness
sliders, Now Playing card, battery row and session buttons. Four looks share one layout engine (`SPECS`): win, mac, ubuntu, kylin."""
import threading
from . import gfx
from .kit import View, Node, Group, p_button
from .quickmodel import QuickModel, PROFILE_NAMES, PROFILE_GLYPH
from .system import signal_level
from .theme import mix

SPECS = {
    # w: width, pad: outer padding, gap: tile gap, sr: surface radius, tr: tile radius, wide_h / small_h: tile heights, cols: small tiles per row
    "win":    dict(w=360, pad=16, gap=8, sr=14, tr=10, wide_h=64, small_h=72, cols=4, tile="card", slider="knob", footer="bottom"),
    "mac":    dict(w=360, pad=14, gap=10, sr=20, tr=16, wide_h=60, small_h=72, cols=4, tile="circle", slider="bar", footer="bottom"),
    "ubuntu": dict(w=368, pad=16, gap=8, sr=18, tr=999, wide_h=52, small_h=52, cols=2, tile="pill", slider="bar", footer="top"),
    "kylin":  dict(w=396, pad=16, gap=12, sr=12, tr=8, wide_h=72, small_h=72, cols=4, tile="card", slider="kylin", footer="bottom"),
}


def clip_text_w(cr, s, px, w, weight=400): return gfx.text_size(cr, s, px, weight, maxw=w)[0]


class QuickView(View):
    def __init__(self, theme, model: QuickModel, look="win", on_close=None, async_run=None, now_fn=None):
        super().__init__(theme)
        self.m = model; self.look = look; self.sp = SPECS[look]
        self.radius = self.sp["sr"]; self.on_close = on_close or (lambda: None)
        self.async_run = async_run or (lambda fn, cb=None: (cb(fn()) if cb else fn()))
        self.pane = None; self.pane_t = 1.0; self.prev_pane = None
        self.status = ""           # one-line message in panes ("Connected to X", errors)
        self.pw_for = None         # ssid whose password field is open
        self.pw_text = ""
        self.entry_rect = None     # host places a Gtk.Entry here
        self.busy = set()
        self.W = self.sp["w"]
        self.H = self._main_height()
        self.groups = {}

    # ------------------------------------------------------------------ geometry
    def _tiles_split(self):
        t = self.m.tiles(); return [x for x in t if x.kind == "wide"], [x for x in t if x.kind == "small"]

    def _main_height(self):
        saved = self.pane; self.pane = None
        self._build_main()
        self.pane = saved
        return int(self._end + self.sp["pad"])

    def _slider_h(self): return 56 if self.sp["slider"] == "kylin" else 40 if self.sp["slider"] == "bar" else 36

    def size(self): return (self.W, self.H)

    # ------------------------------------------------------------------ pane navigation
    def open_pane(self, name):
        self.prev_pane = self.pane; self.pane = name; self.pane_t = 0.0; self.status = ""; self.pw_for = None; self.entry_rect = None
        self.groups = {}
        if name == "wifi": self.load("wifi")
        elif name == "bt": self.load("bt")
        elif name == "output": self.load("output")
        self.refresh(); self.canvas and self.canvas.kick()

    def back(self):
        self.prev_pane = self.pane; self.pane = None; self.pane_t = 0.0; self.pw_for = None; self.entry_rect = None; self.groups = {}
        self.m.refresh(); self.refresh()

    def load(self, what, rescan=False):
        def job():
            if what == "wifi": return self.m.load_wifi(rescan)
            if what == "bt": return self.m.load_bt()
            return self.m.load_sinks()
        self.busy.add(what)
        def done(_r): self.busy.discard(what); self.refresh()
        self.async_run(job, done)

    def animating(self): return self.pane_t < 1.0

    def tick(self, dt):
        self.pane_t = min(1.0, self.pane_t + dt / 0.18)

    def fx(self):
        """(dx, alpha) of the content for the pane slide."""
        if self.pane_t >= 1.0: return 0.0, 1.0
        e = gfx.ease_out(self.pane_t)
        return ((1 - e) * (18 if self.pane else -18)), 0.35 + 0.65 * e

    def key(self, ev):
        from gi.repository import Gdk
        if ev.keyval == Gdk.KEY_Escape and self.pane:
            if self.pw_for: self.pw_for = None; self.entry_rect = None; self.refresh(); return True
            self.back(); return True
        if ev.keyval == Gdk.KEY_BackSpace and self.pane and not self.pw_for: self.back(); return True
        return False

    # ------------------------------------------------------------------ build
    entry_kind = "password"
    entry_placeholder = "Password"

    def on_entry_change(self, text): self.pw_text = text

    def on_entry_activate(self, text, entry): self.pw_text = text; self.submit_password()

    def build(self):
        self.entry_rect = None
        if self.pane is None: self.H = self._main_height()
        return self._build_main() if self.pane is None else self._build_pane()

    def _build_main(self):
        t, sp, m = self.theme, self.sp, self.m
        nodes = []; x0 = sp["pad"]; cw = self.W - 2 * sp["pad"]; y = sp["pad"]
        if sp["footer"] == "top":
            nodes += self._footer_top(x0, y, cw); y += 36 + 12
        wide, small = self._tiles_split()
        gap = sp["gap"]
        i = 0
        while i < len(wide):
            single = i == len(wide) - 1 and len(wide) % 2 == 1
            tw = cw if single else (cw - gap) / 2
            nodes += self._wide_tile(wide[i], x0, y, tw)
            if not single and i + 1 < len(wide): nodes += self._wide_tile(wide[i + 1], x0 + tw + gap, y, tw)
            y += sp["wide_h"] + gap; i += 2
        if wide: y += 16 - gap
        if small:
            cols = sp["cols"] if sp["tile"] != "pill" else 2
            tw = (cw - gap * (cols - 1)) / cols
            for k, tl in enumerate(small):
                r, c = divmod(k, cols)
                nodes += self._small_tile(tl, x0 + c * (tw + gap), y + r * (sp["small_h"] + gap), tw)
            rows = (len(small) + cols - 1) // cols
            y += rows * sp["small_h"] + (rows - 1) * gap + 16
        if m.caps["volume"]:
            nodes += self._slider("vol", y, cw, m.volume_glyph(), m.v.get("vol", 0), m.volume_level(), muted=m.v.get("muted"), chevron=True); y += self._slider_h() + 4
        if m.caps["brightness"]:
            nodes += self._slider("bright", y, cw, "sun", m.v.get("bright", 0), 3); y += self._slider_h() + 4
        if m.caps["volume"] or m.caps["brightness"]: y += 12
        if m.media_state:
            nodes += self._media_card(x0, y, cw); y += 84 + 16
        if sp["footer"] == "bottom":
            nodes += self._footer_bottom(x0, y, cw); y += 1 + 12 + 36
        else:
            y -= 16 if (m.media_state or m.caps["volume"] or m.caps["brightness"]) else 0
        self._end = y
        return nodes

    # ------------------------------------------------------------------ tiles
    def _tile_fill(self, cr, n, st, on, radius):
        t = self.theme
        if on:
            c = t.accent
            gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, radius, c)
            if st.hover or st.press:
                ov = (0, 0, 0, 0.10 * st.hover + (0.08 if st.press else 0)) if t.accent_fg[0] > 0.5 else (1, 1, 1, 0.14 * st.hover + (0.08 if st.press else 0))
                gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, radius, ov)
        else:
            gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, radius, t.tile_off)
            if st.hover or st.press:
                c = t.press if st.press else t.hover
                gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, radius, (c[0], c[1], c[2], c[3] * (1.0 if st.press else st.hover)))

    def _wide_tile(self, tl, x, y, w):
        t, sp = self.theme, self.sp; h = sp["wide_h"]; r = min(sp["tr"], h / 2); style = sp["tile"]
        drill_w = 32 if tl.drill else 0
        body_w = w - drill_w if (tl.drill and tl.toggles) else w
        nodes = []
        def paint_body(cr, n, st):
            # the tile background is painted once, by the body node, over the whole tile
            full = Node(x=x, y=y, w=w, h=h)
            self._tile_fill(cr, full, st if not (tl.drill and tl.toggles) else st, tl.on, r)
            fgc = t.accent_fg if tl.on else t.fg
            sub = (fgc[0], fgc[1], fgc[2], 0.78) if tl.on else t.fg_muted
            if style == "circle":
                ccol = (0, 0, 0, 0.14) if tl.on and t.accent_fg[0] < 0.5 else (1, 1, 1, 0.22) if tl.on else t.accent_soft if False else (t.fg[0], t.fg[1], t.fg[2], 0.10)
                gfx.circle(cr, x + 12 + 16, y + h / 2, 16, ccol); gx = x + 28
                gfx.glyph(cr, tl.glyph, gx, y + h / 2, 20, fgc, level=tl.level)
                tx = x + 12 + 32 + 8
            elif style == "pill":
                gfx.glyph(cr, tl.glyph, x + 24, y + h / 2, 20, fgc, level=tl.level); tx = x + 44
            else:
                gfx.glyph(cr, tl.glyph, x + 14 + 11, y + h / 2, 22, fgc, level=tl.level); tx = x + 14 + 22 + 8
            maxw = x + w - (26 if not tl.toggles else drill_w) - 6 - tx if tl.drill else x + w - 12 - tx
            if style == "pill" and not tl.subtitle: pass
            if tl.subtitle and not (style == "pill" and h < 56 and False):
                ty = y + h / 2 - 9 if h >= 56 else y + h / 2 - 8
                gfx.text(cr, tl.title, tx, ty, 13, fgc, 600, maxw=maxw)
                gfx.text(cr, tl.subtitle, tx, ty + 18 if h >= 56 else ty + 16, 11.5 if h >= 56 else 10.5, sub, 400, maxw=maxw)
            else:
                gfx.text(cr, tl.title, tx, y + h / 2, 13, fgc, 600, maxw=maxw)
            if tl.drill and not tl.toggles:
                gfx.glyph(cr, "chevron_r", x + w - 20, y + h / 2, 16, fgc, lw=1.8)
        body = Node(id="t:" + tl.id, x=x, y=y, w=body_w, h=h, paint=paint_body, on_click=(lambda n, tid=tl: self._tile_click(tid)),
                    tooltip=tl.title, radius=r, ring=True, data=tl)
        nodes.append(body)
        if tl.drill and tl.toggles:
            def paint_drill(cr, n, st):
                fgc = t.accent_fg if tl.on else t.fg
                cr.set_source_rgba(fgc[0], fgc[1], fgc[2], 0.22); cr.rectangle(n.x, n.y + 14, 1, n.h - 28); cr.fill()
                if st.hover or st.press:
                    gfx.rrect(cr, n.x, n.y, n.w, n.h, r); cr.save(); cr.clip(); gfx.fill_rrect(cr, n.x - 20, n.y, n.w + 20, n.h, 0, (fgc[0], fgc[1], fgc[2], 0.12)); cr.restore()
                gfx.glyph(cr, "chevron_r", n.x + n.w / 2 + 2, n.y + n.h / 2, 16, fgc, lw=1.8)
            nodes.append(Node(id="d:" + tl.id, x=x + w - drill_w, y=y, w=drill_w, h=h, paint=paint_drill, on_click=(lambda n, d=tl.drill: self.open_pane(d)),
                              radius=r, tooltip=f"{tl.title} settings"))
        return nodes

    def _small_tile(self, tl, x, y, w):
        t, sp = self.theme, self.sp; h = sp["small_h"]; r = min(sp["tr"], h / 2); style = sp["tile"]
        def paint(cr, n, st):
            self._tile_fill(cr, n, st, tl.on, r)
            fgc = t.accent_fg if tl.on else t.fg
            if style == "pill":
                gfx.glyph(cr, tl.glyph, n.x + 24, n.y + n.h / 2, 20, fgc); gfx.text(cr, tl.title, n.x + 44, n.y + n.h / 2, 13, fgc, 600, maxw=n.w - 56)
            else:
                gfx.glyph(cr, tl.glyph, n.x + n.w / 2, n.y + h / 2 - 9, 22, fgc)
                gfx.text(cr, tl.title, n.x + n.w / 2, n.y + h - 17, 11, fgc, 500, "c", maxw=n.w - 8)
        return [Node(id="t:" + tl.id, x=x, y=y, w=w, h=h, paint=paint, on_click=(lambda n, tt=tl: self._tile_click(tt)), radius=r, tooltip=tl.title)]

    def _tile_click(self, tl):
        if tl.drill and not tl.toggles: self.open_pane(tl.drill); return
        tid = tl.id
        if tid == "capture":
            self.on_close(); self.m.toggle("capture"); return
        self.m.toggle(tid)
        if tid in ("dark",): pass
        self.refresh()

    # ------------------------------------------------------------------ sliders
    def _slider(self, key, y, cw, glyph_name, value, level, muted=False, chevron=False):
        t, sp = self.theme, self.sp; x0 = sp["pad"]; h = self._slider_h(); kind = sp["slider"]; nodes = []
        val_w = 34
        if kind == "bar":
            # one thick rounded bar with the icon inside (Control Centre / GNOME)
            bw = cw - (30 if chevron else 0)
            def paint(cr, n, st):
                gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, n.h / 2, t.tile_off)
                frac = 0 if muted else value / 100
                fw = max(n.h, n.w * frac) if frac > 0 else n.h if False else 0
                if frac > 0:
                    cr.save(); gfx.rrect(cr, n.x, n.y, n.w, n.h, n.h / 2); cr.clip()
                    gfx.fill_rrect(cr, n.x, n.y, max(n.h, n.w * frac), n.h, n.h / 2, t.accent); cr.restore()
                over = frac > 0 and (n.w * frac) > 28
                gfx.glyph(cr, glyph_name, n.x + 20, n.y + n.h / 2, 18, t.accent_fg if over else t.fg_muted, level=level)
            node = Node(id="s:" + key, x=x0, y=y, w=bw, h=h - 4 if h > 36 else h, paint=paint, radius=h / 2, on_press=(lambda n, lx, ly, k=key: self._slide(k, n, lx)),
                        on_drag=(lambda n, lx, ly, ph, k=key: self._slide(k, n, lx, ph)), focusable=True, data=key)
            node.y = y + (h - node.h) / 2
            nodes.append(node)
            if chevron:
                nodes.append(Node(id="o:out", x=x0 + bw + 4, y=y + (h - 28) / 2, w=26, h=28, paint=self._icon_btn_paint("chevron_r", 16), on_click=lambda n: self.open_pane("output"), radius=13, tooltip="Sound output"))
            return nodes
        # knob / kylin: icon button + thin track + knob + value
        bx = x0
        def mute_paint(cr, n, st):
            p_button(t, 8)(cr, n, st)
            gfx.glyph(cr, glyph_name, n.x + n.w / 2, n.y + n.h / 2, 20, t.fg, level=level)
        if key == "vol":
            nodes.append(Node(id="m:vol", x=bx, y=y + (h - 36) / 2 if h > 36 else y, w=36, h=36, paint=mute_paint, on_click=lambda n: (self.m.toggle_mute(), self.refresh()), radius=8, tooltip="Mute"))
        else:
            nodes.append(Node(x=bx, y=y + (h - 36) / 2 if h > 36 else y, w=36, h=36, paint=lambda cr, n, st: gfx.glyph(cr, glyph_name, n.x + 18, n.y + 18, 20, t.fg_muted, level=level)))
        tx = bx + 36 + 8; tw = cw - 36 - 8 - val_w - (30 if chevron else 0)
        track_h = 16 if kind == "kylin" else 4
        def paint_track(cr, n, st):
            cy = n.y + n.h / 2; frac = 0 if muted else value / 100
            gfx.fill_rrect(cr, n.x + 8, cy - track_h / 2, n.w - 16, track_h, track_h / 2, t.border_strong if kind == "knob" else t.tile_off)
            if frac > 0: gfx.fill_rrect(cr, n.x + 8, cy - track_h / 2, max(track_h, (n.w - 16) * frac), track_h, track_h / 2, t.accent)
            kx = n.x + 8 + (n.w - 16) * frac
            if kind == "knob":
                r = 9 if (st.hover or st.press) else 8
                gfx.circle(cr, kx, cy, r + 1, (0, 0, 0, 0.18)); gfx.circle(cr, kx, cy, r, t.fg if not t.dark else t.fg)
                gfx.circle(cr, kx, cy, 4 if not st.press else 3, t.accent)
            else:
                gfx.circle(cr, kx - (6 if frac > 0.05 else -6), cy, 4.5, (1, 1, 1, 0.92) if frac > 0.05 else t.fg_muted)
        nodes.append(Node(id="s:" + key, x=tx, y=y + (h - 36) / 2 if h > 36 else y, w=tw, h=36, paint=paint_track, radius=8,
                          on_press=(lambda n, lx, ly, k=key: self._slide(k, n, lx - 8, "start", inner=tw - 16)),
                          on_drag=(lambda n, lx, ly, ph, k=key: self._slide(k, n, lx - 8, ph, inner=tw - 16)), focusable=True, ring=False, data=key))
        nodes.append(Node(x=tx + tw, y=y + (h - 36) / 2 if h > 36 else y, w=val_w, h=36, paint=lambda cr, n, st: gfx.text(cr, "%d" % (0 if muted else value), n.x + n.w, n.y + n.h / 2, 12, t.fg_muted, 500, "r", tnum=True)))
        if chevron:
            nodes.append(Node(id="o:out", x=tx + tw + val_w + 2, y=y + (h - 28) / 2, w=26, h=28, paint=self._icon_btn_paint("chevron_r", 16),
                              on_click=lambda n: self.open_pane("output"), radius=13, tooltip="Sound output"))
        return nodes

    def _icon_btn_paint(self, glyph_name, size=18, col=None):
        t = self.theme
        def paint(cr, n, st):
            p_button(t, min(8, n.radius))(cr, n, st)
            gfx.glyph(cr, glyph_name, n.x + n.w / 2, n.y + n.h / 2, size, col or t.fg_muted if not st.hover else t.fg)
        return paint

    def _slide(self, key, node, lx, phase="start", inner=None):
        inner = inner if inner is not None else node.w
        v = max(0, min(100, round(100 * lx / max(1, inner))))
        if key == "vol": self.m.v["vol"] = v; self.m.v["muted"] = False
        else: self.m.v["bright"] = v
        self._pending = (key, v)
        if phase in ("start", "move", "end"): self._flush(phase == "end")
        self.refresh()

    def _flush(self, final=False):
        key, v = self._pending
        if final or not getattr(self, "_flush_busy", False):
            self._flush_busy = True
            fn = (lambda: self.m.sys.volume_set(v)) if key == "vol" else (lambda: self.m.sys.brightness_set(v))
            self.async_run(fn, lambda _r: setattr(self, "_flush_busy", False))

    # ------------------------------------------------------------------ media
    def _media_card(self, x, y, w):
        t = self.theme; st = self.m.media_state; media = self.m.media; nodes = []
        h = 84
        pos = [0.0]
        def paint(cr, n, s):
            gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, 12 if self.sp["tr"] > 6 else 8, t.tile_off)
            art = st.get("art")
            ax, ay, asz = n.x + 12, n.y + 12, 60
            surf = load_art(art, asz) if art else None
            if surf is not None:
                cr.save(); gfx.rrect(cr, ax, ay, asz, asz, 8); cr.clip(); cr.set_source_surface(surf, ax, ay); cr.paint(); cr.restore()
            else:
                gfx.fill_rrect(cr, ax, ay, asz, asz, 8, t.accent_soft); gfx.glyph(cr, "music", ax + asz / 2, ay + asz / 2, 26, t.accent)
            tx = ax + asz + 12; maxw = n.x + n.w - tx - 12
            gfx.text(cr, st["title"] or "Nothing playing", tx, n.y + 22, 13, t.fg, 600, maxw=maxw)
            gfx.text(cr, st["artist"] or st.get("player", ""), tx, n.y + 40, 12, t.fg_muted, 400, maxw=maxw)
            # progress
            if st.get("length"):
                gfx.fill_rrect(cr, tx, n.y + h - 16, maxw, 3, 1.5, t.border_strong)
                gfx.fill_rrect(cr, tx, n.y + h - 16, max(3, maxw * min(1, st["position"] / st["length"])), 3, 1.5, t.accent)
        nodes.append(Node(x=x, y=y, w=w, h=h, paint=paint))
        bx = x + 12 + 60 + 12 + (w - 12 - 60 - 12 - 12) - 3 * 30 - 4 * 2 + 0
        by = y + 6
        specs = (("prev", "prev", lambda: media.prev(st)), ("pp", "pause" if st["playing"] else "play", lambda: media.play_pause(st)), ("next", "next", lambda: media.next(st)))
        for k, (id_, g, fn) in enumerate(specs):
            def pb(cr, n, s, g=g, id_=id_):
                if id_ == "pp":
                    gfx.fill_rrect(cr, n.x + 1, n.y + 1, n.w - 2, n.h - 2, 14, t.accent if not (s.hover or s.press) else mix(t.accent, (1, 1, 1, 1), 0.12))
                    gfx.glyph(cr, g, n.x + n.w / 2 + (1 if g == "play" else 0), n.y + n.h / 2, 14, t.accent_fg)
                else:
                    p_button(t, 15)(cr, n, s); gfx.glyph(cr, g, n.x + n.w / 2, n.y + n.h / 2, 14, t.fg)
            nodes.append(Node(id="mp:" + id_, x=bx + k * 34, y=y + 46 - 6 - 14 + 6 if False else y + 48 - 14, w=30, h=30, paint=pb, on_click=(lambda n, f=fn: (f(), self.m.refresh(), self.refresh())), radius=15))
        return nodes

    # ------------------------------------------------------------------ footer
    def _footer_buttons(self):
        s = self.m.sys
        return [("settings", "sliders" if False else "gear", "Settings", lambda: s.spawn("carpatic-settings")),
                ("lock", "lock", "Lock", lambda: s.spawn("carpatic-lock")),
                ("power", "power", "Power", lambda: s.spawn("carpatic-powermenu"))]

    def _footer_bottom(self, x, y, w):
        t = self.theme; nodes = []
        nodes.append(Node(x=x, y=y, w=w, h=1, paint=lambda cr, n, st: (cr.set_source_rgba(*t.border), cr.rectangle(n.x, n.y, n.w, 1), cr.fill())))
        y += 12
        b = self.m.v.get("battery")
        if b:
            def pb(cr, n, st):
                gfx.glyph(cr, "battery", n.x + 14, n.y + n.h / 2, 22, t.fg, level=b["percent"], charging=b["charging"])
                if b["charging"]: gfx.glyph(cr, "bolt_fill", n.x + 14 - 1, n.y + n.h / 2, 9, t.success if False else t.fg)
                gfx.text(cr, self.m.battery_text(), n.x + 34, n.y + n.h / 2, 13, t.fg, 500, tnum=True, maxw=n.w - 40)
            nodes.append(Node(x=x, y=y, w=w - 3 * 38 - 4, h=36, paint=pb))
        bx = x + w - 36 * len(self._footer_buttons()) - 2 * (len(self._footer_buttons()) - 1)
        for k, (id_, g, tip, fn) in enumerate(self._footer_buttons()):
            nodes.append(Node(id="f:" + id_, x=bx + k * 38, y=y, w=36, h=36, paint=self._footer_paint(g), on_click=(lambda n, f=fn: (f(), self.on_close())), radius=8, tooltip=tip))
        return nodes

    def _footer_paint(self, g):
        t = self.theme; circle = self.look == "ubuntu"
        def paint(cr, n, st):
            p_button(t, 18 if circle else 8)(cr, n, st)
            gfx.glyph(cr, g, n.x + n.w / 2, n.y + n.h / 2, 20, t.fg)
        return paint

    def _footer_top(self, x, y, w):
        t = self.theme; nodes = []; b = self.m.v.get("battery")
        if b:
            nodes.append(Node(x=x, y=y, w=120, h=36, paint=lambda cr, n, st: (gfx.glyph(cr, "battery", n.x + 14, n.y + 18, 22, t.fg, level=b["percent"]),
                                                                              gfx.text(cr, f"{b['percent']}%", n.x + 34, n.y + 18, 13, t.fg, 600, tnum=True))))
        bs = [("capture", "capture", "Screenshot", lambda: (self.m.sys.screenshot(), self.on_close()))] + self._footer_buttons()
        bx = x + w - 38 * len(bs) + 2
        for k, (id_, g, tip, fn) in enumerate(bs):
            def p(cr, n, st, g=g):
                gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, 18, t.tile_off if not (st.hover or st.press) else t.press); gfx.glyph(cr, g, n.x + 18, n.y + 18, 18, t.fg)
            nodes.append(Node(id="f:" + id_, x=bx + k * 38, y=y, w=36, h=36, paint=p, on_click=(lambda n, f=fn: (f(), self.on_close()) if id_ != "capture" else f()), radius=18, tooltip=tip))
        return nodes

    # ------------------------------------------------------------------ panes
    def _pane_header(self, title, right=None):
        t, sp = self.theme, self.sp; x0 = sp["pad"]; cw = self.W - 2 * sp["pad"]; nodes = []
        def pb(cr, n, st):
            p_button(t, 8)(cr, n, st); gfx.glyph(cr, "chevron_l", n.x + n.w / 2, n.y + n.h / 2, 20, t.fg)
        nodes.append(Node(id="back", x=x0 - 4, y=sp["pad"] - 2, w=36, h=36, paint=pb, on_click=lambda n: self.back(), radius=8, tooltip="Back"))
        nodes.append(Node(x=x0 + 36, y=sp["pad"] - 2, w=cw - 36 - (60 if right else 0), h=36, paint=lambda cr, n, st: gfx.text(cr, title, n.x + 4, n.y + 18, 16, t.fg, 600, maxw=n.w)))
        if right: nodes.append(right)
        return nodes

    def _switch(self, x, y, on, id_, click):
        t = self.theme
        def paint(cr, n, st):
            gfx.fill_rrect(cr, n.x, n.y, 40, 22, 11, t.accent if on else t.border_strong)
            kx = n.x + (30 if on else 10)
            gfx.circle(cr, kx, n.y + 11, 8.5 if st.hover or st.press else 8, t.accent_fg if on else t.fg if t.dark else (1, 1, 1, 1))
        return Node(id=id_, x=x, y=y, w=40, h=22, paint=paint, on_click=click, radius=11)

    def _build_pane(self):
        return {"wifi": self._pane_wifi, "bt": self._pane_bt, "power": self._pane_power, "output": self._pane_output}[self.pane]()

    def _list_row(self, id_, x, y, w, h, glyph_name, title, sub, right_text="", on=False, click=None, glyph_level=3, check=False, lock=False, group=None, tip=None):
        t = self.theme
        def paint(cr, n, st):
            if on: gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, 8, t.accent_soft)
            p_button(t, 8)(cr, n, st)
            col = t.accent if on else t.fg
            gfx.glyph(cr, glyph_name, n.x + 24, n.y + n.h / 2, 20, col, level=glyph_level)
            mw = n.w - 48 - 16 - (30 if (check or lock) else 0) - (gfx.text_size(gfx._scratch(), right_text, 12)[0] + 8 if right_text and False else 0)
            if sub:
                gfx.text(cr, title, n.x + 48, n.y + n.h / 2 - 8, 13, t.fg, 600 if on else 500, maxw=mw)
                gfx.text(cr, sub, n.x + 48, n.y + n.h / 2 + 9, 11.5, t.accent if on else t.fg_muted, 400, maxw=mw)
            else:
                gfx.text(cr, title, n.x + 48, n.y + n.h / 2, 13, t.fg, 600 if on else 500, maxw=mw)
            if check: gfx.glyph(cr, "check", n.x + n.w - 22, n.y + n.h / 2, 18, t.accent, lw=2)
            elif lock: gfx.glyph(cr, "lock", n.x + n.w - 22, n.y + n.h / 2, 15, t.fg_muted)
        return Node(id=id_, x=x, y=y, w=w, h=h, paint=paint, on_click=click, radius=8, group=group, tooltip=tip)

    def _pane_scroll(self, name, top, bottom_pad=12):
        cw = self.W - 2 * self.sp["pad"]
        g = self.groups.get(name)
        if g is None: g = self.groups[name] = Group(self.sp["pad"] - 4, top, cw + 8, self.H - top - bottom_pad)
        g.x, g.y, g.w, g.h = self.sp["pad"] - 4, top, cw + 8, self.H - top - bottom_pad
        return g

    def _pane_wifi(self):
        t, sp, m = self.theme, self.sp, self.m; x0 = sp["pad"]; cw = self.W - 2 * x0
        on = m.v.get("wifi_on", False)
        nodes = self._pane_header("Wi-Fi", self._switch(self.W - x0 - 40, sp["pad"] + 5, on, "sw:wifi", lambda n: (m.toggle("wifi"), self.load("wifi", True), self.refresh())))
        y = sp["pad"] + 44
        nodes.append(Node(x=x0, y=y - 4, w=cw, h=1, paint=lambda cr, n, st: (cr.set_source_rgba(*t.border), cr.rectangle(n.x, n.y, n.w, 1), cr.fill())))
        g = self._pane_scroll("wifi", y, 56)
        cy = y + 4
        if not on:
            nodes.append(Node(x=x0, y=y + 40, w=cw, h=60, paint=lambda cr, n, st: (gfx.glyph(cr, "wifi_off", n.x + n.w / 2, n.y + 10, 28, t.fg_subtle), gfx.text(cr, "Wi-Fi is off", n.x + n.w / 2, n.y + 44, 13, t.fg_muted, 500, "c"))))
            g.content_h = 0
        else:
            nets = m.networks
            if not nets:
                msg = "Looking for networks…" if "wifi" in self.busy else "No networks found"
                nodes.append(Node(x=x0, y=y + 30, w=cw, h=40, paint=lambda cr, n, st: gfx.text(cr, msg, n.x + n.w / 2, n.y + 20, 13, t.fg_muted, 500, "c")))
            for a in nets:
                known = a["ssid"] in m.known
                rh = 52
                sub = "Connected" if a["active"] else ("Saved" if known else ("Secured" if a["secure"] else "Open"))
                nodes.append(self._list_row("w:" + a["ssid"], x0, cy, cw, rh, "wifi", a["ssid"], sub, on=a["active"], click=(lambda n, aa=a: self._wifi_click(aa)),
                                            glyph_level=signal_level(a["signal"]), lock=a["secure"] and not a["active"], group="wifi"))
                cy += rh + 2
                if self.pw_for == a["ssid"]:
                    self.entry_rect = (x0 + 48, cy + 4, cw - 48 - 92, 34)
                    def pw_paint(cr, n, st):
                        gfx.fill_rrect(cr, n.x - 2, n.y, n.w + 4, n.h, 8, t.tile_off)
                    nodes.append(Node(x=x0, y=cy, w=cw, h=44, paint=pw_paint, group="wifi"))
                    nodes.append(Node(id="pw:go", x=x0 + cw - 84, y=cy + 4, w=76, h=34, paint=self._primary_paint("Connect"), on_click=lambda n: self.submit_password(), radius=8, group="wifi"))
                    cy += 48
            g.content_h = cy - y + 4
        bottom = self.H - 48
        def foot(cr, n, st):
            cr.set_source_rgba(*t.border); cr.rectangle(n.x, n.y, n.w, 1); cr.fill()
            if self.status: gfx.text(cr, self.status, n.x, n.y + 24, 12, t.danger if self.status_err else t.fg_muted, 500, maxw=n.w - 120)
        self.status_err = getattr(self, "status_err", False)
        nodes.append(Node(x=x0, y=bottom, w=cw, h=44, paint=foot))
        nodes.append(Node(id="rescan", x=x0 + cw - 108, y=bottom + 6, w=108, h=32, paint=self._link_paint("refresh", "Rescan"), on_click=lambda n: self.load("wifi", True), radius=8))
        return nodes

    def _primary_paint(self, label):
        t = self.theme
        def paint(cr, n, st):
            c = t.accent
            gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, n.radius, c)
            if st.hover or st.press: gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, n.radius, (1, 1, 1, 0.12) if t.accent_fg[0] > 0.5 else (0, 0, 0, 0.10))
            gfx.text(cr, label, n.x + n.w / 2, n.y + n.h / 2, 13, t.accent_fg, 600, "c")
        return paint

    def _link_paint(self, glyph_name, label):
        t = self.theme
        def paint(cr, n, st):
            p_button(t, 8)(cr, n, st)
            w = gfx.text_size(gfx._scratch(), label, 12.5, 500)[0]
            x = n.x + (n.w - (w + 22)) / 2
            gfx.glyph(cr, glyph_name, x + 8, n.y + n.h / 2, 15, t.fg_muted); gfx.text(cr, label, x + 22, n.y + n.h / 2, 12.5, t.fg_muted, 500)
        return paint

    def _wifi_click(self, a):
        m = self.m
        if a["active"]:
            self.status = ""; self.async_run(lambda: m.sys.wifi_disconnect(), lambda _r: (self.load("wifi"), None)); return
        known = a["ssid"] in m.known
        if a["secure"] and not known:
            self.pw_for = a["ssid"]; self.pw_text = ""; self.status = ""; self.refresh(); return
        self._wifi_connect(a["ssid"], None)

    def _wifi_connect(self, ssid, pw):
        self.status = f"Connecting to {ssid}…"; self.status_err = False; self.refresh()
        def done(res):
            ok, msg = res; self.status = msg; self.status_err = not ok
            if ok: self.pw_for = None; self.entry_rect = None; self.m.refresh()
            self.load("wifi"); self.refresh()
        self.async_run(lambda: self.m.sys.wifi_connect(ssid, pw), done)

    def submit_password(self):
        if self.pw_for and self.pw_text: self._wifi_connect(self.pw_for, self.pw_text)

    def _pane_bt(self):
        t, sp, m = self.theme, self.sp, self.m; x0 = sp["pad"]; cw = self.W - 2 * x0
        on = m.v.get("bt_on", False)
        nodes = self._pane_header("Bluetooth", self._switch(self.W - x0 - 40, sp["pad"] + 5, on, "sw:bt", lambda n: (m.toggle("bt"), self.load("bt"), self.refresh())))
        y = sp["pad"] + 44
        nodes.append(Node(x=x0, y=y - 4, w=cw, h=1, paint=lambda cr, n, st: (cr.set_source_rgba(*t.border), cr.rectangle(n.x, n.y, n.w, 1), cr.fill())))
        g = self._pane_scroll("bt", y, 56); cy = y + 4
        if not on:
            nodes.append(Node(x=x0, y=y + 40, w=cw, h=60, paint=lambda cr, n, st: (gfx.glyph(cr, "bluetooth", n.x + n.w / 2, n.y + 10, 28, t.fg_subtle), gfx.text(cr, "Bluetooth is off", n.x + n.w / 2, n.y + 44, 13, t.fg_muted, 500, "c"))))
            g.content_h = 0
        else:
            if not m.bt_devices:
                nodes.append(Node(x=x0, y=y + 30, w=cw, h=40, paint=lambda cr, n, st: gfx.text(cr, "No paired devices", n.x + n.w / 2, n.y + 20, 13, t.fg_muted, 500, "c")))
            for d in m.bt_devices:
                ic = "headphones" if "head" in d["icon"] else "keyboard" if "keyboard" in d["icon"] else "bluetooth"
                nodes.append(self._list_row("b:" + d["mac"], x0, cy, cw, 52, ic, d["name"], "Connected" if d["connected"] else "Paired", on=d["connected"],
                                            click=(lambda n, dd=d: self._bt_click(dd)), group="bt"))
                cy += 54
            g.content_h = cy - y + 4
        bottom = self.H - 48
        nodes.append(Node(x=x0, y=bottom, w=cw, h=44, paint=lambda cr, n, st: (cr.set_source_rgba(*t.border), cr.rectangle(n.x, n.y, n.w, 1), cr.fill(),
                                                                              gfx.text(cr, self.status, n.x, n.y + 24, 12, t.fg_muted, 500, maxw=n.w - 190))))
        nodes.append(Node(id="btmore", x=x0 + cw - 180, y=bottom + 6, w=180, h=32, paint=self._link_paint("gear", "More Bluetooth settings"),
                          on_click=lambda n: (m.sys.spawn("blueman-manager"), self.on_close()), radius=8))
        return nodes

    def _bt_click(self, d):
        self.status = ("Disconnecting " if d["connected"] else "Connecting to ") + d["name"] + "…"; self.refresh()
        def done(ok):
            self.status = "" if ok else f"Could not reach {d['name']}. Is it switched on and nearby?"; self.status_err = not ok
            self.load("bt"); self.m.refresh(); self.refresh()
        self.async_run(lambda: self.m.sys.bt_toggle_device(d["mac"], not d["connected"]), done)

    def _pane_power(self):
        t, sp, m = self.theme, self.sp, self.m; x0 = sp["pad"]; cw = self.W - 2 * x0
        nodes = self._pane_header("Power mode"); y = sp["pad"] + 48
        cur = m.v.get("profile")
        info = (("saver", "Power saver", "Longer battery life, quieter fans"), ("balanced", "Balanced", "Good performance and battery life"), ("performance", "Performance", "Fastest, uses more power"))
        for k, (pid, title, desc) in enumerate(info):
            nodes.append(self._list_row("p:" + pid, x0, y + k * 64, cw, 60, PROFILE_GLYPH[pid], title, desc, on=pid == cur, check=pid == cur,
                                        click=(lambda n, p=pid: (m.set_profile(p), self.refresh()))))
        return nodes

    def _pane_output(self):
        t, sp, m = self.theme, self.sp, self.m; x0 = sp["pad"]; cw = self.W - 2 * x0
        nodes = self._pane_header("Sound output"); y = sp["pad"] + 48
        g = self._pane_scroll("out", y, 12); cy = y
        if not m.sinks:
            nodes.append(Node(x=x0, y=y + 24, w=cw, h=30, paint=lambda cr, n, st: gfx.text(cr, "No sound devices found", n.x + n.w / 2, n.y + 15, 13, t.fg_muted, 500, "c")))
        for sid, name, dflt in m.sinks:
            ic = "headphones" if any(k in name.lower() for k in ("head", "wh-", "buds", "airpods")) else "volume"
            nodes.append(self._list_row("o:%d" % sid, x0, cy, cw, 52, ic, name, "Default" if dflt else "", on=dflt, check=dflt, click=(lambda n, i=sid: (m.set_sink(i), self.refresh())), group="out"))
            cy += 54
        g.content_h = cy - y
        return nodes


def gfx_cr():
    from .kit import scratch_cr
    return scratch_cr()


_ART = {}


def load_art(path, size):
    if (path, size) in _ART: return _ART[(path, size)]
    surf = None
    try:
        from gi.repository import GdkPixbuf, Gdk
        pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, size, size, False)
        surf = Gdk.cairo_surface_create_from_pixbuf(pb, 1, None)
    except Exception:
        surf = None
    _ART[(path, size)] = surf
    return surf
