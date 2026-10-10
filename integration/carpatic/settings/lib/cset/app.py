"""SettingsWindow: sidebar with live search, sticky toolbar, navigation (pages and sub-pages), keyboard handling, window sizing."""
import os, json, sys
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib, GObject
from . import sysutil as su, theme, ui
from .search import SearchIndex


def default_window_size(sw, sh):
    """First-run window size: 880x620 on a small screen, growing with the screen (60% x 70%, at most 1200x800)
    so Settings on a 1920x1080 display does not open as a cramped box with clipped cards."""
    return max(880, min(1200, int(sw * 0.6))), max(620, min(800, int(sh * 0.7)))

class Page:
    """One sidebar entry. Subclasses set the class attributes and implement build(pb)."""
    id = ""; title = ""; icon = "preferences-system"; color = "#8e8e93"; group = 0
    keywords = ""        # words that find the page in the search
    entries = ()         # ((title, keywords[, anchor]), ...): every setting on the page; anchor = Row.key (default: title)
    sub = ""             # subtitle under the large title
    aliases = ()         # old deep-link names (carpatic-settings <alias>)
    async_fill = False       # rows arrive later from a background thread; the page calls win.on_page_filled(self) when done
    optional = frozenset()   # entry anchors whose row exists only when a tool/hardware is present: dropped from the search once the page is built without them
    big_title = True
    raw = False          # True: build(pb) returns a widget that is shown as the whole page (it scrolls itself)
    max_width = 680
    def __init__(self, win):
        self.win = win; self.view = None; self.pb = None; self.subs = {}; self.sub_builders = []
    def available(self): return True
    def all_settings(self):
        """{configuration key: [rows]} of this page and of the sub pages opened so far (the IA test builds them all)"""
        out = {}
        for pb in ([self.pb] if self.pb is not None else []) + self.sub_builders:
            for k, v in pb.settings.items(): out.setdefault(k, []).extend(v)
        return out
    def min_content_width(self): return 0   # raw pages that cannot shrink report their minimum so the window can hide the sidebar
    def build(self, pb): raise NotImplementedError
    def on_show(self): pass
    def open_sub(self, name): pass
    # helpers
    def push(self, title, builder, max_width=680, raw=False):
        return self.win.push(self, title, builder, max_width, raw)

class SidebarRow(Gtk.ListBoxRow):
    def __init__(self, page=None, title=None, sub=None, icon=None, color=None, entry=None):
        super().__init__(); self.page = page; self.entry = entry
        self.group = page.group if page else -1
        box = Gtk.Box(spacing=12); box.set_margin_start(8); box.set_margin_end(8); box.set_margin_top(4); box.set_margin_bottom(4)
        t = title or page.title
        box.pack_start(ui.icon_tile(icon or page.icon, color or page.color, "md"), False, False, 0)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); col.set_valign(Gtk.Align.CENTER)
        col.pack_start(ui.label(t, "sb-row-title", ellipsize=True), False, False, 0)
        if sub: col.pack_start(ui.label(sub, "sb-row-sub", ellipsize=True), False, False, 0)
        box.pack_start(col, True, True, 0); self.add(box); ui.set_a11y(self, t + (", " + sub if sub else ""))

