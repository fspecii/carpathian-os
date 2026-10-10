"""WallpaperBrowser: the reusable GTK3 wallpaper widget (macOS-style Wallpaper settings look).

    from carpatic_wallpapers.ui import WallpaperBrowser, install_css
    install_css("dark")            # once per process; uses design/tokens/out/gtk
    browser = WallpaperBrowser()   # Gtk.Box; embed it anywhere
    browser.connect("wallpaper-set", lambda b, path: ...)
    browser.connect("accent-picked", lambda b, hex: ...)

Tabs: Carpatic / My pictures / Wallhaven / Colours. Everything slow (decoding, network) runs on worker threads; the main loop only draws."""
import math, os, subprocess, threading, time

import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0"); gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, Gdk, GLib, GObject, GdkPixbuf, Pango
import cairo

from . import apply, color, library, paths, state, thumbs, wallhaven
from .ui_grid import Cell, ThumbGrid, ColorChips, rgba, rounded

EXTRA_CSS = """
.wp-browser { padding: 0; }
.wp-card { background-color: @card_bg_color; border: 1px solid @borders; border-radius: 14px; padding: 16px; }
.wp-seg { background-color: alpha(@window_fg_color, 0.07); border-radius: 9px; padding: 2px; }
.wp-seg button { border: none; border-radius: 7px; padding: 4px 16px; background: none; min-height: 22px; font-weight: 500; color: alpha(@window_fg_color, 0.8); }
.wp-seg button:checked { background-color: @card_bg_color; color: @window_fg_color; box-shadow: 0 1px 2px alpha(black, 0.25); }
.wp-seg button:hover:not(:checked) { background-color: alpha(@window_fg_color, 0.06); }
.wp-title { font-weight: 600; font-size: 17px; }
.wp-sub { color: alpha(@window_fg_color, 0.62); font-size: 12px; }
.wp-row-label { color: alpha(@window_fg_color, 0.85); }
.wp-chip { border-radius: 999px; padding: 3px 10px; background-color: alpha(@window_fg_color, 0.08); font-size: 12px; border: none; min-height: 16px; }
.wp-chip:hover { background-color: alpha(@window_fg_color, 0.14); }
.wp-warn { border-radius: 10px; padding: 8px 12px; background-color: alpha(@warning_bg_color, 0.18); border: 1px solid alpha(@warning_bg_color, 0.5); }
.wp-note { color: alpha(@window_fg_color, 0.55); font-size: 11px; }
.wp-empty { color: alpha(@window_fg_color, 0.6); }
.wp-drop { border: 2px dashed @accent_bg_color; border-radius: 14px; background-color: alpha(@accent_bg_color, 0.1); }
.wp-link { color: @accent_color; }
.wp-search entry { border-radius: 9px; }
.wp-browser check { border-radius: 5px; min-width: 16px; min-height: 16px; border: 1px solid alpha(@window_fg_color, 0.35); background-image: none; background-color: transparent; box-shadow: none; }
.wp-browser check:checked { background-color: @accent_bg_color; border-color: @accent_bg_color; color: @accent_fg_color; }
.wp-browser radio { background-image: none; }
.wp-accent-dot { border-radius: 999px; min-width: 14px; min-height: 14px; }
"""

_installed = {"css": None}


def _token_dirs():
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.abspath(os.path.join(here, "..", "..", ".."))
    return [os.environ.get("CARPATIC_TOKENS", ""), os.path.join(here, "..", "..", "gtk"), "/usr/local/share/carpatic/gtk",
            os.path.join(repo, "design", "tokens", "out", "gtk"), "/usr/local/share/carpatic/store/gui/theme"]


def install_css(mode="dark", standalone=False):
    """Style the widget. Embedded (default): only this widget's own rules, all scoped under `.wp-browser` / `.wp-*`, so nothing else in the host
    app is restyled; the colour names (@card_bg_color ...) come from the host, and are defined from the Carpatic tokens only when the host lacks them.
    standalone=True (the carpatic-wallpapers window): also loads colors-<mode>.css and carpatic-widgets.css for the whole window."""
    screen = Gdk.Screen.get_default()
    if _installed["css"]:
        for p in _installed["css"]: Gtk.StyleContext.remove_provider_for_screen(screen, p)
    provs = []
    d = next((d for d in _token_dirs() if d and os.path.isfile(os.path.join(d, f"colors-{mode}.css"))), None)
    fallback = "@define-color window_bg_color #11151c; @define-color window_fg_color #e7ecf3; @define-color card_bg_color #171c25; @define-color accent_bg_color #5cc8a8; @define-color accent_color #5cc8a8; @define-color accent_fg_color #08241d; @define-color warning_bg_color #f2c25a; @define-color warning_fg_color #2b2000;"
    if mode == "light": fallback = fallback.replace("#11151c", "#f6f7f9").replace("#e7ecf3", "#1b1f27").replace("#171c25", "#ffffff").replace("#5cc8a8", "#16806a").replace("#08241d", "#ffffff")
    colours = open(os.path.join(d, f"colors-{mode}.css")).read() if d else fallback
    widgets = open(os.path.join(d, "carpatic-widgets.css")).read() if d and os.path.isfile(os.path.join(d, "carpatic-widgets.css")) else ""
    # does the host already define the colour names? (Settings does, from the same tokens)
    probe = Gtk.Window().get_style_context()
    host_has = probe.lookup_color("card_bg_color")[0] and probe.lookup_color("accent_bg_color")[0] and not standalone
    texts = []
    if standalone: texts.append((colours + "\n@define-color borders alpha(#808080, 0.28);\n" + widgets + "\nwindow, .background { background-color: @window_bg_color; color: @window_fg_color; }", Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION))
    elif not host_has: texts.append((colours + "\n@define-color borders alpha(#808080, 0.28);\n", Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION))
    elif not probe.lookup_color("borders")[0]: texts.append(("@define-color borders alpha(#808080, 0.28);\n", Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION))
    texts.append((EXTRA_CSS, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1))
    for text, prio in texts:
        p = Gtk.CssProvider()
        try: p.load_from_data(text.encode())
        except GLib.Error as e: print("css:", e.message)
        Gtk.StyleContext.add_provider_for_screen(screen, p, prio); provs.append(p)
    _installed["css"] = provs


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB": return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024


def in_thread(fn, done=None):
    """Run fn() on a thread, then done(result, error) on the main loop."""
    def run():
        try: r, e = fn(), None
        except Exception as ex: r, e = None, ex
        if done: GLib.idle_add(lambda: (done(r, e), False)[1])
    threading.Thread(target=run, daemon=True).start()


def friendly(e):
    if isinstance(e, (wallhaven.WallhavenError, apply.WallpaperError, ValueError)): return str(e)
    if isinstance(e, OSError): return "Something went wrong reading or writing a file."
    return "Something went wrong. Please try again."


def pixbuf_loader(path, w=320, h=200):
    """Loader for a ThumbGrid cell backed by the thumbnail cache."""
    def load():
        p = thumbs.make_thumb(path, w, h)
        return GdkPixbuf.Pixbuf.new_from_file(p)
    return load


def label(text="", cls=None, xalign=0, wrap=False, sel=False):
    l = Gtk.Label(label=text, xalign=xalign); l.set_line_wrap(wrap); l.set_selectable(sel)
    if cls:
        for c in cls.split(): l.get_style_context().add_class(c)
    return l


