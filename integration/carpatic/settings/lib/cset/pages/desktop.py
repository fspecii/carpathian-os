"""Desktop & Dock (window look, window buttons, panel/dock through carpatic-panel, widgets), Wallpaper, General (login items, startup),
Accessibility, Control Centre."""
import os, glob, math, sys
import gi
from gi.repository import Gtk, Gdk, GLib
from .. import sysutil as su, ui, theme
from ..app import Page
from ..ui import *
from ..preview import rgb, profile_conf
from . import legacy, panelcfg

def appearance_env(): return su.read_env(os.path.join(su.CFG, "appearance.env"))

def look_vals(st=None):
    st = st or su.settings(); prof = st.get("PROFILE", "tiling"); d = {}
    for key, env, dflt in (("corners", "CORNER_RADIUS", 0), ("inner-gap", "INNER_GAP", 8), ("outer-gap", "OUTER_GAP", 8), ("border-width", "BORDER_WIDTH", 2), ("border-highlight", "BORDER_HIGHLIGHT", 0)):
        v = st.get(env) or profile_conf(prof, env) or dflt
        try: d[key] = int(v)
        except ValueError: d[key] = dflt
    d["smart"] = (st.get("SMART_GAPS") or profile_conf(prof, "SMART_GAPS") or "0") == "1"
    return d

def layout_val(st=None):
    st = st or su.settings(); v = st.get("LAYOUT") or profile_conf(st.get("PROFILE", "tiling"), "LAYOUT") or "tile"
    return "float" if v == "float" else "tile"

def ws_count(st=None):
    st = st or su.settings()
    try: return max(1, min(9, int(st.get("WORKSPACES") or 4)))
    except ValueError: return 4

def current_btn_style(st):
    return st.get("WINDOW_BUTTONS") or profile_conf(st.get("PROFILE", "tiling"), "TITLEBAR_STYLE", "windows")

