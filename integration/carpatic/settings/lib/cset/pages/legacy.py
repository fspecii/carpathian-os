"""Adapter that lets the older page classes of other components (motion/gui, widgets/gui: they call window.lazy / window.boxes / window.flow
and use the .h1 .sub .ctitle classes) run inside the new Settings as sub-pages without being rewritten. They are restyled by theme.CSS
(.legacy-page)."""
import os, sys
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
from .. import ui

REPO = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
for d in ("motion/gui", "widgets/gui", "widgets/lib", "compat/gui", "configurator/lib", "stylepacks/lib"):
    p = os.path.join(REPO, d)
    if os.path.isdir(p) and p not in sys.path: sys.path.append(p)
for p in ("/usr/local/lib/carpatic", "/usr/lib/carpatic", "/usr/local/share/carpatic/widgets/lib", "/usr/share/carpatic/widgets/lib"):
    if os.path.isdir(p) and p not in sys.path: sys.path.append(p)

class _Stack:
    def __init__(self, host): self.host = host
    def get_visible_child_name(self): return self.host.name if self.host.visible else None

class LegacyHost:
    def __init__(self, page):
        self.page = page; self.boxes = {}; self.builders = {}; self.name = None; self.title = ""; self.visible = False; self.stack = _Stack(self)
    def lazy(self, name, title, builder):
        self.name = name; self.title = title; self.builders[name] = builder
        b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12); ui.cls(b, "legacy-page"); self.boxes[name] = b
    def flow(self, cols=3):
        f = Gtk.FlowBox(); f.set_selection_mode(Gtk.SelectionMode.NONE); f.set_max_children_per_line(cols); f.set_min_children_per_line(2)
        f.set_row_spacing(12); f.set_column_spacing(12); f.set_homogeneous(True); f.set_valign(Gtk.Align.START); return f
    def open(self):
        """Push the legacy page as a sub-page of self.page"""
        def make():
            box = self.boxes[self.name]; box.set_margin_start(32); box.set_margin_end(32); box.set_margin_top(8); box.set_margin_bottom(24)
            self.builders[self.name](); self.visible = True
            sw = Gtk.ScrolledWindow(); sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            c = ui.Clamp(760); c.add(box); sw.add(c); sw.connect("destroy", lambda *_: setattr(self, "visible", False)); return sw
        return self.page.push(self.title, make, raw=True)

def load(page, module, cls_name):
    """Instantiate a legacy page class; returns a LegacyHost or None when the component is not installed."""
    try:
        mod = __import__(module, fromlist=[cls_name]); host = LegacyHost(page); getattr(mod, cls_name)(host).register(); return host if host.name else None
    except Exception:
        return None
