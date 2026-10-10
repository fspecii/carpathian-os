"""Appearance: everything about how Carpatic LOOKS. The desktop style preset, light/dark, accent, the colour theme gallery (same cards as the Welcome and the keyboard
theme picker), wallpaper, fonts, icon packs, cursors, window buttons, window corners/borders/gaps. Everything goes through the CLI (carpatic-theme, carpatic-appearance,
carpatic-profile, carpatic-pack) so scripts and the GUI stay equivalent. Behaviour (bar/dock design and position, window layout) lives in Desktop & Dock."""
import os, math, sys
import gi
gi.require_version("Pango", "1.0"); gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, Gdk, GLib, Pango
from .. import sysutil as su, ui, theme
from ..app import Page
from ..ui import *
from ..preview import rgb, profile_conf
for _p in (os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "..", "..", "configurator", "lib"), "/usr/local/lib/carpatic", "/usr/lib/carpatic"):
    if os.path.isdir(_p) and _p not in sys.path: sys.path.append(_p)
import carpatic_looks as looks

ACCENTS = [("spruce", "Spruce", "#5cc8a8", "#16806a"), ("glacier", "Glacier", "#6cb4f0", "#1e6fb8"), ("dusk", "Dusk", "#a99bf0", "#6a4fd0"),
           ("rose", "Rose", "#f08aa8", "#c2386a"), ("ember", "Ember", "#f2a65a", "#b8640f"), ("moss", "Moss", "#a3d36b", "#4f8a1c")]

def theme_label(t): return {"carpatic": "Carpatic", "carpatic-light": "Carpatic Light"}.get(t, t.replace("-", " ").title())

def draw_mode_tile(cr, W, H, c, selected=False):
    r = 8
    cr.new_sub_path(); cr.arc(W - r, r, r, -math.pi / 2, 0); cr.arc(W - r, H - r, r, 0, math.pi / 2); cr.arc(r, H - r, r, math.pi / 2, math.pi); cr.arc(r, r, r, math.pi, 1.5 * math.pi); cr.close_path(); cr.clip()
    cr.set_source_rgb(*rgb(theme.mix(c.get("background", "#000"), c.get("accent", "#888"), 0.35))); cr.paint()
    cr.set_source_rgb(*rgb(theme.mix(c.get("background", "#000"), c.get("accent", "#888"), 0.18))); cr.rectangle(0, H * 0.6, W, H * 0.4); cr.fill()
    wx, wy, ww, wh = W * 0.16, H * 0.2, W * 0.68, H * 0.62
    cr.set_source_rgb(*rgb(c.get("background", "#000"))); cr.rectangle(wx, wy, ww, wh); cr.fill()
    cr.set_source_rgb(*rgb(c.get("lighter_background", "#444"))); cr.rectangle(wx, wy, ww, 10); cr.fill()
    for i, col in enumerate(("red", "yellow", "green")):
        cr.set_source_rgb(*rgb(c.get(col, "#888"))); cr.arc(wx + 8 + i * 9, wy + 5, 2.5, 0, 6.3); cr.fill()
    cr.set_source_rgba(*rgb(c.get("foreground", "#fff")), 0.7)
    cr.rectangle(wx + 8, wy + 20, ww * 0.5, 4); cr.fill(); cr.rectangle(wx + 8, wy + 30, ww * 0.35, 4); cr.fill()
    cr.set_source_rgb(*rgb(c.get("accent", "#888"))); cr.rectangle(wx + 8, wy + 42, 26, 8); cr.fill()

def current_btn_style(st):
    return st.get("WINDOW_BUTTONS") or profile_conf(st.get("PROFILE", "tiling"), "TITLEBAR_STYLE", "windows")

def look_vals(st=None):
    st = st or su.settings(); prof = st.get("PROFILE", "tiling"); d = {}
    for key, env, dflt in (("corners", "CORNER_RADIUS", 0), ("inner-gap", "INNER_GAP", 8), ("outer-gap", "OUTER_GAP", 8), ("border-width", "BORDER_WIDTH", 2), ("border-highlight", "BORDER_HIGHLIGHT", 0)):
        v = st.get(env) or profile_conf(prof, env) or dflt
        try: d[key] = int(v)
        except ValueError: d[key] = dflt
    d["smart"] = (st.get("SMART_GAPS") or profile_conf(prof, "SMART_GAPS") or "0") == "1"
    return d