# ----- the preview card -------------------------------------------------------------------------------------------------
class MiniScreen(Gtk.DrawingArea):
    """A small monitor: bezel, menu bar, dock and the wallpaper drawn with the chosen fill mode, at the real aspect ratio."""
    def __init__(self):
        super().__init__()
        self.path, self.fill, self.pb, self._key = "", "fill", None, None
        self.set_size_request(300, 200)
        self.dw, self.dh = apply.display_size()
        self.connect("draw", self._draw)

    def set_wallpaper(self, path, fill):
        self.fill = fill
        if path != self.path:
            self.path = path; self.pb = None
            if path:
                def load():
                    return thumbs.load_pixbuf(path, 900)
                in_thread(load, lambda pb, e: (setattr(self, "pb", pb), self.queue_draw()) if path == self.path else None)
        self.queue_draw()

    def _draw(self, w, cr):
        W, H = self.get_allocated_width(), self.get_allocated_height()
        sc = self.get_style_context()
        ok, fg = sc.lookup_color("window_fg_color"); fg = fg if ok else Gdk.RGBA(.9, .9, .9, 1)
        aspect = self.dw / max(self.dh, 1)
        sw = min(W - 16, (H - 34) * aspect); sh = sw / aspect
        x0, y0 = (W - sw) / 2, 6
        # bezel
        rounded(cr, x0 - 5, y0 - 5, sw + 10, sh + 10, 9); cr.set_source_rgb(0.08, 0.09, 0.11); cr.fill()
        rounded(cr, x0 - 5.5, y0 - 5.5, sw + 11, sh + 11, 9.5); cr.set_source_rgba(*rgba(fg, 0.28)); cr.set_line_width(1); cr.stroke()
        cr.save(); rounded(cr, x0, y0, sw, sh, 4); cr.clip()
        cr.set_source_rgb(0.12, 0.13, 0.16); cr.paint()
        if self.pb is not None:
            pw, ph = self.pb.get_width(), self.pb.get_height()
            s = None; cr.save(); cr.translate(x0, y0)
            f = self.fill
            if f == "stretch": cr.scale(sw / pw, sh / ph); self._src(cr)
            elif f == "fit": s = min(sw / pw, sh / ph); cr.translate((sw - pw * s) / 2, (sh - ph * s) / 2); cr.scale(s, s); self._src(cr)
            elif f == "center":
                s = sw / self.dw; cr.translate((sw - pw * s) / 2, (sh - ph * s) / 2); cr.scale(s, s); self._src(cr)
            elif f == "tile":
                s = sw / self.dw; cr.scale(s, s); self._src(cr); cr.get_source().set_extend(cairo.EXTEND_REPEAT); cr.rectangle(0, 0, sw / s, sh / s); cr.fill()
            else: s = max(sw / pw, sh / ph); cr.translate((sw - pw * s) / 2, (sh - ph * s) / 2); cr.scale(s, s); self._src(cr)
            if f != "tile": cr.get_source().set_filter(cairo.FILTER_GOOD); cr.paint()
            cr.restore()
        # menu bar + dock hints (drawn, so they match any wallpaper)
        cr.set_source_rgba(0, 0, 0, 0.30); cr.rectangle(x0, y0, sw, sh * 0.075); cr.fill()
        cr.set_source_rgba(1, 1, 1, 0.8)
        for k in range(3): cr.arc(x0 + 8 + k * 7, y0 + sh * 0.0375, 1.6, 0, 6.3); cr.fill()
        cr.rectangle(x0 + sw - 26, y0 + sh * 0.0375 - 1.5, 18, 3); cr.fill()
        dw_ = sw * 0.34; rounded(cr, x0 + (sw - dw_) / 2, y0 + sh - sh * 0.11, dw_, sh * 0.08, sh * 0.04); cr.set_source_rgba(1, 1, 1, 0.28); cr.fill()
        cr.restore()
        # stand
        cr.set_source_rgba(*rgba(fg, 0.22)); rounded(cr, x0 + sw / 2 - 22, y0 + sh + 9, 44, 4, 2); cr.fill()
        return False

    def _src(self, cr):
        Gdk.cairo_set_source_pixbuf(cr, self.pb, 0, 0)