class DesktopPage(Page):
    order = 4
    id = "desktop"; title = "Desktop & Dock"; icon = "preferences-desktop-wallpaper"; color = "#ff9f0a"; group = 2
    aliases = ("dock", "taskbar", "panel", "windows", "widgets", "layout", "tiling", "bar")
    keywords = "bar dock taskbar panel design position size autohide hide icons labels windows layout tiling floating auto-tiling drag workspaces desktop widgets menu bar start button clock"
    sub = "How the bar or dock works and how windows behave. How they look is in Appearance."
    entries = (("Bar design", "dock taskbar panel macos windows ubuntu zorin kylin floating minimal menu bar", "panel-design"), ("Taskbar and dock", "panel position size icon autohide clock labels grouping", "panel"),
               ("Workspaces", "desktops spaces number names virtual", "workspaces"), ("Window layout", "auto-tiling floating tiling windows arrange", "layout"), ("When you drag a tiled window", "float place drag out", "drag-tiled"),
               ("Widgets", "desktop cards clock weather calendar", "widgets"), ("Restart the bar", "bar missing disappeared not showing", "panel-restart"))
    optional = frozenset({"panel-design", "panel", "widgets", "panel-restart", "layout", "drag-tiled"})
    def open_sub(self, name):
        if name == "widgets" and getattr(self, "wh", None): self.wh.open()
    def build(self, pb):
        self.pb = pb; self.guard = True; st = su.settings()
        # --- bar / dock: design, position, behaviour
        self.build_panel(pb)
        # --- window layout and behaviour
        if su.which("carpatic-layout"):
            g = pb.group("Windows", "How windows arrange themselves. The look of windows (buttons, corners, gaps) is in Appearance.")
            cur = su.out("carpatic-layout", "get") or "tile"
            self.layout = PopupRow("Window layout", "Auto-tiling arranges windows for you; floating leaves them where you put them. Super+T flips the current workspace", [("tile", "Auto-tiling"), ("float", "Floating")], cur if cur in ("tile", "float") else "tile",
                                   lambda v: self.win.apply("carpatic-layout", "set", v, msg="Changing the window layout..."), key="layout", setting="LAYOUT")
            g.add(self.layout)
            self.drag = PopupRow("When you drag a tiled window", "", [("float", "Let it float"), ("place", "Move it to a new place in the tiling")], (su.settings().get("DRAG_TILED") or "float"),
                                 lambda v: self.win.apply("carpatic-appearance", "set", "drag-tiled", v, msg="Saving..."), key="drag-tiled", setting="DRAG_TILED")
            g.add(self.drag)
        # --- widgets
        self.wh = legacy.load(self, "carpatic_widgets_pages", "WidgetsPages")
        if self.wh:
            g4 = pb.group(); g4.add(NavRow("Widgets", "Clock, calendar, weather and more on the desktop. Off by default.", "view-grid", "#5ac8fa", "", self.wh.open, key="widgets"))
        self.guard = False
    def build_panel(self, pb):
        self.panel_group = None
        if not panelcfg.available(): return
        opts, val, eff, designs = panelcfg.load()
        if not opts: return
        if designs and "design" in opts:
            mode = self.win.pal["mode"]; cur = val.get("design", designs[0][0])
            gal = Gallery(3, lambda v: self.win.apply("carpatic-panel", "set", "design", v, msg="Switching the bar...", done=lambda *_: gal.select(v)))
            for did, name in designs: gal.add_item(did, name, "", panelcfg.design_preview(did, mode))
            gal.select(cur); self.design_gal = gal
            g0 = pb.group("Bar design", "How the bar, menu and dock look. A desktop style in Appearance picks one for you; change it here any time. Your pinned apps stay.", key="panel-design"); g0.add_plain(gal, "panel-design-gallery", setting="panel.design")
        if val.get("position") in ("left", "right"):
            pb.banner("The bar is set to the side of the screen. That is not supported yet and leaves the bar in the middle of the screen. Put it back to continue.", "warn", title="The bar is in an unsupported place")
            pb.group().add(ButtonRow("Put the bar back", "Uses the design's own edge", "Put it back", lambda: self.win.apply("carpatic-panel", "set", "position", "auto", msg="Moving the bar..."), "suggested", key="panel-fix"))
        g = pb.group("Taskbar and dock", "Every setting below starts from the design's own default.", key="panel")
        self.panel_group = g
        for k, lab, sub in panelcfg.TASKBAR:
            if k == "position" and val.get("design") in panelcfg.FIXED_POSITION: continue
            r = panelcfg.make_row(self.win, k, lab, sub, opts, val, eff)
            if r is not None: g.add(r)
        rows = [panelcfg.make_row(self.win, k, lab, sub, opts, val, eff) for k, lab, sub in panelcfg.BUTTONS]
        rows = [r for r in rows if r is not None]
        if rows:
            g2 = pb.group("Bar buttons"); g2.add(*rows)
        g3 = pb.group()
        if su.which("carpatic-session"): g3.add(ButtonRow("The bar is not showing?", "Restarts the bar and the shortcuts. Your windows stay open.", "Restart the bar", lambda: self.win.restart_bar(), key="panel-restart"))
        g3.add(ButtonRow("Reset the bar", "Back to the design's defaults", "Reset", lambda: self.win.apply("sh", "-c", "for k in position size icon_size align autohide labels grouping indicator monitors theme show_search show_taskview show_widgets show_desktop tags; do carpatic-panel set $k auto >/dev/null 2>&1; done", msg="Resetting the bar..."), "destructive", key="panel-reset"))
    def on_external_change(self):
        if hasattr(self, "layout"): self.layout.set_value_quiet(su.out("carpatic-layout", "get") or "tile")
    def on_show(self): self.on_external_change()

# ---------------------------------------------------------------- Wallpaper
class WallpaperPage(Page):
    order = 6
    id = "wallpaper"; title = "Wallpaper"; icon = "image-x-generic"; color = "#af52de"; group = 2
    aliases = ("wallpapers", "background")
    keywords = "background picture image wallhaven desktop colour rotate slideshow"
    entries = (("Choose a wallpaper", "background picture image", "wp-gallery"), ("Wallhaven", "online download search", "wallhaven"), ("Rotate wallpapers", "slideshow change automatically", "rotate"), ("Choose a file", "my pictures", "file"))
    raw = True; max_width = 900
    def build(self, pb):
        wbrowser = self.embed()
        if wbrowser is not None: return wbrowser
        # fallback: the built-in gallery (themes' wallpapers + Pictures/Wallpapers)
        return self.build_fallback(pb)
    def embed(self):
        for p in (os.path.join(legacy.REPO, "wallpapers", "lib"), "/usr/local/share/carpatic/wallpapers/lib", "/usr/share/carpatic/wallpapers/lib"):
            if os.path.isdir(os.path.join(p, "carpatic_wallpapers")) and p not in sys.path: sys.path.insert(0, p)
        try:
            from carpatic_wallpapers import ui as wui
            mode = self.win.pal["mode"]; wui.install_css(mode)
            b = wui.WallpaperBrowser(); b.set_margin_start(24); b.set_margin_end(24); b.set_margin_top(8); b.set_margin_bottom(8)
            self.browser = b
            return b
        except Exception:
            import traceback; traceback.print_exc(); return None
    def build_fallback(self, pb):
        sw = Gtk.ScrolledWindow(); sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16); box.set_margin_start(32); box.set_margin_end(32); box.set_margin_bottom(24)
        box.pack_start(label("Wallpaper", "page-title"), False, False, 0)
        gal = Gallery(3, lambda f: self.set_wall(f)); items = []
        mode = theme.palette()["mode"]
        for key in ("bucegi", "retezat", "fagaras", "rodna", "apuseni", "piatra", "ceahlau", "tatra"):
            items.append((key.title(), os.path.join(su.SHARE, "wallpapers", f"{key}-{mode}.jpg")))
        items += [("Picture", f) for f in sorted(glob.glob(os.path.expanduser("~/Pictures/Wallpapers/*")))]
        from gi.repository import GdkPixbuf
        for name, f in [i for i in items if os.path.exists(i[1])]:
            img = Gtk.Image()
            try: img.set_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(f, 168, 105, True))
            except Exception: continue
            gal.add_item(f, name, "", img)
        box.pack_start(gal, False, False, 0)
        r = ButtonRow("Choose a file", "Any picture from your computer", "Choose...", self.choose, key="file"); g = GroupCard(); g.add(r); box.pack_start(g, False, False, 0)
        sw.add(Clamp(760)); sw.get_child().add(box); return sw
    def set_wall(self, f): self.win.apply("carpatic-theme", "set", su.settings().get("THEME", "carpatic"), "--wallpaper", f, msg="Setting the wallpaper...")
    def choose(self):
        d = Gtk.FileChooserDialog(title="Choose a wallpaper", transient_for=self.win, action=Gtk.FileChooserAction.OPEN); d.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Open", Gtk.ResponseType.OK)
        if d.run() == Gtk.ResponseType.OK: self.set_wall(d.get_filename())
        d.destroy()