class AppearancePage(Page):
    order = 1
    id = "appearance"; title = "Appearance"; icon = "applications-graphics"; color = "#5e5ce6"; group = 2
    aliases = ("style", "colours", "colors", "fonts", "icons", "cursors", "theme", "themes", "buttons", "windowlook")
    keywords = "look theme dark light mode accent colour color style preset desktop windows macos ubuntu tiling fonts icons cursor window buttons corners borders gaps picker"
    sub = "How Carpatic looks. Changes apply at once and are kept after a restart."
    entries = (("Desktop style", "preset profile windows macos ubuntu zen kylin tiling beginner layout look", "style"), ("Light or dark", "mode night day", "mode"), ("Accent colour", "highlight color", "accent"),
               ("Colour theme", "palette nord gruvbox catppuccin themes swatches", "themes"), ("Browse themes", "theme picker live preview arrow keys keyboard", "picker"),
               ("App colours", "gtk qt follow colours terminal editors browser app theme", "appcolours"), ("Wallpaper", "background picture image", "wallpaper-link"),
               ("Fonts", "typeface text size hinting antialiasing subpixel", "fonts"), ("Icon pack", "icons papirus", "icons"), ("Cursor", "pointer mouse size", "cursors"),
               ("Window buttons", "close minimise maximise macos windows traffic lights position left right", "window-buttons"), ("Corners, borders and gaps", "rounded window corners border width gap spacing zen compact highlight smart gaps", "window-shape"))
    optional = frozenset({"picker"})
    def open_sub(self, name):
        {"colours": self.sub_appcolours, "colors": self.sub_appcolours, "fonts": self.sub_fonts, "icons": self.sub_icons, "cursors": self.sub_cursors,
         "buttons": self.sub_buttons, "windowlook": self.sub_shape}.get(name, lambda: None)()
    def sub_appcolours(self): self.push("App colours", self.build_appcolours)
    def sub_fonts(self): self.push("Fonts", self.build_fonts)
    def sub_icons(self): self.push("Icon packs", self.build_icons)
    def sub_cursors(self): self.push("Cursors", self.build_cursors)
    def sub_buttons(self): self.push("Window buttons", self.build_buttons)
    def sub_shape(self): self.push("Corners, borders and gaps", self.build_shape)

    def state(self):
        s = su.settings(); t = s.get("THEME", "carpatic"); c = theme.read_colors(t)
        return s, t, c.get("mode", "dark")
    def build(self, pb):
        self.pb = pb; s, t, mode = self.state()
        # 1. the desktop style preset
        g2 = pb.group("Desktop style", "A style preset sets the dock or bar, the window buttons and the shortcuts. Era presets also select their matching colour theme. Change the dock, buttons or layout later in Desktop & Dock.", key="style")
        self.style_gal = looks.LookGallery(self.win.pal, cols=3, preview_w=232, on_pick=self.on_style)
        for pid, name, desc in looks.style_choices():
            png = os.path.join(su.SHARE, "profiles", f"{pid}.preview-{mode}.png")
            self.style_gal.add_item(pid, name, desc, looks.painter_mock(t, pid, s, png if os.path.isfile(png) else None))
        g2.add_plain(self.style_gal, "style", setting="PROFILE")
        self.missing_row = ButtonRow("Get the full look", "", "Download", None, "suggested", key="fulllook"); g2.add(self.missing_row); self.missing_row.hide(); self.missing_row.set_no_show_all(True)
        g2.add(NavRow("Dock, buttons and window layout", "Choose the bar or dock design and how windows behave", "preferences-desktop-wallpaper", "#ff9f0a", "", lambda: self.win.open_page("desktop"), key="to-desktop"))
        # 2. light / dark and accent
        g = pb.group("Colour")
        self.mode_gal = Gallery(2, self.on_mode); self.mode_gal.set_halign(Gtk.Align.START); self.mode_gal.set_homogeneous(False)
        for m, name in (("light", "Light"), ("dark", "Dark")):
            c = theme.read_colors("carpatic-light" if m == "light" else "carpatic") or dict(theme.FALLBACK[m])
            da = Gtk.DrawingArea(); da.set_size_request(132, 84); da.connect("draw", lambda w, cr, c=c: (draw_mode_tile(cr, w.get_allocated_width(), w.get_allocated_height(), c), False)[1])
            da.set_halign(Gtk.Align.CENTER); self.mode_gal.add_item(m, name, "", da)
        g.add(CustomRow(self.mode_gal, key="mode", setting="THEME:mode"))
        self.accent = ColorRow("Accent colour", "Buttons, selections and highlights", [], None, self.on_accent, key="accent", setting="ACCENT"); g.add(self.accent)
        # 3. the colour theme gallery + the keyboard picker
        g3 = pb.group("Colour theme", "Every theme recolours the bars, apps, terminal and more. Click one to try it now.", key="themes")
        self.theme_gal = looks.LookGallery(self.win.pal, cols=4, preview_w=148, on_pick=self.on_theme); self.fill_themes(s, t, mode)
        g3.add_plain(self.theme_gal, "themes", setting="THEME")
        g3b = pb.group()
        if su.which("carpatic-theme-picker"):
            g3b.add(ButtonRow("Browse themes", "Try themes, wallpapers and window shapes live with the arrow keys. Super + Ctrl + Shift + Space", "Open", lambda: su.spawn("carpatic-theme-picker"), key="picker"))
        self.nav_apps = NavRow("App colours", "Which apps follow the theme, and the GTK app theme", "preferences-desktop-theme", "#ff9f0a", "", self.sub_appcolours, key="appcolours"); g3b.add(self.nav_apps)
        # 4. wallpaper, text and icons, windows
        g4 = pb.group("Wallpaper, text and icons")
        self.nav_wall = NavRow("Wallpaper", "Pictures, Wallhaven and colours", "image-x-generic", "#af52de", "", lambda: self.win.open_page("wallpaper"), key="wallpaper-link")
        self.nav_fonts = NavRow("Fonts", "Typefaces, sizes and sharpness", "font-x-generic", "#5ac8fa", "", self.sub_fonts, key="fonts")
        self.nav_icons = NavRow("Icon pack", "How apps and folders look", "folder", "#34c759", "", self.sub_icons, key="icons")
        self.nav_cur = NavRow("Cursor", "Pointer theme and size", "input-mouse", "#8e8e93", "", self.sub_cursors, key="cursors")
        g4.add(self.nav_wall, self.nav_fonts, self.nav_icons, self.nav_cur)
        g5 = pb.group("Windows")
        self.nav_btn = NavRow("Window buttons", "Close, minimise and maximise: style and side", "window-close", "#ff453a", "", self.sub_buttons, key="window-buttons")
        self.nav_shape = NavRow("Corners, borders and gaps", "Rounded corners, border width and the space between windows", "view-fullscreen", "#0a84ff", "", self.sub_shape, key="window-shape")
        g5.add(self.nav_btn, self.nav_shape)
        self.refresh()
    def fill_themes(self, s, t, mode):
        self.theme_gal.clear(); self.theme_mode = mode
        st = {k: v for k, v in s.items() if k != "ACCENT"}   # each theme shows its own accent
        for tid, name, c in looks.theme_choices(mode):
            self.theme_gal.add_item(tid, name, "", looks.painter_mock(tid, s.get("PROFILE", "tiling"), st))
        self.theme_gal.select(t); self.theme_gal.show_all()
    def on_external_change(self): self.refresh()
    def on_show(self):
        if self.pb: self.refresh()
    def refresh(self):
        s, t, mode = self.state(); ae = su.read_env(os.path.join(su.CFG, "appearance.env"))
        self.style_gal.set_palette(self.win.pal); self.theme_gal.set_palette(self.win.pal)
        self.mode_gal.guard = True; self.mode_gal.select(mode); self.mode_gal.guard = False
        if getattr(self, "theme_mode", mode) != mode: self.fill_themes(s, t, mode)
        self.theme_gal.select(t)
        cur = s.get("ACCENT", "") or theme.read_colors(t).get("accent", "")
        cols = [(n, dk if mode == "dark" else lt, name) for n, name, dk, lt in ACCENTS]
        self.accent.guard = True
        for cid, b in list(self.accent.btns.items()): self.accent.sw.remove(b)
        self.accent.btns = {}; self.accent.colors = cols
        for cid, hx, name in cols:
            b = Gtk.Button(); b.set_relief(Gtk.ReliefStyle.NONE); ui.cls(b, "swatch"); b.set_tooltip_text(name); ui.set_a11y(b, name)
            p = Gtk.CssProvider(); p.load_from_data(f"button.swatch {{ background-color: {hx}; background-image: none; }}".encode()); b.get_style_context().add_provider(p, Gtk.STYLE_PROVIDER_PRIORITY_USER + 3)
            b.connect("clicked", self.accent._pick, cid); self.accent.btns[cid] = b; self.accent.sw.pack_start(b, False, False, 0)
        sel = next((cid for cid, hx, n in cols if hx.lower() == cur.lower()), None)
        self.accent.value = sel; self.accent._mark(); self.accent.sw.show_all(); self.accent.guard = False
        self.style_gal.guard = True; self.style_gal.select(s.get("PROFILE", "tiling")); self.style_gal.guard = False
        wp = ""
        try:
            with open(os.path.join(su.CFG, "wallpaper")) as f: wp = os.path.basename(f.read().strip())
        except OSError: pass
        self.nav_wall.set_value(wp); self.nav_apps.set_value("")
        self.nav_fonts.set_value((ae.get("UI_FONT", "") or "").rsplit(" ", 1)[0])
        self.nav_icons.set_value(ae.get("ICON_THEME", "") or "Style default")
        self.nav_cur.set_value(s.get("CURSOR_THEME") or ae.get("CURSOR_THEME", "") or "Style default")
        self.nav_btn.set_value(current_btn_style(s).title()); lv = look_vals(s); self.nav_shape.set_value(f"{lv['corners']} px corners")
        self.check_pack(s.get("PROFILE", "tiling"))
    def check_pack(self, cur):
        ids = (profile_conf(cur, "PACKS") or "").split()
        if not ids or not su.which("carpatic-pack"): self.missing_row.hide(); return
        def work(): return [r.split("\t") for r in su.lines("carpatic-pack", "list")]
        def done(rows):
            if isinstance(rows, Exception): return
            miss = [r for r in rows if len(r) > 7 and r[0] in ids and r[3] == "0"]
            if not miss: self.missing_row.hide(); return
            dl = sum(float(r[7] or 0) for r in miss)
            self.missing_row.set_title(f"Get the full look"); self.missing_row.set_sub(f"{', '.join(r[2] for r in miss)} ({dl:.1f} MB to download)")
            self.missing_row.buttons[0].disconnect_by_func if False else None
            for b in self.missing_row.buttons: b.destroy()
            todo = [(r[0], r[2], r[6]) for r in miss]
            self.missing_row.buttons = []; self.missing_row.add_button("Download", lambda: su.install_packs(self.win, todo, "Getting the full look", lambda ok: self.refresh(), apply_after=True), "suggested")
            self.missing_row.set_no_show_all(False); self.missing_row.show_all()
        su.bg(work, done)
    # ---- handlers
    def on_mode(self, m):
        s, t, mode = self.state()
        if mode == m: return
        self.win.apply("carpatic-theme", "set", "carpatic-light" if m == "light" else "carpatic", "--accent", "default", msg="Switching to " + m + "...", done=lambda *_: self.refresh())
    def on_accent(self, cid):
        s, t, mode = self.state(); col = next(((dk if mode == "dark" else lt) for n, name, dk, lt in ACCENTS if n == cid), None)
        if col: self.win.apply("carpatic-theme", "set", t, "--accent", col, msg="Changing the accent...", done=lambda *_: self.refresh())
    def on_style(self, pid):
        if pid == su.settings().get("PROFILE", "tiling"): return
        self.win.apply("carpatic-profile", "set", pid, msg="Switching style (the bars restart, a few seconds)...", done=lambda *_: self.refresh())

    # ================= App colours sub-page =================
    def build_appcolours(self, pb):
        s, t, mode = self.state()
        a = pb.group("Also colour", "The desktop, launcher and notifications always follow the theme. Choose which other apps follow it too.")
        on = (s.get("ALSO") or "terminal editors browser qt cli").split(); self.also = {}
        for k, lab, sub in (("terminal", "Terminal", "kitty, foot, alacritty and open terminals"), ("editors", "Code editors", "VS Code, VSCodium and Helix"), ("browser", "Web browser", "Chromium and Firefox (restart the browser)"),
                            ("qt", "Qt apps", "Through Kvantum"), ("cli", "Command-line tools", "btop, tmux, bat, fzf and friends")):
            r = SwitchRow(lab, sub, k in on, lambda v: self.on_also(), key="also-" + k, setting="ALSO:" + k); self.also[k] = r; a.add(r)
        gt = pb.group("App theme (GTK)", "\u201cFollow colours\u201d recolours GTK apps with the theme. Native themes keep their own look.")
        self.gtk_row = PopupRow("GTK theme", "", [("", "Style default"), ("palette", "Follow colours (recommended)")], s.get("GTK_THEME", "") or "", self.on_gtk, key="gtk", setting="GTK_THEME")
        gt.add(self.gtk_row)
        def work(): return [t for t in su.lines("carpatic-appearance", "list", "gtk") if t != "palette"]
        su.bg(work, lambda r: None if isinstance(r, Exception) else self.gtk_row.set_options([("", "Style default"), ("palette", "Follow colours (recommended)")] + [(x, x) for x in r], s.get("GTK_THEME", "") or ""))
        self.packs_group(pb, "gtk")
    def on_theme(self, tn):
        self.win.apply("carpatic-theme", "set", tn, msg="Applying the theme...", done=lambda *_: (self.theme_gal.select(tn), self.refresh()))
    def on_also(self):
        on = [k for k, r in self.also.items() if r.get_value()]
        self.win.apply("carpatic-theme", "also", *(on or ["none"]), msg="Updating which apps follow the theme...")
    def on_gtk(self, v): self.win.apply("carpatic-appearance", "set", "gtk", v or "default", msg="Applying the app theme...")

    # ================= Window buttons and window shape (moved here from Desktop & Dock: they are looks) =================
    def build_buttons(self, pb):
        st = su.settings()
        g2 = pb.group("Style", "How the close, minimise and maximise buttons look. Changing the desktop style resets them to that style's usual buttons.")
        self.btn_gal = Gallery(3, lambda sid: self.win.apply("carpatic-appearance", "set", "window-buttons", sid, msg="Applying window buttons...", done=lambda *_: self.refresh_look()))
        try:
            from carpatic_buttons import STYLES, draw_card
            for sid, lab, desc in STYLES:
                da = Gtk.DrawingArea(); da.set_size_request(168, 84); da.connect("draw", lambda w, cr, sid=sid: self.draw_btn(w, cr, sid, draw_card)); da.set_halign(Gtk.Align.CENTER)
                self.btn_gal.add_item(sid, lab, desc, da)
        except ImportError: pass
        g2.add_plain(self.btn_gal, "buttons", setting="WINDOW_BUTTONS")
        g3 = pb.group()
        self.side = PopupRow("Button position", "", [("auto", "Style default"), ("left", "Left"), ("right", "Right")], st.get("BUTTONS_SIDE") or "auto", lambda v: self.win.apply("carpatic-appearance", "set", "buttons-side", v, msg="Applying...", done=lambda *_: self.refresh_look()), key="buttons-side", setting="BUTTONS_SIDE")
        self.shown = PopupRow("Show buttons", "", [("all", "Close, minimise and maximise"), ("close", "Only close")], st.get("BUTTONS_SHOWN") or "all", lambda v: self.win.apply("carpatic-appearance", "set", "buttons-shown", v, msg="Applying...", done=lambda *_: self.refresh_look()), key="buttons-shown", setting="BUTTONS_SHOWN")
        g3.add(self.side, self.shown); self.refresh_look()
    def draw_btn(self, w, cr, sid, draw_card):
        st = su.settings(); dark = theme.read_colors("carpatic") or dict(theme.FALLBACK["dark"]); light = theme.read_colors("carpatic-light") or dict(theme.FALLBACK["light"])
        if st.get("ACCENT"): dark["accent"] = light["accent"] = st["ACCENT"]
        try: draw_card(cr, w.get_allocated_width(), w.get_allocated_height(), sid, dark, light, st.get("BUTTONS_SIDE") or "auto", st.get("BUTTONS_SHOWN") or "all")
        except Exception: pass
    def build_shape(self, pb):
        st = su.settings(); lv = look_vals(st); self.guard = True
        g = pb.group("Window shape", "Borders, rounded corners and the space between tiled windows. Changes apply live.")
        self.look_prev = Gtk.DrawingArea(); self.look_prev.set_size_request(-1, 150); self.look_prev.connect("draw", self.on_look_draw)
        g.add(CustomRow(self.look_prev, key="look"))
        self.presets = Segmented([("default", "Style default"), ("zen", "Zen"), ("compact", "Compact")], None, lambda n: self.win.apply("carpatic-appearance", "look", n, msg="Applying window look...", done=lambda *_: self.refresh_look()))
        g.add(CustomRow(self.presets, key="presets", pad=12))
        self.spins = {}
        for key, env, lab, sub, lo, hi in (("corners", "CORNER_RADIUS", "Corner radius", "Rounded window corners (needs the compositor)", 0, 20), ("inner-gap", "INNER_GAP", "Gap between windows", "", 0, 60),
                                           ("outer-gap", "OUTER_GAP", "Gap to the screen edge", "", 0, 60), ("border-width", "BORDER_WIDTH", "Border width", "", 0, 8), ("border-highlight", "BORDER_HIGHLIGHT", "Highlight", "Extra border on the focused window", 0, 6)):
            r = SpinRow(lab, sub, lo, hi, 1, lv[key], lambda v, k=key: self.on_look(k, int(v)), "px", key=key, setting=env); self.spins[key] = r; g.add(r)
        self.smart = SwitchRow("No gaps with a single window", "", lv["smart"], lambda v: self.win.apply("carpatic-appearance", "set", "smart-gaps", "1" if v else "0", msg="Applying window look...", done=lambda *_: self.refresh_look()), key="smart-gaps", setting="SMART_GAPS"); g.add(self.smart)
        self.cols = {}
        for key, env, lab in (("border-active", "BORDER_ACTIVE", "Focused window border"), ("border-inactive", "BORDER_INACTIVE", "Other windows border")):
            r = Row(lab, "", key=key, setting=env); cb = Gtk.ColorButton(); cb.set_use_alpha(False); cb.connect("color-set", self.on_color, key)
            rb = Gtk.Button(label="Use the theme"); rb.connect("clicked", lambda _b, k=key: self.win.apply("carpatic-appearance", "set", k, "default", msg="Applying...", done=lambda *_: self.refresh_look()))
            r.ctl.pack_start(cb, False, False, 0); r.ctl.pack_start(rb, False, False, 0); self.cols[key] = cb; g.add(r); ui.set_a11y(cb, lab)
        self.guard = False; self.refresh_look()
    def on_look(self, key, v):
        if getattr(self, "guard", False): return
        self.win.apply("carpatic-appearance", "set", key, str(v), msg="Applying window look...", done=lambda *_: self.refresh_look()); self.look_prev.queue_draw()
    def on_color(self, cb, key):
        c = cb.get_rgba(); hx = "#%02x%02x%02x" % (round(c.red * 255), round(c.green * 255), round(c.blue * 255))
        self.win.apply("carpatic-appearance", "set", key, hx, msg="Applying...", done=lambda *_: self.refresh_look())
    def refresh_look(self):
        st = su.settings(); lv = look_vals(st); self.guard = True
        if hasattr(self, "spins") and self.spins and self.spins[next(iter(self.spins))].get_parent() is not None:
            for k, r in self.spins.items(): r.set_value_quiet(lv[k])
            self.smart.set_value_quiet(lv["smart"]); pal = theme.read_colors(st.get("THEME", "carpatic"))
            for k, env, d in (("border-active", "BORDER_ACTIVE", pal.get("accent", "#81a1c1")), ("border-inactive", "BORDER_INACTIVE", pal.get("lighter_background", "#3b4252"))):
                c = Gdk.RGBA(); c.parse(st.get(env) or d); self.cols[k].set_rgba(c)
            self.look_prev.queue_draw()
        if hasattr(self, "btn_gal") and self.btn_gal.get_parent() is not None:
            self.btn_gal.select(current_btn_style(st))
            for ch in self.btn_gal.get_children(): ch.queue_draw()
            self.side.set_value_quiet(st.get("BUTTONS_SIDE") or "auto"); self.shown.set_value_quiet(st.get("BUTTONS_SHOWN") or "all")
        self.guard = False
        self.refresh()
    def on_look_draw(self, w, cr):
        v = {k: int(r.spin.get_value()) for k, r in self.spins.items()}; st = su.settings()
        pal = theme.read_colors(st.get("THEME", "carpatic")); acc = st.get("BORDER_ACTIVE") or pal.get("accent", "#81a1c1"); ina = st.get("BORDER_INACTIVE") or pal.get("lighter_background", "#3b4252")
        W, H = w.get_allocated_width(), w.get_allocated_height(); k = 0.6
        def col(h, a=1.0): r, g, b = rgb(h); cr.set_source_rgba(r, g, b, a)
        def rr(x, y, ww, hh, r):
            r = max(0, min(r, ww / 2, hh / 2)); cr.new_sub_path(); cr.arc(x + ww - r, y + r, r, -math.pi / 2, 0); cr.arc(x + ww - r, y + hh - r, r, 0, math.pi / 2); cr.arc(x + r, y + hh - r, r, math.pi / 2, math.pi); cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi); cr.close_path()
        rr(0, 0, W, H, 8); cr.clip()
        col(theme.mix(pal.get("background", "#2e3440"), pal.get("accent", "#888888"), 0.25)); cr.paint()
        og, ig, r, bw, hl = v["outer-gap"] * k, v["inner-gap"] * k, v["corners"] * k, max(1, v["border-width"] * k), v["border-highlight"] * k
        cw = (W - 2 * og - ig) / 2; ch = H - 2 * og
        for i, focused in enumerate((False, True)):
            x = og + i * (cw + ig); y = og; b = bw + (hl if focused else 0); rad = min(r, cw / 2, ch / 2)
            col(acc if focused else ina); rr(x, y, cw, ch, rad); cr.fill()
            col(pal.get("background", "#2e3440")); ri = max(0, rad - b); rr(x + b, y + b, cw - 2 * b, ch - 2 * b, ri); cr.fill()
            col(pal.get("lighter_background", "#3b4252")); cr.rectangle(x + b + ri / 2, y + b, cw - 2 * b - ri, 12); cr.fill()
        return False

    def after_pack(self, ok, cat):
        """a pack arrived: refresh the main page and rebuild the sub page it was installed from so the new theme shows up"""
        self.refresh()
        if ok and len(self.win.trail) > 1:
            sub = {"icons": "icons", "fonts": "fonts", "cursors": "cursors", "gtk": "colours"}.get(cat)
            if sub: self.win.back(); GLib.timeout_add(450, lambda: (self.open_sub(sub), False)[1])
    def packs_group(self, pb, cat):
        if not su.which("carpatic-pack"): return
        g = pb.group("More to install"); g.hide(); g.set_no_show_all(True)
        def work(): return [r.split("\t") for r in su.lines("carpatic-pack", "list")]
        def done(rows):
            if isinstance(rows, Exception): return
            miss = [r for r in rows if len(r) > 7 and r[1] == cat and r[3] == "0"]
            for pid, c_, name, inst, mb, lic, kind, dl in [r[:8] for r in miss]:
                how = f"{dl} MB download" if kind != "apk" else "from Alpine, asks for your password"
                row = ButtonRow(name, f"{mb} MB on disk, {how}, {lic}", "Install", None, key="pack-" + pid)
                row.buttons[0].connect("clicked", lambda b, pid=pid, name=name, kind=kind: su.install_packs(self.win, [(pid, name, kind)], f"Installing {name}", lambda ok, cat=cat: self.after_pack(ok, cat)))
                g.add(row)
            if miss: g.set_no_show_all(False); g.show_all()
        su.bg(work, done)

    # ================= Fonts =================
    def build_fonts(self, pb):
        ae = su.read_env(os.path.join(su.CFG, "appearance.env")); s = su.settings()
        self.fguard = True
        fonts = [f for f in su.lines("carpatic-appearance", "list", "fonts")] or ["Inter", "JetBrains Mono"]
        def font_opts(cur): return [(f, f) for f in fonts] + ([(cur, cur)] if cur and cur not in fonts else [])
        uf = ae.get("UI_FONT", "Sans 10"); mf = ae.get("MONO_FONT", "Monospace 10")
        ucur, usz = (uf.rsplit(" ", 1) + ["10"])[:2] if " " in uf else (uf, "10"); mcur, msz = (mf.rsplit(" ", 1) + ["10"])[:2] if " " in mf else (mf, "10")
        g0 = pb.group()
        self.sample = Gtk.Label(label="The quick brown fox jumps over the lazy dog 0123456789", xalign=0, wrap=True)
        self.sample2 = Gtk.Label(label="$ carpatic-theme set carpatic  # {}[]() 0O1lI", xalign=0)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); box.pack_start(self.sample, False, False, 0); box.pack_start(self.sample2, False, False, 0)
        g0.add(CustomRow(box, key="fsample"))
        self.apply_sample(uf, mf)
        presets = [("", "Choose a pairing...")]
        for p in su.lines("carpatic-appearance", "list", "presets"):
            parts = p.split("|")
            if len(parts) == 4: presets.append((parts[0], parts[3]))
        g1 = pb.group("Typefaces")
        r_pre = PopupRow("Pairing", "Interface and monospace font together", presets, "", lambda v: v and self.win.apply("carpatic-appearance", "preset", v, msg="Applying fonts...", done=lambda *_: self.refresh_fonts()), key="f-pairing"); g1.add(r_pre)
        self.r_ui = PopupRow("Interface font", "Bars, launcher, notifications and apps", font_opts(ucur), ucur, lambda v: self.fset("ui-font", v), key="f-ui", setting="UI_FONT")
        self.r_uis = SpinRow("Interface size", "", 8, 20, 1, int(usz) if usz.isdigit() else 10, lambda v: self.fset("ui-size", str(int(v))), "pt", key="f-uis", setting="UI_SIZE")
        self.r_m = PopupRow("Monospace font", "Terminal and code", font_opts(mcur), mcur, lambda v: self.fset("mono-font", v), key="f-mono", setting="MONO_FONT")
        self.r_ms = SpinRow("Monospace size", "", 8, 20, 1, int(msz) if msz.isdigit() else 10, lambda v: self.fset("mono-size", str(int(v))), "pt", key="f-monos", setting="MONO_SIZE")
        g1.add(self.r_ui, self.r_uis, self.r_m, self.r_ms)
        g2 = pb.group("Text rendering", "Terminals and the tiling bar pick up a new font for newly opened windows or the next login. Scale applies to windows, bars, apps, text and cursors; open apps such as a browser need a restart.")
        self.r_scale = PopupRow("Scale", su.scale_status() or "Make everything bigger on high-resolution screens", su.SCALE_CHOICES, su.scale_value(), lambda v: self.fset("scale", v), key="f-scale")
        self.r_hint = PopupRow("Hinting", "", [("none", "None"), ("slight", "Slight (recommended)"), ("medium", "Medium"), ("full", "Full")], s.get("HINTING") or "slight", lambda v: self.fset("hinting", v), key="f-hint", setting="HINTING")
        self.r_rgba = PopupRow("Subpixel order", "Match your screen type", [("none", "Greyscale"), ("rgb", "RGB (most screens)"), ("bgr", "BGR"), ("vrgb", "Vertical RGB"), ("vbgr", "Vertical BGR")], s.get("RGBA") or "rgb", lambda v: self.fset("rgba", v), key="f-rgba", setting="RGBA")
        self.r_aa = SwitchRow("Smooth edges", "Antialiasing", (s.get("ANTIALIAS") or "1") != "0", lambda v: self.fset("antialias", "1" if v else "0"), key="f-aa", setting="ANTIALIAS")
        g2.add(self.r_hint, self.r_rgba, self.r_aa)
        g3 = pb.group()
        g3.add(ButtonRow("Reset fonts", "Go back to the style's fonts", "Reset", lambda: self.win.apply("carpatic-appearance", "set", "ui-font", "default", "ui-size", "default", "mono-font", "default", "mono-size", "default", "hinting", "default", "rgba", "default", "lcdfilter", "default", "antialias", "default", "scale", "default", msg="Resetting fonts...", done=lambda *_: self.refresh_fonts()), "destructive", key="f-reset"))
        self.packs_group(pb, "fonts"); self.fguard = False
    def apply_sample(self, uf, mf):
        try:
            n, sz = uf.rsplit(" ", 1); self.sample.override_font(Pango.FontDescription(f"{n} {int(sz) + 4}")); self.sample2.override_font(Pango.FontDescription(mf))
        except Exception: pass
    def fset(self, k, v):
        if self.fguard: return
        self.win.apply("carpatic-appearance", "set", k, v, msg="Applying fonts...", done=lambda rc, *_: (self.refresh_fonts(), su.reopen_after_scale("appearance") if k == "scale" and rc == 0 else None))
    def refresh_fonts(self):
        ae = su.read_env(os.path.join(su.CFG, "appearance.env")); self.apply_sample(ae.get("UI_FONT", "Sans 10"), ae.get("MONO_FONT", "Monospace 10")); self.refresh()

    # ================= Icons =================
    def build_icons(self, pb):
        ae = su.read_env(os.path.join(su.CFG, "appearance.env")); cur = ae.get("ICON_THEME", "")
        g = pb.group("Icon pack", "Icons are chosen independently of the desktop style.")
        self.igal = Gallery(3, lambda n: self.win.apply("carpatic-appearance", "set", "icons", n or "default", msg="Applying icons...", done=lambda *_: (self.igal.select(n), self.refresh())))
        names = [""] + su.lines("carpatic-appearance", "list", "icons"); todo = []
        for n in names:
            row = Gtk.Box(spacing=4); row.set_size_request(-1, 36); row.set_halign(Gtk.Align.CENTER)
            if not n: row.pack_start(Gtk.Label(label="Default"), False, False, 0)
            else: todo.append((n, row))
            self.igal.add_item(n, n or "Style default", "", row)
        self.igal.select(cur); g.add_plain(self.igal, "icon-gallery", setting="ICON_THEME")
        def step():
            if not todo or not self.igal.get_realized(): return bool(todo) and self.igal.get_realized() or False
            n, row = todo.pop(0); it = Gtk.IconTheme.new(); it.set_custom_theme(n)
            for ic in ("folder", "utilities-terminal", "web-browser", "preferences-system"):
                try: row.pack_start(Gtk.Image.new_from_pixbuf(it.load_icon(ic, 32, 0)), False, False, 0)
                except Exception: pass
            row.show_all(); return True
        GLib.idle_add(step, priority=GLib.PRIORITY_LOW)
        self.packs_group(pb, "icons")

    # ================= Cursors =================
    def build_cursors(self, pb):
        ae = su.read_env(os.path.join(su.CFG, "appearance.env")); s = su.settings()
        g = pb.group("Pointer", "Move the mouse over this window to see the new cursor. Apps started earlier may keep the old one until restarted.")
        themes = [("", "Style default")] + [(t, t) for t in su.lines("carpatic-appearance", "list", "cursors")]
        g.add(PopupRow("Cursor theme", "", themes, s.get("CURSOR_THEME") or "", lambda v: self.win.apply("carpatic-appearance", "set", "cursor", v or "default", msg="Applying the cursor...", done=lambda *_: self.refresh()), key="c-theme", setting="CURSOR_THEME"))
        try: sz = int(ae.get("CURSOR_SIZE", "24"))
        except ValueError: sz = 24
        g.add(SliderRow("Size", "", 16, 64, 4, sz, lambda v: self.win.apply("carpatic-appearance", "set", "cursor-size", str(int(v)), msg="Applying the cursor size..."), fmt=lambda v: f"{v:.0f}", key="c-size", setting="CURSOR_SIZE"))
        self.packs_group(pb, "cursors")

PAGES = [AppearancePage]
