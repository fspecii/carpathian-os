"""Displays (xrandr, carpatic-display, carpatic-appearance scale, carpatic-nightlight, brightness via carpatic-power)."""
import re, os, math
from gi.repository import Gtk
from .. import sysutil as su, ui, theme
from ..app import Page
from ..ui import *

def parse_xrandr(text):
    """xrandr --query -> [{name, connected, primary, w,h,x,y, rotation, modes:[{res, rates:[(rate, current, preferred)]}]}]"""
    outs = []; cur = None
    for line in text.splitlines():
        m = re.match(r"^(\S+) (connected|disconnected)\s*(primary)?\s*(?:(\d+)x(\d+)\+(\d+)\+(\d+))?\s*(left|right|inverted|normal)?", line)
        if m and not line.startswith(" "):
            cur = {"name": m.group(1), "connected": m.group(2) == "connected", "primary": bool(m.group(3)), "w": int(m.group(4) or 0), "h": int(m.group(5) or 0),
                   "x": int(m.group(6) or 0), "y": int(m.group(7) or 0), "rotation": m.group(8) or "normal", "modes": []}
            mm = re.search(r"(\d+)mm x (\d+)mm", line); cur["mm"] = (int(mm.group(1)), int(mm.group(2))) if mm else None
            outs.append(cur); continue
        m = re.match(r"^\s+(\d+x\d+)i?\s+(.*)$", line)
        if m and cur is not None:
            rates = []
            for r in re.findall(r"(\d+\.\d+)([*+ ]*)", m.group(2)):
                rates.append((r[0], "*" in r[1], "+" in r[1]))
            cur["modes"].append({"res": m.group(1), "rates": rates})
    return outs

def pretty_res(r): return r.replace("x", " × ")
def human_rate(r): return f"{float(r):.0f} Hz" if abs(float(r) - round(float(r))) < 0.05 else f"{float(r):.2f} Hz"
def sort_res(modes): return sorted({m["res"] for m in modes}, key=lambda r: -int(r.split("x")[0]) * int(r.split("x")[1]))

