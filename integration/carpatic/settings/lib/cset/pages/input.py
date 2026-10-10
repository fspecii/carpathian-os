"""Keyboard (carpatic-keyboard, shortcut list via carpatic-keys), Mouse (carpatic-mouse), Trackpad (carpatic-touchpad)."""
import os, re
from gi.repository import Gtk
from .. import sysutil as su, ui
from ..app import Page
from ..ui import *

def parse_layout_names(text):
    return [tuple(l.split("\t", 1)) for l in text.splitlines() if "\t" in l]

class KeyboardPage(Page):
    id = "keyboard"; title = "Keyboard"; icon = "input-keyboard"; color = "#8e8e93"; group = 3
    keywords = "keys layout language typing repeat delay shortcuts caps lock hotkeys input source"
    entries = (("Keyboard layouts", "input sources language qwerty azerty qwertz", "layouts"), ("Add a layout", "language input source", "add-layout"), ("Switch layouts with", "toggle alt shift super space", "switch"),
               ("Caps Lock key", "escape control ctrl remap", "caps"), ("Key repeat delay", "hold slow fast", "delay"), ("Key repeat rate", "speed hold", "rate"), ("Keyboard shortcuts", "hotkeys cheat sheet super", "shortcuts"))
    optional = frozenset({"layouts", "add-layout", "switch", "caps", "delay", "rate", "shortcuts"})
    def available(self): return su.which("carpatic-keyboard") or su.which("setxkbmap")
    def build(self, pb):
        self.pb = pb; have = su.which("carpatic-keyboard")
        st = su.kv_lines("carpatic-keyboard", "status") if have else {}
        self.layouts = [l for l in (st.get("layouts") or "us").split(",") if l]
        names = dict(parse_layout_names(su.out("carpatic-keyboard", "list-layouts"))) if have else {}
        self.names = names
        if have:
            self.lg = pb.group("Keyboard layouts", "The first layout is the default.", key="layouts")
            self.fill_layouts()
            g2 = pb.group()
            self.add_row = PopupRow("Add a layout", "", [("", "Choose...")] + sorted([(c, n) for c, n in names.items()], key=lambda x: x[1]), "", self.add_layout, key="add-layout", icon="list-add", color="#34c759")
            g2.add(self.add_row)
            opts = st.get("options", "")
            sw = "win_space" if "win_space" in opts else "ctrl_space" if "ctrl_space" in opts else "alt_shift"
            self.switch = PopupRow("Switch layouts with", "", [("alt_shift", "Alt + Shift"), ("win_space", "Super + Space"), ("ctrl_space", "Ctrl + Space")], sw, lambda v: self.win.apply("carpatic-keyboard", "switch-key", v, msg="Saving..."), key="switch")
            g2.add(self.switch); self.switch.set_visible(len(self.layouts) > 1); self.switch.set_no_show_all(len(self.layouts) <= 1)
            caps = "ctrl" if "ctrl:nocaps" in opts else "escape" if "caps:escape" in opts else "none" if "caps:none" in opts else "default"
            g2.add(PopupRow("Caps Lock key", "What the Caps Lock key does", [("default", "Caps Lock"), ("ctrl", "Control"), ("escape", "Escape"), ("none", "Nothing")], caps, lambda v: self.win.apply("carpatic-keyboard", "capslock", v, msg="Saving..."), key="caps"))
            rp = (st.get("repeat") or "600 25").split(); delay = int(rp[0]) if rp and rp[0].isdigit() else 600; rate = int(rp[1]) if len(rp) > 1 and rp[1].isdigit() else 25
            g3 = pb.group("Key repeat", "Hold a key to repeat it.")
            self.delay = SliderRow("Key repeat delay", "How long before it starts", 150, 1000, 50, delay, lambda v: self.set_repeat(), fmt=lambda v: f"{v:.0f} ms", key="delay")
            self.rate = SliderRow("Key repeat rate", "How fast it repeats", 5, 60, 1, rate, lambda v: self.set_repeat(), fmt=lambda v: f"{v:.0f}/s", key="rate")
            g3.add(self.delay, self.rate)
        g4 = pb.group()
        if su.which("carpatic-keys") or su.which("carpatic-cheatsheet"):
            g4.add(NavRow("Keyboard shortcuts", "Every shortcut of your desktop style. Super+K shows them any time.", "preferences-desktop-keyboard-shortcuts", "#5e5ce6", "", lambda: self.push("Keyboard shortcuts", self.shortcuts), key="shortcuts"))
    def fill_layouts(self):
        self.lg.clear()
        for i, l in enumerate(self.layouts):
            r = Row(self.names.get(l, l.upper()), "Default" if i == 0 else "", key="layout-" + l, icon="input-keyboard", color="#8e8e93")
            if i > 0:
                b = Gtk.Button(label="Make default"); b.connect("clicked", lambda _b, l=l: self.set_layouts([l] + [x for x in self.layouts if x != l])); r.ctl.pack_start(b, False, False, 0)
            if len(self.layouts) > 1:
                b = Gtk.Button(label="Remove"); ui.cls(b, "destructive-action"); b.connect("clicked", lambda _b, l=l: self.set_layouts([x for x in self.layouts if x != l])); r.ctl.pack_start(b, False, False, 0)
            self.lg.add(r); r.show_all()
    def set_layouts(self, new):
        self.layouts = new; self.fill_layouts()
        self.switch.set_visible(len(new) > 1); self.switch.set_no_show_all(len(new) <= 1)
        self.win.apply("carpatic-keyboard", "layouts", ",".join(new), msg="Saving...")
    def add_layout(self, code):
        if code and code not in self.layouts: self.set_layouts(self.layouts + [code])
        self.add_row.set_value_quiet("")
    def set_repeat(self):
        self.win.apply("carpatic-keyboard", "repeat", str(int(self.delay.scale.get_value())), str(int(self.rate.scale.get_value())), msg="Saving...")
    def shortcuts(self, pb):
        txt = su.out("carpatic-keys", "--print") if su.which("carpatic-keys") else ""
        rows = []
        for l in txt.splitlines():
            m = re.match(r"^(\S.*?)\s{2,}(.+)$", l.strip())
            if m: rows.append((m.group(1), m.group(2)))
        if su.which("carpatic-cheatsheet"):
            pb.group().add(ButtonRow("Show all shortcuts", "A searchable sheet of every shortcut. Press Super+K any time.", "Open", lambda: su.spawn("carpatic-cheatsheet", "show")))
        if not rows: pb.banner("No shortcuts found for this desktop style.", "warn"); return
        g = pb.group(f"{len(rows)} shortcuts")
        for k, d in rows: g.add(InfoRow(d, k.replace("+", " + "), selectable=False))

