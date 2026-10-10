"""Carpatic Settings page "Widgets": the gallery (live previews drawn from your theme), on/off, edit mode, peek, weather place, card style.
Every control calls `carpatic-widgets`, so everything here also works from a terminal (`carpatic widgets ...`). Widgets are OFF until the switch
at the top is turned on. Loaded by carpatic-settings like carpatic_motion_pages (ImportError = page absent). License: MIT."""
import datetime, os, subprocess, threading
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib
from cwidgets import conf, look as L, preview

STYLES = [("auto", "Follow my theme and desktop style"), ("macos", "macOS: soft, rounded"), ("windows", "Windows: clean cards"), ("ubuntu", "Ubuntu: flat with an accent line"),
          ("tiling", "Tiling: square, monospace"), ("nothing", "Nothing: dot-matrix")]


def cli(*a):
    try: r = subprocess.run(["carpatic-widgets", *a], capture_output=True, text=True, timeout=30); return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.SubprocessError): return 1, "Widgets are not installed on this system."


class Preview(Gtk.DrawingArea):
    """One card, drawn by the same code the desktop uses, at 60 %."""
    SCALE = 0.62
    def __init__(self, pages, kind, size):
        super().__init__(); self.pages, self.kind, self.size = pages, kind, size; self.set_size_request(*self.dims())
        self.connect("draw", self.on_draw)
    def dims(self): w, h = preview.pixel_size(self.kind, self.size, self.SCALE); return w, h
    def set_size_(self, size): self.size = size; self.set_size_request(*self.dims()); self.queue_resize(); self.queue_draw()
    def on_draw(self, w, cr):
        pal, lk, _ = self.pages.look()
        s, _c = preview.render(self.kind, self.size, pal, lk, self.pages.sample(), self.SCALE, now=datetime.datetime.now(), backdrop=False)
        cr.set_source_surface(s, 0, 0); cr.paint(); return True