# ----- the browser ------------------------------------------------------------------------------------------------------
class WallpaperBrowser(Gtk.Box):
    __gsignals__ = {"wallpaper-set": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
                    "accent-picked": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
                    "toast": (GObject.SignalFlags.RUN_FIRST, None, (str,))}

    def __init__(self, client=None, tab="carpatic", watch=True):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.get_style_context().add_class("wp-browser")
        self.set_border_width(0)
        self.client = client
        self.st = state.load()
        self.dw, self.dh = apply.display_size()
        self.suggested = None
        self._dead = False
        self._wh = {"q": None, "loading": False, "res": None, "seen_tags": [], "gen": 0}
        self._build_card()
        self._build_tabs(tab)
        self._drop_setup()
        if watch: self._start_watch()
        self.refresh_current()
        self.connect("destroy", self._on_destroy)
        GLib.timeout_add_seconds(2, self._poll_external)
        self._last_wp = apply.get_setting("WALLPAPER")

    # ---- card
    def _build_card(self):
        # a FlowBox: the mini screen and the controls sit side by side, and wrap under each other when the page is narrow (minimum width about 480 px)
        card = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=2, min_children_per_line=1, column_spacing=20, row_spacing=14, homogeneous=False)
        card.get_style_context().add_class("wp-card"); self.pack_start(card, False, False, 0)
        self.screen = MiniScreen(); self.screen.set_valign(Gtk.Align.START); self.screen.set_halign(Gtk.Align.CENTER); card.add(self.screen)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); col.set_hexpand(True); card.add(col)
        for fc in card.get_children(): fc.set_can_focus(False)
        self.title = label("", "wp-title"); self.title.set_ellipsize(Pango.EllipsizeMode.END)
        self.sub = label("", "wp-sub"); self.sub.set_ellipsize(Pango.EllipsizeMode.END)
        col.pack_start(self.title, False, False, 0); col.pack_start(self.sub, False, False, 0)
        self.small_warn = label("", "wp-sub", wrap=True); col.pack_start(self.small_warn, False, False, 0)

        grid = Gtk.Grid(column_spacing=14, row_spacing=8); col.pack_start(grid, False, False, 6)
        r = 0
        grid.attach(label("Fill", "wp-row-label"), 0, r, 1, 1)
        self.fill_combo = Gtk.ComboBoxText()
        for k, t in state.FILL_MODES: self.fill_combo.append(k, t)
        self.fill_combo.set_active_id(self.st["fill"]); self.fill_combo.connect("changed", self._on_fill); grid.attach(self.fill_combo, 1, r, 2, 1)
        r += 1
        grid.attach(label("Light and dark", "wp-row-label"), 0, r, 1, 1)
        self.pair_sw = Gtk.Switch(active=self.st["pair"]["enabled"], halign=Gtk.Align.START, valign=Gtk.Align.CENTER); self.pair_sw.connect("notify::active", self._on_pair)
        grid.attach(self.pair_sw, 1, r, 1, 1)
        self.pair_menu = Gtk.MenuButton(label="Use this for…"); self.pair_menu.set_popover(self._pair_popover()); grid.attach(self.pair_menu, 2, r, 1, 1)
        r += 1
        self.pair_lbl = label("", "wp-sub"); grid.attach(self.pair_lbl, 1, r, 2, 1)
        r += 1
        grid.attach(label("Change picture", "wp-row-label"), 0, r, 1, 1)
        rot = self.st["rotation"]
        self.rot_sw = Gtk.Switch(active=rot["enabled"], halign=Gtk.Align.START, valign=Gtk.Align.CENTER); self.rot_sw.connect("notify::active", self._on_rotate)
        grid.attach(self.rot_sw, 1, r, 1, 1)
        self.rot_every = Gtk.ComboBoxText()
        for k, t in (("5", "Every 5 minutes"), ("15", "Every 15 minutes"), ("30", "Every 30 minutes"), ("60", "Every hour"), ("360", "Every 6 hours"), ("1440", "Every day"), ("login", "At login")): self.rot_every.append(k, t)
        self.rot_every.set_active_id("login" if rot["on_login"] and not rot["enabled"] else str(rot["every"]) if str(rot["every"]) in ("5", "15", "30", "60", "360", "1440") else "30")
        self.rot_every.connect("changed", self._on_rotate); grid.attach(self.rot_every, 2, r, 1, 1)
        r += 1
        self.rot_coll = Gtk.ComboBoxText()
        for k, t in state.VIRTUAL.items(): self.rot_coll.append(k, "From: " + t)
        for k in self.st["collections"]: self.rot_coll.append(k, "From: " + k)
        self.rot_coll.set_active_id(rot["collection"] if rot["collection"] in list(state.VIRTUAL) + list(self.st["collections"]) else "carpatic-mode"); self.rot_coll.connect("changed", self._on_rotate)
        self.rot_shuffle = Gtk.CheckButton(label="Shuffle", active=rot["shuffle"]); self.rot_shuffle.connect("toggled", self._on_rotate)
        self.rot_rev = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN, transition_duration=150, reveal_child=rot["enabled"] or rot["on_login"])
        rb = Gtk.Box(spacing=10); rb.pack_start(self.rot_coll, True, True, 0); rb.pack_start(self.rot_shuffle, False, False, 0); self.rot_rev.add(rb)
        grid.attach(self.rot_rev, 1, r + 1, 2, 1)
        # accent suggestion
        ar = Gtk.Box(spacing=8); col.pack_start(ar, False, False, 2)
        self.acc_dot = Gtk.DrawingArea(); self.acc_dot.set_size_request(18, 18); self.acc_dot.connect("draw", self._draw_acc); ar.pack_start(self.acc_dot, False, False, 0)
        self.acc_lbl = label("", "wp-sub"); ar.pack_start(self.acc_lbl, False, False, 0)
        self.acc_btn = Gtk.Button(label="Use as accent"); self.acc_btn.get_style_context().add_class("wp-chip"); self.acc_btn.connect("clicked", self._use_accent); ar.pack_start(self.acc_btn, False, False, 0)
        self._set_accent_row(None)

    def _pair_popover(self):
        pop = Gtk.Popover(); box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin=8)
        for key, text in (("dark", "Dark mode"), ("light", "Light mode"), ("theme", "This theme only")):
            b = Gtk.ModelButton(text=text); b.connect("clicked", lambda _b, k=key: (pop.popdown(), self._assign(k))); box.pack_start(b, False, False, 0)
        ms = apply.monitors()
        if len(ms) > 1:
            for n, w_, h_, *_ in ms:
                b = Gtk.ModelButton(text=f"Only on {n} ({w_} \u00d7 {h_})"); b.connect("clicked", lambda _b, k="mon:" + n: (pop.popdown(), self._assign(k))); box.pack_start(b, False, False, 0)
        box.show_all(); pop.add(box); return pop

    def _assign(self, key):
        p = self.current_path()
        if not p: return
        try:
            if key.startswith("mon:"): apply.set_wallpaper(p, monitor=key[4:]); self.emit("toast", f"Used on {key[4:]} only.")
            elif key == "theme": apply.set_wallpaper(p, for_theme=True, paint_now=False); self.emit("toast", "This picture will come back with this theme.")
            else: apply.set_wallpaper(p, pair=key, paint_now=False); self.emit("toast", f"Used for {key} mode.")
        except Exception as e: self.emit("toast", friendly(e))
        self.st = state.load(); self._sync_pair_ui()

    def _sync_pair_ui(self):
        self.pair_sw.handler_block_by_func(self._on_pair); self.pair_sw.set_active(self.st["pair"]["enabled"]); self.pair_sw.handler_unblock_by_func(self._on_pair)
        pr = self.st["pair"]
        nm = lambda p: os.path.splitext(os.path.basename(p))[0] if p else "not set"
        self.pair_lbl.set_text(f"Dark: {nm(pr['dark'])}  ·  Light: {nm(pr['light'])}")

    def _on_pair(self, sw, _p):
        pr = self.st["pair"]
        if sw.get_active() and not (pr["light"] and pr["dark"]):
            self.emit("toast", "Pick a picture and use “Use this for…” for both dark and light first.")
            sw.set_active(False); return
        state.update(lambda d: d["pair"].update(enabled=sw.get_active())); self.st = state.load()
        if sw.get_active(): in_thread(apply.sync, lambda r, e: self.refresh_current())

    def _on_fill(self, combo):
        f = combo.get_active_id()
        if not f or f == self.st["fill"]: return
        self.st["fill"] = f; state.update(lambda d: d.update(fill=f)); apply.set_setting("WALLPAPER_MODE", f)
        cur = self.current_path()
        self.screen.set_wallpaper(cur, f)
        if cur: in_thread(lambda: apply.paint(cur, f))

    def _on_rotate(self, *a):
        on = self.rot_sw.get_active(); ev = self.rot_every.get_active_id() or "30"
        self.rot_rev.set_reveal_child(on)
        login = ev == "login"
        try:
            apply.set_rotation(on and not login, None if login else int(ev), self.rot_coll.get_active_id(), self.rot_shuffle.get_active(), login and on)
            if on and not login:
                from . import cli
                cli.spawn_daemon()
        except Exception as e: self.emit("toast", friendly(e))
        self.st = state.load()

    def _draw_acc(self, w, cr):
        if self.suggested:
            cr.arc(9, 9, 8, 0, 6.3); cr.set_source_rgb(*(int(self.suggested[i:i + 2], 16) / 255 for i in (1, 3, 5))); cr.fill()
            cr.arc(9, 9, 8.5, 0, 6.3); cr.set_source_rgba(.5, .5, .5, .5); cr.set_line_width(1); cr.stroke()

    def _set_accent_row(self, hexv):
        self.suggested = hexv; self.acc_dot.queue_draw()
        self.acc_lbl.set_text(f"Accent from this picture: {hexv}" if hexv else "This picture has no clear colour, so the accent stays.")
        self.acc_btn.set_visible(bool(hexv)); self.acc_btn.set_no_show_all(True)
        if hexv: self.acc_btn.show()

    def _use_accent(self, b):
        if not self.suggested: return
        hexv = self.suggested
        self.emit("accent-picked", hexv)
        def run():
            return subprocess.run(["carpatic-theme", "set", apply.current_theme(), "--accent", hexv], capture_output=True, timeout=60).returncode
        in_thread(run, lambda rc, e: self.emit("toast", "Accent applied." if rc == 0 else "The theme engine is not available here; the colour is " + hexv))

    def current_path(self): return apply.current_wallpaper()

    def refresh_current(self):
        p = self.current_path(); self.st = state.load()
        self.screen.set_wallpaper(p, self.st["fill"])
        known = {os.path.realpath(i.path): i for i in library.builtin_items()}
        bi = known.get(os.path.realpath(p)) if p else None
        name = (bi.title + (f" ({bi.mode})" if bi.mode else "")) if bi else os.path.splitext(os.path.basename(p))[0].replace("-", " ").replace("_", " ").title() if p else "No wallpaper"
        self.title.set_text(name)
        d = imageinfo_dims(p)
        src = "Carpatic" if bi else "Wallhaven" if "/Wallhaven/" in p else "My pictures" if p else ""
        self.sub.set_text(("  ·  ".join(x for x in (src, f"{d[0]} × {d[1]}" if d else "") if x)) or "Choose a picture below")
        small = bool(d and (d[0] < self.dw * 0.9 or d[1] < self.dh * 0.9))
        self.small_warn.set_text(f"Smaller than your screen ({self.dw} × {self.dh}): it will look soft." if small else ""); self.small_warn.set_visible(small); self.small_warn.set_no_show_all(True)
        if small: self.small_warn.show()
        self._sync_pair_ui()
        for g in (self.grid_carpatic, self.grid_local): g.select_key(p)
        if p and p != getattr(self, "_acc_for", None):
            self._acc_for = p; dark = apply.theme_mode() == "dark"
            in_thread(lambda: color.accent_for(p, dark), lambda h, e: self._set_accent_row(h) if p == self._acc_for else None)

    def _poll_external(self):
        if getattr(self, "_dead", False): return False
        cur = apply.get_setting("WALLPAPER")
        if cur != self._last_wp: self._last_wp = cur; self.refresh_current()
        return True

    # ---- tabs
    def _build_tabs(self, tab):
        bar = Gtk.Box(spacing=12); self.pack_start(bar, False, False, 0)
        seg = Gtk.Box(); seg.get_style_context().add_class("wp-seg"); bar.pack_start(seg, False, False, 0)
        self.stack = Gtk.Stack(); self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE); self.stack.set_transition_duration(120)
        self.tab_btns, first = {}, None
        for key, text in (("carpatic", "Carpatic"), ("mine", "My pictures"), ("wallhaven", "Wallhaven"), ("colours", "Colours")):
            b = Gtk.RadioButton.new_with_label_from_widget(first, text); b.set_mode(False); first = first or b
            b.connect("toggled", lambda b, k=key: b.get_active() and self._show_tab(k)); seg.pack_start(b, False, False, 0); self.tab_btns[key] = b
        self.tab_extra = Gtk.Box(spacing=8); bar.pack_end(self.tab_extra, False, False, 0)
        self.pack_start(self.stack, True, True, 0)
        self.grid_carpatic, sw1 = self._scrolled_grid()
        self.stack.add_named(sw1, "carpatic")
        self.stack.add_named(self._build_mine(), "mine")
        self.stack.add_named(self._build_wallhaven(), "wallhaven")
        self.stack.add_named(self._build_colours(), "colours")
        self._load_carpatic()
        self._extras = {}
        self.show_all()
        self.tab_btns[tab].set_active(True); self._show_tab(tab)

    def _scrolled_grid(self):
        g = ThumbGrid(); g.connect("activated", self._on_activated, g)
        sw = Gtk.ScrolledWindow(); sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); sw.add(g); sw.set_min_content_height(260)
        sw.set_overlay_scrolling(True)
        return g, sw

    def _show_tab(self, key):
        self.stack.set_visible_child_name(key); self.current_tab = key
        for c in self.tab_extra.get_children(): self.tab_extra.remove(c)
        self.tab_extra.show_all()
        if key == "wallhaven" and self._wh["res"] is None and not self._wh["loading"]: self._wh_search(reset=True)
        if key == "mine": self._load_local()

    # ---- Carpatic
    def _load_carpatic(self):
        items = library.builtin_items()
        cells = []
        mode = apply.theme_mode()
        for group in ("Carpathians", "Themes"):
            gi_ = [i for i in items if i.group == group]
            if not gi_: continue
            cells.append(Cell("h:" + group, "Carpathian scenes" if group == "Carpathians" else "Theme pictures", header=True))
            gi_.sort(key=lambda i: (i.mode != mode,) if group == "Carpathians" else 0)
            for i in gi_:
                cells.append(Cell(i.path, i.title, (i.mode.title() if i.mode else ""), pixbuf_loader(i.path), data=i))
        self.grid_carpatic.set_cells(cells)
        self.grid_carpatic.select_key(self.current_path())

    def _on_activated(self, grid, idx, g):
        c = g.cells[idx]
        if c.header or not c.data or not isinstance(c.data, library.Item): return
        self._set_path(c.data.path)

    def _set_path(self, path, fill=None):
        def run(): return apply.set_wallpaper(path, fill=fill)
        def done(r, e):
            if e: self.emit("toast", friendly(e)); return
            self._last_wp = r; self.refresh_current(); self.emit("wallpaper-set", r)
        # optimistic: ring moves at once
        for g in (self.grid_carpatic, self.grid_local): g.select_key(path)
        in_thread(run, done)

    # ---- My pictures
    def _build_mine(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add_folder_btn = Gtk.Button(label="Add folder…"); self.add_folder_btn.connect("clicked", self._add_folder_dialog)
        self.add_files_btn = Gtk.Button(label="Add pictures…"); self.add_files_btn.connect("clicked", self._add_files_dialog)
        top = Gtk.Box(spacing=8); box.pack_start(top, False, False, 0)
        self.folder_row = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=6, column_spacing=6, row_spacing=6, valign=Gtk.Align.CENTER); top.pack_start(self.folder_row, True, True, 0)
        top.pack_end(self.add_files_btn, False, False, 0); top.pack_end(self.add_folder_btn, False, False, 0)
        self.mine_stack = Gtk.Stack(); box.pack_start(self.mine_stack, True, True, 0)
        self.grid_local, sw = self._scrolled_grid(); self.mine_stack.add_named(sw, "grid")
        empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        img = Gtk.Image.new_from_icon_name("folder-pictures-symbolic", Gtk.IconSize.DIALOG); img.set_pixel_size(56); img.set_opacity(.5); empty.pack_start(img, False, False, 0)
        empty.pack_start(label("No pictures yet", "wp-title", xalign=.5), False, False, 0)
        self.empty_lbl = label("", "wp-empty", xalign=.5, wrap=True); self.empty_lbl.set_justify(Gtk.Justification.CENTER); empty.pack_start(self.empty_lbl, False, False, 0)
        b = Gtk.Button(label="Add folder…", halign=Gtk.Align.CENTER); b.get_style_context().add_class("suggested-action"); b.connect("clicked", self._add_folder_dialog); empty.pack_start(b, False, False, 6)
        self.mine_stack.add_named(empty, "empty")
        self.mine_overlay = box
        return box

    def _load_local(self):
        def work():
            return library.local_items(with_hashes=True)
        def done(items, e):
            if self._dead: return
            if e: self.emit("toast", friendly(e)); return
            self._local_items = items
            self._render_folders()
            if not items:
                self.empty_lbl.set_text(f"Drop pictures or folders here, or add a folder.\nPictures in {paths.pictures_dir().replace(paths.home(), '~')} show up on their own."); self.mine_stack.set_visible_child_name("empty")
            else:
                cells = []
                for i in items:
                    badges = ["Wallhaven"] if i.source == "wallhaven" else []
                    if i.dup_of: badges.append("Duplicate")
                    sub = f"{i.width} × {i.height}" if i.width else ""
                    cells.append(Cell(i.path, i.title, sub, pixbuf_loader(i.path), badges=badges, warn="Low resolution" if i.small_for(self.dw, self.dh) else "", data=i))
                self.grid_local.set_cells(cells); self.grid_local.select_key(self.current_path()); self.mine_stack.set_visible_child_name("grid")
        in_thread(work, done)

    def _render_folders(self):
        for c in self.folder_row.get_children(): self.folder_row.remove(c)
        for f in library.folders():
            b = Gtk.Button(label=f.replace(paths.home(), "~") + "  ×"); b.get_style_context().add_class("wp-chip"); b.set_tooltip_text("Stop showing pictures from this folder (nothing is deleted)")
            b.connect("clicked", lambda _b, f=f: (library.remove_folder(f), self._restart_watch(), self._load_local())); self.folder_row.add(b)
        self.folder_row.show_all()

    def _add_folder_dialog(self, *a):
        d = Gtk.FileChooserNative(title="Add a folder of pictures", action=Gtk.FileChooserAction.SELECT_FOLDER, transient_for=self.get_toplevel() if isinstance(self.get_toplevel(), Gtk.Window) else None)
        if d.run() == Gtk.ResponseType.ACCEPT: self.add_paths([d.get_filename()])
    def _add_files_dialog(self, *a):
        d = Gtk.FileChooserNative(title="Add pictures", action=Gtk.FileChooserAction.OPEN, transient_for=self.get_toplevel() if isinstance(self.get_toplevel(), Gtk.Window) else None)
        d.set_select_multiple(True)
        f = Gtk.FileFilter(); f.set_name("Pictures")
        for g in ("jpg", "jpeg", "png", "webp", "avif", "jxl", "heic", "heif", "gif", "bmp", "tif", "tiff"): f.add_pattern("*." + g); f.add_pattern("*." + g.upper())
        d.add_filter(f)
        if d.run() == Gtk.ResponseType.ACCEPT: self.add_paths(d.get_filenames())

    def add_paths(self, items):
        """Add files, folders or wallhaven links (what a drop or a dialog hands us). Reports problems with a toast."""
        errs, added = [], 0
        for it in items:
            try:
                if it.startswith("file://"):
                    from urllib.parse import unquote, urlsplit
                    it = unquote(urlsplit(it).path)
                if it.startswith("http"):
                    from . import cli
                    in_thread(lambda it=it: cli.add_target(it, self._client()), lambda r, e: (self.emit("toast", friendly(e)) if e else (self.emit("toast", "Added from Wallhaven."), self._load_local())))
                    continue
                if os.path.isdir(it): library.add_folder(it)
                else: library.add_file(it)
                added += 1
            except (ValueError, apply.WallpaperError, wallhaven.WallhavenError) as e: errs.append(str(e))
        if added: self._restart_watch(); self.tab_btns["mine"].set_active(True); self._load_local()
        if errs: self.emit("toast", errs[0])

    # drag and drop of files, folders and text/URLs onto the whole widget
    def _drop_setup(self):
        tl = Gtk.TargetList.new([]); tl.add_uri_targets(0); tl.add_text_targets(1)
        self.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY); self.drag_dest_set_target_list(tl)
        self.connect("drag-data-received", self._on_drop)
        self.connect("drag-motion", lambda w, c, x, y, t: (self.get_style_context().add_class("wp-drop"), False)[1])
        self.connect("drag-leave", lambda w, c, t: self.get_style_context().remove_class("wp-drop"))

    def _on_drop(self, w, ctx, x, y, data, info, t):
        uris = data.get_uris() or [l.strip() for l in (data.get_text() or "").splitlines() if l.strip()]
        self.get_style_context().remove_class("wp-drop"); self.add_paths(uris[:200])

    # folder watching (inotify through GLib)
    def _start_watch(self):
        self._watcher, self._watch_src, self._watch_timer = None, None, None
        try:
            self._watcher = library.Watcher(library.folders())
            self._watch_src = GLib.io_add_watch(self._watcher.fileno(), GLib.IO_IN, self._on_inotify)
        except OSError:
            pass
    def _restart_watch(self):
        if getattr(self, "_watch_src", None): GLib.source_remove(self._watch_src)
        if getattr(self, "_watcher", None): self._watcher.close()
        self._start_watch()
    def _on_inotify(self, fd, cond):
        if self._dead: return False
        if self._watcher.read() and not self._watch_timer:
            def go(): self._watch_timer = None; self._load_local(); return False
            self._watch_timer = GLib.timeout_add(600, go)   # debounce a burst of writes (copying 200 files)
        return True
    def _on_destroy(self, *a):
        self._dead = True
        if getattr(self, "_watch_src", None): GLib.source_remove(self._watch_src); self._watch_src = None
        if getattr(self, "_watch_timer", None): GLib.source_remove(self._watch_timer); self._watch_timer = None
        if getattr(self, "_watcher", None): self._watcher.close()

    # ---- Colours
    def _build_colours(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.grid_colours, sw = self._scrolled_grid()
        cells = [Cell("h:c", "Solid colours and gradients", header=True)]
        for name, stops in apply.PRESET_COLOURS:
            cells.append(Cell("colour:" + name, name, "Solid" if len(stops) == 1 else "Gradient", self._colour_loader(stops), data=(name, stops)))
        self.grid_colours.disconnect_by_func(self._on_activated); self.grid_colours.connect("activated", self._on_colour)
        self.grid_colours.set_cells(cells)
        box.pack_start(sw, True, True, 0)
        row = Gtk.Box(spacing=8); box.pack_start(row, False, False, 0)
        row.pack_start(label("Your own", "wp-row-label"), False, False, 0)
        self.c1 = Gtk.ColorButton.new_with_rgba(Gdk.RGBA(.12, .24, .2, 1)); self.c2 = Gtk.ColorButton.new_with_rgba(Gdk.RGBA(.36, .78, .66, 1))
        self.c1.set_tooltip_text("First colour"); self.c2.set_tooltip_text("Second colour (for a gradient)")
        self.grad_chk = Gtk.CheckButton(label="Gradient", active=True)
        mk = Gtk.Button(label="Use this colour"); mk.connect("clicked", self._custom_colour)
        for w in (self.c1, self.c2, self.grad_chk, mk): row.pack_start(w, False, False, 0)
        return box

    def _colour_loader(self, stops):
        def load():
            import cairo as c
            w, h = 320, 200; s = c.ImageSurface(c.FORMAT_RGB24, w, h); cr = c.Context(s)
            rgb = lambda x: tuple(int(x[i:i + 2], 16) / 255 for i in (1, 3, 5))
            if len(stops) == 1: cr.set_source_rgb(*rgb(stops[0]))
            else:
                g = c.LinearGradient(0, 0, w, h)
                for i, st in enumerate(stops): g.add_color_stop_rgb(i / (len(stops) - 1), *rgb(st))
                cr.set_source(g)
            cr.paint()
            import io; b = io.BytesIO(); s.write_to_png(b)
            ld = GdkPixbuf.PixbufLoader.new_with_type("png"); ld.write(b.getvalue()); ld.close(); return ld.get_pixbuf()
        return load

    def _on_colour(self, g, idx):
        c = g.cells[idx]
        if c.header: return
        name, stops = c.data
        self._make_colour(name, stops)

    def _make_colour(self, name, stops):
        def run():
            f = apply.generate_colour(name, stops, size=(self.dw, self.dh)); return apply.set_wallpaper(f, fill="stretch")
        def done(r, e):
            if e: self.emit("toast", friendly(e)); return
            self.st = state.load(); self.fill_combo.set_active_id("stretch"); self._last_wp = r; self.refresh_current(); self.emit("wallpaper-set", r)
        in_thread(run, done)

    def _custom_colour(self, b):
        hx = lambda btn: "#%02x%02x%02x" % tuple(round(v * 255) for v in (btn.get_rgba().red, btn.get_rgba().green, btn.get_rgba().blue))
        stops = [hx(self.c1)] + ([hx(self.c2)] if self.grad_chk.get_active() else [])
        self._make_colour("custom-" + "-".join(s[1:] for s in stops), stops)

    # ---- Wallhaven
    def _client(self):
        if self.client is None: self.client = wallhaven.Client()
        return self.client

    def _build_wallhaven(self):
        page = Gtk.Stack(); self.wh_stack = page
        browse = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10); page.add_named(browse, "browse")
        bar = Gtk.Box(spacing=8); bar.get_style_context().add_class("wp-search"); browse.pack_start(bar, False, False, 0)
        self.wh_entry = Gtk.SearchEntry(placeholder_text="Search Wallhaven: mountains, +forest, -city, id:123"); self.wh_entry.set_hexpand(True); self.wh_entry.set_width_chars(8)
        self.wh_entry.connect("activate", lambda e: self._wh_search(reset=True)); self.wh_entry.connect("search-changed", self._wh_suggest)
        bar.pack_start(self.wh_entry, True, True, 0)
        comp = Gtk.EntryCompletion(); self.wh_store = Gtk.ListStore(str); comp.set_model(self.wh_store); comp.set_text_column(0); comp.set_inline_completion(False); comp.set_popup_single_match(True)
        comp.connect("match-selected", self._wh_pick_tag); comp.set_match_func(lambda c, k, it: True); self.wh_entry.set_completion(comp)
        self.wh_sort = Gtk.ComboBoxText()
        for k, t in wallhaven.SORTINGS: self.wh_sort.append(k, t)
        self.wh_sort.set_active_id("toplist"); self.wh_sort.connect("changed", lambda *a: (self._wh_sync_range(), self._wh_search(reset=True))); bar.pack_start(self.wh_sort, False, False, 0)
        self.wh_range = Gtk.ComboBoxText()
        for k, t in wallhaven.TOP_RANGES: self.wh_range.append(k, "Top " + t.lower())
        self.wh_range.set_active_id("1M"); self.wh_range.connect("changed", lambda *a: self._wh_search(reset=True)); bar.pack_start(self.wh_range, False, False, 0)
        fb = Gtk.MenuButton(label="Filters"); fb.set_popover(self._wh_filters()); bar.pack_start(fb, False, False, 0)
        self.wh_msg = Gtk.Box(spacing=10); self.wh_msg.get_style_context().add_class("wp-warn"); self.wh_msg_lbl = label("", wrap=True); self.wh_msg.pack_start(self.wh_msg_lbl, True, True, 0)
        rb = Gtk.Button(label="Try again"); rb.connect("clicked", lambda *a: self._wh_search(reset=self._wh["res"] is None)); self.wh_msg.pack_end(rb, False, False, 0)
        self.wh_msg.set_no_show_all(True); browse.pack_start(self.wh_msg, False, False, 0)
        self.grid_wh, sw = self._scrolled_grid()
        self.grid_wh.disconnect_by_func(self._on_activated); self.grid_wh.connect("activated", self._wh_open); self.grid_wh.connect("need-more", lambda *a: self._wh_more())
        browse.pack_start(sw, True, True, 0)
        note = label("Pictures come from wallhaven.cc and belong to the people who made them; each has its own licence. Carpatic OS does not ship any. "
                     "Only safe-for-work pictures are shown. Nothing is downloaded until you choose Download or Set as wallpaper.", "wp-note", wrap=True)
        browse.pack_start(note, False, False, 0)
        dsw = Gtk.ScrolledWindow(); dsw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); dsw.add(self._wh_detail_page())
        page.add_named(dsw, "detail")
        return page

    def _wh_filters(self):
        pop = Gtk.Popover(); g = Gtk.Grid(column_spacing=12, row_spacing=10, margin=14)
        r = 0
        g.attach(label("Categories", "wp-row-label"), 0, r, 1, 1)
        cb = Gtk.Box(spacing=10); self.wh_cats = {}
        for k, t in wallhaven.CATEGORIES:
            c = Gtk.CheckButton(label=t, active=(k == "general")); c.connect("toggled", lambda *a: self._wh_filter_changed()); cb.pack_start(c, False, False, 0); self.wh_cats[k] = c
        g.attach(cb, 1, r, 1, 1); r += 1
        g.attach(label("Size", "wp-row-label"), 0, r, 1, 1)
        self.wh_atleast = Gtk.ComboBoxText()
        mine = f"{self.dw}x{self.dh}"
        for k, t in ((mine, f"At least my screen ({self.dw} × {self.dh})"), ("", "Any size"), ("1920x1080", "At least 1920 × 1080"), ("2560x1440", "At least 2560 × 1440"), ("3840x2160", "At least 3840 × 2160")):
            if self.wh_atleast.get_model() is None or k not in [r_[0] for r_ in self.wh_atleast.get_model()]: self.wh_atleast.append(k, t) if k else self.wh_atleast.append("any", t)
        self.wh_atleast.set_active(0); self.wh_atleast.connect("changed", lambda *a: self._wh_filter_changed()); g.attach(self.wh_atleast, 1, r, 1, 1); r += 1
        g.attach(label("Shape", "wp-row-label"), 0, r, 1, 1)
        self.wh_ratio = Gtk.ComboBoxText()
        ratio = self._screen_ratio()
        self.wh_ratio.append(ratio, f"My screen ({ratio.replace('x', ':')})")
        for k, t in (("any", "Any shape"), ("16x9", "16:9"), ("16x10", "16:10"), ("21x9", "21:9 ultrawide"), ("4x3", "4:3"), ("portrait", "Portrait")):
            if k != ratio: self.wh_ratio.append(k, t)
        self.wh_ratio.set_active(0); self.wh_ratio.connect("changed", lambda *a: self._wh_filter_changed()); g.attach(self.wh_ratio, 1, r, 1, 1); r += 1
        g.attach(label("Colour", "wp-row-label"), 0, r, 1, 1)
        self.wh_chips = ColorChips(wallhaven.COLORS); self.wh_chips.connect("changed", lambda *a: self._wh_filter_changed()); g.attach(self.wh_chips, 1, r, 1, 1); r += 1
        g.attach(label("Wallhaven API key (optional)", "wp-row-label"), 0, r, 1, 1)
        self.wh_key = Gtk.Entry(visibility=False, placeholder_text="Not needed for browsing"); self.wh_key.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        self.wh_key.set_text("•" * 12 if wallhaven.load_api_key() else ""); self.wh_key.connect("activate", self._wh_save_key); self.wh_key.connect("focus-out-event", lambda *a: (self._wh_save_key(), False)[1]); g.attach(self.wh_key, 1, r, 1, 1); r += 1
        g.attach(label("Stored privately in your settings folder (mode 600). Press Enter to save; empty it to remove.", "wp-note", wrap=True), 1, r, 1, 1)
        g.show_all(); pop.add(g); return pop

    def _screen_ratio(self):
        from math import gcd
        w, h = self.dw, self.dh; best = min(((16, 9), (16, 10), (21, 9), (4, 3), (3, 2), (5, 4), (32, 9)), key=lambda r: abs(r[0] / r[1] - w / h))
        return f"{best[0]}x{best[1]}"

    def _wh_save_key(self, *a):
        t = self.wh_key.get_text().strip()
        if t and set(t) == {"•"}: return
        try:
            wallhaven.save_api_key(t); self._client().api_key = wallhaven.load_api_key()
            self.emit("toast", "API key saved." if t else "API key removed.")
        except ValueError as e: self.emit("toast", str(e))
        if t: self.wh_key.set_text("•" * 12)

    def _wh_sync_range(self): self.wh_range.set_visible(self.wh_sort.get_active_id() == "toplist")

    def _wh_filter_changed(self):
        if getattr(self, "_wh_ft", None): GLib.source_remove(self._wh_ft)
        self._wh_ft = GLib.timeout_add(400, lambda: (setattr(self, "_wh_ft", None), self._wh_search(reset=True), False)[2])

    def _wh_query(self, page=1):
        cats = "".join("1" if self.wh_cats[k].get_active() else "0" for k, _ in wallhaven.CATEGORIES)
        at = self.wh_atleast.get_active_id(); rt = self.wh_ratio.get_active_id()
        return wallhaven.Query(text=self.wh_entry.get_text(), categories=cats if cats != "000" else "100", sorting=self.wh_sort.get_active_id() or "toplist", top_range=self.wh_range.get_active_id() or "1M",
                               atleast="" if at in ("any", None) else at, ratios="" if rt in ("any", None) else rt, colors=self.wh_chips.value, page=page,
                               seed=(self._wh.get("seed") or "") if page > 1 else "")

    def _wh_suggest(self, entry):
        t = entry.get_text().split(" ")[-1]
        self.wh_store.clear()
        for s in wallhaven.suggest_tags(t, self._wh["seen_tags"]): self.wh_store.append([s])

    def _wh_pick_tag(self, comp, model, it):
        words = self.wh_entry.get_text().split(" "); words[-1] = ("+" if words[-1].startswith("+") else "-" if words[-1].startswith("-") else "") + model[it][0]
        self.wh_entry.set_text(" ".join(words)); self.wh_entry.set_position(-1); self._wh_search(reset=True); return True

    def _wh_error(self, e):
        self.wh_msg_lbl.set_text(friendly(e) if e else ""); self.wh_msg.set_visible(bool(e))
        if e: self.wh_msg.show_all()

    def _wh_search(self, reset=True):
        if not self.get_mapped() and reset is None: return
        self._wh["gen"] += 1; gen = self._wh["gen"]
        q = self._wh_query(1); self._wh["q"] = q; self._wh["res"] = None; self._wh["loading"] = True; self._wh_error(None)
        self.grid_wh.set_skeletons(18)
        c = self._client()
        def done(res, e):
            if self._dead or gen != self._wh["gen"]: return
            self._wh["loading"] = False
            if e: self.grid_wh.set_cells([]); self._wh_error(e); self._wh["res"] = None; return
            self._wh["res"] = res; self._wh["seed"] = res.seed
            if res.stale: self.wh_msg_lbl.set_text("You are offline: showing the last results saved on this computer."); self.wh_msg.show_all()
            cells = [self._wh_cell(w) for w in res.items]
            self.grid_wh.set_cells(cells)
            if not cells: self._wh_empty()
            self.grid_wh.scrolled_window().get_vadjustment().set_value(0)
        in_thread(lambda: c.search(q), done)

    def _wh_empty(self):
        self.wh_msg_lbl.set_text("Nothing matches. Try fewer words, a different colour, or Size → Any size."); self.wh_msg.show_all()

    def _wh_cell(self, w):
        c = self._client()
        def load():
            p = c.thumb(w, "small"); return GdkPixbuf.Pixbuf.new_from_file(p)
        return Cell("wh:" + w.id, f"★ {w.favorites:,}" if w.favorites else "Wallhaven", "", load, badges=[w.resolution.replace(" ", "")], data=w)

    def _wh_more(self):
        res, q = self._wh["res"], self._wh["q"]
        if not res or self._wh["loading"] or not res.has_more: return
        self._wh["loading"] = True; gen = self._wh["gen"]
        q2 = self._wh_query(res.page + 1); self.grid_wh.add_skeletons(6)
        def done(r, e):
            if self._dead or gen != self._wh["gen"]: return
            self._wh["loading"] = False
            if e: self.grid_wh.add_skeletons(0); self._wh_error(e); return
            self._wh["res"] = r; self.grid_wh.append_cells([self._wh_cell(w) for w in r.items])
        in_thread(lambda: self._client().search(q2), done)

    # detail
    def _wh_detail_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        top = Gtk.Box(spacing=8); back = Gtk.Button(label="‹ Back"); back.connect("clicked", lambda *a: self.wh_stack.set_visible_child_name("browse")); top.pack_start(back, False, False, 0); box.pack_start(top, False, False, 0)
        body = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=2, column_spacing=18, row_spacing=12, homogeneous=False); box.pack_start(body, True, True, 0)
        self.det_img = Gtk.DrawingArea(); self.det_img.set_hexpand(True); self.det_img.set_vexpand(True); self.det_img.set_size_request(300, 240); self.det_img.connect("draw", self._draw_det)
        self.det_pb = None; body.add(self.det_img)
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); side.set_size_request(300, -1); body.add(side)
        for fc in body.get_children(): fc.set_can_focus(False)
        self.det_title = label("", "wp-title"); self.det_meta = label("", "wp-sub", wrap=True); self.det_by = label("", "wp-sub", wrap=True)
        for w in (self.det_title, self.det_meta, self.det_by): side.pack_start(w, False, False, 0)
        self.det_tags = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4, column_spacing=4, row_spacing=4); side.pack_start(self.det_tags, False, False, 0)
        self.det_src = Gtk.LinkButton.new_with_label("", "Original source"); self.det_src.set_halign(Gtk.Align.START); side.pack_start(self.det_src, False, False, 0)
        self.det_status = label("", "wp-sub", wrap=True)
        self.det_set = Gtk.Button(label="Set as wallpaper"); self.det_set.get_style_context().add_class("suggested-action"); self.det_set.connect("clicked", lambda *a: self._wh_do("set"))
        self.det_dl = Gtk.Button(label="Download"); self.det_dl.connect("clicked", lambda *a: self._wh_do("download"))
        self.det_add = Gtk.Button(label="Add to my wallpapers"); self.det_add.connect("clicked", lambda *a: self._wh_do("add"))
        self.det_open = Gtk.Button(label="Open on wallhaven.cc"); self.det_open.connect("clicked", self._wh_open_web)
        for b in (self.det_set, self.det_dl, self.det_add, self.det_open): side.pack_start(b, False, False, 0)
        side.pack_start(self.det_status, False, False, 0)
        side.pack_start(label("Uploaded by a Wallhaven user. Copyright stays with its creator; check the licence before using it elsewhere.", "wp-note", wrap=True), False, False, 0)
        return box

    def _draw_det(self, w, cr):
        W, H = w.get_allocated_width(), w.get_allocated_height()
        sc = w.get_style_context(); ok, fg = sc.lookup_color("window_fg_color"); fg = fg if ok else Gdk.RGBA(.9, .9, .9, 1)
        if self.det_pb is None:
            rounded(cr, 0, 0, W, H, 12); cr.set_source_rgba(*rgba(fg, .07)); cr.fill(); return False
        pw, ph = self.det_pb.get_width(), self.det_pb.get_height(); s = min(W / pw, H / ph)
        cr.save(); cr.translate((W - pw * s) / 2, (H - ph * s) / 2)
        rounded(cr, 0, 0, pw * s, ph * s, 12); cr.clip(); cr.scale(s, s); Gdk.cairo_set_source_pixbuf(cr, self.det_pb, 0, 0); cr.get_source().set_filter(cairo.FILTER_GOOD); cr.paint(); cr.restore()
        return False

    def _wh_open(self, grid, idx):
        c = grid.cells[idx]
        if c.header or not isinstance(c.data, wallhaven.Wallpaper): return
        w = c.data; self._det = w; self.det_pb = None; self.det_img.queue_draw()
        self.det_title.set_text(f"Wallhaven {w.id}"); self.det_meta.set_text(f"{w.resolution}  ·  {human(w.file_size)}  ·  {w.file_type.split('/')[-1].upper()}\n{w.views:,} views  ·  ★ {w.favorites:,}")
        self.det_by.set_text("Loading details…"); self.det_status.set_text(""); self._det_tags([]); self.det_src.set_visible(False)
        self.wh_stack.set_visible_child_name("detail")
        cl = self._client()
        in_thread(lambda: GdkPixbuf.Pixbuf.new_from_file(cl.thumb(w, "large")), self._det_pixbuf_done(w))
        def info_done(full, e):
            if self._det.id != w.id: return
            if e or not full: self.det_by.set_text(w.attribution if not e else friendly(e)); return
            self._det = full; self.det_by.set_text(full.attribution); self._det_tags(full.tags[:14])
            self._wh["seen_tags"] = list(dict.fromkeys(self._wh["seen_tags"] + full.tags))[-300:]
            if full.source: self.det_src.set_uri(full.source); self.det_src.set_visible(True)
        in_thread(lambda: cl.info(w.id), info_done)

    def _det_pixbuf_done(self, w):
        def cb(pb, e):
            if pb is not None and self._det.id == w.id:
                self.det_pb = pb; self.det_img.queue_draw()
        return cb

    def _det_tags(self, tags):
        for c in self.det_tags.get_children(): self.det_tags.remove(c)
        for t in tags:
            b = Gtk.Button(label=t); b.get_style_context().add_class("wp-chip")
            b.connect("clicked", lambda _b, t=t: (self.wh_stack.set_visible_child_name("browse"), self.wh_entry.set_text(t), self._wh_search(reset=True)))
            self.det_tags.add(b)
        self.det_tags.show_all()

    def _wh_open_web(self, *a):
        url = self._det.url
        try: wallhaven.check_url(url); subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except (OSError, wallhaven.WallhavenError): self.det_status.set_text("Could not open the browser. The address is " + url)

    def _wh_do(self, what):
        w = self._det; cl = self._client()
        for b in (self.det_set, self.det_dl, self.det_add): b.set_sensitive(False)
        self.det_status.set_text("Downloading…")
        def prog(got, total): GLib.idle_add(lambda: self.det_status.set_text(f"Downloading… {got * 100 // total}%" if total else f"Downloading… {human(got)}") or False)
        def run():
            p = cl.download(w, progress=prog)
            if what == "add":
                if "Wallhaven picks" not in state.load()["collections"]: state.collection_new("Wallhaven picks")
                state.collection_add("Wallhaven picks", p)
            if what == "set": apply.set_wallpaper(p)
            return p
        def done(p, e):
            for b in (self.det_set, self.det_dl, self.det_add): b.set_sensitive(True)
            if e: self.det_status.set_text(friendly(e)); return
            short = p.replace(paths.home(), "~")
            self.det_status.set_text({"set": "Set as your wallpaper. Saved to " + short, "download": "Saved to " + short, "add": "Saved to " + short + " and added to the “Wallhaven picks” collection."}[what])
            if what == "set": self._last_wp = p; self.refresh_current(); self.emit("wallpaper-set", p)
            if getattr(self, "_local_items", None) is not None: self._load_local()
        in_thread(run, done)


