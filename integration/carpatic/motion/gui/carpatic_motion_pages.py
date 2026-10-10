"""Carpatic Settings page "Startup and screensaver": login animation, reduced motion, screensaver, boot menu. Every control calls a CLI tool
(carpatic-intro, carpatic-screensaver, carpatic-boot, plus settings.conf for MOTION), so everything here also works from a terminal (`carpatic intro ...`).
Loaded by carpatic-settings the same way as carpatic_system_pages (ImportError = page simply absent). License: MIT."""
import os, subprocess
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
from carpatic_ui import run


def out(*cmd):
    try: return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout
    except Exception: return ""


def setting(key, default=""):
    cfg = os.environ.get("CARPATIC_CONFIG", os.path.expanduser("~/.config/carpatic"))
    try:
        for line in reversed(open(os.path.join(cfg, "settings.conf")).read().splitlines()):
            if line.startswith(key + '="') and line.endswith('"'): return line[len(key) + 2:-1]
    except OSError: pass
    return default


class MotionPages:
    def __init__(self, window):
        self.w = window; self.guard = False
    def register(self):
        self.w.lazy("startup", "Startup and screensaver", lambda: self.build(self.w.boxes["startup"]))
    def refresh(self, name):
        pass
    # --- small widgets (same look as the System pages) ---
    def head(self, box, title, sub):
        t = Gtk.Label(label=title, xalign=0); t.get_style_context().add_class("h1"); box.pack_start(t, False, False, 0)
        s = Gtk.Label(label=sub, xalign=0, wrap=True); s.get_style_context().add_class("sub"); box.pack_start(s, False, False, 0)
    def section(self, box, title):
        l = Gtk.Label(label=title, xalign=0); l.get_style_context().add_class("h1"); box.pack_start(l, False, False, 8)
    def note(self, box, text):
        l = Gtk.Label(label=text, xalign=0, wrap=True); l.get_style_context().add_class("sub"); box.pack_start(l, False, False, 0); return l
    def _row(self, box, title, sub, widget):
        row = Gtk.Box(spacing=12); col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        a = Gtk.Label(label=title, xalign=0); a.get_style_context().add_class("ctitle"); col.pack_start(a, False, False, 0)
        b = Gtk.Label(label=sub, xalign=0, wrap=True); b.get_style_context().add_class("sub"); col.pack_start(b, False, False, 0)
        widget.set_valign(Gtk.Align.CENTER); row.pack_start(col, True, True, 0); row.pack_end(widget, False, False, 0); box.pack_start(row, False, False, 6)
    def switch_row(self, box, title, sub, active, cb):
        sw = Gtk.Switch(); sw.set_active(active); sw.connect("notify::active", lambda w, _p: None if self.guard else cb(w.get_active())); self._row(box, title, sub, sw); return sw
    def combo_row(self, box, title, sub, items, current, cb):
        c = Gtk.ComboBoxText()
        for k, v in items: c.append(k, v)
        c.set_active_id(current if current in dict(items) else items[0][0]); c.connect("changed", lambda w: None if self.guard else cb(w.get_active_id())); self._row(box, title, sub, c); return c
    def button_row(self, box, label, cb):
        b = Gtk.Button(label=label); b.set_halign(Gtk.Align.START); b.connect("clicked", lambda *_: cb()); box.pack_start(b, False, False, 4); return b

    def build(self, box):
        self.head(box, "Startup and screensaver", "How Carpatic looks while it starts and while it waits. Everything here can be turned off.")
        # ---- motion in general
        reduced = setting("MOTION", "full") == "reduced"
        self.switch_row(box, "Reduce motion", "Login animation, installer greeter and screensaver stand still. The boot screen follows after the next restart.", reduced, self.on_reduced)
        self.status = self.note(box, "")
        # ---- login animation
        self.section(box, "Login animation")
        self.note(box, "A short animation when your desktop starts: mountains rise over your wallpaper. Press any key to skip it.")
        self.combo_row(box, "Play it", "Skipped automatically on battery saver, low battery or when this screen is too slow for it.",
                       [("first-login-only", "At the first login only"), ("every-login", "At every login"), ("off", "Never")], setting("INTRO", "first-login-only"),
                       lambda v: run("carpatic-intro", "set", v))
        self.button_row(box, "Play it now", lambda: run("carpatic-intro", "play"))
        # ---- screensaver
        self.section(box, "Screensaver")
        self.note(box, "After a few quiet minutes the screen shows the Carpatic mark and mountains. Touch any key or the mouse to come back. The screen still locks as before.")
        self.switch_row(box, "Screensaver", "Turn the idle animation on or off.", setting("SCREENSAVER", "on") == "on", lambda v: run("carpatic-screensaver", "set", "on" if v else "off"))
        self.combo_row(box, "Start after", "Minutes without touching the computer. It always starts before the screen locks.",
                       [(str(m), "%d minute%s" % (m, "" if m == 1 else "s")) for m in (1, 2, 3, 5, 8)], setting("SCREENSAVER_MIN", "3"),
                       lambda v: run("carpatic-screensaver", "set", "timeout", v))
        self.combo_row(box, "Animation", "Mountain mark, falling peaks, sunrise or stars.",
                       [("random", "Surprise me"), ("brand", "Carpatic mark"), ("rain", "Falling peaks"), ("sunrise", "Sunrise"), ("stars", "Stars")], setting("SAVER_EFFECT", "random"),
                       lambda v: run("carpatic-screensaver", "set", "effect", v))
        self.switch_row(box, "Also on battery", "Off by default: the animation uses a little power.", setting("SAVER_ON_BATTERY", "no") == "yes",
                        lambda v: run("carpatic-screensaver", "set", "battery", "yes" if v else "no"))
        self.button_row(box, "Preview now", lambda: run("carpatic-screensaver", "start"))
        # ---- boot menu
        self.section(box, "Faster start")
        menu = out("carpatic-boot", "menu", "status")
        self.menu_note = self.note(box, "")
        self.menu_sw = self.switch_row(box, "Hide the boot menu", "Starts Carpatic at once. Hold a key (for example Shift) while the computer starts to show the menu. "
                                       "Not offered when another system such as Windows is installed.", menu.startswith("hidden"), self.on_menu)
        if "another operating system" in menu:
            self.menu_sw.set_sensitive(False); self.menu_note.set_text("Another system is installed, so the boot menu stays visible.")
    def on_reduced(self, v):
        run("carpatic-set-motion", "reduced" if v else "full", done=lambda rc: self.status.set_text(
            "" if rc == 0 else "That did not work. Try again."))
        if os.path.exists("/usr/local/bin/carpatic-boot"): run("pkexec", "/usr/local/bin/carpatic-boot", "motion", "reduced" if v else "full")
    def on_menu(self, v):
        def done(rc):
            if rc != 0:
                self.guard = True; self.menu_sw.set_active(not v); self.guard = False
                self.menu_note.set_text("The menu was not changed. If you cancelled the password window that is fine; otherwise another system may be installed.")
            else: self.menu_note.set_text("Done. It applies from the next start.")
        run("pkexec", "/usr/local/bin/carpatic-boot", "menu", "hide" if v else "show", done=done)
