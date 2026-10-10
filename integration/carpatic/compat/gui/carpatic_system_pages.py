"""Carpatic System pages (Updates and restore points, Accessibility, Touchpad, Screen, Typing in other languages) for the Carpatic Settings
window. Every control calls a CLI tool (carpatic-update, carpatic-rollback, carpatic-a11y, carpatic-touchpad, carpatic-display,
carpatic-appearance, carpatic-input-method), so everything here also works from a terminal. License: MIT."""
import os, subprocess
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib
from carpatic_ui import run

def out(*cmd):
    try: return subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout.strip()
    except Exception: return ""

def lines(cmd):
    return [l for l in out(*cmd).split("\n") if l]

def kv(cmd):
    d = {}
    for l in lines(cmd):
        p = l.split(None, 1)
        if len(p) == 2: d[p[0]] = p[1].strip()
        elif len(p) == 1: d[p[0]] = ""
    return d

PAGES = (("updates", "Updates", "build_updates"), ("access", "Accessibility", "build_access"), ("touchpad", "Touchpad", "build_touchpad"),
         ("display", "Screen", "build_display"), ("language", "Typing in other languages", "build_language"))

class SystemPages:
    def __init__(self, window):
        self.w = window; self.guard = False
    def register(self):
        """Add the pages to a Carpatic Settings window (its lazy() builds each page the first time it is shown)."""
        for name, title, fn in PAGES:
            self.w.lazy(name, title, lambda n=name, f=fn: getattr(self, f)(self.w.boxes[n]))
    def refresh(self, name):
        if name == "updates" and hasattr(self, "upd_status"): self.refresh_updates()
    def head(self, box, title, sub):
        t = Gtk.Label(label=title, xalign=0); t.get_style_context().add_class("h1"); box.pack_start(t, False, False, 0)
        s = Gtk.Label(label=sub, xalign=0, wrap=True); s.get_style_context().add_class("sub"); box.pack_start(s, False, False, 0)
    def note(self, box, text):
        l = Gtk.Label(label=text, xalign=0, wrap=True); l.get_style_context().add_class("sub"); box.pack_start(l, False, False, 0); return l
    def switch_row(self, box, title, sub, active, cb):
        row = Gtk.Box(spacing=12); col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        a = Gtk.Label(label=title, xalign=0); a.get_style_context().add_class("ctitle"); col.pack_start(a, False, False, 0)
        b = Gtk.Label(label=sub, xalign=0, wrap=True); b.get_style_context().add_class("sub"); col.pack_start(b, False, False, 0)
        sw = Gtk.Switch(); sw.set_active(active); sw.set_valign(Gtk.Align.CENTER)
        sw.connect("notify::active", lambda w, _p: None if self.guard else cb(w.get_active()))
        row.pack_start(col, True, True, 0); row.pack_end(sw, False, False, 0); box.pack_start(row, False, False, 6); return sw
    def combo_row(self, box, title, sub, items, current, cb):
        row = Gtk.Box(spacing=12); col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        a = Gtk.Label(label=title, xalign=0); a.get_style_context().add_class("ctitle"); col.pack_start(a, False, False, 0)
        b = Gtk.Label(label=sub, xalign=0, wrap=True); b.get_style_context().add_class("sub"); col.pack_start(b, False, False, 0)
        c = Gtk.ComboBoxText()
        for k, v in items: c.append(k, v)
        c.set_active_id(current); c.set_valign(Gtk.Align.CENTER)
        c.connect("changed", lambda w: None if self.guard else cb(w.get_active_id()))
        row.pack_start(col, True, True, 0); row.pack_end(c, False, False, 0); box.pack_start(row, False, False, 6); return c

    # ---- Updates and restore points ----
    def build_updates(self, box):
        self.head(box, "Updates", "Keep Carpatic up to date. Nothing is installed without you asking.")
        self.upd_status = self.note(box, "")
        bar = Gtk.Box(spacing=8)
        self.btn_check = Gtk.Button(label="Check for updates"); self.btn_check.connect("clicked", lambda *_: self.admin("check", ["carpatic-update", "check"], "Looking for updates..."))
        self.btn_apply = Gtk.Button(label="Install updates"); self.btn_apply.get_style_context().add_class("suggested-action")
        self.btn_apply.connect("clicked", lambda *_: self.admin("apply", ["carpatic-update", "apply"], "Installing updates. This can take a few minutes..."))
        self.btn_restart = Gtk.Button(label="Restart now"); self.btn_restart.set_no_show_all(True); self.btn_restart.connect("clicked", lambda *_: run("loginctl", "reboot"))
        for b in (self.btn_check, self.btn_apply, self.btn_restart): bar.pack_start(b, False, False, 0)
        self.spin = Gtk.Spinner(); bar.pack_start(self.spin, False, False, 6)
        box.pack_start(bar, False, False, 6)
        l = Gtk.Label(label="Restore points", xalign=0); l.get_style_context().add_class("h1"); box.pack_start(l, False, False, 8)
        self.note(box, "Before every update Carpatic keeps a copy of the system. If something goes wrong, restore it and restart. Your files in the home folder are never changed.")
        self.snap_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        sw = Gtk.ScrolledWindow(); sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); sw.add(self.snap_box); sw.set_min_content_height(160)
        box.pack_start(sw, True, True, 0)
        self.btn_snap = Gtk.Button(label="Make a restore point now"); self.btn_snap.set_halign(Gtk.Align.START)
        self.btn_snap.connect("clicked", lambda *_: self.admin("snap", ["carpatic-rollback", "snapshot", "manual"], "Saving a restore point..."))
        box.pack_start(self.btn_snap, False, False, 0)
        self.refresh_updates(); GLib.timeout_add_seconds(30, lambda: (self.refresh_updates(), True)[1])
    def refresh_updates(self):
        st = out("carpatic-update", "status")             # "updates: N, restart needed: yes|no"
        n = st.split("updates:")[-1].split(",")[0].strip() if "updates:" in st else "unknown"
        restart = "restart needed: yes" in st
        if restart: msg = "Restart to finish updating."
        elif n in ("0",): msg = "Your system is up to date."
        elif n == "unknown": msg = "Press \"Check for updates\" to see if anything is new."
        else: msg = f"{n} update(s) are ready to install."
        self.upd_status.set_text(msg)
        self.btn_restart.set_visible(restart); self.btn_apply.set_sensitive(n not in ("0",))
        for c in self.snap_box.get_children(): self.snap_box.remove(c)
        snaps = lines(["carpatic-rollback", "list"]) if os.path.exists("/usr/local/bin/carpatic-rollback") else []
        fs = "btrfs" if any(l.split()[1:3] == ["/", "btrfs"] for l in open("/proc/mounts")) else "ext4 or another file system"
        if fs != "btrfs":
            self.snap_box.pack_start(Gtk.Label(label="Restore points need the Btrfs disk layout, which the installer offers. This computer was installed with a different one.", xalign=0, wrap=True), False, False, 0)
            self.btn_snap.set_sensitive(False)
        elif not snaps or snaps[0].startswith("No snapshots"):
            self.snap_box.pack_start(Gtk.Label(label="No restore points yet.", xalign=0), False, False, 0)
        else:
            for s in snaps[:12]:
                sid, _, label = s.partition("  ")
                row = Gtk.Box(spacing=8); t = Gtk.Label(label=f"{self.nice(sid)}   {label}", xalign=0)
                b = Gtk.Button(label="Restore"); b.connect("clicked", lambda _b, sid=sid: self.restore(sid))
                row.pack_start(t, True, True, 0); row.pack_end(b, False, False, 0); self.snap_box.pack_start(row, False, False, 0)
        self.snap_box.show_all()
    @staticmethod
    def nice(sid):
        d = sid[:15]
        try: return f"{d[6:8]}.{d[4:6]}.{d[0:4]} {d[9:11]}:{d[11:13]}"
        except Exception: return sid
    def restore(self, sid):
        dlg = Gtk.MessageDialog(transient_for=self.w, modal=True, message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.NONE,
                                text="Go back to this restore point?", secondary_text=f"{self.nice(sid)}\n\nYour computer will look like it did then after the next restart. Your files stay as they are, and you can undo this.")
        dlg.add_button("Cancel", Gtk.ResponseType.CANCEL); dlg.add_button("Restore", Gtk.ResponseType.OK)
        r = dlg.run(); dlg.destroy()
        if r == Gtk.ResponseType.OK: self.admin("restore", ["carpatic-rollback", "restore", sid], "Restoring...")
    def admin(self, what, cmd, msg):
        self.upd_status.set_text(msg); self.spin.start()
        for b in (self.btn_check, self.btn_apply, self.btn_snap): b.set_sensitive(False)
        def done(rc):
            self.spin.stop()
            for b in (self.btn_check, self.btn_apply, self.btn_snap): b.set_sensitive(True)
            self.refresh_updates()
            if rc != 0: self.upd_status.set_text("That did not finish. If you cancelled the password window, nothing was changed. Otherwise try again.")
            elif what == "restore": self.upd_status.set_text("Done. Restart your computer to go back to that restore point."); self.btn_restart.show()
        run("pkexec", *["/usr/local/bin/" + cmd[0]] + cmd[1:], done=done)

    # ---- Accessibility ----
    def build_access(self, box):
        self.head(box, "Accessibility", "Make Carpatic easier to see, hear and use. Choices are kept for the next login.")
        st = kv(["carpatic-a11y", "status"]); on = lambda k: st.get(k, "off") == "on"
        A = lambda k, v: run("carpatic-a11y", k, "on" if v else "off")
        self.switch_row(box, "Larger text", "Bigger menus, buttons, terminal text and mouse pointer.", on("large-text"), lambda v: A("large-text", v))
        self.switch_row(box, "High contrast", "White on black with yellow highlights. Switch off to get your theme back.", on("high-contrast"), lambda v: A("high-contrast", v))
        self.switch_row(box, "Screen reader", "Orca reads the screen aloud. Needs sound.", on("screen-reader"), lambda v: A("screen-reader", v))
        self.switch_row(box, "On-screen keyboard", "Type by clicking keys on the screen.", on("onscreen-keyboard"), lambda v: A("keyboard", v))
        self.switch_row(box, "Sticky keys", "Press Shift, Ctrl or Alt one key at a time instead of holding them.", on("sticky-keys"), lambda v: A("sticky", v))
        self.switch_row(box, "Slow keys", "Ignore keys that are only touched briefly.", on("slow-keys"), lambda v: A("slow", v))
        self.switch_row(box, "Bounce keys", "Ignore a key that is pressed twice by accident.", on("bounce-keys"), lambda v: A("bounce", v))
        self.switch_row(box, "Mouse keys", "Move the pointer with the number pad.", on("mouse-keys"), lambda v: A("mousekeys", v))

    # ---- Touchpad ----
    def build_touchpad(self, box):
        self.head(box, "Touchpad", "How your touchpad behaves. If the cursor jumps or text gets selected while you scroll, turn off \"Tap to click\".")
        st = kv(["carpatic-touchpad", "status"])
        if not st or "No touchpad" in " ".join(st.keys()):
            self.note(box, "No touchpad found on this computer. These settings apply when you plug one in.")
        on = lambda k, d="off": st.get(k, d) == "on"
        T = lambda k, v: run("carpatic-touchpad", "set", k, v)
        self.switch_row(box, "Tap to click", "Tap the pad with one finger to click.", on("tap"), lambda v: T("tap", "on" if v else "off"))
        self.switch_row(box, "Tap and drag", "Tap, then touch again and move to drag.", on("tap-drag"), lambda v: T("tap-drag", "on" if v else "off"))
        self.switch_row(box, "Natural scrolling", "Content follows your fingers, like on a phone.", on("natural", "on"), lambda v: T("natural", "on" if v else "off"))
        self.switch_row(box, "Ignore the pad while typing", "Stops your palm from moving the cursor.", on("typing-guard", "on"), lambda v: T("typing-guard", "on" if v else "off"))
        self.switch_row(box, "Three- and four-finger swipes", "Swipe left or right to change workspace, up to switch apps.", on("gestures"), lambda v: T("gestures", "on" if v else "off"))
        self.combo_row(box, "Scrolling", "Two fingers anywhere, or one finger along the right edge.", [("two-finger", "Two fingers"), ("edge", "Right edge")], st.get("scroll", "two-finger"), lambda v: T("scroll", v))
        self.combo_row(box, "Pointer speed", "How fast the cursor moves.", [("-0.5", "Slow"), ("0", "Normal"), ("0.5", "Fast")], st.get("speed", "0") if st.get("speed", "0") in ("-0.5", "0", "0.5") else "0", lambda v: T("speed", v))

    # ---- Screen ----
    def build_display(self, box):
        self.head(box, "Screen", "Make everything bigger or smaller on this screen. Sharp text on high-resolution displays.")
        cur = out("carpatic-appearance", "get")
        scale = "100"
        for l in cur.split("\n"):
            if l.startswith("SCALE="): scale = l.split("=", 1)[1].strip('"') or "100"
        self.combo_row(box, "Scale", "100% is the normal size. 150% suits most 13-inch Full HD and 4K laptops.",
                       [("100", "100%"), ("125", "125%"), ("150", "150%"), ("175", "175%"), ("200", "200%")], scale if scale in ("100", "125", "150", "175", "200") else "100",
                       lambda v: run("carpatic-appearance", "set", "scale", v))
        self.note(box, "Some apps need to be closed and opened again to pick up the new size.")
        l = Gtk.Label(label="More than one screen", xalign=0); l.get_style_context().add_class("h1"); box.pack_start(l, False, False, 8)
        self.note(box, "Carpatic sets up screens when you plug them in or unplug them. Pick how they are used right now:")
        bar = Gtk.Box(spacing=8)
        for label, mode in (("Extend", "extend"), ("Mirror", "mirror"), ("Only the other screen", "external"), ("Only this screen", "internal")):
            b = Gtk.Button(label=label); b.connect("clicked", lambda _b, m=mode: run("carpatic-display", m)); bar.pack_start(b, False, False, 0)
        box.pack_start(bar, False, False, 4)
        env = {}
        try:
            for ln in open(os.path.expanduser("~/.config/carpatic/display.env")):
                if "=" in ln: k, v = ln.strip().split("=", 1); env[k] = v.strip('"')
        except OSError: pass
        self.switch_row(box, "Set up new screens automatically", "When you plug in a monitor or projector it is added to the right.", env.get("AUTO", "on") != "off",
                        lambda v: run("carpatic-display", "set", "auto", "on" if v else "off"))

    # ---- Typing in other languages ----
    def build_language(self, box):
        self.head(box, "Typing in other languages", "Chinese, Japanese, Korean, Vietnamese and some other languages need an input method to type.")
        cur = out("carpatic-input-method", "status").split("\n")[0].replace("input method:", "").strip() or "off"
        self.combo_row(box, "Input method", "Fcitx5 works in all apps, including Chrome and other apps from the compatibility box. Takes effect after you log out and in.",
                       [("off", "Off"), ("fcitx5", "Fcitx5 (recommended)"), ("ibus", "IBus")], cur if cur in ("off", "fcitx5", "ibus") else "off",
                       lambda v: run("carpatic-input-method", "set", v))
        row = Gtk.Box(spacing=12); col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        a = Gtk.Label(label="Add a language", xalign=0); a.get_style_context().add_class("ctitle"); col.pack_start(a, False, False, 0)
        b = Gtk.Label(label="Installs the keyboard engine and fonts for it (about 100 MB for Chinese, Japanese and Korean). Needs your password.", xalign=0, wrap=True)
        b.get_style_context().add_class("sub"); col.pack_start(b, False, False, 0)
        self.lang = Gtk.ComboBoxText()
        for k, v in (("chinese", "Chinese"), ("japanese", "Japanese"), ("korean", "Korean"), ("vietnamese", "Vietnamese"), ("other", "Other (engine only)")): self.lang.append(k, v)
        self.lang.set_active(0); self.lang.set_valign(Gtk.Align.CENTER)
        btn = Gtk.Button(label="Install"); btn.set_valign(Gtk.Align.CENTER)
        self.lang_msg = self.note(box, "")
        def done(rc): btn.set_sensitive(True); self.lang_msg.set_text("Done. Log out and in again, then press Ctrl+Space to switch." if rc == 0 else "That did not finish. If you cancelled the password window, nothing was changed.")
        def go(*_): btn.set_sensitive(False); self.lang_msg.set_text("Installing..."); run("carpatic-input-method", "install", self.lang.get_active_id(), done=done)
        btn.connect("clicked", go)
        row.pack_start(col, True, True, 0); row.pack_end(btn, False, False, 0); row.pack_end(self.lang, False, False, 0); box.pack_start(row, False, False, 6)
        box.reorder_child(self.lang_msg, -1)

