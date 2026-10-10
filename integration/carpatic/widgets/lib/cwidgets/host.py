"""The widget host: ONE process, one small borderless window per card (override-redirect, so dwm and tint2 never tile or list them), drawn with
cairo/Pango from the design tokens. Started only when the user enabled widgets. A card that raises an exception is paused and never takes the host
or the desktop with it."""
import datetime, json, os, shutil, signal, subprocess, sys, threading, time, traceback, fcntl
import cairo
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0"); gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, Gdk, GLib, Gio, GdkPixbuf
from . import conf, data, draw, look as L

LOG = os.path.join(conf.STATE, "widgets.log")
ICONS = {"Terminal": "utilities-terminal", "Files": "system-file-manager", "Web": "web-browser", "Settings": "preferences-system", "Store": "system-software-install"}
DEFAULT_SHORTCUTS = [dict(name="Terminal", cmd="carpatic-term"), dict(name="Files", cmd="thunar"), dict(name="Web", cmd="firefox"),
                     dict(name="Settings", cmd="carpatic-settings"), dict(name="Store", cmd="carpatic-store")]
LOCKERS = ("slock", "xsecurelock", "i3lock", "xss-lock-locker", "carpatic-lock")


def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        if os.path.exists(LOG) and os.path.getsize(LOG) > 100_000: os.replace(LOG, LOG + ".1")
        open(LOG, "a").write(time.strftime("%F %T ") + msg + "\n")
    except OSError: pass


def screen_locked():
    try:
        for d in os.listdir("/proc"):
            if d.isdigit():
                try:
                    if open(f"/proc/{d}/comm").read().strip() in LOCKERS: return True
                except OSError: pass
    except OSError: pass
    return False