def imageinfo_dims(p):
    from . import imageinfo
    return imageinfo.oriented_dimensions(p) if p and os.path.isfile(p) else None


# ----- standalone window ------------------------------------------------------------------------------------------------
class WallpaperWindow(Gtk.ApplicationWindow):
    def __init__(self, app, tab="carpatic", size=(980, 760)):
        super().__init__(application=app, title="Wallpapers")
        self.set_default_size(*size)
        hb = Gtk.HeaderBar(show_close_button=True, title="Wallpapers"); self.set_titlebar(hb)
        ov = Gtk.Overlay(); self.add(ov)
        self.browser = WallpaperBrowser(tab=tab); self.browser.set_margin_start(20); self.browser.set_margin_end(20); self.browser.set_margin_top(16); self.browser.set_margin_bottom(16)
        ov.add(self.browser)
        self.toast = Gtk.Label(); self.toast.get_style_context().add_class("wp-warn"); self.toast.set_valign(Gtk.Align.END); self.toast.set_halign(Gtk.Align.CENTER); self.toast.set_margin_bottom(28); self.toast.set_no_show_all(True)
        ov.add_overlay(self.toast); self._tt = None
        self.browser.connect("toast", self._show_toast)
        self.add_accel_group(Gtk.AccelGroup())
        self.connect("key-press-event", self._key)

    def _show_toast(self, b, msg):
        self.toast.set_text(msg); self.toast.show()
        if self._tt: GLib.source_remove(self._tt)
        self._tt = GLib.timeout_add_seconds(4, lambda: (self.toast.hide(), setattr(self, "_tt", None), False)[2])

    def _key(self, w, e):
        if e.state & Gdk.ModifierType.CONTROL_MASK:
            k = {Gdk.KEY_1: "carpatic", Gdk.KEY_2: "mine", Gdk.KEY_3: "wallhaven", Gdk.KEY_4: "colours"}.get(e.keyval)
            if k: self.browser.tab_btns[k].set_active(True); return True
            if e.keyval == Gdk.KEY_f: self.browser.tab_btns["wallhaven"].set_active(True); self.browser.wh_entry.grab_focus(); return True
        if e.keyval == Gdk.KEY_Escape and self.browser.stack.get_visible_child_name() == "wallhaven" and self.browser.wh_stack.get_visible_child_name() == "detail":
            self.browser.wh_stack.set_visible_child_name("browse"); return True
        return False
