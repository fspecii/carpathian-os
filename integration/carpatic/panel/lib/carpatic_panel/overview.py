"""Workspace overview (Super+Tab on Windows/Tiling, Ctrl+Alt+Up everywhere, the taskbar's Task view button, three-finger swipe up).
One card per workspace with its windows drawn as a master/stack sketch (what auto-tiling would do); click a card or press its number to go there,
drag a window onto another card to move it. Like the flyouts it never grabs the keyboard: keys arrive through X input focus, and Esc, a click outside,
losing focus or 30 s without input close it."""
import math
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib
import cairo
from .theme import Theme
from .ewmh import Ewmh
from .xlib import X
from . import gfx, uiscale


def sketch(n, x, y, w, h, gap=5):
    """Rectangles for n windows: master on the left (55 %), the rest stacked on the right."""
    if n <= 0: return []
    if n == 1: return [(x, y, w, h)]
    mw = (w - gap) * 0.55
    out = [(x, y, mw, h)]
    k = n - 1; sh = (h - gap * (k - 1)) / k
    for i in range(k): out.append((x + mw + gap, y + i * (sh + gap), w - mw - gap, sh))
    return out


class Overview(Gtk.Window):
    def __init__(self, theme, ewmh):
        super().__init__(type=Gtk.WindowType.POPUP)
        self.t, self.ew = theme, ewmh
        self.n, self.cur, self.names = ewmh.desktops()
        self.n = max(1, self.n)
        self.sel = self.cur
        self.press_win = None; self.press_xy = (0, 0); self.moved = False
        self.drag = None; self.drag_xy = (0, 0); self.hits = []; self.cards = []
        self.load()
        sc = Gdk.Display.get_default().get_primary_monitor() or Gdk.Display.get_default().get_monitor(0)
        g = sc.get_workarea()   # without the bars and docks (dwm publishes _NET_WORKAREA)
        self.cols = 3 if self.n > 4 else min(self.n, 4)
        self.rows = math.ceil(self.n / self.cols)
        ch = min(((min(g.width - 80, 1180) - 24 * (self.cols + 1)) / self.cols) * 9 / 16, (g.height - 40 - 36 - self.rows * 52) / self.rows)
        self.ch = max(60, ch); cw = self.ch * 16 / 9
        self.W = cw * self.cols + 24 * (self.cols + 1)
        self.H = int(24 + self.rows * (self.ch + 52) + 12)
        self.set_default_size(int(self.W), self.H); self.resize(int(self.W), self.H)
        self.area = Gtk.DrawingArea(); self.area.connect("draw", self.on_draw); self.add(self.area)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.KEY_PRESS_MASK)
        self.connect("key-press-event", self.on_key); self.connect("button-press-event", self.on_press)
        self.connect("button-release-event", self.on_release); self.connect("motion-notify-event", self.on_motion)
        self.show_all()
        self.move(int(g.x + (g.width - self.W) / 2), int(g.y + (g.height - self.H) / 2))
        GLib.idle_add(self.grab_pointer_and_focus)
        self.idle = GLib.timeout_add_seconds(30, self.close_me)

    def load(self):
        self.by_ws = {i: [] for i in range(self.n)}
        for w in self.ew.windows():
            if 0 <= w.desktop < self.n: self.by_ws[w.desktop].append(w)

    def grab_pointer_and_focus(self):
        win = self.get_window()
        if win is None: return False
        Gdk.Display.get_default().get_default_seat().grab(win, Gdk.SeatCapabilities.POINTER, True, None, None, None)
        try:
            x = X(); x.set_focus(win.get_xid()); x.close()
        except Exception: pass
        GLib.timeout_add(700, lambda: (self.connect("focus-out-event", self._focus_out), False)[1])   # armed after start-up, which produces a spurious focus-out
        return False

    def _focus_out(self, w, ev):
        if not ev.in_: GLib.idle_add(self.close_me)
        return False

    def poke(self):
        GLib.source_remove(self.idle); self.idle = GLib.timeout_add_seconds(30, self.close_me)

    def close_me(self, *_):
        try: Gdk.Display.get_default().get_default_seat().ungrab()
        except Exception: pass
        Gtk.main_quit(); return False

    # ------------------------------------------------------------------ drawing
    def on_draw(self, w, cr):
        t = self.t; W, H = self.W, self.H
        gfx.fill_rrect(cr, 0, 0, W, H, 14, t.surface)
        cr.set_source_rgba(*t.border_strong); gfx.rrect(cr, 0.5, 0.5, W - 1, H - 1, 14); cr.set_line_width(1); cr.stroke()
        self.hits = []; self.cards = []
        gapx = 24; cw = (W - gapx * (self.cols + 1)) / self.cols
        for i in range(self.n):
            r, c = divmod(i, self.cols)
            x = gapx + c * (cw + gapx); y = 24 + r * (self.ch + 52)
            self.cards.append((i, x, y, cw, self.ch))
            focus = i == self.sel
            gfx.fill_rrect(cr, x, y, cw, self.ch, 8, t.card)
            if i == self.cur: cr.set_source_rgba(*t.accent); gfx.rrect(cr, x + 1, y + 1, cw - 2, self.ch - 2, 8); cr.set_line_width(2); cr.stroke()
            elif focus: cr.set_source_rgba(*t.border_strong); gfx.rrect(cr, x + 1, y + 1, cw - 2, self.ch - 2, 8); cr.set_line_width(2); cr.stroke()
            wins = self.by_ws[i]
            for j, (wx, wy, ww, wh) in enumerate(sketch(len(wins), x + 10, y + 10, cw - 20, self.ch - 20)):
                win = wins[j]
                if self.drag is win: continue
                gfx.fill_rrect(cr, wx, wy, ww, wh, 5, t.surface2)
                cr.set_source_rgba(*(t.accent if win.active else t.border_strong)); gfx.rrect(cr, wx + .5, wy + .5, ww - 1, wh - 1, 5); cr.set_line_width(1); cr.stroke()
                gfx.text(cr, win.title or win.klass or "Window", wx + 8, wy + min(16, wh / 2), 11, t.fg_muted, 500, maxw=ww - 14)
                self.hits.append((win, wx, wy, ww, wh, i))
            if not wins: gfx.text(cr, "Empty", x + cw / 2, y + self.ch / 2, 12, t.fg_subtle, 500, "c")
            name = self.names[i] if i < len(self.names) and self.names[i] and self.names[i] != str(i + 1) else ""
            gfx.text(cr, f"{i + 1}  {name}" if name else f"Workspace {i + 1}", x + 4, y + self.ch + 18, 12.5, t.fg if i == self.cur else t.fg_muted, 700 if i == self.cur else 500)
        if self.drag:
            dx, dy = self.drag_xy
            gfx.fill_rrect(cr, dx - 60, dy - 20, 120, 40, 6, t.accent_soft)
            cr.set_source_rgba(*t.accent); gfx.rrect(cr, dx - 59.5, dy - 19.5, 119, 39, 6); cr.set_line_width(1); cr.stroke()
            gfx.text(cr, self.drag.title or "Window", dx - 52, dy, 11, t.fg, 600, maxw=104)

    # ------------------------------------------------------------------ input
    def card_at(self, x, y):
        for i, cx, cy, cw, ch in self.cards:
            if cx <= x <= cx + cw and cy <= y <= cy + ch + 28: return i
        return None

    def go(self, i):
        self.ew.switch_desktop(i); self.close_me()

    def on_press(self, w, ev):
        self.poke()
        if not (0 <= ev.x <= self.W and 0 <= ev.y <= self.H): self.close_me(); return True
        self.press_xy = (ev.x, ev.y); self.moved = False
        self.press_win = next((h[0] for h in self.hits if h[1] <= ev.x <= h[1] + h[3] and h[2] <= ev.y <= h[2] + h[4]), None)
        return True

    def on_motion(self, w, ev):
        i = self.card_at(ev.x, ev.y)
        if self.press_win_active(ev):
            self.drag = self.press_win; self.drag_xy = (ev.x, ev.y); self.moved = True
        if i is not None and i != self.sel and not self.drag: self.sel = i
        self.area.queue_draw(); return True

    def press_win_active(self, ev):
        return bool(ev.state & Gdk.ModifierType.BUTTON1_MASK) and getattr(self, "press_win", None) is not None and \
            (abs(ev.x - self.press_xy[0]) > 6 or abs(ev.y - self.press_xy[1]) > 6)

    def on_release(self, w, ev):
        i = self.card_at(ev.x, ev.y)
        if self.drag is not None:
            win = self.drag; self.drag = None
            if i is not None and i != win.desktop:
                self.ew.x.send(win.id, "_NET_WM_DESKTOP", (i, 2, 0, 0, 0)); self.ew.x.flush()
                self.by_ws[win.desktop] = [v for v in self.by_ws[win.desktop] if v is not win]; win.desktop = i; self.by_ws[i].append(win)
            self.area.queue_draw(); return True
        if i is not None: self.go(i)
        return True

    def on_key(self, w, ev):
        self.poke(); k = ev.keyval
        if k == Gdk.KEY_Escape: self.close_me(); return True
        if k in (Gdk.KEY_Return, Gdk.KEY_KP_Enter): self.go(self.sel); return True
        if Gdk.KEY_1 <= k <= Gdk.KEY_9 and k - Gdk.KEY_1 < self.n: self.go(k - Gdk.KEY_1); return True
        d = {Gdk.KEY_Left: -1, Gdk.KEY_Right: 1, Gdk.KEY_Up: -self.cols, Gdk.KEY_Down: self.cols, Gdk.KEY_Tab: 1, Gdk.KEY_ISO_Left_Tab: -1}.get(k)
        if d: self.sel = max(0, min(self.n - 1, self.sel + d)); self.area.queue_draw(); return True
        return False


def main():
    import os, signal
    from .config import runtime_dir
    pidfile = os.path.join(runtime_dir(), f"carpatic-overview.{os.getuid()}")
    try:   # calling it again closes it
        old = int(open(pidfile).read())
        cmd = open(f"/proc/{old}/cmdline", "rb").read().split(b"\0")
        if cmd and cmd[0].startswith(b"python") and any(a.endswith(b"carpatic-overview") for a in cmd[1:3]):
            os.kill(old, signal.SIGTERM); return 0   # only ever signal a real overview, never a recycled pid
    except Exception: pass
    open(pidfile, "w").write(str(os.getpid()))
    def bye(*_):
        try: os.unlink(pidfile)
        except OSError: pass
        os._exit(0)
    signal.signal(signal.SIGTERM, bye)
    try:
        ov = Overview(Theme.load(), Ewmh(X())); Gtk.main(); del ov
    finally:
        try: os.unlink(pidfile)
        except OSError: pass
    return 0