class Mpris:
    """Event-driven (D-Bus signals), nothing polls while no player exists."""
    def __init__(self, on_change):
        self.on_change, self.bus, self.player, self.info = on_change, None, None, None; self._t = 0
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            for iface, sig, path in (("org.freedesktop.DBus.Properties", "PropertiesChanged", "/org/mpris/MediaPlayer2"), ("org.freedesktop.DBus", "NameOwnerChanged", "/org/freedesktop/DBus")):
                self.bus.signal_subscribe(None, iface, sig, path, None, Gio.DBusSignalFlags.NONE, self._sig)
            self.refresh()
        except GLib.Error: self.bus = None

    def _sig(self, *a):
        if not self._t: self._t = GLib.timeout_add(200, self._deb)
    def _deb(self): self._t = 0; self.refresh(); self.on_change(); return False

    def _call(self, name, path, iface, method, args=None, sig=None):
        return self.bus.call_sync(name, path, iface, method, args, GLib.VariantType(sig) if sig else None, 0, 800, None)

    def refresh(self):
        if not self.bus: return
        try:
            names = [n for n in self._call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListNames", None, "(as)").unpack()[0] if n.startswith("org.mpris.MediaPlayer2.")]
            best = None
            for n in names:
                pr = self._call(n, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties", "GetAll", GLib.Variant("(s)", ("org.mpris.MediaPlayer2.Player",)), "(a{sv})").unpack()[0]
                ident = ""
                try: ident = self._call(n, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties", "Get", GLib.Variant("(ss)", ("org.mpris.MediaPlayer2", "Identity")), "(v)").unpack()[0]
                except GLib.Error: pass
                cand = (n, data.parse_mpris(pr.get("Metadata", {}), pr.get("PlaybackStatus", "Stopped"), pr.get("Position", 0), ident))
                if best is None or (cand[1]["playing"] and not best[1]["playing"]): best = cand
            self.player, self.info = best if best else (None, None)
        except GLib.Error: self.player, self.info = None, None

    def command(self, act):
        if not (self.bus and self.player): return
        m = dict(prev="Previous", next="Next", playpause="PlayPause")[act]
        try: self._call(self.player, "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", m)
        except GLib.Error: pass


class Card:
    def __init__(self, host, item):
        self.host, self.item = host, item; self.id = item["id"]; self.hits = []; self.errors = 0; self.dead = False; self.timer = 0; self.drag = None
        w = self.win = Gtk.Window(type=Gtk.WindowType.POPUP); w.set_decorated(False); w.set_app_paintable(True); w.set_accept_focus(False)
        w.set_skip_taskbar_hint(True); w.set_skip_pager_hint(True); w.set_title("carpatic-widget-" + self.id)
        vis = host.screen.get_rgba_visual()
        if vis and host.screen.is_composited(): w.set_visual(vis); self.alpha = True
        else: self.alpha = False
        w.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.SCROLL_MASK)
        w.connect("draw", self.on_draw); w.connect("button-press-event", self.on_press); w.connect("button-release-event", self.on_release); w.connect("motion-notify-event", self.on_motion)
        w.connect("scroll-event", self.on_scroll); self.layout_window()

    # --- geometry
    def rect(self): return conf.cell_rect(self.host.area, self.item, self.host.layout["anchor"], self.host.scale)
    def layout_window(self):
        x, y, w, h = self.rect(); self.win.set_default_size(w, h); self.win.resize(w, h); self.win.move(x, y); self.w, self.h = w, h; self.shaped = False
        if self.win.get_realized(): self.set_shape()

    def set_shape(self):
        """Without a compositor, cut rounded corners with the X SHAPE extension so the card is not a rectangle with square corners."""
        win = self.win.get_window()
        if win is None: return
        if self.alpha or self.host.look["radius"] == 0: win.shape_combine_region(None, 0, 0); return
        s = cairo.ImageSurface(cairo.FORMAT_A8, self.w, self.h); cr = cairo.Context(s); ctx = draw.Ctx(cr, self.w, self.h, self.host.pal, self.host.look)
        ctx.rrect(0, 0, self.w, self.h, self.host.look["radius"] * self.host.scale); cr.fill()
        win.shape_combine_region(Gdk.cairo_region_create_from_surface(s), 0, 0)

    def show(self):
        self.win.show_all(); w = self.win.get_window(); self.set_shape(); w.lower()
    def raise_(self): self.win.get_window().raise_()
    def lower(self): self.win.get_window().lower()
    def destroy(self):
        if self.timer: GLib.source_remove(self.timer); self.timer = 0
        self.win.destroy()

    # --- drawing
    def on_draw(self, widget, cr):
        try:
            h = self.host
            if self.alpha: cr.set_operator(cairo.OPERATOR_SOURCE); cr.set_source_rgba(0, 0, 0, 0); cr.paint(); cr.set_operator(cairo.OPERATOR_OVER)
            s = dict(h.state); s["_alpha"] = h.look["alpha"] if self.alpha else 1.0
            if self.dead:
                ctx = draw.Ctx(cr, self.w / h.scale, self.h / h.scale, h.pal, h.look, self.item["size"]); cr.scale(h.scale, h.scale); ctx.frame(conf.CATALOG[self.id]["title"])
                ctx.text("This widget stopped.", ctx.x, ctx.y, 14, h.pal["fg"], 600); ctx.text("Click to try again.", ctx.x, ctx.y + 22, 12, h.pal["muted"], 400); self.hits = [(0, 0, self.w, self.h, ("retry",))]; return True
            cr.scale(h.scale, h.scale)
            ctx = draw.Ctx(cr, self.w / h.scale, self.h / h.scale, h.pal, h.look, self.item["size"], s, self.item.get("opts"))
            self.hits = draw.paint(self.id, ctx); self.errors = 0
            if h.edit: self.edit_decor(cr)
        except Exception:
            self.errors += 1; log(f"draw {self.id}: {traceback.format_exc(limit=3)}")
            if self.errors >= 3: self.dead = True
            GLib.idle_add(self.win.queue_draw)
        return True

    def edit_decor(self, cr):
        h = self.host; p = h.pal; sel = h.selected is self
        cr.set_source_rgba(*L.hex2rgb(p["accent"]), 1.0 if sel else 0.6); cr.set_line_width(3 if sel else 2); cr.set_dash([6, 4])
        cr.rectangle(1.5, 1.5, self.w / h.scale - 3, self.h / h.scale - 3); cr.stroke(); cr.set_dash([])
        ctx = draw.Ctx(cr, self.w / h.scale, self.h / h.scale, p, h.look); W, H = self.w / h.scale, self.h / h.scale; y = H - 32
        chips = [sz for sz in conf.SIZES if sz in conf.CATALOG[self.id]["dims"]]
        ctx.fill_rrect(6, y - 4, len(chips) * 30 + 6, 30, 15, p["card"], 0.96)
        for i, sz in enumerate(chips):
            x = 8 + i * 30; on = sz == self.item["size"]; ctx.fill_rrect(x, y, 26, 22, 11, p["accent"] if on else p["card2"], 1.0); ctx.text(sz, x + 13, y + 3, 12, p["accent_fg"] if on else p["fg"], 700, "c")
        ctx.fill_rrect(W - 32, 8, 24, 24, 12, p["bad"], 1.0); ctx.text("\u00d7", W - 20, 8, 17, "#ffffff", 700, "c")

    # --- schedule
    def schedule(self):
        if self.timer: GLib.source_remove(self.timer); self.timer = 0
        per = conf.CATALOG[self.id]["period"]
        if per == 0 or self.dead: return
        if self.id == "clock":
            mode = (self.item.get("opts") or {}).get("clock") or ("dots" if self.host.look["name"] == "nothing" else "analog" if self.host.look["name"] == "macos" and self.item["size"] != "M" else "digital")
            ms = 1000 if mode == "analog" else int((60 - time.time() % 60) * 1000) + 50
        else: ms = int(per * 1000 * self.host.slow)
        self.timer = GLib.timeout_add(max(200, ms), self.tick)

    def tick(self):
        self.timer = 0
        if not self.host.paused:
            try: self.host.refresh(self.id)
            except Exception: self.errors += 1; log(f"refresh {self.id}: {traceback.format_exc(limit=3)}"); self.dead = self.errors >= 3
            self.win.queue_draw()
        self.schedule(); return False

    # --- input
    def hit_at(self, x, y):
        x, y = x / self.host.scale, y / self.host.scale
        for hx, hy, hw, hh, act in reversed(self.hits):
            if hx <= x <= hx + hw and hy <= y <= hy + hh: return act
        return None

    def on_press(self, w, ev):
        h = self.host
        if h.edit:
            x, y = ev.x / h.scale, ev.y / h.scale; W = self.w / h.scale
            H = self.h / h.scale
            if y < 36 and x > W - 38: h.remove(self.id); return True
            if H - 36 <= y <= H - 6:
                for i, sz in enumerate([s for s in conf.SIZES if s in conf.CATALOG[self.id]["dims"]]):
                    if 8 + i * 30 <= x <= 8 + i * 30 + 26: h.resize(self.id, sz); return True
            h.select(self); self.drag = (ev.x_root, ev.y_root, *self.win.get_position()); return True
        return True

    def on_motion(self, w, ev):
        if self.drag and self.host.edit:
            x0, y0, wx, wy = self.drag; self.win.move(int(wx + ev.x_root - x0), int(wy + ev.y_root - y0))
        return True

    def on_release(self, w, ev):
        h = self.host
        if self.drag:
            x, y = self.win.get_position(); moved = abs(ev.x_root - self.drag[0]) + abs(ev.y_root - self.drag[1]) > 4; self.drag = None
            if moved: h.drop(self, x, y)
            else: self.layout_window()
            return True
        act = self.hit_at(ev.x, ev.y)
        if act: h.act(self, act)
        return True

    def on_scroll(self, w, ev): return False


class Host:
    def __init__(self):
        self.layout = conf.load(); self.screen = Gdk.Screen.get_default(); self.cards = {}; self.state = {}; self.edit = False; self.peek = False
        self.selected = None; self.paused = False; self.slow = 1; self.overlay = None; self.toolbar = None; self.addlist = False; self.mpris = None
        self.sysmon = None; self.weather = None; self.pix = {}; self.art_path = ""; self.settings_mt = 0
        self.reload_look(); self.compute_area()

    # --- environment
    def compute_area(self):
        d = self.screen.get_display(); mon = d.get_primary_monitor() or d.get_monitor(0)
        want = str(self.layout.get("monitor", "primary"))
        if want.isdigit() and int(want) < d.get_n_monitors(): mon = d.get_monitor(int(want))
        else:
            for i in range(d.get_n_monitors()):
                if (d.get_monitor(i).get_model() or "") == want: mon = d.get_monitor(i)
        g = mon.get_workarea()
        top = bot = left = 0; env = L.read_env(os.path.join(conf.CFG, "profile.env"))
        try: top, bot, left = int(env.get("BAR_TOP", 0)), int(env.get("BAR_BOTTOM", 0)), int(env.get("BAR_LEFT", 0))
        except ValueError: pass
        if env.get("BAR") == "dwm": top = max(top, 32)
        if "macos-dock" in env.get("BAR_TEMPLATES", ""): bot = max(bot, 84)      # the floating dock is not counted in BAR_BOTTOM
        if g.height >= mon.get_geometry().height - 4 and g.y == mon.get_geometry().y: g = Gdk.Rectangle(); g.x, g.y = mon.get_geometry().x + left, mon.get_geometry().y + top; g.width, g.height = mon.get_geometry().width - left, mon.get_geometry().height - top - bot
        self.area = (g.x, g.y, g.width, g.height); sf = mon.get_scale_factor(); dpi = Gtk.Settings.get_default().get_property("gtk-xft-dpi") / 1024.0 or 96.0
        self.scale = conf.scale_for(dpi, sf)
        self.cols, self.rows = conf.grid_size(self.area, self.layout["anchor"], self.scale); self.mon = mon

    def fit_layout(self):
        """Cards that do not fit this screen (saved on a bigger one, or added from the terminal without knowing the size) move to the nearest free place."""
        items = self.layout["items"]; placed = []; changed = False
        for it in items:
            if getattr(self.cards.get(it["id"]), "hidden", False): continue
            w, h = conf.dims(it["id"], it["size"])
            if it["col"] + w > self.cols or it["row"] + h > self.rows or conf.overlaps(placed, it):
                col, row = conf.free_spot(placed, it["id"], it["size"], self.cols, self.rows)
                if (col, row) != (it["col"], it["row"]): it["col"], it["row"] = col, row; changed = True
            placed.append(it)
        if changed:
            try: conf.save(self.layout)
            except OSError: pass

    @staticmethod
    def cfg_mtimes():
        out = []
        for f in ("settings.conf", "profile.env"):       # theme / accent / fonts, and the bar layout of the desktop style
            try: out.append(os.stat(os.path.join(conf.CFG, f)).st_mtime)
            except OSError: out.append(0)
        return out

    def reload_look(self):
        self.pal, self.look, self.settings = L.current(self.layout)
        self.settings_mt = self.cfg_mtimes()

    # --- data
    def refresh(self, wid):
        s = self.state
        if wid == "sysmon":
            if self.sysmon is None: self.sysmon = data.SysMon()
            s["sysmon"] = self.sysmon.sample()
        elif wid == "weather": self.fetch_weather()
        elif wid == "battery": s["battery"] = data.battery(); s["profile"] = data.power_profile() if s["battery"] else ""; self.sync_visibility("battery")
        elif wid == "notes": s["notes"] = data.read_notes()
        elif wid == "todo": s["todo"] = data.read_todo()
        elif wid == "toggles": self.probe_toggles()
        elif wid == "calendar": s["events"] = data.read_events(); s["firstweekday"] = 0
        elif wid == "tip": s["tip"] = data.tip_of_day(offset=getattr(self, "tipoff", 0))
        elif wid == "nowplaying": self.update_np()
        elif wid == "photo": self.load_photo()
        elif wid == "shortcuts": self.load_shortcuts()

    def fetch_weather(self):
        cfg = self.layout.get("weather", {}); s = self.state
        if self.weather is None or self.weather.cfg != cfg: self.weather = data.Weather(cfg)
        s["weather_cfg"] = cfg; s["weather"] = self.weather.data; s["weather_age"] = self.weather.age_text()
        s["weather_error"] = "nolocation" if not self.weather.located() else s.get("weather_error", "")
        if self.weather.located() and not getattr(self, "_wbusy", False):
            self._wbusy = True
            def work():
                ok = self.weather.refresh()
                def done():
                    self._wbusy = False; s["weather"] = self.weather.data; s["weather_age"] = self.weather.age_text(); s["weather_error"] = self.weather.error
                    c = self.cards.get("weather"); c and c.win.queue_draw(); return False
                GLib.idle_add(done)
            threading.Thread(target=work, daemon=True).start()

    def probe_toggles(self):
        if getattr(self, "_tbusy", False): return
        self._tbusy = True
        def work():
            res = [dict(id=t.id, label=t.label, kind=t.kind, state=t.state()) for t in data.TOGGLES]
            def done():
                self._tbusy = False; self.state["toggles"] = res; self.sync_visibility("toggles"); c = self.cards.get("toggles"); c and c.win.queue_draw(); return False
            GLib.idle_add(done)
        threading.Thread(target=work, daemon=True).start()

    def surf(self, path, w, h, cover=True):
        try:
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, int(w), int(h), not cover) if not cover else GdkPixbuf.Pixbuf.new_from_file_at_scale(path, int(w), int(h), False)
            return Gdk.cairo_surface_create_from_pixbuf(pb, 1, None)
        except GLib.Error: return None

    def update_np(self):
        if self.mpris is None: self.mpris = Mpris(self.np_changed)
        info = self.mpris.info; self.state["nowplaying"] = info
        if info and info["art"] != self.art_path: self.art_path = info["art"]; self.state["art"] = self.surf(info["art"], 160, 160) if info["art"] else None
        if info and info["playing"] and self.mpris.bus:
            try: info["position"] = self.mpris._call(self.mpris.player, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties", "Get", GLib.Variant("(ss)", ("org.mpris.MediaPlayer2.Player", "Position")), "(v)").unpack()[0] / 1e6
            except GLib.Error: pass
        if info is None: self.state["art"] = None
        self._np_poll()

    def np_changed(self):
        self.update_np(); c = self.cards.get("nowplaying"); c and c.win.queue_draw()

    def _np_poll(self):
        # progress bar: only while something plays and the card exists (one wake-up every 2 s, nothing otherwise)
        if getattr(self, "_nptimer", 0): return
        info = self.state.get("nowplaying")
        if info and info["playing"] and self.mpris.bus and "nowplaying" in self.cards:
            def t():
                self._nptimer = 0; self.update_np(); c = self.cards.get("nowplaying"); c and c.win.queue_draw(); return False
            self._nptimer = GLib.timeout_add(2000, t)

    def load_photo(self):
        c = self.cards.get("photo"); s = self.settings; path = s.get("WALLPAPER", "")
        if not path or not os.path.isfile(path):
            for g in (os.path.join(L.SYS_THEMES, s.get("THEME", "carpatic"), "wallpaper.jpg"), os.path.join(conf.CFG, "themes", s.get("THEME", "carpatic"), "wallpaper.jpg")):
                if os.path.isfile(g): path = g; break
        self.state["photo_name"] = os.path.splitext(os.path.basename(path))[0].replace("-", " ").replace("_", " ").title() if path else ""
        if c and path:
            if self.pix.get("photo") != (path, c.w, c.h):
                self.state["photo"] = self.surf(path, c.w / self.scale * 1.0, c.h / self.scale * 1.0); self.pix["photo"] = (path, c.w, c.h)
        else: self.state["photo"] = None

    def load_shortcuts(self):
        apps = self.layout.get("shortcuts") or DEFAULT_SHORTCUTS; theme = Gtk.IconTheme.get_default(); out = []
        for a in apps[:10]:
            im = None
            try:
                pb = theme.load_icon(a.get("icon") or ICONS.get(a["name"], a["cmd"]), 48, 0); im = Gdk.cairo_surface_create_from_pixbuf(pb, 1, None)
            except GLib.Error: pass
            out.append(dict(name=a["name"], cmd=a["cmd"], icon=im))
        self.state["shortcuts"] = out

    # --- actions from clicks
    def act(self, card, a):
        kind = a[0]
        try:
            if kind == "retry": card.dead = False; card.errors = 0; card.schedule(); card.win.queue_draw()
            elif kind == "mpris": self.mpris and self.mpris.command(a[1])
            elif kind == "launch": subprocess.Popen(["sh", "-c", a[1]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            elif kind == "todo": self.state["todo"] = data.toggle_todo(a[1]); card.win.queue_draw()
            elif kind == "nexttip": self.tipoff = getattr(self, "tipoff", 0) + 1; self.refresh("tip"); card.win.queue_draw()
            elif kind == "edit_notes": self.edit_notes()
            elif kind == "edit_todo": self.edit_todo()
            elif kind == "power":      # needs administrator rights: carpatic-sudo asks (graphical prompt from the desktop)
                tool = ["carpatic-sudo", "carpatic-power"] if shutil.which("carpatic-sudo") else ["carpatic-power"]
                def work():
                    subprocess.run([*tool, "profile", a[1]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); GLib.idle_add(lambda: (self.refresh("battery"), card.win.queue_draw(), False)[2])
                threading.Thread(target=work, daemon=True).start()
            elif kind == "toggle": self.do_toggle(a[1])
            elif kind == "slider": self.do_slider(card, a)
        except Exception: log(f"action {a}: {traceback.format_exc(limit=3)}")

    def do_toggle(self, tid):
        t = [t for t in data.TOGGLES if t.id == tid][0]
        def work(): t.act(); GLib.idle_add(lambda: (self.probe_toggles(), False)[1])
        threading.Thread(target=work, daemon=True).start()

    def do_slider(self, card, a):
        t = [t for t in data.TOGGLES if t.id == a[1]][0]; ptr = card.win.get_pointer(); frac = max(0, min(1, (ptr[0] / self.scale - a[2]) / a[3]))
        threading.Thread(target=lambda: (t.act(round(frac * 100)), GLib.idle_add(lambda: (self.probe_toggles(), False)[1])), daemon=True).start()

    def small_window(self, title, widget, w=380, h=300):
        win = Gtk.Window(title=title); win.set_default_size(w, h); win.set_type_hint(Gdk.WindowTypeHint.DIALOG); win.add(widget); win.show_all(); win.present(); return win

    def edit_notes(self):
        if getattr(self, "_notes_win", None): self._notes_win.present(); return
        tv = Gtk.TextView(); tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR); tv.get_buffer().set_text(data.read_notes()); tv.set_left_margin(8); tv.set_top_margin(8)
        sw = Gtk.ScrolledWindow(); sw.add(tv); win = self._notes_win = self.small_window("Note", sw)
        def close(*_):
            b = tv.get_buffer(); data.write_notes(b.get_text(b.get_start_iter(), b.get_end_iter(), False)); self._notes_win = None; self.refresh("notes"); c = self.cards.get("notes"); c and c.win.queue_draw()
        win.connect("destroy", close)

    def edit_todo(self):
        if getattr(self, "_todo_win", None): self._todo_win.present(); return
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); box.set_border_width(12)
        e = Gtk.Entry(); e.set_placeholder_text("Add something to do and press Enter"); box.pack_start(e, False, False, 0)
        def add(*_):
            t = e.get_text().strip()
            if t: items = data.read_todo(); items.append(dict(t=t, done=False)); data.write_todo(items); e.set_text(""); self.refresh("todo"); c = self.cards.get("todo"); c and c.win.queue_draw()
        e.connect("activate", add); win = self._todo_win = self.small_window("To-do", box, 380, 80); win.connect("destroy", lambda *_: setattr(self, "_todo_win", None))

    # --- life cycle
    def start(self):
        self.fit_layout()
        for it in self.layout["items"]: self.add_card(it)
        GLib.timeout_add_seconds(15, self.housekeeping)
        for sig in ("monitors-changed", "size-changed"): self.screen.connect(sig, lambda *_: GLib.timeout_add(400, self.on_screen))     # xrandr, docking, HiDPI switch
        for sig, fn in ((signal.SIGTERM, self.quit), (signal.SIGINT, self.quit), (signal.SIGHUP, self.reload), (signal.SIGUSR1, self.toggle_peek), (signal.SIGUSR2, self.toggle_edit)):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, fn)
        log(f"started: {len(self.cards)} widgets, look {self.look['name']}, scale {self.scale}, composited {self.screen.is_composited()}")

    def available(self, wid):
        """A card whose hardware or data does not exist here is not shown at all (no battery on a desktop PC, no tile this computer can do)."""
        if wid == "battery": return self.state.get("battery") is not None
        if wid == "toggles": return any(t["state"] is not None for t in self.state.get("toggles", []))
        return True

    def sync_visibility(self, wid=None):
        for k, c in list(self.cards.items()):
            if wid and k != wid: continue
            ok = self.available(k)
            if ok and getattr(c, "hidden", False): c.hidden = False; c.win.show_all(); c.win.get_window().lower(); c.layout_window(); c.win.queue_draw()
            elif not ok and not getattr(c, "hidden", False): c.hidden = True; c.win.hide()

    def add_card(self, it):
        if it["id"] in self.cards: return
        try:
            c = Card(self, it); self.cards[it["id"]] = c
            try: self.refresh(it["id"])
            except Exception: log(f"first refresh {it['id']}: {traceback.format_exc(limit=3)}")
            c.hidden = False
            if self.available(it["id"]): c.show()
            else: c.hidden = True
            c.schedule()
        except Exception: log(f"card {it['id']}: {traceback.format_exc(limit=3)}")

    def housekeeping(self):
        was = self.paused; self.paused = screen_locked()
        if self.cfg_mtimes() != self.settings_mt: self.restyle()
        self.slow = 4 if (not self.paused and (self.state.get("profile") in ("saver", "power-saver") or os.path.exists(os.path.join(conf.WDIR, "saver")))) else 1
        if was and not self.paused:
            for c in self.cards.values(): c.win.queue_draw()
        return True

    def on_screen(self):
        self.restyle(); return False

    def restyle(self):
        self.layout = conf.load(); self.reload_look(); self.compute_area(); self.fit_layout()
        for c in self.cards.values(): c.item = next((i for i in self.layout["items"] if i["id"] == c.id), c.item); c.layout_window(); c.win.queue_draw()

    def reload(self):
        new = conf.load(); self.layout = new; self.reload_look(); self.compute_area(); self.fit_layout(); ids = {i["id"] for i in new["items"]}
        for wid in list(self.cards):
            if wid not in ids: self.cards.pop(wid).destroy()
        for it in new["items"]:
            if it["id"] in self.cards: c = self.cards[it["id"]]; c.item = it; c.layout_window(); self.refresh(it["id"]); c.schedule(); c.win.queue_draw()
            else: self.add_card(it)
        return True

    def quit(self):
        try: os.unlink(conf.PIDFILE)
        except OSError: pass
        Gtk.main_quit(); return False

    # --- peek and edit
    def toggle_peek(self):
        if self.edit: self.end_edit(); return True
        if self.peek: self.end_peek()
        else: self.begin_overlay(peek=True)
        return True

    def toggle_edit(self):
        if self.edit: self.end_edit()
        else:
            if self.peek: self.end_peek()
            self.begin_overlay(peek=False)
        return True

    def begin_overlay(self, peek):
        self.peek, self.edit = peek, not peek; x, y, w, h = self.mon.get_geometry().x, self.mon.get_geometry().y, self.mon.get_geometry().width, self.mon.get_geometry().height
        o = self.overlay = Gtk.Window(type=Gtk.WindowType.POPUP); o.set_decorated(False); o.set_app_paintable(True); o.set_default_size(w, h); o.move(x, y)
        vis = self.screen.get_rgba_visual(); comp = bool(vis and self.screen.is_composited())
        if comp: o.set_visual(vis)
        o.add_events(Gdk.EventMask.KEY_PRESS_MASK | Gdk.EventMask.BUTTON_PRESS_MASK)
        back = None if comp else self.make_backdrop(peek, w, h)       # without a compositor the dim is painted from a picture of the screen

        def draw_o(wd, cr):
            cr.set_operator(cairo.OPERATOR_SOURCE); r, g, b = L.hex2rgb(self.pal["bg"])
            if back is not None: cr.set_source_surface(back, 0, 0); cr.paint(); cr.set_operator(cairo.OPERATOR_OVER); cr.set_source_rgba(r * .2, g * .2, b * .2, 0.58); cr.paint()
            else: cr.set_source_rgba(r * .2, g * .2, b * .2, 0.62 if comp else 1.0); cr.paint()
            return True
        o.connect("destroy", lambda *_: None)
        o.connect("draw", draw_o); o.connect("key-press-event", self.on_key); o.connect("button-press-event", lambda *_: (self.end_peek() if self.peek else self.end_edit(), True)[1])
        o.show_all(); o.get_window().raise_()
        for c in self.cards.values(): c.raise_(); c.win.queue_draw()
        if self.edit: self.show_toolbar()
        GLib.timeout_add(80, self.grab)

    def make_backdrop(self, peek, w, h):
        """Peek: the screen as it is now (windows included). Edit: the wallpaper, so cards that move leave no ghost behind."""
        try:
            if peek:
                root = Gdk.get_default_root_window(); pb = Gdk.pixbuf_get_from_window(root, 0, 0, root.get_width(), root.get_height())
                return Gdk.cairo_surface_create_from_pixbuf(pb, 1, None) if pb else None
            path = self.settings.get("WALLPAPER", "")
            if not path or not os.path.isfile(path):
                path = next((g for g in (os.path.join(conf.CFG, "themes", self.settings.get("THEME", "carpatic"), "wallpaper.jpg"), os.path.join(L.SYS_THEMES, self.settings.get("THEME", "carpatic"), "wallpaper.jpg")) if os.path.isfile(g)), "")
            if not path: return None
            pb = GdkPixbuf.Pixbuf.new_from_file(path); k = max(w / pb.get_width(), h / pb.get_height())
            pb = pb.scale_simple(int(pb.get_width() * k) + 1, int(pb.get_height() * k) + 1, GdkPixbuf.InterpType.BILINEAR)
            surf = cairo.ImageSurface(cairo.FORMAT_RGB24, w, h); cr = cairo.Context(surf); cr.set_source_surface(Gdk.cairo_surface_create_from_pixbuf(pb, 1, None), (w - pb.get_width()) / 2, (h - pb.get_height()) / 2); cr.paint()
            return surf
        except Exception: log("backdrop: " + traceback.format_exc(limit=2)); return None

    def grab(self):
        try:
            seat = self.screen.get_display().get_default_seat(); gw = self.overlay.get_window()
            if gw: seat.grab(gw, Gdk.SeatCapabilities.KEYBOARD, False, None, None, None, None)
        except Exception: log("grab failed " + traceback.format_exc(limit=2))
        return False

    def end_overlay(self):
        try: self.screen.get_display().get_default_seat().ungrab()
        except Exception: pass
        if self.overlay: self.overlay.destroy(); self.overlay = None
        if self.toolbar: self.toolbar.destroy(); self.toolbar = None
        for c in self.cards.values(): c.lower(); c.win.queue_draw()

    def end_peek(self): self.peek = False; self.end_overlay()
    def end_edit(self): self.edit = False; self.selected = None; self.addlist = False; conf.save(self.layout); self.end_overlay()

    def on_key(self, w, ev):
        k = Gdk.keyval_name(ev.keyval) or ""
        if self.peek:
            if k not in ("Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Super_L", "Super_R", "Meta_L", "Meta_R"): self.end_peek()
            return True
        order = [i["id"] for i in self.layout["items"]]
        if k in ("Escape", "Return", "KP_Enter"): self.end_edit()
        elif k in ("Tab", "ISO_Left_Tab") and order:
            cur = order.index(self.selected.id) if self.selected else -1; self.select(self.cards[order[(cur + (-1 if k == "ISO_Left_Tab" else 1)) % len(order)]])
        elif self.selected and k in ("Left", "Right", "Up", "Down"):
            it = self.selected.item; d = {"Left": (1, 0), "Right": (-1, 0), "Up": (0, -1), "Down": (0, 1)}[k]
            if self.layout["anchor"] != "right": d = (-d[0], d[1])
            self.place(self.selected, it["col"] + d[0], it["row"] + d[1])
        elif self.selected and k in ("plus", "equal", "KP_Add", "minus", "KP_Subtract"):
            avail = [s for s in conf.SIZES if s in conf.CATALOG[self.selected.id]["dims"]]; i = avail.index(self.selected.item["size"]); i += 1 if k in ("plus", "equal", "KP_Add") else -1
            if 0 <= i < len(avail): self.resize(self.selected.id, avail[i])
        elif self.selected and k in ("Delete", "BackSpace"): self.remove(self.selected.id)
        elif k == "r": self.auto_arrange()
        elif k == "a": self.addlist = not self.addlist; self.toolbar_redraw()
        return True

    def auto_arrange(self):
        vis = [i for i in self.layout["items"] if not getattr(self.cards.get(i["id"]), "hidden", False)]
        conf.auto_arrange(vis, self.cols, self.rows); conf.save(self.layout)
        for c in self.cards.values(): c.layout_window(); c.win.queue_draw()

    def select(self, card):
        old = self.selected; self.selected = card
        for c in (old, card):
            if c: c.win.queue_draw()

    def place(self, card, col, row):
        it = card.item; col, row = conf.snap(col, row, self.cols, self.rows, *conf.dims(it["id"], it["size"]))
        trial = dict(it, col=col, row=row)
        if conf.overlaps(self.layout["items"], trial): card.layout_window(); return False
        it["col"], it["row"] = col, row; conf.save(self.layout); card.layout_window(); return True

    def drop(self, card, x, y):
        col, row = conf.px_to_cell(self.area, x, y, card.item, self.layout["anchor"], self.scale); self.place(card, col, row)

    def resize(self, wid, size):
        c = self.cards[wid]; it = c.item; old = it["size"]; it["size"] = size
        w, h = conf.dims(wid, size); it["col"], it["row"] = conf.snap(it["col"], it["row"], self.cols, self.rows, w, h)
        if conf.overlaps(self.layout["items"], it):
            col, row = conf.free_spot([i for i in self.layout["items"] if i is not it], wid, size, self.cols, self.rows); it["col"], it["row"] = col, row
        conf.save(self.layout); c.layout_window(); self.refresh(wid); c.schedule(); c.win.queue_draw()

    def remove(self, wid):
        conf.remove(self.layout, wid); conf.save(self.layout); self.cards.pop(wid).destroy(); self.selected = None

    def add_widget(self, wid):
        try: conf.add(self.layout, wid, None, self.cols, self.rows)
        except conf.Error: return
        conf.save(self.layout); self.add_card(self.layout["items"][-1]); self.cards[wid].raise_(); self.select(self.cards[wid]); self.toolbar_redraw()

    def toolbar_redraw(self):
        if self.toolbar: self.toolbar.queue_draw(); self.toolbar_resize()

    # --- toolbar (drawn with cairo in the same style)
    def show_toolbar(self):
        t = self.toolbar = Gtk.Window(type=Gtk.WindowType.POPUP); t.set_decorated(False); t.set_app_paintable(True)
        vis = self.screen.get_rgba_visual()
        if vis and self.screen.is_composited(): t.set_visual(vis)
        t.add_events(Gdk.EventMask.BUTTON_PRESS_MASK); t.connect("draw", self.draw_toolbar); t.connect("button-press-event", self.toolbar_click); self.toolbar_resize(); t.show_all(); t.get_window().raise_()

    def toolbar_resize(self):
        g = self.mon.get_geometry(); w = 680; n = len([k for k in conf.CATALOG if k not in self.cards]); h = 56 + (n * 30 + 12 if self.addlist else 0)
        self.toolbar.set_default_size(w, h); self.toolbar.resize(w, h); self.toolbar.move(g.x + (g.width - w) // 2, g.y + g.height - h - 24)

    def draw_toolbar(self, wd, cr):
        p, lk = self.pal, self.look; W, H = wd.get_allocated_width(), wd.get_allocated_height(); s = self.scale
        ctx = draw.Ctx(cr, W, H, p, lk); ctx.fill_rrect(0, 0, W, H, 16, p["card"]); ctx.rrect(.5, .5, W - 1, H - 1, 16); ctx.color(p["border"]); cr.set_line_width(1); cr.stroke()
        ctx.text("Edit widgets", 20, 18, 14, p["fg"], 600)
        self._tb = []; x = W - 16
        for label, act, prim in (("Done", "done", True), ("Reset", "reset", False), ("Auto arrange", "arrange", False), ("Add widget", "add", False)):
            tw = len(label) * 8 + 28; x -= tw; ctx.fill_rrect(x, 12, tw, 32, 16 if lk["radius"] else 0, p["accent"] if prim else p["card2"])
            ctx.text(label, x + tw / 2, 19, 13, p["accent_fg"] if prim else p["fg"], 600, "c"); self._tb.append((x, 12, tw, 32, act)); x -= 8
        if self.addlist:
            y = 56
            for k, meta in conf.CATALOG.items():
                if k in self.cards: continue
                ctx.text(meta["title"], 20, y + 4, 13, p["fg"], 600); ctx.text(meta["desc"], 160, y + 5, 11, p["muted"], 400, maxw=W - 180); self._tb.append((8, y, W - 16, 30, "add:" + k)); y += 30
        ctx.text("Drag cards. Tab selects, arrows move, + and - resize, Delete removes, Esc finishes.", W / 2, H - 0, 1, p["bg"], 400, "c") if False else None
        return True

    def toolbar_click(self, wd, ev):
        for x, y, w, h, act in reversed(self._tb):
            if x <= ev.x <= x + w and y <= ev.y <= y + h:
                if act == "done": self.end_edit()
                elif act == "arrange": self.auto_arrange()
                elif act == "add": self.addlist = not self.addlist; self.toolbar_redraw()
                elif act == "reset": conf.save(conf.reset_layout(self.layout)); self.reload(); self.addlist = False; self.toolbar_redraw(); [c.raise_() for c in self.cards.values()]
                elif act.startswith("add:"): self.add_widget(act[4:])
                break
        return True


def run():
    if not conf.in_carpatic_session(): print("Widgets only run on a Carpathian desktop."); return 1
    os.makedirs(conf.STATE, exist_ok=True)
    fd = os.open(conf.PIDFILE, os.O_RDWR | os.O_CREAT, 0o644)
    try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError: print("Widgets are already running."); return 0
    os.ftruncate(fd, 0); os.write(fd, str(os.getpid()).encode())
    if not conf.enabled(): print("Widgets are off. Turn them on with: carpatic widgets enable"); return 1
    h = Host(); h.start()
    try: Gtk.main()
    finally:
        try: os.unlink(conf.PIDFILE)
        except OSError: pass
    return 0