class SettingsWindow(Gtk.Window):
    def __init__(self, pages_cls, palette=None, size=None):
        super().__init__(title="Settings")
        self.set_name("cset-window"); ui.cls(self, "cset")
        self.set_icon_name("preferences-system")
        self.provider = Gtk.CssProvider(); Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), self.provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
        self.pal = palette or theme.palette(); self.provider.load_from_data(theme.css(self.pal).encode())
        self.pages = [c(self) for c in pages_cls]
        self.pages = [p for p in self.pages if self._safe_available(p)]
        self.by_id = {p.id: p for p in self.pages}
        self.aliases = {a: p.id for p in self.pages for a in p.aliases}
        self.built = {}; self.trail = []; self.current = None; self.sub_n = 0
        self.index = SearchIndex(); self.build_index()
        self.size_window(size)
        self.build_ui()
        self.connect("key-press-event", self.on_key); self.connect("delete-event", self.on_close)
        self.watch_id = GLib.timeout_add_seconds(2, self.watch_theme); self._mt = self._mtime()

    # ---------- sizing ----------
    def size_window(self, size=None):
        disp = Gdk.Display.get_default(); mon = disp.get_primary_monitor() or disp.get_monitor(0)
        wa = mon.get_workarea() if mon else Gdk.Rectangle()
        sw, sh = (wa.width, wa.height) if mon and wa.width > 0 else (1280, 800)
        maxw, maxh = int(sw * 0.9), int(sh * 0.9)
        w, h = default_window_size(sw, sh)
        saved = self._load_size()
        if saved: w, h = saved
        if size: w, h = size
        w, h = max(min(w, maxw), min(720, maxw)), max(min(h, maxh), min(480, maxh))
        self.set_default_size(w, h); self.set_size_request(min(720, maxw), min(480, maxh))
        self.set_position(Gtk.WindowPosition.CENTER)
    def _size_file(self): return os.path.join(su.CFG, "settings-window.json")
    def _load_size(self):
        try:
            d = json.load(open(self._size_file())); return int(d["w"]), int(d["h"])
        except Exception: return None
    def on_close(self, *_):
        try:
            w, h = self.get_size(); os.makedirs(su.CFG, exist_ok=True)
            json.dump({"w": w, "h": h}, open(self._size_file(), "w"))
        except Exception: pass
        return False

    # ---------- live theme ----------
    def _mtime(self):
        try: return os.stat(os.path.join(su.CFG, "settings.conf")).st_mtime
        except OSError: return 0
    def watch_theme(self):
        m = self._mtime()
        if m != self._mt:
            self._mt = m; self.pal = theme.palette(); self.provider.load_from_data(theme.css(self.pal).encode())
            for p in self.pages:
                if hasattr(p, "on_external_change") and p.id in self.built:
                    try: p.on_external_change()
                    except Exception: pass
        return True
    def _safe_available(self, p):
        try: return p.available()
        except Exception: return False

    # ---------- index ----------
    def build_index(self):
        for p in self.pages:
            self.index.add(p.id, p.title, p.title, p.keywords, None)
            for e in p.entries:
                self.index.add(p.id, p.title, e[0], e[1] if len(e) > 1 else "", e[2] if len(e) > 2 else e[0])

    # ---------- UI ----------
    def build_ui(self):
        root = Gtk.Box(); self.add(root)
        # sidebar
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); ui.cls(side, "sidebar-pane"); side.set_size_request(248, -1); root.pack_start(side, False, False, 0)
        self.side = side; self.auto_hidden = False
        sb = Gtk.Box(); ui.cls(sb, "sidebar-search")
        self.search = Gtk.SearchEntry(); ui.cls(self.search, "sb-entry"); self.search.set_placeholder_text("Search"); sb.pack_start(self.search, True, True, 0)
        ui.set_a11y(self.search, "Search settings"); side.pack_start(sb, False, False, 0)
        self.search.connect("search-changed", self.on_search); self.search.connect("activate", lambda *_: self.pick_first_result())
        self.search.connect("key-press-event", self.on_search_key)
        side.pack_start(self.build_user_card(), False, False, 0)
        self.side_stack = Gtk.Stack(); side.pack_start(self.side_stack, True, True, 0)
        self.sb_list = Gtk.ListBox(); ui.cls(self.sb_list, "sidebar-list"); self.sb_list.set_selection_mode(Gtk.SelectionMode.BROWSE)
        self.sb_list.set_header_func(self.sb_header); self.sb_rows = {}
        for p in self.pages:
            r = SidebarRow(p); self.sb_list.add(r); self.sb_rows[p.id] = r
        self.sb_list.connect("row-selected", self.on_sb_selected)
        sw = Gtk.ScrolledWindow(); sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); sw.add(self.sb_list); sw.set_margin_bottom(8)
        self.side_stack.add_named(sw, "list")
        self.res_list = Gtk.ListBox(); ui.cls(self.res_list, "sidebar-list"); self.res_list.set_selection_mode(Gtk.SelectionMode.BROWSE)
        self.res_list.connect("row-activated", self.on_result)
        self.res_sw = Gtk.ScrolledWindow(); self.res_sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); self.res_sw.add(self.res_list)
        self.side_stack.add_named(self.res_sw, "results")
        # content
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); root.pack_start(right, True, True, 0)
        self.toolbar = Gtk.Box(spacing=8); ui.cls(self.toolbar, "toolbar"); right.pack_start(self.toolbar, False, False, 0)
        self.side_btn = Gtk.Button(); ui.cls(self.side_btn, "nav-btn"); self.side_btn.add(Gtk.Image.new_from_icon_name("view-sidebar-start-symbolic" if Gtk.IconTheme.get_default().has_icon("view-sidebar-start-symbolic") else "view-list-symbolic", Gtk.IconSize.BUTTON))
        self.side_btn.set_tooltip_text("Show or hide the sidebar (Ctrl+B)"); ui.set_a11y(self.side_btn, "Show or hide the sidebar"); self.side_btn.connect("clicked", lambda *_: self.toggle_sidebar())
        self.toolbar.pack_start(self.side_btn, False, False, 0)
        self.back_btn = Gtk.Button(); ui.cls(self.back_btn, "nav-btn"); self.back_btn.add(Gtk.Image.new_from_icon_name("go-previous-symbolic", Gtk.IconSize.BUTTON))
        self.back_btn.set_tooltip_text("Back (Alt+Left)"); ui.set_a11y(self.back_btn, "Back"); self.back_btn.connect("clicked", lambda *_: self.back())
        self.back_btn.set_no_show_all(True); self.toolbar.pack_start(self.back_btn, False, False, 0)
        self.tb_title = ui.label("", "toolbar-title"); self.toolbar.pack_start(self.tb_title, False, False, 0)
        self.tb_title.set_opacity(0.0)
        self.status = ui.label("", "muted", xalign=1.0); self.toolbar.pack_end(self.status, False, False, 0)
        self.status_spin = Gtk.Spinner(); self.toolbar.pack_end(self.status_spin, False, False, 0)
        self.stack = Gtk.Stack(); self.stack.set_transition_duration(180); self.stack.set_hexpand(True); right.pack_start(self.stack, True, True, 0)
        self.empty = ui.label("", "muted")
        self.show_all(); self.back_btn.hide()

    def build_user_card(self):
        import pwd
        from .pages.account import avatar, is_admin
        fake = bool(os.environ.get("CSET_FAKE_HW"))
        try: p = pwd.getpwuid(os.getuid()); me = "anna" if fake else p.pw_name; full = "Anna Popescu" if fake else ((p.pw_gecos or "").split(",")[0] or p.pw_name)
        except KeyError: me = full = "You"
        b = Gtk.Button(); ui.cls(b, "user-card"); b.set_relief(Gtk.ReliefStyle.NONE); h = Gtk.Box(spacing=12)
        h.pack_start(avatar(full, 40), False, False, 0)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0); col.set_valign(Gtk.Align.CENTER)
        col.pack_start(ui.label(full, "user-name", ellipsize=True), False, False, 0)
        col.pack_start(ui.label("Administrator" if (fake is False and is_admin(me)) else "Your account", "user-sub", ellipsize=True), False, False, 0)
        h.pack_start(col, True, True, 0); b.add(h); ui.set_a11y(b, f"{full}, account settings"); b.connect("clicked", lambda *_: self.open_page("users"))
        return b
    def toggle_sidebar(self):
        self.auto_hidden = False; self.side.set_visible(not self.side.get_visible())
    def set_sidebar_for(self, need):
        """a page that needs more width than the content area has (the wallpaper browser) hides the sidebar instead of scrolling sideways"""
        avail = self.get_size()[0] - 248
        if need > avail and self.side.get_visible(): self.side.hide(); self.auto_hidden = True
        elif need <= avail and self.auto_hidden: self.side.show(); self.auto_hidden = False
    def sb_header(self, row, before):
        if before is None or getattr(before, "group", 0) != getattr(row, "group", 0):
            if before is None: row.set_header(Gtk.Box()); row.get_header().set_size_request(-1, 4)
            else:
                g = Gtk.Box(); g.set_size_request(-1, 12); row.set_header(g)
        else: row.set_header(None)

    # ---------- search ----------
    def focus_search(self): self.search.grab_focus()
    def on_search(self, entry):
        q = entry.get_text().strip()
        if not q:
            self.side_stack.set_visible_child_name("list"); return
        self.fill_results(q); self.side_stack.set_visible_child_name("results")
    def fill_results(self, q):
        for c in self.res_list.get_children(): self.res_list.remove(c)
        res = self.index.query(q)
        if not res:
            r = Gtk.ListBoxRow(); r.set_activatable(False); r.set_selectable(False)
            l = ui.label(f"No results for “{q}”", "sb-empty", wrap=True); r.add(l); self.res_list.add(r)
        for e in res:
            p = self.by_id.get(e.page)
            if not p: continue
            sub = None if e.anchor is None else p.title
            row = SidebarRow(p, title=e.title, sub=sub); row.entry = e; self.res_list.add(row)
        self.res_list.show_all()
        first = next((r for r in self.res_list.get_children() if getattr(r, "entry", None)), None)
        if first: self.res_list.select_row(first)
    def pick_first_result(self):
        r = self.res_list.get_selected_row()
        if r is not None and getattr(r, "entry", None): self.on_result(self.res_list, r)
    def on_result(self, lb, row):
        e = getattr(row, "entry", None)
        if not e: return
        self.open_page(e.page, anchor=e.anchor)
        self.search.set_text(""); 
    def on_search_key(self, w, ev):
        if ev.keyval == Gdk.KEY_Down:
            tgt = self.res_list if self.side_stack.get_visible_child_name() == "results" else self.sb_list
            r = tgt.get_selected_row() or next(iter(tgt.get_children()), None)
            if r is not None: r.grab_focus()
            return True
        if ev.keyval == Gdk.KEY_Escape and self.search.get_text():
            self.search.set_text(""); return True
        return False

    # ---------- keyboard ----------
    def on_key(self, w, ev):
        ctrl = ev.state & Gdk.ModifierType.CONTROL_MASK; alt = ev.state & Gdk.ModifierType.MOD1_MASK
        if ctrl and ev.keyval in (Gdk.KEY_f, Gdk.KEY_F): self.focus_search(); return True
        if ctrl and ev.keyval in (Gdk.KEY_b, Gdk.KEY_B): self.toggle_sidebar(); return True
        if ctrl and ev.keyval in (Gdk.KEY_w, Gdk.KEY_q): self.close(); return True
        if alt and ev.keyval == Gdk.KEY_Left: self.back(); return True
        if ev.keyval == Gdk.KEY_Escape and not isinstance(self.get_focus(), Gtk.Entry):
            if len(self.trail) > 1: self.back(); return True
        # typing in the sidebar starts a search
        if isinstance(self.get_focus(), Gtk.ListBoxRow) and not ctrl and not alt and 32 < ev.keyval < 127 and self.get_focus().get_parent() in (self.sb_list, self.res_list):
            self.search.grab_focus(); self.search.set_text(chr(ev.keyval)); self.search.set_position(-1); return True
        return False

    # ---------- navigation ----------
    def on_sb_selected(self, lb, row):
        if row is None or getattr(row, "page", None) is None: return
        if self.current is row.page and len(self.trail) == 1: return
        self.show_page(row.page)
    def open_page(self, pid, sub=None, anchor=None):
        pid = self.aliases.get(pid, pid)
        p = self.by_id.get(pid)
        if not p: return False
        row = self.sb_rows[pid]
        self.sb_list.select_row(row)
        if self.current is not p or len(self.trail) > 1: self.show_page(p)
        if sub: p.open_sub(sub)
        if anchor: GLib.idle_add(self.reveal, p, anchor)
        return True
    def reveal(self, p, anchor, tries=0):
        """scroll to and flash the row `anchor` of the page, or of the sub page on top (its rows can arrive from a background thread: look again for a few seconds)"""
        top = self.stack.get_child_by_name(self.trail[-1]) if self.trail else None
        pb = getattr(top, "pb", None) or p.pb
        r = pb.find(anchor) if pb else None
        if r is None:
            if tries < 14: GLib.timeout_add(400, lambda: (self.reveal(p, anchor, tries + 1), False)[1])
            return False
        view = top if top is not None and getattr(top, "pb", None) else p.view
        if view is not None:
            view.scroll_to(r); view.flash(r)
            if hasattr(r, "grab_focus"):
                try:
                    if hasattr(r, "focus_control"): r.focus_control()
                    else: r.grab_focus()
                except Exception: pass
        return False
    def show_page(self, p):
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        # drop any open sub pages of the previous page
        for name in self.trail[1:]:
            ch = self.stack.get_child_by_name(name)
            if ch: self.stack.remove(ch)
        self.current = p
        if p.id not in self.built:
            pb = ui.PageBuilder(p.title, p.sub, p.big_title); p.pb = pb
            try:
                res = p.build(pb)
            except Exception as e:
                import traceback; traceback.print_exc(); res = None
                pb.banner("This page could not be shown. Close Settings and open it again; if it keeps happening, restart your computer.", "bad", title="Something went wrong")
            if p.raw and res is not None:
                v = res; p.view = v; v.show_all()
            else:
                v = ui.PageView(pb, p.max_width); p.view = v; v.show_all()
                v.connect("offset", self.on_scroll, p.id)
            self.stack.add_named(v, p.id); self.built[p.id] = v
        if p.raw: self.set_sidebar_for(p.min_content_width())
        elif self.auto_hidden: self.set_sidebar_for(0)
        if p.pb is not None and p.optional and not p.async_fill:
            self.index.entries = [e for e in self.index.entries if not (e.page == p.id and e.anchor in p.optional and p.pb.find(e.anchor) is None)]
        self.trail = [p.id]; self.stack.set_visible_child_name(p.id)
        self.update_toolbar(p.title, 0)
        try: p.on_show()
        except Exception: pass
    def push(self, p, title, builder, max_width=680, raw=False):
        self.sub_n += 1; name = f"{p.id}/{self.sub_n}"
        if raw:
            v = builder(); v.title_text = title; v.pb = None; v.show_all()
            pb = None
        else:
            pb = ui.PageBuilder(title, "", True); builder(pb); p.sub_builders.append(pb)
            v = ui.PageView(pb, max_width); v.show_all(); v.connect("offset", self.on_scroll, name); v.title_text = title; v.pb = pb
        self.stack.add_named(v, name); self.trail.append(name)
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT); self.stack.set_visible_child_name(name)
        self.update_toolbar(title, 0); return pb
    def back(self):
        if len(self.trail) <= 1: return
        old = self.trail.pop(); child = self.stack.get_child_by_name(old)
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_RIGHT); self.stack.set_visible_child_name(self.trail[-1])
        GLib.timeout_add(300, lambda: (self.stack.remove(child) if child and child.get_parent() else None, False)[1])
        top = self.stack.get_child_by_name(self.trail[-1]); title = getattr(top, "title_text", None) or self.current.title
        self.update_toolbar(title, top.get_vadjustment().get_value() if isinstance(top, Gtk.ScrolledWindow) else 0)
    def update_toolbar(self, title, offset):
        self.tb_title.set_text(title); self.back_btn.set_visible(len(self.trail) > 1); self.back_btn.set_no_show_all(len(self.trail) <= 1)
        self.on_scroll(None, offset, None)
    def on_scroll(self, view, off, name):
        if name is not None and name != self.trail[-1]: return
        a = max(0.0, min(1.0, (off - 28) / 24.0)); self.tb_title.set_opacity(a)
        c = self.toolbar.get_style_context(); (c.add_class if off > 4 else c.remove_class)("scrolled")

    # ---------- applying changes through the CLI tools (serial queue) ----------
    def apply(self, *cmd, msg="Applying...", done=None):
        """Queue a command; one at a time, in order. done(rc, output) runs on the main loop. The toolbar shows what is going on."""
        q = self.__dict__.setdefault("_q", []); q.append((cmd, msg, done)); self._pump()
    BAR_COMMANDS = ("carpatic-profile", "carpatic-theme", "carpatic-appearance", "carpatic-panel", "carpatic-display", "carpatic-pack", "carpatic-apply", "xrandr", "sh")
    def restart_bar(self, quiet=False):
        """bring the bar back: carpatic-session restart (what a style switch does). Never touches windows."""
        if not su.which("carpatic-session"): return
        if not quiet: self.busy("Restarting the bar...")
        su.spawn("carpatic-session", "restart", done=lambda rc, o: self.idle("" if quiet else "The bar was restarted."))
    def ensure_bar(self, tries=0):
        """a few seconds after Settings changed something the bar can be affected by: if the bar program died and did not come back, restart it once"""
        from .pages import panelcfg
        def check(): return panelcfg.bar_state()
        def done(res):
            if isinstance(res, Exception): return
            kind, running = res
            if running: return
            if tries == 0: GLib.timeout_add_seconds(4, lambda: (self.ensure_bar(1), False)[1])     # maybe still restarting: look again
            else: self.restart_bar(quiet=True); self.idle("The bar was not running and has been restarted.")
        su.bg(check, done)
    def _pump(self):
        if self.__dict__.get("_running") or not self._q: return
        cmd, msg, done = self._q.pop(0); self._running = True; self.busy(msg)
        def fin(rc, out):
            self._running = False
            if self._q: self._pump()
            else: self.idle("" if rc == 0 else "That did not work. Try again.")
            if cmd and os.path.basename(cmd[0]) in self.BAR_COMMANDS and not su.DRY: GLib.timeout_add_seconds(5, lambda: (self.ensure_bar(), False)[1])
            if done:
                try: done(rc, out)
                except Exception: import traceback; traceback.print_exc()
            self.watch_theme()
        su.spawn(*cmd, done=fin)

    def on_page_filled(self, p):
        """a page added rows after build() returned (background data): drop optional search entries that did not appear"""
        if p.pb is not None and p.optional:
            self.index.entries = [e for e in self.index.entries if not (e.page == p.id and e.anchor in p.optional and p.pb.find(e.anchor) is None)]

    # ---------- status ----------
    def busy(self, msg="Working..."):
        self.status.set_text(msg); self.status_spin.start(); self.status_spin.show()
    def idle(self, msg=""):
        self.status_spin.stop(); self.status.set_text(msg)
        if msg: GLib.timeout_add(4000, lambda: (self.status.set_text("") if self.status.get_text() == msg else None, False)[1])
