"""Carpathian Quick Look widgets that are not specific to one file type: the close button in the user's window-button style, the zoomable image
canvas, the seek bar (waveform), and a small mpv remote control."""
import os, json, math, socket, subprocess, time
import cairo
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf

def rgb(h, a=1.0):
    h = h.lstrip("#"); return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255, a)

def rounded(cr, x, y, w, h, r):
    r = max(0, min(r, w / 2, h / 2))
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0); cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi); cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2); cr.close_path()

# ------------------------------------------------------------------------------------------ close button
class CloseButton(Gtk.EventBox):
    """The window close button, drawn like the title-bar buttons of the active style (docs/DESIGN-SYSTEM.md 9.14)."""
    def __init__(self, style, look, on_close):
        super().__init__()
        self.style, self.look, self.on_close = style, look, on_close
        self.hover = self.down = False
        self.area = Gtk.DrawingArea(); self.add(self.area)
        w = {"windows": 46, "macos": 20, "gnome": 30, "kde": 28, "contrast": 34, "omarchy": 30}.get(style, 30)
        self.set_size_request(w, 40)
        self.set_visible_window(False)
        self.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK | Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK)
        self.connect("enter-notify-event", lambda *a: self._set(hover=True))
        self.connect("leave-notify-event", lambda *a: self._set(hover=False, down=False))
        self.connect("button-press-event", lambda *a: self._set(down=True))
        self.connect("button-release-event", self._release)
        self.area.connect("draw", self.draw)
        self.set_tooltip_text("Close (Space or Esc)")
    def _set(self, **kw):
        for k, v in kw.items(): setattr(self, k, v)
        self.area.queue_draw()
    def _release(self, w, ev):
        was = self.down; self._set(down=False)
        if was and self.hover: self.on_close()
    def draw(self, w, cr):
        L, st = self.look, self.style
        W, H = w.get_allocated_width(), w.get_allocated_height()
        cx, cy = W / 2, H / 2
        fg = L["fg"]; hov, dn = self.hover, self.down
        def glyph(color, s=5.0, lw=1.4):
            cr.set_source_rgba(*rgb(color) if isinstance(color, str) else color); cr.set_line_width(lw); cr.set_line_cap(cairo.LINE_CAP_ROUND)
            cr.move_to(cx - s, cy - s); cr.line_to(cx + s, cy + s); cr.move_to(cx + s, cy - s); cr.line_to(cx - s, cy + s); cr.stroke()
        if st == "none":
            return
        if st == "macos":
            c = rgb(L["red"]); k = 0.75 if dn else 1
            cr.set_source_rgba(c[0] * k, c[1] * k, c[2] * k, 1); cr.arc(cx, cy, 6, 0, 6.2832); cr.fill()
            cr.set_source_rgba(0, 0, 0, 0.18); cr.set_line_width(0.8); cr.arc(cx, cy, 5.8, 0, 6.2832); cr.stroke()
            if hov: glyph((0, 0, 0, 0.62), 2.6, 1.3)
        elif st == "windows":
            if hov:
                cr.set_source_rgba(*rgb(L["red"], 0.78 if dn else 1)); cr.rectangle(0, 0, W, H); cr.fill()
            glyph("#ffffff" if hov else fg, 5.0, 1.0)
        elif st in ("gnome", "minimal", "ring"):
            r = 12 if st == "gnome" else 7
            if st == "ring":
                cr.set_source_rgba(*rgb(L["red"] if hov else fg, 0.6 if not hov else 1)); cr.set_line_width(1.5); cr.arc(cx, cy, r, 0, 6.2832); cr.stroke()
                if hov: cr.set_source_rgba(*rgb(L["red"], 0.6 if dn else 0.3)); cr.arc(cx, cy, r - 1, 0, 6.2832); cr.fill()
            elif st == "minimal":
                cr.set_source_rgba(*rgb(L["red"] if hov else fg, 1 if hov else 0.55)); cr.arc(cx, cy, 5, 0, 6.2832); cr.fill()
            else:
                a = 0.22 if dn else 0.14 if hov else 0.07
                cr.set_source_rgba(*rgb(L["red"] if hov else fg, 0.3 if hov else a)); cr.arc(cx, cy, r, 0, 6.2832); cr.fill()
                glyph(fg, 4.0, 1.6)
        else:                                           # kde, squircle, contrast, omarchy: a plate or a bare glyph
            if st in ("kde", "squircle"):
                size, rad = (22, 4) if st == "kde" else (22, 7)
                rounded(cr, cx - size / 2, cy - size / 2, size, size, rad)
                cr.set_source_rgba(*rgb(L["red"] if hov else fg, (1 if dn else 0.88) if hov else 0.10)); cr.fill()
                glyph("#ffffff" if hov else fg, 4.5, 1.3)
            elif st == "contrast":
                rounded(cr, cx - 14, cy - 14, 28, 28, 3)
                if hov:
                    cr.set_source_rgba(*rgb(fg, 0.8 if dn else 1)); cr.fill()
                else:
                    cr.set_source_rgba(*rgb(fg)); cr.set_line_width(2.2); cr.stroke()
                glyph(L["surface"] if hov else fg, 6, 2.0)
            else:
                glyph(L["red"] if hov else rgb(fg, 0.55), 6, 1.4)
        return True