class DisplaysPage(Page):
    order = 5
    id = "displays"; title = "Displays"; icon = "video-display"; color = "#0a84ff"; group = 2
    aliases = ("display", "screen")
    keywords = "monitor screen resolution scale refresh rate brightness night light mirror extend rotation hidpi external projector"
    entries = (("Resolution", "size pixels", "screens"), ("Refresh rate", "hz hertz", "screens"), ("Rotation", "orientation portrait landscape", "screens"), ("Scale", "hidpi size bigger smaller 200%", "scale"),
               ("Brightness", "backlight dim", "brightness"), ("Night Light", "warm colour blue light evening redshift", "night"), ("Extend or mirror", "multiple monitors projector external arrangement", "arrange"),
               ("Use as main display", "primary", "screens"), ("Set up new screens automatically", "plug hotplug", "auto"))
    optional = frozenset({"brightness", "scale", "night", "arrange", "auto"})
    def available(self): return su.which("xrandr") and bool(os.environ.get("DISPLAY"))
    def build(self, pb):
        self.pb = pb; self.outs = []; self.groups = []
        self.top = pb.group()
        # brightness (laptop panels)
        self.bright = None
        if su.which("carpatic-power"):
            v = su.out("carpatic-power", "brightness", "get")
            if v.strip().isdigit():
                self.bright = SliderRow("Brightness", "", 1, 100, 1, int(v), lambda x: su.spawn("carpatic-power", "brightness", "set", str(int(x))), fmt=lambda x: f"{x:.0f}%", icon="display-brightness", color="#ff9f0a", key="brightness", setting="display.brightness")
                self.top.add(self.bright)
        self.scale = PopupRow("Scale", su.scale_status() or "Make everything bigger on high-resolution screens", su.SCALE_CHOICES, su.scale_value(),
                              lambda v: self.win.apply("carpatic-appearance", "set", "scale", v, msg="Applying the scale...", done=lambda rc, *_: (self.scale.set_sub(su.scale_status()), su.reopen_after_scale("displays") if rc == 0 else None)), icon="zoom-in", color="#5e5ce6", key="scale", setting="SCALE")
        if su.which("carpatic-appearance"): self.top.add(self.scale)
        self.top.set_footer(su.SCALE_NOTE) if su.which("carpatic-appearance") else None
        self.screens = pb.group("Screens", key="screens")
        self.arr = None
        self.multi = pb.group("More than one screen", "Carpatic sets up screens when you plug them in or out. Pick how they are used right now.", key="arrange")
        self.layout_seg = Segmented([("extend", "Extend"), ("mirror", "Mirror"), ("external", "Only other"), ("internal", "Only this")], None, lambda m: self.win.apply("carpatic-display", m, msg="Changing screens...", done=lambda *_: self.refresh()))
        self.multi.add(CustomRow(self.layout_seg, key="arrange", pad=12))
        if su.which("carpatic-display"):
            env = su.read_env(os.path.join(su.CFG, "display.env"))
            self.multi.add(SwitchRow("Set up new screens automatically", "A monitor or projector you plug in is added to the right", env.get("AUTO", "on") != "off", lambda v: su.spawn("carpatic-display", "set", "auto", "on" if v else "off"), key="auto"))
        self.multi.hide(); self.multi.set_no_show_all(True)
        self.build_night(pb)
        self.refresh()
    def build_night(self, pb):
        if not su.which("carpatic-nightlight"): return
        st = su.kv_lines("carpatic-nightlight", "status")
        if st.get("tool", "none") == "none": return
        g = pb.group("Night Light", "Warmer colours in the evening are easier on your eyes. With a time window it switches on and off by itself.", key="night")
        on = st.get("off", None) is None and "on" in (su.out("carpatic-nightlight", "status").split("\n")[0].split() or [""])[0]
        k = su.out("carpatic-nightlight", "status").split("\n")[0].split()
        kelvin = int(k[1]) if len(k) > 1 and k[1].isdigit() else 4000
        self.nl = SwitchRow("Night Light", "", on, lambda v: self.win.apply("carpatic-nightlight", "on" if v else "off", msg="Night Light...") , key="night")
        self.nl_k = SliderRow("Warmth", "", 2500, 6500, 100, kelvin, lambda v: self.win.apply("carpatic-nightlight", "on", str(int(v)), msg="Night Light..."), fmt=lambda v: f"{v:.0f} K", key="night-k")
        g.add(self.nl, self.nl_k)
        sch = (st.get("schedule") or "always")
        self.nl_s = PopupRow("Schedule", "", [("always", "All day"), ("20:00-07:00", "8 pm to 7 am"), ("21:00-06:00", "9 pm to 6 am"), ("22:00-07:00", "10 pm to 7 am")], sch if sch in ("always", "20:00-07:00", "21:00-06:00", "22:00-07:00") else "always",
                             lambda v: self.win.apply("carpatic-nightlight", "schedule", v, msg="Night Light..."), key="night-s")
        g.add(self.nl_s)
    def on_show(self):
        if self.pb: self.refresh()
    def refresh(self):
        su.bg(lambda: su.out("xrandr", "--query"), self.fill)
    def fill(self, text):
        if isinstance(text, Exception): return
        outs = parse_xrandr(text); self.outs = outs; conn = [o for o in outs if o["connected"]]
        self.screens.clear()
        for o in conn:
            self.screens.add(NavRow(self.nice(o, conn), f"{o['w']} × {o['h']}" if o["w"] else "Off", "video-display", "#0a84ff", "Main" if o["primary"] else "", lambda o=o: self.push(self.nice(o, conn), lambda pb: self.detail(pb, o, conn)), key="screen-" + o["name"]))
        self.screens.show_all()
        self.multi.set_visible(len(conn) > 1); self.multi.set_no_show_all(len(conn) <= 1)
        if len(conn) > 1:
            act = [o for o in conn if o["w"]]; same = len(act) > 1 and all((o["x"], o["y"]) == (act[0]["x"], act[0]["y"]) for o in act)
            self.layout_seg.set_value("mirror" if same else ("extend" if len(act) > 1 else ("external" if act and "eDP" not in act[0]["name"] and "LVDS" not in act[0]["name"] else "internal")))
        if self.arr is None and len(conn) > 1:
            self.arr = Gtk.DrawingArea(); self.arr.set_size_request(-1, 120); self.arr.connect("draw", self.draw_arr); self.multi.add(CustomRow(self.arr, key="arr", pad=12)); self.arr.show()
        if self.arr: self.arr.queue_draw()
    def nice(self, o, conn):
        n = o["name"]
        if re.match(r"(eDP|LVDS|DSI)", n): return "Built-in display"
        if len(conn) == 1: return f"Display ({n})"
        return "External display" + (f" {n}" if len([c for c in conn if not re.match(r"(eDP|LVDS|DSI)", c["name"])]) > 1 else "") + f" ({n})"
    def draw_arr(self, w, cr):
        act = [o for o in self.outs if o["connected"] and o["w"]]
        if not act: return
        W, H = w.get_allocated_width(), w.get_allocated_height()
        minx = min(o["x"] for o in act); miny = min(o["y"] for o in act); maxx = max(o["x"] + o["w"] for o in act); maxy = max(o["y"] + o["h"] for o in act)
        k = min((W - 24) / max(1, maxx - minx), (H - 16) / max(1, maxy - miny)); ox = (W - (maxx - minx) * k) / 2; oy = (H - (maxy - miny) * k) / 2
        p = self.win.pal
        def rgbc(h): h = h.lstrip("#"); return tuple(int(h[i:i+2], 16) / 255 for i in (0, 2, 4))
        for o in act:
            x, y, ww, hh = ox + (o["x"] - minx) * k, oy + (o["y"] - miny) * k, o["w"] * k, o["h"] * k
            cr.set_source_rgb(*rgbc(theme.mix(p["bg"], p["accent"], 0.35))); cr.rectangle(x + 1, y + 1, ww - 2, hh - 2); cr.fill()
            cr.set_source_rgb(*rgbc(p["accent"])); cr.set_line_width(2); cr.rectangle(x + 1, y + 1, ww - 2, hh - 2); cr.stroke()
            cr.set_source_rgb(*rgbc(p["fg"])); cr.select_font_face("sans"); cr.set_font_size(11); cr.move_to(x + 8, y + 18); cr.show_text(o["name"] + ("  (main)" if o["primary"] else ""))
    def detail(self, pb, o, conn):
        res = sort_res(o["modes"]); cur = f"{o['w']}x{o['h']}" if o["w"] else (res[0] if res else "")
        curmode = next((m for m in o["modes"] if m["res"] == cur), None)
        g = pb.group(self.nice(o, conn))
        r_res = PopupRow("Resolution", "", [(r, pretty_res(r)) for r in res], cur, None, key="res"); g.add(r_res)
        def rates_for(res_id):
            m = next((m for m in o["modes"] if m["res"] == res_id), None)
            return [(r[0], human_rate(r[0])) for r in m["rates"]] if m else []
        cr_ = next((r[0] for r in curmode["rates"] if r[1]), None) if curmode else None
        r_rate = PopupRow("Refresh rate", "", rates_for(cur), cr_, None, key="rate"); g.add(r_rate)
        def set_mode(res_id=None, rate=None):
            res_id = res_id or r_res.get_value(); rate = rate or r_rate.get_value()
            self.win.apply("xrandr", "--output", o["name"], "--mode", res_id, *(["--rate", rate] if rate else []), msg="Changing the resolution...", done=lambda *_: self.refresh())
        def on_res(v):
            rr = rates_for(v); r_rate.set_options(rr, rr[0][0] if rr else None); set_mode(v, rr[0][0] if rr else None)
        r_res.pb.on_change = on_res; r_rate.pb.on_change = lambda v: set_mode(None, v)
        g.add(PopupRow("Rotation", "", [("normal", "Standard"), ("left", "90° left"), ("right", "90° right"), ("inverted", "Upside down")], o["rotation"],
                       lambda v: self.win.apply("xrandr", "--output", o["name"], "--rotate", v, msg="Rotating...", done=lambda *_: self.refresh()), key="rot"))
        g2 = pb.group()
        if len([c for c in conn if c["w"]]) > 1 or not o["primary"]:
            g2.add(ButtonRow("Use as main display", "The panel and new windows appear here" if not o["primary"] else "This is the main display", "Use", lambda: self.win.apply("xrandr", "--output", o["name"], "--primary", msg="Changing the main display...", done=lambda *_: self.refresh()), key="primary"))
        if o["mm"] and o["w"]:
            dpi = o["w"] / (o["mm"][0] / 25.4); g2.add(InfoRow("Size", f"{math.hypot(o['mm'][0], o['mm'][1]) / 25.4:.1f} inch, about {dpi:.0f} pixels per inch"))
        g2.add(InfoRow("Connection", o["name"]))

PAGES = [DisplaysPage]
