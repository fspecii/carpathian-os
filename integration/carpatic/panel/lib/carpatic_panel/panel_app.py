"""carpatic-panel: the daemon. One process, one X connection for EWMH, one GTK window per surface (bar or dock) and monitor."""
import json, os, shutil, signal, subprocess, sys, threading, time
import cairo
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0"); gi.require_version("GdkX11", "3.0")
from gi.repository import Gtk, Gdk, GdkX11, GLib

from . import config, designs, tasks as tk, gfx, placement, system as sysmod, uiscale
from .theme import Theme
from .kit import Canvas, scratch_cr
from .barview import BarView, Ctx
from .xlib import X
from .ewmh import Ewmh
from .tray import TrayManager
from .menu import MenuView
from .popup import Popup, rounded_region
from . import preview as pv


def bin_path(name):
    here = os.path.dirname(os.path.abspath(sys.argv[0]))
    for p in (os.path.join(here, name), shutil.which(name)):
        if p and os.path.exists(p): return p
    return name


def spawn(argv):
    try: return subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError: return None


class SurfaceWin(Gtk.Window):
    """One bar or dock on one monitor."""

    def __init__(self, panel, surf, mon, primary_bar):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.panel, self.surf, self.mon = panel, surf, mon
        self.set_decorated(False); self.set_resizable(True); self.set_type_hint(Gdk.WindowTypeHint.DOCK)
        self.set_skip_taskbar_hint(True); self.set_skip_pager_hint(True); self.set_accept_focus(False); self.set_app_paintable(True)
        self.stick(); self.set_keep_above(True)
        # dwm treats a wide dock-type window as THE bar; every other dock only reserves a strip when named carpatic-dock*
        self.set_title("carpatic-panel" if (surf.kind == "main" and primary_bar) else f"carpatic-dock-{surf.role}")
        scr = self.get_screen(); vis = scr.get_rgba_visual()
        self.composited = bool(vis and scr.is_composited())
        if self.composited: self.set_visual(vis)
        self.view = BarView(panel.theme, surf, panel.opts, panel.ctx, 100)
        mx, my, mw, mh = mon
        # monitor sizes are device px; the view is laid out in logical px (design tokens) and the Canvas multiplies by the UI scale
        length = uiscale.logical(mw) if surf.horizontal and surf.kind == "main" else uiscale.logical(mh - (uiscale.dev(30) if surf.role == "dock" and not surf.horizontal else 0))
        self.view.set_length(length)
        self.canvas = Canvas(self.view); self.canvas.frame_alpha = 0.97 if self.composited else 1.0; self.canvas.clear_first = self.composited
        self.overlay = Gtk.Overlay(); self.overlay.add(self.canvas); self.add(self.overlay)
        self.hidden = False; self.hide_timer = None
        self.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.connect("enter-notify-event", self.on_enter); self.connect("leave-notify-event", self.on_leave)
        self.connect("realize", self.on_realize)
        orig = self.canvas.rebuild
        def rebuild(): orig(); self.after_build()
        self.canvas.rebuild = rebuild
        self.place(); self.show_all()

    # ------------------------------------------------------------------ geometry
    def natural(self):
        """Logical size of the view."""
        v = self.view
        if self.surf.kind == "dock" and v.horiz: v.set_length(max(v.natural_length(), 120))
        return v.size()

    def dsize(self):
        """Device size of the window (logical size x UI scale)."""
        w, h = self.natural(); return uiscale.dev(w), uiscale.dev(h)

    def origin(self):
        mx, my, mw, mh = self.mon; s = self.surf; w, h = self.dsize()
        if s.horizontal:
            x = mx if s.kind == "main" else mx + (mw - w) // 2
            y = my if s.edge == "top" else my + mh - h
        else:
            top = uiscale.dev(30) if s.role == "dock" and self.panel.has_topbar else 0
            x = mx if s.edge == "left" else mx + mw - w
            y = my + top; self.view.set_length(uiscale.logical(mh - top)); w, h = self.dsize()
        return x, y

    def place(self):
        w, h = self.dsize(); x, y = self.origin()
        self.set_default_size(w, h); self.resize(w, h); self.move(x, y)
        self.canvas.set_size_request(w, h)
        if self.get_realized(): self.apply_shape(); self.apply_struts()

    def on_realize(self, *_):
        self.apply_shape(); self.apply_struts()

    def apply_shape(self):
        win = self.get_window()
        if win is None: return
        cx, cy, cw, ch, r = self.view.shape_rects()
        w, h = self.view.size()
        if (cx, cy, cw, ch) == (0, 0, w, h) and not r: win.shape_combine_region(None, 0, 0); win.input_shape_combine_region(cairo.Region(), 0, 0) if False else None; return
        cx, cy, cw, ch, r = uiscale.devr(cx), uiscale.devr(cy), uiscale.dev(cw), uiscale.dev(ch), uiscale.devr(r)      # logical -> device px
        reg = rounded_region(cw, ch, r) if (r and not self.composited) else cairo.Region(cairo.RectangleInt(0, 0, cw, ch))
        reg.translate(cx, cy)
        win.shape_combine_region(reg, 0, 0); win.input_shape_combine_region(reg, 0, 0)

    def apply_struts(self):
        win = self.get_window()
        if win is None: return
        try: xid = win.get_xid()
        except Exception: return
        p = self.panel
        w, h = self.dsize(); x, y = self.origin(); s = self.surf
        sw, sh = p.screen_size
        d = uiscale.dev(self.view.T + self.view.margin)
        if self.hidden or p.opts.get("autohide") == "on": d = 0
        l = r = t = b = 0; rng = (0,) * 8
        if s.edge == "bottom": b = d + (sh - (self.mon[1] + self.mon[3])); rng = (0, 0, 0, 0, 0, 0, x, x + w - 1)
        elif s.edge == "top": t = d + self.mon[1]; rng = (0, 0, 0, 0, x, x + w - 1, 0, 0)
        elif s.edge == "left": l = d + self.mon[0]; rng = (y, y + h - 1, 0, 0, 0, 0, 0, 0)
        else: r = d + (sw - (self.mon[0] + self.mon[2])); rng = (0, 0, y, y + h - 1, 0, 0, 0, 0)
        p.ewmh.set_struts(xid, l, r, t, b, rng)

    # ------------------------------------------------------------------ after a layout
    def after_build(self):
        v = self.view
        if "tray" in v.rects and self.panel.tray is not None and self.panel.tray_win is self:
            tr = self.panel.tray; tr.rect = v.rects["tray"]; tr.horizontal = v.horiz; tr.layout()
        if self.surf.kind == "dock" and v.horiz:
            w, h = self.dsize()
            if (w, h) != tuple(self.get_size()): GLib.idle_add(self.place)
        self.panel.publish()

    # ------------------------------------------------------------------ autohide
    def on_enter(self, *_):
        if self.hide_timer: GLib.source_remove(self.hide_timer); self.hide_timer = None
        if self.hidden: self.reveal()

    def on_leave(self, w, ev):
        if self.panel.opts.get("autohide") == "on" and not self.hidden and ev.detail != Gdk.NotifyType.INFERIOR:
            if self.hide_timer: GLib.source_remove(self.hide_timer)
            self.hide_timer = GLib.timeout_add(700, self.conceal)

    def conceal(self):
        self.hide_timer = None
        if self.panel.popup_open: return False
        self.hidden = True; x, y = self.origin(); w, h = self.dsize()
        e = self.surf.edge
        if e == "bottom": y = self.mon[1] + self.mon[3] - 2
        elif e == "top": y = self.mon[1] - h + 2
        elif e == "left": x = self.mon[0] - w + 2
        else: x = self.mon[0] + self.mon[2] - 2
        self.move(x, y); return False

    def reveal(self):
        self.hidden = False; x, y = self.origin(); self.move(x, y)