# ------------------------------------------------------------------------------------------ zoomable picture
class Canvas(Gtk.ScrolledWindow):
    """A picture in a scroller: fit, 100 %, zoom with + - 0 1 or Ctrl+wheel, drag to pan. Draws the pixbuf scaled by cairo (no copies)."""
    def __init__(self, look, on_zoom=None, on_resize_render=None):
        super().__init__()
        self.look, self.pb, self.zoom, self.fit = look, None, 1.0, True
        self.on_zoom, self.on_resize_render = on_zoom, on_resize_render
        self.native = (0, 0)        # real size of the picture in pixels (the pixbuf can be a smaller preview)
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.area = Gtk.DrawingArea(); self.add(self.area)
        self.area.connect("draw", self.draw)
        self.connect("size-allocate", lambda *a: self.refit())
        self.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.POINTER_MOTION_MASK)
        self.connect("scroll-event", self.on_scroll)
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.POINTER_MOTION_MASK)
        self.area.connect("button-press-event", self.on_press); self.area.connect("button-release-event", lambda *a: setattr(self, "drag", None))
        self.area.connect("motion-notify-event", self.on_motion); self.drag = None
    def set_pixbuf(self, pb, native=None, keep_zoom=False):
        self.pb = pb
        self.native = native or (pb.get_width(), pb.get_height())
        if not keep_zoom: self.fit = True
        self.refit()
    def _scale_of_pb(self):          # cairo scale that maps the pixbuf to the *native* size at zoom 1
        return self.native[0] / max(1, self.pb.get_width())
    def fit_zoom(self):
        W, H = self.get_allocated_width(), self.get_allocated_height()
        if not self.pb or W < 10: return 1.0
        return min(1.0, W / self.native[0], H / self.native[1]) if self.native[0] else 1.0
    def refit(self):
        if not self.pb: return
        if self.fit: self.zoom = self.fit_zoom()
        w, h = int(self.native[0] * self.zoom), int(self.native[1] * self.zoom)
        self.area.set_size_request(w, h)
        self.area.queue_draw()
        if self.on_zoom: self.on_zoom(self.zoom, self.fit)
    def set_zoom(self, z, fit=False):
        self.fit = fit; self.zoom = max(0.05, min(z, 16.0)); self.refit()
        if self.on_resize_render: self.on_resize_render()
    def zoom_by(self, f): self.set_zoom(self.zoom * f)
    def draw(self, w, cr):
        if not self.pb: return
        W, H = w.get_allocated_width(), w.get_allocated_height()
        iw, ih = self.native[0] * self.zoom, self.native[1] * self.zoom
        ox, oy = max(0, (W - iw) / 2), max(0, (H - ih) / 2)
        cr.translate(ox, oy)
        s = self.zoom * self._scale_of_pb()
        # a quiet checkerboard under transparent pictures
        if self.pb.get_has_alpha():
            cr.save(); cr.rectangle(0, 0, iw, ih); cr.clip()
            for yy in range(0, int(ih) + 12, 12):
                for xx in range(0, int(iw) + 12, 12):
                    cr.set_source_rgba(*rgb(self.look["fg"], 0.07 if (xx // 12 + yy // 12) % 2 else 0.12)); cr.rectangle(xx, yy, 12, 12); cr.fill()
            cr.restore()
        cr.scale(s, s)
        Gdk.cairo_set_source_pixbuf(cr, self.pb, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_BEST if self.zoom < 1 else cairo.FILTER_NEAREST if self.zoom > 3 else cairo.FILTER_BILINEAR)
        cr.paint()
    def on_scroll(self, w, ev):
        if ev.state & Gdk.ModifierType.CONTROL_MASK:
            if ev.direction == Gdk.ScrollDirection.UP: self.zoom_by(1.15)
            elif ev.direction == Gdk.ScrollDirection.DOWN: self.zoom_by(1 / 1.15)
            return True
        return False
    def on_press(self, w, ev):
        self.drag = (ev.x_root, ev.y_root, self.get_hadjustment().get_value(), self.get_vadjustment().get_value())
        if ev.type == Gdk.EventType.DOUBLE_BUTTON_PRESS:                   # double click: actual size <-> fit
            self.set_zoom(1.0) if self.fit else self.set_zoom(0, fit=True)
        return True
    def on_motion(self, w, ev):
        if self.drag:
            x0, y0, hx, vy = self.drag
            self.get_hadjustment().set_value(hx - (ev.x_root - x0)); self.get_vadjustment().set_value(vy - (ev.y_root - y0))

# ------------------------------------------------------------------------------------------ seek bar / waveform
class SeekBar(Gtk.DrawingArea):
    """Waveform when we have peaks, a plain rounded bar otherwise. Played part in the accent colour. Click or drag to seek."""
    def __init__(self, look, on_seek, height=64):
        super().__init__()
        self.look, self.on_seek, self.peaks, self.frac = look, on_seek, None, 0.0
        self.set_size_request(-1, height)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.POINTER_MOTION_MASK)
        self.connect("draw", self.draw); self.down = False
        self.connect("button-press-event", self._p); self.connect("button-release-event", lambda *a: setattr(self, "down", False))
        self.connect("motion-notify-event", self._m)
    def set_frac(self, f):
        if abs(f - self.frac) > 0.0005: self.frac = f; self.queue_draw()
    def _seek(self, ev): self.on_seek(max(0.0, min(1.0, ev.x / max(1, self.get_allocated_width()))))
    def _p(self, w, ev): self.down = True; self._seek(ev)
    def _m(self, w, ev):
        if self.down: self._seek(ev)
    def draw(self, w, cr):
        L = self.look
        W, H = w.get_allocated_width(), w.get_allocated_height()
        if self.peaks:
            n = len(self.peaks); gap = 2; bw = max(2.0, (W - gap * (n - 1)) / n)
            mid = H / 2
            for i, p in enumerate(self.peaks):
                x = i * (bw + gap); h = max(3, p * (H - 6))
                cr.set_source_rgba(*rgb(L["accent"]) if (i + 0.5) / n <= self.frac else rgb(L["fg"], 0.22))
                rounded(cr, x, mid - h / 2, bw, h, bw / 2); cr.fill()
        else:
            cy = H / 2
            rounded(cr, 0, cy - 3, W, 6, 3); cr.set_source_rgba(*rgb(L["fg"], 0.2)); cr.fill()
            rounded(cr, 0, cy - 3, max(6, W * self.frac), 6, 3); cr.set_source_rgba(*rgb(L["accent"])); cr.fill()
            cr.arc(max(6, W * self.frac), cy, 7, 0, 6.2832); cr.fill()

# ------------------------------------------------------------------------------------------ mpv remote
class Mpv:
    """Starts mpv for ONE file (no config, no scripts, no youtube-dl, no network protocols) and talks to it over its IPC socket."""
    def __init__(self, path, rtdir, wid=None, vo=None):
        self.sock_path = os.path.join(rtdir, "mpv-%d-%d.sock" % (os.getpid(), int(time.time() * 1000) % 100000))
        args = ["mpv", "--no-config", "--no-terminal", "--really-quiet", "--idle=no", "--keep-open=yes", "--input-ipc-server=" + self.sock_path,
                "--no-input-default-bindings", "--no-input-vo-keyboard", "--no-osc", "--no-osd-bar", "--cursor-autohide=no", "--ytdl=no",
                "--load-scripts=no", "--sub-auto=no", "--audio-display=no", "--volume=85", "--no-input-terminal", "--load-unsafe-playlists=no",
                "--demuxer-max-bytes=48MiB", "--demuxer-max-back-bytes=8MiB"]
        args += ["--no-video"] if wid is None else ["--wid=%d" % wid, "--hwdec=no"] + (["--vo=" + vo] if vo else [])
        self.p = subprocess.Popen(args + ["--", path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.s = None; self.t0 = time.monotonic(); self.rid = 0
    def alive(self): return self.p.poll() is None
    def _conn(self):
        if self.s: return True
        if not os.path.exists(self.sock_path): return False
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(0.08); s.connect(self.sock_path); self.s = s; return True
        except OSError:
            return False
    def cmd(self, *a):
        if not self._conn(): return None
        self.rid += 1
        try:
            self.s.sendall((json.dumps({"command": list(a), "request_id": self.rid}) + "\n").encode())
            buf = b""
            end = time.monotonic() + 0.12
            while time.monotonic() < end:
                buf += self.s.recv(65536)
                for line in buf.split(b"\n"):
                    if not line: continue
                    try: d = json.loads(line)
                    except ValueError: continue
                    if d.get("request_id") == self.rid: return d.get("data") if d.get("error") == "success" else None
        except (OSError, ValueError):
            pass
        return None
    def get(self, prop): return self.cmd("get_property", prop)
    def toggle(self): self.cmd("cycle", "pause")
    def seek_abs(self, sec): self.cmd("seek", sec, "absolute")
    def seek_rel(self, sec): self.cmd("seek", sec, "relative")
    def stop(self):
        if self.s:
            try: self.s.close()
            except OSError: pass
            self.s = None
        if self.p.poll() is None:
            self.p.terminate()
            try: self.p.wait(0.4)
            except subprocess.TimeoutExpired: self.p.kill(); self.p.wait()
        try: os.unlink(self.sock_path)
        except OSError: pass