class WidgetsPages:
    def __init__(self, window):
        self.w = window; self.guard = False; self.previews = []; self._state = None; self.timer = 0
    def register(self):
        self.w.lazy("widgets", "Widgets", lambda: self.build(self.w.boxes["widgets"]))
    def refresh(self, name):
        if name == "widgets": self.sync()

    # --- helpers
    def look(self): return L.current(conf.load())
    def sample(self):
        if self._state is None: self._state = preview.sample_state()
        return self._state
    def head(self, box, title, sub):
        t = Gtk.Label(label=title, xalign=0); t.get_style_context().add_class("h1"); box.pack_start(t, False, False, 0)
        s = Gtk.Label(label=sub, xalign=0, wrap=True); s.get_style_context().add_class("sub"); box.pack_start(s, False, False, 0)
    def note(self, box, text):
        l = Gtk.Label(label=text, xalign=0, wrap=True); l.get_style_context().add_class("sub"); box.pack_start(l, False, False, 0); return l
    def row(self, box, title, sub, widget):
        row = Gtk.Box(spacing=12); col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        a = Gtk.Label(label=title, xalign=0); a.get_style_context().add_class("ctitle"); col.pack_start(a, False, False, 0)
        b = Gtk.Label(label=sub, xalign=0, wrap=True); b.get_style_context().add_class("sub"); col.pack_start(b, False, False, 0)
        widget.set_valign(Gtk.Align.CENTER); row.pack_start(col, True, True, 0); row.pack_end(widget, False, False, 0); box.pack_start(row, False, False, 6); return row
    def status(self, text): self.msg.set_text(text)
    def do(self, *a, then=None):
        """Run carpatic-widgets off the GTK thread (enable starts a process, weather city asks the network), then refresh the page."""
        def work():
            rc, out = cli(*a)
            def done():
                self.status("" if rc == 0 else out)
                if then: then()
                self.sync(); return False
            GLib.idle_add(done)
        threading.Thread(target=work, daemon=True).start()

    # --- page
    def build(self, outer):
        sw = Gtk.ScrolledWindow(); sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); outer.pack_start(sw, True, True, 0)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10); box.set_margin_end(12); sw.add(box)
        self.head(box, "Widgets", "Small cards on your desktop: clock, calendar, weather and more. They are off until you turn them on, and nothing runs while they are off.")
        self.main = Gtk.Switch(); self.main.connect("notify::active", self.on_main); self.row(box, "Show widgets on the desktop", "Starts them now and at every login. Turn off and no widget process is left running.", self.main)
        self.msg = self.note(box, "")
        self.state_note = self.note(box, "")
        bar = Gtk.Box(spacing=8)
        self.btn_edit = Gtk.Button(label="Arrange widgets"); self.btn_edit.connect("clicked", lambda *_: self.do("edit")); bar.pack_start(self.btn_edit, False, False, 0)
        self.btn_peek = Gtk.Button(label="Peek (hold Super+Alt+W)"); self.btn_peek.connect("clicked", lambda *_: self.do("peek")); bar.pack_start(self.btn_peek, False, False, 0)
        b = Gtk.Button(label="Reset layout"); b.connect("clicked", lambda *_: self.do("reset")); bar.pack_start(b, False, False, 0); box.pack_start(bar, False, False, 6)
        self.style = Gtk.ComboBoxText()
        for k, v in STYLES: self.style.append(k, v)
        self.style.connect("changed", lambda c: None if self.guard else self.do("look", c.get_active_id(), then=self.redraw)); self.row(box, "Card style", "How the cards look. Normally they follow your theme and desktop style.", self.style)
        # weather place
        wb = Gtk.Box(spacing=6); self.city = Gtk.Entry(); self.city.set_placeholder_text("City, for example Bucharest"); self.city.connect("activate", self.on_city); wb.pack_start(self.city, True, True, 0)
        go = Gtk.Button(label="Set"); go.connect("clicked", self.on_city); wb.pack_start(go, False, False, 0)
        loc = Gtk.Button(label="Use my approximate location"); loc.set_tooltip_text("Asks ipwho.is for a rough place from your internet address. Only when you press this.")
        loc.connect("clicked", self.on_locate); wb.pack_start(loc, False, False, 0); self.row(box, "Weather place", "Forecasts come from Open-Meteo: no account, no key. Your city is sent only to look it up.", wb)
        self.place = self.note(box, "")
        l = Gtk.Label(label="Gallery", xalign=0); l.get_style_context().add_class("h1"); box.pack_start(l, False, False, 8)
        self.gallery = self.w.flow(2); self.gallery.set_max_children_per_line(3); box.pack_start(self.gallery, False, False, 0)
        self.cells = {}
        for k, meta in conf.CATALOG.items():
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); card.get_style_context().add_class("card")
            pv = Preview(self, k, meta["default"]); self.previews.append(pv); card.pack_start(pv, False, False, 0); pv.set_halign(Gtk.Align.START)
            t = Gtk.Label(label=meta["title"], xalign=0); t.get_style_context().add_class("ctitle"); card.pack_start(t, False, False, 0)
            d = Gtk.Label(label=meta["desc"], xalign=0, wrap=True); d.get_style_context().add_class("cdesc"); d.set_max_width_chars(40); card.pack_start(d, False, False, 0)
            line = Gtk.Box(spacing=8); sw = Gtk.Switch(); sw.set_valign(Gtk.Align.CENTER); sw.set_tooltip_text("Show on the desktop"); sw.get_accessible().set_name(f"{meta['title']} on the desktop")
            sz = Gtk.ComboBoxText()
            for s in conf.SIZES:
                if s in meta["dims"]: sz.append(s, {"S": "Small", "M": "Medium", "L": "Large"}[s])
            sz.set_active_id(meta["default"]); sz.get_accessible().set_name(f"{meta['title']} size")
            sw.connect("notify::active", self.on_widget, k, sz); sz.connect("changed", self.on_size, k, pv)
            line.pack_start(Gtk.Label(label="On desktop"), False, False, 0); line.pack_start(sw, False, False, 0); line.pack_end(sz, False, False, 0); card.pack_start(line, False, False, 0)
            self.gallery.add(card); self.cells[k] = (sw, sz, pv)
        self.sync(); self.timer = GLib.timeout_add_seconds(1, self.tick)
        box.connect("destroy", lambda *_: self.timer and GLib.source_remove(self.timer))

    def tick(self):
        if self.w.stack.get_visible_child_name() == "widgets":
            for k in ("clock", "calendar"):
                if k in self.cells: self.cells[k][2].queue_draw()
        return True

    def redraw(self):
        for pv in self.previews: pv.queue_draw()

    def sync(self):
        d = conf.load(); have = {i["id"]: i for i in d["items"]}; on = conf.enabled(); self.guard = True
        try:
            self.main.set_active(on); self.style.set_active_id(d.get("look", "auto"))
            self.state_note.set_text("Widgets are on." if on else "Widgets are off. The cards below are the ones that will appear when you turn them on.")
            for b in (self.btn_edit, self.btn_peek): b.set_sensitive(on)
            for k, (sw, sz, pv) in self.cells.items():
                sw.set_active(k in have)
                if k in have: sz.set_active_id(have[k]["size"]); pv.set_size_(have[k]["size"])
            w = d.get("weather") or {}; self.place.set_text(f"Showing the weather for {w['name']}." if w.get("name") else "No place chosen yet: the Weather widget will ask for one.")
        finally: self.guard = False
        self.redraw()

    def on_main(self, sw, _p):
        if self.guard: return
        self.do("enable" if sw.get_active() else "disable")
    def on_widget(self, sw, _p, k, sz):
        if self.guard: return
        self.do("add" if sw.get_active() else "remove", k, *( [sz.get_active_id()] if sw.get_active() else []))
    def on_size(self, sz, k, pv):
        if self.guard: return
        if k in {i["id"] for i in conf.load()["items"]}: self.do("size", k, sz.get_active_id())
        pv.set_size_(sz.get_active_id())
    def on_city(self, *_):
        c = self.city.get_text().strip()
        if c: self.status("Looking up " + c + "..."); self.do("weather", "city", c)
    def on_locate(self, *_): self.do("weather", "locate", "--yes")
