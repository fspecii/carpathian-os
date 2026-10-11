"""Popup host for flyouts: override-redirect GTK window around a Canvas, grabbed pointer + keyboard, closes on Esc / outside click / focus loss,
rounded by XShape without a compositor (true alpha with one), small slide-in, optional text entry overlay positioned by the view."""
import math, os, signal, time
import cairo
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib
from .kit import Canvas
from . import uiscale, motion
from .theme import Theme


def rounded_region(w, h, r):
    """1-bit rounded-rectangle region built from scanlines (what XShape can express)."""
    reg = cairo.Region()
    r = int(min(r, w // 2, h // 2))
    for y in range(h):
        if y < r: dy = r - y - 0.5
        elif y >= h - r: dy = y - (h - r) + 0.5
        else: dy = None
        inset = 0 if dy is None else int(math.ceil(r - (r * r - dy * dy) ** 0.5 + 0.5))
        reg.union(cairo.RectangleInt(inset, y, max(1, w - 2 * inset), 1))
    return reg


def entry_css(theme: Theme):
    fg = "#%02x%02x%02x" % tuple(int(c * 255) for c in theme.fg[:3])
    sub = "#%02x%02x%02x" % tuple(int(c * 255) for c in theme.fg_subtle[:3])
    return uiscale.css(f"""
    window entry.cp, window entry.cp:focus, window entry.cp:hover, window entry.cp:disabled {{ background: none; background-color: transparent; background-image: none;
                border: none; border-image: none; border-radius: 0; box-shadow: none; outline: none; color: {fg}; padding: 0; margin: 0; min-height: 0;
                font-family: "{theme.font}", "Noto Sans", sans-serif; font-size: 13px; caret-color: {fg}; text-shadow: none; }}
    window entry.cp selection {{ background: alpha({fg}, 0.25); color: {fg}; }}
    window entry.cp placeholder {{ color: {sub}; }}
    """)


class Popup(Gtk.Window):
    def __init__(self, view, theme, pos, edge="bottom", on_closed=None, slide=True):
        super().__init__(type=Gtk.WindowType.POPUP)
        self.view, self.theme, self.edge, self.on_closed = view, theme, edge, on_closed
        self._sources = set()
        self._closed = False
        scr = self.get_screen(); vis = scr.get_rgba_visual()
        self._screen = scr
        self._rgba = vis is not None
        self.composited = bool(self._rgba and scr.is_composited())
        # Keep an RGBA visual available when composition starts later. XShape
        # supplies the rounded outline while composition is absent.
        if self._rgba: self.set_visual(vis)
        self.set_app_paintable(True)
        self.canvas = Canvas(view)
        self.canvas.frame_alpha = 1.0; self.canvas.clear_first = self.composited
        self.overlay = Gtk.Overlay(); self.overlay.add(self.canvas); self.add(self.overlay)
        self.entry = None
        css = Gtk.CssProvider(); css.load_from_data(entry_css(theme).encode())
        Gtk.StyleContext.add_provider_for_screen(scr, css, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        self._entry_css = css
        self._compositor_signal = scr.connect("composited-changed", self._compositor_changed)
        orig = self.canvas.rebuild
        def rebuild():
            orig(); self.sync_entry()
        self.canvas.rebuild = rebuild
        self.canvas.rebuild()
        w, h = uiscale.dev(view.size()[0]), uiscale.dev(view.size()[1]); self.set_default_size(w, h); self.resize(w, h)
        self.connect("key-press-event", self.on_key); self.connect("button-press-event", self.on_button)
        self.connect("realize", self.on_realize); self.connect("destroy", self._destroyed)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.KEY_PRESS_MASK)
        self.final = pos
        self._duration = motion.slide_duration(slide)
        self.slide = self._duration > 0
        # Position before mapping; keep the first unpainted GTK buffer hidden.
        # The flyout stays opaque while sliding, so underlying app icons cannot
        # appear through its content during the opening transition.
        self._paint_ready = False
        self._anim = 0
        self.move(*(self._start_pos() if self.slide else pos))
        if self.composited: self.set_opacity(0)
        self.canvas.connect_after("draw", self._first_paint)
        self.show_all()
        self._schedule(0, self.grab_all)

    def _schedule(self, delay, callback):
        holder = []
        def run():
            keep = False if self._closed else bool(callback())
            if not keep: self._sources.discard(holder[0])
            return keep
        source = GLib.timeout_add(delay, run) if delay else GLib.idle_add(run)
        holder.append(source)
        self._sources.add(source)
        return source

    def _destroyed(self, *_):
        self._closed = True
        dispose = getattr(self.view, 'dispose', None)
        if dispose: dispose()
        for source in tuple(self._sources): GLib.source_remove(source)
        self._sources.clear()
        self._screen.disconnect(self._compositor_signal)
        Gtk.StyleContext.remove_provider_for_screen(self._screen, self._entry_css)
        if Gtk.main_level(): Gtk.main_quit()

    def on_realize(self, *_):
        self._update_surface()

    def _compositor_changed(self, *_):
        self.composited = bool(self._rgba and self._screen.is_composited())
        self.canvas.clear_first = self.composited
        self.set_opacity(0 if self.composited and not self._paint_ready else 1)
        self._update_surface()
        self.canvas.queue_draw()

    def _update_surface(self):
        window = self.get_window()
        if window is None: return
        # Initialise even an uncomposited, not-yet-painted window with its own
        # surface colour; X11 must never expose a recycled backing buffer.
        r, g, b = self.theme.surface[:3]
        window.set_background_rgba(Gdk.RGBA(red=r, green=g, blue=b, alpha=1))
        if self.view.framed:
            w, h = uiscale.dev(self.view.size()[0]), uiscale.dev(self.view.size()[1])
            region = None if self.composited else rounded_region(w, h, uiscale.devr(self.view.radius))
            window.shape_combine_region(region, 0, 0)

    def _start_pos(self):
        x, y = self.final; d = uiscale.devr(12)
        return {"bottom": (x, y + d), "top": (x, y - d), "left": (x - d, y), "right": (x + d, y)}.get(self.edge, (x, y))

    def _first_paint(self, *_):
        if not self._paint_ready:
            self._paint_ready = True
            self._schedule(0, self._reveal)
        return False

    def _reveal(self):
        if self.get_window() is None: return False
        if self.composited: self.set_opacity(1)
        if self.slide:
            self._started = time.monotonic()
            self._schedule(16, self._slide_step)
        return False

    def _slide_step(self):
        t = min(1.0, (time.monotonic() - self._started) / self._duration); e = 1 - (1 - t) ** 3
        self._anim = 7 if t == 1 else 0
        sx, sy = self._start_pos(); fx, fy = self.final
        self.move(int(sx + (fx - sx) * e), int(sy + (fy - sy) * e))
        return t < 1.0

    def grab_all(self):
        win = self.get_window()
        if win is None: return False
        seat = Gdk.Display.get_default().get_default_seat()
        # Pointer-only grab (outside clicks close the flyout). The KEYBOARD is never grabbed: a global keyboard grab silences dwm's hotkeys and could lock the
        # user out. Keys reach us through plain X input focus instead, and the window gives everything back on Esc, click outside, focus loss or 30 s idle.
        seat.grab(win, Gdk.SeatCapabilities.POINTER, True, None, None, None)
        try:
            from .xlib import X
            x = X(); x.set_focus(win.get_xid()); x.close()
        except Exception: pass
        self.canvas.grab_focus()
        self._schedule(700, lambda: (self.connect("focus-out-event", self._focus_out), False)[1])   # armed after start-up, which produces a spurious focus-out
        self._idle = self._schedule(30000, self._idle_close)
        return False

    def _focus_out(self, w, ev):
        # something else took the input focus (another window was clicked or activated): give everything back
        if self._anim_done() and not ev.in_ and not (self.entry is not None and self.entry.has_focus()):
            self._schedule(0, self.close_me)
        return False

    def _anim_done(self): return not getattr(self, "slide", False) or getattr(self, "_anim", 99) >= 7

    def _idle_close(self):
        self.close_me(); return False

    def poke(self):
        """Any key or click restarts the 30 s safety timer."""
        if getattr(self, "_idle", None) in self._sources:
            GLib.source_remove(self._idle); self._sources.discard(self._idle)
        self._idle = self._schedule(30000, self._idle_close)

    def sync_entry(self):
        r = getattr(self.view, "entry_rect", None)
        if r is None:
            if self.entry is not None: self.overlay.remove(self.entry); self.entry = None
            return
        x, y, w, h = r
        kind = getattr(self.view, "entry_kind", "text")
        if self.entry is None:
            e = Gtk.Entry(); e.get_style_context().add_class("cp"); e.set_has_frame(False)
            e.set_placeholder_text(getattr(self.view, "entry_placeholder", "Add event, e.g. Lunch tomorrow 13:00"))
            e.set_visibility(kind != "password"); e.set_halign(Gtk.Align.START); e.set_valign(Gtk.Align.START)
            e.connect("changed", lambda en: self.view.on_entry_change(en.get_text()) if hasattr(self.view, "on_entry_change") else None)
            e.connect("activate", lambda en: self.view.on_entry_activate(en.get_text(), en) if hasattr(self.view, "on_entry_activate") else None)
            self.overlay.add_overlay(e); self.entry = e; e.show()
            GLib.idle_add(e.grab_focus)
        D = uiscale.devr
        self.entry.set_size_request(D(w - 40), D(h))
        self.entry.set_margin_start(D(x + 38)); self.entry.set_margin_top(D(y))
        self.view.live_entry = True

    def on_key(self, w, ev):
        self.poke()
        if ev.keyval == Gdk.KEY_Escape:
            if self.canvas.view.key(ev): self.canvas.invalidate(); return True
            self.close_me(); return True
        if self.entry is not None and self.entry.has_focus(): return False
        if self.canvas.handle_key(ev): return True
        return False

    def on_button(self, w, ev):
        self.poke()
        x, y = self.get_position(); a = self.get_allocation()
        if not (x <= ev.x_root <= x + a.width and y <= ev.y_root <= y + a.height): self.close_me()
        return False

    def close_me(self, *_):
        if self._closed: return False
        try: Gdk.Display.get_default().get_default_seat().ungrab()
        except Exception: pass
        if self.on_closed: self.on_closed()
        self.destroy()
        return False


def toggle_instance(mode, pidfile):
    """True when another flyout was running with the same mode (it is closed and we must not reopen)."""
    try:
        parts = open(pidfile).read().split(); old = int(parts[0]); mode_old = parts[1]
        os.kill(old, 0); os.kill(old, signal.SIGTERM); time.sleep(0.15)
        if mode_old == mode: return True
    except Exception:
        pass
    open(pidfile, "w").write(f"{os.getpid()} {mode}")
    return False