# ---------------------------------------------------------------- Control Centre
class ControlCentrePage(Page):
    id = "controlcentre"; title = "Control Centre"; icon = "preferences-other"; color = "#8e8e93"; group = 2; order = 3
    aliases = ("quicksettings", "control")
    sub = "The status area of the bar: tray, clock, quick settings and calendar."
    keywords = "quick settings flyout toggles menu bar status tray clock calendar notification centre"
    entries = (("Open Quick Settings", "wifi bluetooth volume brightness toggles flyout", "quick"), ("Open the calendar", "notifications centre date", "calendar"), ("System tray", "status icons network volume", "panel-tray"),
               ("24-hour clock", "time format am pm", "panel-clock_24h"), ("Date under the time", "clock", "panel-date_in_clock"), ("Hover previews", "tooltips window previews", "panel-previews"))
    optional = frozenset({"quick", "calendar", "panel-tray", "panel-clock_24h", "panel-date_in_clock", "panel-previews"})
    def available(self): return panelcfg.available() and bool(su.out("carpatic-panel", "options"))
    def build(self, pb):
        opts, val, eff, designs = panelcfg.load()
        if su.which("carpatic-flyout"):
            g = pb.group("Flyouts", "The same panels open from the bar.")
            g.add(ButtonRow("Open Quick Settings", "Wi-Fi, Bluetooth, sound, brightness, power", "Open", lambda: su.spawn("carpatic-flyout", "quick"), key="quick", icon="preferences-system", color="#8e8e93"),
                  ButtonRow("Open the calendar", "Date, month view and notifications", "Open", lambda: su.spawn("carpatic-flyout", "calendar"), key="calendar", icon="x-office-calendar", color="#ff3b30"))
        rows = [panelcfg.make_row(self.win, k, lab, sub, opts, val, eff) for k, lab, sub in panelcfg.SYSTEM]
        rows = [r for r in rows if r is not None]
        if rows: pb.group("Status area").add(*rows)

