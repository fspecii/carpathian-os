"""Taskbar/dock settings through the panel component's CLI: `carpatic-panel get | options | designs | set KEY VALUE` (see panel/NEEDS.md).
Rows are generated from `carpatic-panel options`, so a key the panel does not know is simply not shown."""
import os, re
from gi.repository import Gtk
from .. import sysutil as su
from ..ui import *

def parse_options(text):
    """options lines 'name  a|b|c  description' -> {name: (type, values_or_range, description)}"""
    out = {}
    for l in text.splitlines():
        m = re.match(r"^(\w+)\s+(\S+)\s+(.*)$", l.strip())
        if not m: continue
        k, v, d = m.groups()
        if "|" in v: out[k] = ("enum", v.split("|"), d)
        elif re.fullmatch(r"-?\d+\.\.-?\d+", v): lo, hi = v.split(".."); out[k] = ("int", (int(lo), int(hi)), d)
        else: out[k] = (v, None, d)
    return out

def parse_get(text):
    """'key=value  (effective: X)' -> ({key: value}, {key: effective})"""
    val, eff = {}, {}
    for l in text.splitlines():
        m = re.match(r"^(\w+)=(.*?)\s+\(effective: (.*)\)\s*$", l)
        if m: val[m.group(1)], eff[m.group(1)] = m.group(2), m.group(3)
    return val, eff

def parse_designs(text):
    return [tuple(l.split(None, 1)) for l in text.splitlines() if len(l.split(None, 1)) == 2]

WORDS = {"auto": "Design default", "on": "On", "off": "Off", "top": "Top", "bottom": "Bottom", "left": "Left", "right": "Right", "center": "Centre", "pill": "Pill", "dot": "Dot", "line": "Line", "dots": "Dots",
         "primary": "Main display only", "all": "Every display", "dark": "Dark", "light": "Light"}

PREVIEW_DIRS = [os.path.join(os.path.dirname(__file__), "..", "..", "..", "share", "panel-previews"), "/usr/share/carpatic-settings/panel-previews", "/usr/local/share/carpatic-settings/panel-previews", "/usr/share/carpatic/panel/previews"]

def design_preview(design, mode, width=168):
    """thumbnail of a panel design (320x180 PNG from the panel's screenshots) as a Gtk.Image, or None when it is not installed"""
    for d in PREVIEW_DIRS:
        f = os.path.join(d, f"{design}-{mode}.png")
        if os.path.isfile(f):
            try:
                from gi.repository import GdkPixbuf
                pb = GdkPixbuf.Pixbuf.new_from_file(f)
                img = Gtk.Image.new_from_pixbuf(pb.scale_simple(width, int(width * pb.get_height() / pb.get_width()), GdkPixbuf.InterpType.BILINEAR)); img.set_halign(Gtk.Align.CENTER); return img
            except Exception: return None
    return None

def available():
    return su.which("carpatic-panel")

def load():
    return parse_options(su.out("carpatic-panel", "options")), *parse_get(su.out("carpatic-panel", "get")), parse_designs(su.out("carpatic-panel", "designs"))

def make_row(win, key, label, sub, opts, val, eff, anchor=None, on_done=None):
    """one row for a panel key; None when the panel does not have it"""
    if key not in opts: return None
    typ, rng, desc = opts[key]; cur = val.get(key, "auto"); effective = eff.get(key, cur)
    def setter(v):
        win.apply("carpatic-panel", "set", key, str(v), msg="Applying...", done=lambda rc, o: (win.idle("" if rc == 0 else o.strip().splitlines()[-1][:80] if o.strip() else "That did not work."), on_done and on_done()))
    k = anchor or "panel-" + key; st = "panel." + key
    if typ == "enum" and set(rng) == {"on", "off"}:
        return SwitchRow(label, sub, cur == "on", lambda v: setter("on" if v else "off"), key=k, setting=st)
    if typ == "enum":
        if key == "position":   # left/right main bars leave the bar in the middle of the screen and a second dwm bar on top (found in the VM): offer only what works
            rng = [r for r in rng if r in ("auto", "top", "bottom")]
            if cur not in rng: cur = "auto"
        return PopupRow(label, sub, [(r, WORDS.get(r, r.replace("_", " ").title())) for r in rng], cur if cur in rng else rng[0], setter, key=k, setting=st)
    if typ == "int":
        try: shown = int(effective)
        except ValueError: shown = rng[0]
        return SliderRow(label, sub, rng[0], rng[1], 1, max(rng[0], min(rng[1], shown)), lambda v: setter(int(v)), fmt=lambda v: f"{v:.0f} px", key=k, setting=st)
    if typ == "bool":
        return SwitchRow(label, sub, cur in ("1", "true", "on") if cur != "auto" else effective in ("1", "True", "true", "on"), lambda v: setter("1" if v else "0"), key=k, setting=st)
    return None

# designs whose bar is always the top menu bar: a position choice would do nothing
FIXED_POSITION = ("macos", "ubuntu")

def bar_state():
    """-> (kind, running) for the bar of the current profile: kind panel|tint2|dwm, running = the bar program is alive (dwm's own bar needs no process)"""
    kind = su.read_env(os.path.join(su.CFG, "profile.env")).get("BAR", "dwm")
    if kind == "panel": return kind, int(su.out("sh", "-c", "pgrep -f '^python3 .*carpatic-panel run' | wc -l") or 0) >= 1
    if kind == "tint2": return kind, bool(su.out("pgrep", "-x", "tint2"))
    return kind, True

TASKBAR = (("position", "Position", "Top or bottom edge of the screen"), ("size", "Size", "Thickness of the bar"), ("icon_size", "Icon size", ""), ("align", "Icon alignment", ""),
           ("autohide", "Hide automatically", "Slides away until the pointer touches the edge"), ("labels", "Window titles", "Show titles next to icons"), ("grouping", "Group windows of one app", ""),
           ("indicator", "Running-app indicator", ""), ("monitors", "Show the bar on", ""), ("theme", "Bar colours", "Force dark or light bar colours"))
BUTTONS = (("show_search", "Search button", ""), ("show_taskview", "Task view button", "Overview of all windows"), ("show_widgets", "Widgets button", ""), ("show_desktop", "Show-desktop strip", "At the end of the bar"), ("tags", "Workspace indicator", ""))
SYSTEM = (("tray", "System tray", "Network, volume and other status icons"), ("clock_24h", "24-hour clock", ""), ("date_in_clock", "Date under the time", ""), ("previews", "Hover previews", "Window previews and tooltips"))