class PanelCtx(Ctx):
    """Bridges BarView to the panel."""

    def __init__(self, panel): self.p = panel; self.tasks = []; self.tray_w = 0; self.notif_count = 0; self.dnd = False; self.flyout_open = None
    def now(self): return self.p.now()
    def icon(self, task, size): return self.p.task_icon(task, size)
    def activate(self, task): self.p.activate(task)
    def task_menu(self, task, node, ev): self.p.task_menu(task, node, ev)
    def task_middle(self, task): self.p.launch_new(task)
    def hover_task(self, task, node): self.p.hover_task(task, node)
    def flyout(self, name, node): self.p.flyout(name, node)
    def show_desktop(self): self.p.show_desktop()
    def switch_tag(self, n): self.p.ewmh.switch_desktop(n)
    def panel_menu(self, ev, node): self.p.panel_menu(ev)
    def reorder(self, task, i): self.p.reorder(task, i)
    def overflow(self, tasks, node): self.p.overflow_menu(tasks, node)


class Panel:
    def __init__(self, fake=False, cfg_path=None):
        self.fake = fake; self.cfg_path = cfg_path
        self.cfg = config.load(cfg_path); self.opts = designs.resolve(self.cfg)
        self.theme = Theme.load(None if self.cfg.get("theme", "auto") == "auto" else self.cfg["theme"])
        self.x = X(); self.ewmh = Ewmh(self.x)
        self.apps = {}; self.order = {}; self.wins = []
        self.ctx = PanelCtx(self)
        self.surfaces = []; self.popup_open = False; self.tray = None; self.tray_win = None
        self.icon_cache = {}; self.win_icons = {}
        self.hover = None; self.hover_timer = None; self.tip = None; self.preview = None; self.preview_leave = None
        self.screen_size = (0, 0); self.has_topbar = False
        self.dirty = None; self.flyout_proc = None; self._pub = None
        self.battery = None
        self.apps = tk.catalogue()
        d = Gdk.Display.get_default()
        sw = sh = 0
        for i in range(d.get_n_monitors()):
            g = d.get_monitor(i).get_geometry(); sw = max(sw, g.x + g.width); sh = max(sh, g.y + g.height)
        self.screen_size = (sw, sh)

    # ------------------------------------------------------------------ lifecycle
    def monitors(self):
        d = Gdk.Display.get_default(); out = []
        prim = d.get_primary_monitor()
        for i in range(d.get_n_monitors()):
            m = d.get_monitor(i); g = m.get_geometry(); out.append(((g.x, g.y, g.width, g.height), m == prim or (prim is None and i == 0)))
        out.sort(key=lambda t: not t[1]); return out

    def build_surfaces(self):
        for s in self.surfaces: s.destroy()
        self.surfaces = []
        if self.tray: self.tray.release(); self.tray = None
        self.opts = designs.resolve(self.cfg)
        self.ctx.dnd = False
        specs = designs.surfaces(self.cfg)
        self.has_topbar = any(s.role in ("topbar", "menubar") for s in specs)
        mons = self.monitors()
        if self.opts.get("monitors", "primary") == "primary": mons = mons[:1]
        for geo, primary in mons:
            for sp in specs:
                if not primary and sp.kind != "main": continue
                self.surfaces.append(SurfaceWin(self, sp, geo, primary_bar=(sp.kind == "main")))
        # tray goes to the surface that has the item
        for sw_ in self.surfaces:
            if "tray" in sw_.surf.left + sw_.surf.center + sw_.surf.right and (self.tray_win is None or self.tray_win not in self.surfaces):
                self.tray_win = sw_
        if self.tray_win in self.surfaces and self.opts.get("tray", "on") != "off":
            self.tray = TrayManager(self.x, self.on_tray_change, 18 if self.opts["icon_size"] < 40 else 20)      # logical px; self.tray.overlay = self.tray_win.overlay
            self.try_tray(0)
        self.refresh_all()

    def try_tray(self, n):
        if self.tray is None: return False
        if self.tray.acquire(): self.on_tray_change(); return False
        if n < 40: GLib.timeout_add(500, lambda: self.try_tray(n + 1) and False)
        return False

    def on_tray_change(self):
        self.ctx.tray_w = self.tray.width() if self.tray else 0
        self.refresh_all()

    def run(self):
        open(config.runtime_pid_path(), "w").write(str(os.getpid()))
        self.build_surfaces()
        self.x.attach(GLib, self.on_x)
        self.read_windows()
        GLib.timeout_add_seconds(1, self.clock_tick)
        GLib.timeout_add_seconds(20, self.poll_status); self.poll_status()
        signal.signal(signal.SIGUSR1, lambda *a: GLib.idle_add(self.reload))
        self.watch_theme()
        # a new display scale (Settings > Displays, or another screen): xsettingsd updates GTK's Xft DPI -> rebuild every surface at the new size
        self._dpi_t = 0
        def dpi_changed(*_):
            if self._dpi_t: GLib.source_remove(self._dpi_t)
            self._dpi_t = GLib.timeout_add(600, lambda: (setattr(self, "_dpi_t", 0), self.reload() if uiscale.refresh() else None, False)[2])
        Gtk.Settings.get_default().connect("notify::gtk-xft-dpi", dpi_changed)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: (Gtk.main_quit(), False)[1])
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, lambda: (Gtk.main_quit(), False)[1])
        try: Gtk.main()
        finally:
            try:
                if int(open(config.runtime_pid_path()).read().split()[0]) == os.getpid(): os.unlink(config.runtime_pid_path())
            except (OSError, ValueError, IndexError): pass
            try: os.unlink(placement.state_path())
            except OSError: pass

    def watch_theme(self):
        """Retint when the theme / accent / light-dark setting changes (inotify, no polling): settings.conf and current/accent.effective."""
        from gi.repository import Gio
        cfg = os.environ.get("CARPATIC_CONFIG", os.path.expanduser("~/.config/carpatic")); state = os.environ.get("CARPATIC_STATE", os.path.expanduser("~/.local/state/carpatic"))
        self._mons = []
        for path in (f"{cfg}/settings.conf", f"{state}/current/accent.effective"):
            try:
                m = Gio.File.new_for_path(path).monitor_file(Gio.FileMonitorFlags.WATCH_MOVES, None)
                m.connect("changed", lambda mon, f, o, ev: self.theme_changed() if ev in (Gio.FileMonitorEvent.CHANGES_DONE_HINT, Gio.FileMonitorEvent.CREATED, Gio.FileMonitorEvent.MOVED_IN, Gio.FileMonitorEvent.RENAMED) else None)
                self._mons.append(m)
            except GLib.Error: pass

    def theme_changed(self):
        if getattr(self, "_tc", None): GLib.source_remove(self._tc)
        self._tc = GLib.timeout_add(500, lambda: (setattr(self, "_tc", None), self.reload(), False)[2])

    def reload(self):
        uiscale.refresh(); self.icon_cache.clear(); gfx._ICON_CACHE.clear()
        self.cfg = config.load(self.cfg_path); self.theme = Theme.load(None if self.cfg.get("theme", "auto") == "auto" else self.cfg["theme"])
        self.build_surfaces(); self.read_windows(); return False

    # ------------------------------------------------------------------ clock + status
    def now(self):
        import datetime
        return datetime.datetime.now()

    def clock_tick(self):
        fmt = (self.opts.get("clock_format") or "") + "%S"
        sec = "%S" in (self.opts.get("clock_format") or "")
        n = self.now(); key = n.strftime(self.opts.get("clock_format") or "%H:%M")
        if key != getattr(self, "_clk", None):
            self._clk = key
            for s in self.surfaces: s.canvas.invalidate()
        return True

    def poll_status(self):
        def work():
            s = sysmod.System()
            bat = s.battery(); vol = s.volume(); wifi_on = None; level = 0; has_wifi = False; wired = False
            try:
                wired = bool(s.wired_active()); has_wifi = bool(s.has_wifi())
                if has_wifi:
                    wifi_on = s.wifi_enabled(); a = s.wifi_active() if wifi_on else None; level = sysmod.signal_level(a["signal"]) if a else 0
            except Exception: pass
            dnd = s.dnd()
            cnt = 0
            if shutil.which("dunstctl"):
                try: cnt = int(subprocess.run(["dunstctl", "count", "history"], capture_output=True, text=True, timeout=2).stdout.strip() or 0)
                except Exception: cnt = 0
            GLib.idle_add(self.apply_status, bat, vol, wifi_on, level, dnd, cnt, has_wifi, wired)
        threading.Thread(target=work, daemon=True).start(); return True

    def apply_status(self, bat, vol, wifi_on, level, dnd, cnt, has_wifi=True, wired=False):
        c = self.ctx; c.has_wifi, c.wired = has_wifi, wired
        c.battery = bat["percent"] if bat else None; c.charging = bool(bat and bat["charging"])
        if vol: c.vol, c.muted = vol
        c.wifi_on = True if wifi_on is None else wifi_on; c.wifi_level = level if wifi_on else (3 if wifi_on is None else 0)
        c.dnd = bool(dnd); c.notif_count = cnt
        self.refresh_all(); return False

    # ------------------------------------------------------------------ windows
    def on_x(self, kind, win, extra):
        if self.tray and self.tray.handle(kind, win, extra): return
        why = self.ewmh.handle(kind, win, extra)
        if why:
            if self.dirty is None: self.dirty = GLib.timeout_add(40, self.read_windows)

    def read_windows(self):
        self.dirty = None
        self.wins = self.ewmh.windows()
        for w in self.wins:
            g = self.ewmh.geometry(w.id)
            if g:
                cx = g[0] + g[2] // 2
                if cx <= 0: w.minimized = w.minimized   # parked off-screen by dwm: another tag or minimised, still listed
        pinned = [p for p in (self.opts.get("pinned") or config_default_pinned()).split(",") if p]
        self.ctx.tasks = tk.build_tasks(self.wins, pinned, self.apps, group=self.opts.get("grouping", "on") == "on", order=self.order)
        act = next((w for w in self.wins if w.active), None)
        if act:
            a = tk.match_app(act, self.apps)
            self.ctx.focus_app = a.name if a else (act.klass or act.title); self.ctx.focus_title = act.title
        else: self.ctx.focus_app, self.ctx.focus_title = "Desktop", ""
        n, cur, names = self.ewmh.desktops(); self.ctx.tags = (n, cur, names); self.ctx.occupied = frozenset(w.desktop for w in self.wins)
        self.refresh_all(); return False

    def refresh_all(self):
        for s in self.surfaces: s.canvas.invalidate()

    def task_icon(self, task, size):
        k = (task.key, size)
        if k in self.icon_cache: return self.icon_cache[k]
        sf = gfx.load_icon(task.icon, size) if task.icon else None
        if sf is None and task.windows:
            sf = self.window_icon(task.windows[0], size)
        if sf is None and task.windows:
            sf = gfx.load_icon(task.windows[0].klass.lower(), size) or gfx.load_icon(task.windows[0].instance.lower(), size)
        if sf is None: sf = gfx.load_icon("application-x-executable", size) or gfx.load_icon("application-default-icon", size)
        if len(self.icon_cache) > 300: self.icon_cache.clear()
        self.icon_cache[k] = sf; return sf

    def window_icon(self, w, size):
        ic = self.ewmh.icon(w.id, size)
        if not ic: return None
        iw, ih, px = ic
        buf = bytearray(iw * ih * 4)
        for i, v in enumerate(px):
            a = (v >> 24) & 255; r = ((v >> 16) & 255) * a // 255; g = ((v >> 8) & 255) * a // 255; b = (v & 255) * a // 255
            buf[i * 4:i * 4 + 4] = bytes((b, g, r, a))
        return cairo.ImageSurface.create_for_data(buf, cairo.FORMAT_ARGB32, iw, ih, iw * 4)

    # ------------------------------------------------------------------ actions
    def launch(self, app):
        if app is None: return
        argv = tk.exec_argv(app.exec)
        if argv: spawn(argv)

    def launch_new(self, task):
        if task.app: self.launch(task.app)

    def activate(self, task):
        self.hide_hover()
        if not task.windows: self.launch(task.app); return
        ws = task.windows
        if task.active:
            if len(ws) == 1: self.ewmh.minimize(ws[0].id); self.minimise_fallback(ws[0])
            else:
                i = next(i for i, w in enumerate(ws) if w.active); self.ewmh.activate(ws[(i + 1) % len(ws)].id)
        else:
            self.ewmh.activate(ws[-1].id if len(ws) > 1 else ws[0].id)

    def minimise_fallback(self, w):
        """dwm minimises with Super+n (it does not know WM_CHANGE_STATE yet: see panel/NEEDS.md)."""
        if os.environ.get("CARPATIC_PANEL_NO_XDOTOOL") == "1" or not shutil.which("xdotool"): return
        def later():
            if self.ewmh.active_id() == w.id and not self.fake: spawn(["xdotool", "key", "--clearmodifiers", "super+n"])
            return False
        GLib.timeout_add(120, later)

    def show_desktop(self): spawn([bin_path("carpatic-showdesktop")] if shutil.which("carpatic-showdesktop") else ["xdotool", "key", "super+d"])

    def reorder(self, task, new_index):
        pinned = [p for p in (self.opts.get("pinned") or config_default_pinned()).split(",") if p]
        ids = [t.app.id for t in self.ctx.tasks if t.pinned and t.app]
        old = ids.index(task.app.id) if task.app and task.app.id in ids else -1
        if old < 0: return
        ids = tk.move_pin(ids, old, new_index); self.set_option("pinned", ",".join(ids))

    def set_option(self, k, v):
        self.cfg = config.load(self.cfg_path); self.cfg[k] = config.validate(k, v); config.save(self.cfg, self.cfg_path)
        self.reload()

    # ------------------------------------------------------------------ menus
    def popup_menu(self, items, x, y, edge="bottom"):
        mv = MenuView(self.theme, items, lambda: self._close_menu())
        w, h = uiscale.dev(mv.size()[0]), uiscale.dev(mv.size()[1]); sw, sh = self.screen_size
        px = max(4, min(x, sw - w - 4)); py = y - h if edge == "bottom" else y
        py = max(4, min(py, sh - h - 4))
        self.popup_open = True
        self._menu = Popup(mv, self.theme, (px, py), edge, on_closed=lambda: setattr(self, "popup_open", False), slide=False)
        return self._menu

    def _close_menu(self):
        m = getattr(self, "_menu", None)
        if m: m.close_me()
        self.popup_open = False

    def surface_of(self, node):
        for s in self.surfaces:
            if node in s.canvas.nodes: return s
        return self.surfaces[0] if self.surfaces else None

    def node_screen_rect(self, node):
        s = self.surface_of(node); ox, oy = s.origin()
        f = uiscale.factor()      # nodes are logical px, screen rectangles device px
        return (ox + node.x * f, oy + node.y * f, node.w * f, node.h * f), s.surf.edge

    def task_menu(self, task, node, ev):
        self.hide_hover()
        rect, edge = self.node_screen_rect(node); items = []
        if task.app: items.append(dict(label=f"Open new window" if task.running else f"Open {task.name}", glyph="plus", action=lambda: self.launch(task.app)))
        for name, ex in (task.app.actions if task.app else [])[:4]:
            items.append(dict(label=name, glyph="chevron_r", action=lambda ex=ex: spawn(tk.exec_argv(ex))))
        if task.app:
            pinned = [p for p in (self.opts.get("pinned") or config_default_pinned()).split(",") if p]
            is_pin = task.pinned
            items.append(dict(sep=True))
            items.append(dict(label="Unpin from panel" if is_pin else "Pin to panel", glyph="pin", action=lambda: self.set_option("pinned", ",".join(tk.toggle_pin(pinned, task.app.id)))))
        if task.windows:
            items.append(dict(sep=True))
            w0 = task.windows[0]
            items.append(dict(label="Restore" if task.all_minimized else "Minimize", glyph="minus", action=lambda: [self.ewmh.activate(w0.id) if task.all_minimized else (self.ewmh.minimize(w0.id), self.minimise_fallback(w0))]))
            items.append(dict(label="Maximize", glyph="grid", action=lambda: self.ewmh.maximize(w0.id)))
            n = len(task.windows)
            items.append(dict(label="Close window" if n == 1 else f"Close all {n} windows", glyph="close", danger=True, action=lambda: [self.ewmh.close(w.id) for w in task.windows]))
        ex, ey, ew, eh = rect
        self.popup_menu(items, int(ex + ew / 2 - 100), int(ey - 6 if edge == "bottom" else ey + eh + 6), edge)

    def overflow_menu(self, tasks, node):
        rect, edge = self.node_screen_rect(node)
        items = [dict(label=(t.windows[0].title if t.windows else t.name)[:48] or t.name, glyph="dot" if not t.active else "check", action=lambda t=t: self.activate(t)) for t in tasks]
        self.popup_menu(items, int(rect[0]), int(rect[1] - 6 if edge == "bottom" else rect[1] + rect[3] + 6), edge)

    def panel_menu(self, ev):
        self.hide_hover(); opts = self.opts
        items = [dict(label="Show desktop", glyph="desktop", action=self.show_desktop),
                 dict(label="Auto-hide panel", glyph="eye", checked=opts.get("autohide") == "on", action=lambda: self.set_option("autohide", "off" if opts.get("autohide") == "on" else "on")),
                 dict(sep=True)]
        for n, d in designs.DESIGNS.items():
            items.append(dict(label=d["label"], checked=opts["design"] == n, action=lambda n=n: self.set_option("design", n)))
        items += [dict(sep=True), dict(label="Panel settings…", glyph="gear", action=lambda: spawn(["carpatic-settings"]))]
        edge = self.surfaces[0].surf.edge if self.surfaces else "bottom"
        self.popup_menu(items, int(ev.x_root), int(ev.y_root), edge if edge in ("bottom", "top") else "bottom")

    # ------------------------------------------------------------------ flyouts
    def flyout(self, name, node):
        self.hide_hover()
        rect, edge = self.node_screen_rect(node)
        if name in ("search", "taskview", "widgets"):
            cmd = {"search": ["carpatic-launch", "search"], "taskview": ["carpatic-overview"], "widgets": ["carpatic-widgets", "toggle"]}[name]
            spawn(cmd); return
        look = self.opts.get("start", "win") if name == "start" else self.opts.get("flyout", "win")
        argv = [bin_path("carpatic-flyout"), name, "--anchor", ",".join(str(int(v)) for v in rect), "--edge", edge, "--look", look]
        if self.theme.dark is not None and self.cfg.get("theme", "auto") != "auto": argv += ["--mode-theme", self.cfg["theme"]]
        if name == "start" and self.opts.get("align") == "center" and self.surfaces and self.surfaces[0].surf.horizontal: argv += ["--align", "center"]
        if os.environ.get("CARPATIC_FAKE") == "1": argv.append("--fake")
        was_open = self.ctx.flyout_open == name
        p = spawn(argv)
        if p is None: return
        self.flyout_proc = p; self.ctx.flyout_open = None if was_open else name; self.refresh_all()
        def watch():
            p.wait(); GLib.idle_add(self.flyout_closed, p)
        threading.Thread(target=watch, daemon=True).start()

    def flyout_closed(self, p):
        if self.flyout_proc is p: self.ctx.flyout_open = None; self.flyout_proc = None; self.refresh_all(); self.poll_status()
        return False

    # ------------------------------------------------------------------ tooltips and previews
    def hover_task(self, task, node):
        if self.opts.get("previews", "on") != "on": return
        if self.popup_open: return
        self.hover = (task, node)
        if self.hover_timer: GLib.source_remove(self.hover_timer)
        self.hover_timer = GLib.timeout_add(380, self.show_hover)

    def hide_hover(self):
        if self.hover_timer: GLib.source_remove(self.hover_timer); self.hover_timer = None
        self.hover = None
        for a in ("tip", "preview"):
            w = getattr(self, a)
            if w is not None: w.destroy(); setattr(self, a, None)

    def show_hover(self):
        self.hover_timer = None
        if not self.hover: return False
        task, node = self.hover
        s = self.surface_of(node)
        if s is None or s.canvas.hover_id != node.id: self.hover = None; return False
        rect, edge = self.node_screen_rect(node)
        sw, sh = self.screen_size; screen = (0, 0, sw, sh)
        for a in ("tip", "preview"):
            w = getattr(self, a)
            if w is not None: w.destroy(); setattr(self, a, None)
        if task.windows and any(not w.minimized for w in task.windows) and self.opts["design"] not in ("minimal",):
            thumbs = {}
            for w in task.windows:
                pb = pv.grab_thumbnail(w.id, 192, 112)
                if pb is not None: thumbs[w.id] = pv.pb_surface(pb)
            view = pv.PreviewView(self.theme, task, lambda sz: self.task_icon(task, sz), thumbs,
                                  on_activate=lambda w: (self.ewmh.activate(w.id), self.hide_hover()), on_close=lambda w: (self.ewmh.close(w.id), self.hide_hover()))
            self.preview = pv.Float(view, self.theme, pv.place_near(rect, self._dsz(view), edge, screen, uiscale.devr(10)), on_leave=self.preview_left)
        else:
            tip = pv.TipView(self.theme, task.name if not task.windows else (task.windows[0].title or task.name))
            self.tip = pv.Float(tip, self.theme, pv.place_near(rect, self._dsz(tip), edge, screen, uiscale.devr(8)))
        GLib.timeout_add(250, self.watch_hover)
        return False

    @staticmethod
    def _dsz(view):
        w, h = view.size(); return uiscale.dev(w), uiscale.dev(h)

    def preview_left(self):
        GLib.timeout_add(300, lambda: (self.maybe_hide(), False)[1])

    def watch_hover(self):
        if self.preview is None and self.tip is None: return False
        self.maybe_hide(); return self.preview is not None or self.tip is not None

    def maybe_hide(self):
        d = Gdk.Display.get_default(); seat = d.get_default_seat(); _, px, py = seat.get_pointer().get_position()
        if self.preview is not None:
            x, y = self.preview.get_position(); w, h = self._dsz(self.preview.view)
            over_pv = x - 4 <= px <= x + w + 4 and y - 4 <= py <= y + h + 4
        else: over_pv = False
        over_item = False
        if self.hover:
            _, node = self.hover; rect, _e = self.node_screen_rect(node)
            over_item = rect[0] <= px <= rect[0] + rect[2] and rect[1] <= py <= rect[1] + rect[3]
        gap = False
        if self.preview is not None and not over_pv and not over_item and self.hover:
            x, y = self.preview.get_position(); w, h = self._dsz(self.preview.view); _, node = self.hover; rect, _e = self.node_screen_rect(node)
            gap = (rect[0] - 6 <= px <= rect[0] + rect[2] + 6) and (min(y, rect[1]) <= py <= max(y + h, rect[1] + rect[3]))
        if not (over_pv or over_item or gap): self.hide_hover()

    # ------------------------------------------------------------------ published geometry (flyouts read it)
    def publish(self):
        if self._pub: return
        self._pub = GLib.idle_add(self._do_publish)

    def _do_publish(self):
        self._pub = None
        surf = []
        for s in self.surfaces:
            if not s.get_realized(): continue
            ox, oy = s.origin(); v = s.view; w, h = s.dsize(); f = uiscale.factor()      # published in device px (flyouts place themselves with it)
            items = {k: [int(ox + r[0] * f), int(oy + r[1] * f), int(r[2] * f + 0.5), int(r[3] * f + 0.5)] for k, r in v.rects.items()}
            surf.append(dict(role=s.surf.role, edge=s.surf.edge, x=int(ox), y=int(oy), w=w, h=h, design=self.opts["design"], items=items))
        try:
            tmp = placement.state_path() + ".tmp"; open(tmp, "w").write(json.dumps(dict(pid=os.getpid(), design=self.opts["design"], dark=bool(self.theme.dark), surfaces=surf))); os.replace(tmp, placement.state_path())
        except OSError: pass
        return False


def config_default_pinned(): return designs.DEFAULT_PINNED