# ---------------------------------------------------------------- Accessibility
class AccessibilityPage(Page):
    order = 2
    id = "accessibility"; title = "Accessibility"; icon = "preferences-desktop-accessibility"; color = "#0a84ff"; group = 2
    aliases = ("access", "a11y")
    keywords = "larger text bigger font high contrast screen reader orca keyboard sticky slow bounce mouse keys vision hearing motor"
    sub = "Make Carpatic easier to see, hear and use. Choices are kept for the next login."
    entries = (("Larger text", "bigger font size cursor", "large-text"), ("High contrast", "white on black yellow", "high-contrast"), ("Screen reader", "orca speech blind", "screen-reader"), ("On-screen keyboard", "onboard virtual typing", "keyboard"),
               ("Sticky keys", "modifiers one at a time shift ctrl", "sticky"), ("Slow keys", "brief touches", "slow"), ("Bounce keys", "double press", "bounce"), ("Mouse keys", "number pad pointer", "mousekeys"))
    def available(self): return su.which("carpatic-a11y")
    def build(self, pb):
        st = su.kv_lines("carpatic-a11y", "status"); on = lambda k: st.get(k, "off") == "on"
        A = lambda k: (lambda v: self.win.apply("carpatic-a11y", k, "on" if v else "off", msg="Applying..."))
        g = pb.group("Vision")
        g.add(SwitchRow("Larger text", "Bigger menus, buttons, terminal text and mouse pointer", on("large-text"), A("large-text"), key="large-text"),
              SwitchRow("High contrast", "White on black with yellow highlights. Switch off to get your theme back", on("high-contrast"), A("high-contrast"), key="high-contrast"),
              SwitchRow("Screen reader", "Orca reads the screen aloud. Needs sound", on("screen-reader"), A("screen-reader"), key="screen-reader"))
        g2 = pb.group("Typing and pointing")
        g2.add(SwitchRow("On-screen keyboard", "Type by clicking keys on the screen", on("onscreen-keyboard"), A("keyboard"), key="keyboard"),
               SwitchRow("Sticky keys", "Press Shift, Ctrl or Alt one key at a time instead of holding them", on("sticky-keys"), A("sticky"), key="sticky"),
               SwitchRow("Slow keys", "Ignore keys that are only touched briefly", on("slow-keys"), A("slow"), key="slow"),
               SwitchRow("Bounce keys", "Ignore a key that is pressed twice by accident", on("bounce-keys"), A("bounce"), key="bounce"),
               SwitchRow("Mouse keys", "Move the pointer with the number pad", on("mouse-keys"), A("mousekeys"), key="mousekeys"))

# ---------------------------------------------------------------- General (login items, startup)
def autostart_entries():
    """[(file id, name, enabled, system?)] from ~/.config/autostart and /etc/xdg/autostart"""
    res = {}; user = os.path.expanduser("~/.config/autostart")
    for d, sysf in (("/etc/xdg/autostart", True), (user, False)):
        for f in sorted(glob.glob(d + "/*.desktop")):
            data = {}
            try:
                for l in open(f, errors="replace"):
                    if "=" in l and not l.startswith("["):
                        k, v = l.strip().split("=", 1); data.setdefault(k, v)
            except OSError: continue
            fid = os.path.basename(f)
            prev = res.get(fid)
            hidden = data.get("Hidden") == "true" or data.get("X-GNOME-Autostart-enabled") == "false"
            if data.get("NoDisplay") == "true" and sysf and not prev: pass
            name = data.get("Name") or (prev[1] if prev else fid[:-8])
            res[fid] = (fid, name, not hidden, sysf and not (prev and not prev[3]))
    return sorted(res.values(), key=lambda t: t[1].lower())

def set_autostart(fid, enabled):
    user = os.path.expanduser("~/.config/autostart"); os.makedirs(user, exist_ok=True); path = os.path.join(user, fid)
    src = os.path.join("/etc/xdg/autostart", fid); lines = []
    base = path if os.path.exists(path) else (src if os.path.exists(src) else None)
    if base:
        for l in open(base, errors="replace"):
            if not l.startswith(("Hidden=", "X-GNOME-Autostart-enabled=")): lines.append(l.rstrip("\n"))
    else: lines = ["[Desktop Entry]", "Type=Application", f"Name={fid[:-8]}"]
    lines.append("Hidden=" + ("false" if enabled else "true"))
    open(path, "w").write("\n".join(lines) + "\n")

class GeneralPage(Page):
    order = 0
    id = "general"; title = "General"; icon = "preferences-system"; color = "#8e8e93"; group = 2
    aliases = ("startup", "login")
    keywords = "startup login items autostart screensaver animation reduce motion boot welcome"
    sub = "Startup, login items and the first-run experience."
    entries = (("Startup and screensaver", "login animation boot menu reduce motion", "startup"), ("Login items", "autostart apps open at login startup programs", "login-items"))
    optional = frozenset({"startup", "login-items"})
    def build(self, pb):
        self.mh = legacy.load(self, "carpatic_motion_pages", "MotionPages")
        g = pb.group()
        if self.mh: g.add(NavRow("Startup and screensaver", "Login animation, reduce motion, screensaver, boot menu", "preferences-desktop-screensaver", "#5e5ce6", "", self.mh.open, key="startup"))
        items = autostart_entries()
        if items:
            g2 = pb.group("Open at login", "Apps that start when you log in. Turn one off to stop it without removing it.", key="login-items")
            for fid, name, en, sysf in items:
                g2.add(SwitchRow(name, "Provided by the system" if sysf else "", en, lambda v, fid=fid: set_autostart(fid, v), key="login-" + fid))
        else:
            pb.group("Open at login", "Apps you add to ~/.config/autostart start when you log in.")
    def open_sub(self, name):
        if name == "startup" and self.mh: self.mh.open()

PAGES = [DesktopPage, WallpaperPage, ControlCentrePage, AccessibilityPage, GeneralPage]