POINTER_SPEEDS = [("-0.6", "Slow"), ("-0.3", "Slower"), ("0", "Normal"), ("0.3", "Faster"), ("0.6", "Fast")]

def has_mouse():
    if not su.which("carpatic-mouse"): return False
    return not su.out("carpatic-mouse", "status").startswith("No mouse")

class MousePage(Page):
    id = "mouse"; title = "Mouse"; icon = "input-mouse"; color = "#8e8e93"; group = 3
    keywords = "pointer cursor speed acceleration scroll left-handed button"
    entries = (("Mouse pointer speed", "tracking fast slow", "speed"), ("Mouse acceleration", "flat adaptive precision gaming", "accel"), ("Mouse natural scrolling", "reverse direction wheel", "natural"), ("Left-handed", "swap buttons primary", "lefty"), ("Emulate middle button", "both buttons", "middle"))
    def available(self): return su.which("carpatic-mouse") and bool(os.environ.get("DISPLAY"))
    def build(self, pb):
        st = su.kv_lines("carpatic-mouse", "status")
        if not st or "No" in " ".join(list(st.keys())[:1]):
            pb.banner("Plug in or connect a mouse and these settings appear here. Your choices are kept for the next time.", "info", title="No mouse found")
        on = lambda k, d="off": st.get(k, d) == "on"
        sp = st.get("speed", "0")
        try: spv = float(sp)
        except ValueError: spv = 0.0
        g = pb.group("Pointer")
        g.add(SliderRow("Pointer speed", "", -1.0, 1.0, 0.1, spv, lambda v: self.win.apply("carpatic-mouse", "set", "speed", f"{v:.1f}", msg="Saving..."), fmt=lambda v: {-1: "Slow"}.get(round(v), "Fast" if v > 0.5 else "Slow" if v < -0.5 else "Normal"), key="speed", icon="input-mouse", color="#8e8e93"))
        g.add(PopupRow("Pointer acceleration", "Adaptive speeds up with fast movements; flat is exact", [("adaptive", "Adaptive"), ("flat", "Flat")], st.get("accel", "adaptive"), lambda v: self.win.apply("carpatic-mouse", "set", "accel", v, msg="Saving..."), key="accel"))
        g2 = pb.group("Buttons and scrolling")
        g2.add(SwitchRow("Natural scrolling", "Content follows your finger on the wheel", on("natural"), lambda v: self.win.apply("carpatic-mouse", "set", "natural", "on" if v else "off", msg="Saving..."), key="natural"),
               SwitchRow("Left-handed", "Swap the left and right buttons", on("left-handed"), lambda v: self.win.apply("carpatic-mouse", "set", "left-handed", "on" if v else "off", msg="Saving..."), key="lefty"),
               SwitchRow("Emulate middle button", "Press both buttons together to middle-click", on("middle-emulation"), lambda v: self.win.apply("carpatic-mouse", "set", "middle-emulation", "on" if v else "off", msg="Saving..."), key="middle"))

class TrackpadPage(Page):
    id = "trackpad"; title = "Trackpad"; icon = "input-touchpad"; color = "#8e8e93"; group = 3
    aliases = ("touchpad",)
    keywords = "touchpad tap click scroll gestures swipe palm speed natural"
    entries = (("Tap to click", "tapping phantom", "tap"), ("Tap and drag", "dragging", "tap-drag"), ("Trackpad natural scrolling", "reverse direction phone", "natural"), ("Ignore the pad while typing", "palm rejection", "typing-guard"),
               ("Three- and four-finger swipes", "gestures workspace", "gestures"), ("Trackpad scrolling", "two fingers edge", "scroll"), ("Trackpad pointer speed", "tracking", "speed"))
    def available(self): return su.which("carpatic-touchpad") and bool(os.environ.get("DISPLAY")) and self._present()
    def _present(self):
        return not su.out("carpatic-touchpad", "status").startswith("No touchpad")
    def build(self, pb):
        st = su.kv_lines("carpatic-touchpad", "status"); on = lambda k, d="off": st.get(k, d) == "on"
        T = lambda k: (lambda v: self.win.apply("carpatic-touchpad", "set", k, "on" if v else "off", msg="Saving..."))
        g = pb.group("Point and click", "If the cursor jumps or text gets selected while you scroll, turn off “Tap to click”.")
        g.add(SwitchRow("Tap to click", "Tap with one finger to click", on("tap"), T("tap"), key="tap", icon="input-touchpad", color="#8e8e93"),
              SwitchRow("Tap and drag", "Tap, then touch again and move to drag", on("tap-drag"), T("tap-drag"), key="tap-drag"),
              SwitchRow("Ignore the pad while typing", "Stops your palm from moving the cursor", on("typing-guard", "on"), T("typing-guard"), key="typing-guard"))
        try: spv = float(st.get("speed", "0"))
        except ValueError: spv = 0.0
        g.add(SliderRow("Pointer speed", "", -1.0, 1.0, 0.1, spv, lambda v: self.win.apply("carpatic-touchpad", "set", "speed", f"{v:.1f}", msg="Saving..."), fmt=lambda v: "Fast" if v > 0.5 else "Slow" if v < -0.5 else "Normal", key="speed"))
        g2 = pb.group("Scroll and gestures")
        g2.add(SwitchRow("Natural scrolling", "Content follows your fingers, like on a phone", on("natural", "on"), T("natural"), key="natural"),
               PopupRow("Scrolling", "", [("two-finger", "Two fingers"), ("edge", "Right edge")], st.get("scroll", "two-finger"), lambda v: self.win.apply("carpatic-touchpad", "set", "scroll", v, msg="Saving..."), key="scroll"),
               SwitchRow("Three- and four-finger swipes", "Swipe left or right to change workspace, up to see all workspaces", on("gestures"), T("gestures"), key="gestures"))
        h = pb.group()
        h.add(ButtonRow("Reset the trackpad", "Back to the defaults", "Reset", lambda: self.win.apply("carpatic-touchpad", "reset", msg="Resetting..."), "destructive", key="reset"))

PAGES = [KeyboardPage, MousePage, TrackpadPage]
