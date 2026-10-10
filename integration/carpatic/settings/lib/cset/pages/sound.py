"""Sound (PipeWire via wpctl) and Notifications (dunst via dunstctl)."""
import re
from .. import sysutil as su, ui
from ..app import Page
from ..ui import SwitchRow, PopupRow, SliderRow, ButtonRow, InfoRow

SEC = re.compile(r"^\s*[│ ]*[├└]─\s+(\w[\w ]*):\s*$")
ITEM = re.compile(r"^[\s│]*(\*)?\s*(\d+)\.\s+(.+?)(?:\s+\[vol:\s*([\d.]+)(\s+MUTED)?\])?\s*$")

def parse_wpctl(text):
    """wpctl status -> {'sinks': [...], 'sources': [...], 'streams': [...]}; item = {id, name, default, vol, muted}"""
    res = {"sinks": [], "sources": [], "streams": []}; sec = None; audio = False
    for line in text.splitlines():
        s = line.strip()
        if s in ("Audio", "Video", "Settings"): audio = (s == "Audio"); sec = None; continue
        m = SEC.match(line)
        if m:
            sec = {"Sinks": "sinks", "Sources": "sources", "Streams": "streams"}.get(m.group(1)); continue
        if not audio or sec is None: continue
        m = ITEM.match(line)
        if m:
            name = re.sub(r"\s*\[(?:vol|MUTED).*$", "", m.group(3)).strip()
            if sec == "streams" and "[" in m.group(3) and False: pass
            res[sec].append({"id": m.group(2), "name": name, "default": bool(m.group(1)), "vol": float(m.group(4)) if m.group(4) else None, "muted": bool(m.group(5))})
    return res

def get_volume(target):
    t = su.out("wpctl", "get-volume", target)   # "Volume: 0.50 [MUTED]"
    m = re.search(r"Volume:\s*([\d.]+)(\s+\[MUTED\])?", t)
    return (float(m.group(1)), bool(m.group(2))) if m else (None, False)

class SoundPage(Page):
    id = "sound"; title = "Sound"; icon = "audio-volume-high"; color = "#ff453a"; group = 1
    keywords = "audio speakers volume microphone output input headphones pipewire"
    entries = (("Output volume", "speakers headphones loudness mute", "out-vol"), ("Output device", "speakers headphones hdmi", "out-dev"),
               ("Input volume", "microphone mic", "in-vol"), ("Input device", "microphone mic", "in-dev"), ("Apps playing sound", "streams per app volume", "streams"))
    def available(self): return su.which("wpctl")
    def build(self, pb):
        self.pb = pb; self.data = None
        self.banner_w = pb.banner("Sound is not running. Log out and in again; if this stays, ask for help in the forum.", "warn", title="No sound server found"); self.banner_w.hide(); self.banner_w.set_no_show_all(True)
        self.g_out = pb.group("Output")
        self.vol = SliderRow("Output volume", "", 0, 100, 1, 0, lambda v: self.set_vol("@DEFAULT_AUDIO_SINK@", v), fmt=lambda v: f"{v:.0f}%", key="out-vol")
        self.mute = SwitchRow("Mute", "", False, lambda v: su.spawn("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if v else "0"), key="out-mute")
        self.dev = PopupRow("Output device", "Where sound plays", [], None, lambda i: self.set_default(i), key="out-dev")
        self.g_out.add(self.vol, self.mute, self.dev)
        self.g_in = pb.group("Input")
        self.ivol = SliderRow("Input volume", "", 0, 100, 1, 0, lambda v: self.set_vol("@DEFAULT_AUDIO_SOURCE@", v), fmt=lambda v: f"{v:.0f}%", key="in-vol")
        self.imute = SwitchRow("Mute microphone", "", False, lambda v: su.spawn("wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "1" if v else "0"), key="in-mute")
        self.idev = PopupRow("Input device", "Which microphone is used", [], None, lambda i: self.set_default(i), key="in-dev")
        self.g_in.add(self.ivol, self.imute, self.idev)
        self.g_str = pb.group("Apps playing sound", "Each app has its own volume.", key="streams")
        self.stream_rows = []
        for g in (self.g_out, self.g_in, self.g_str): g.set_sensitive(False)
        self.refresh()
    def on_show(self):
        if self.pb: self.refresh()
    def refresh(self):
        su.bg(lambda: (su.out("wpctl", "status", timeout=5), get_volume("@DEFAULT_AUDIO_SINK@"), get_volume("@DEFAULT_AUDIO_SOURCE@")), self.fill)
    def fill(self, res):
        if isinstance(res, Exception): return
        text, (ov, om), (iv, im) = res; d = parse_wpctl(text)
        ok = bool(d["sinks"] or d["sources"])
        self.banner_w.set_visible(not ok); self.banner_w.set_no_show_all(ok)
        has_in = bool(d["sources"]); has_out = bool(d["sinks"])
        self.g_out.set_visible(has_out); self.g_in.set_visible(has_in)
        for g in (self.g_out, self.g_in, self.g_str): g.set_sensitive(ok)
        if ov is not None: self.vol.set_value_quiet(ov * 100); self.mute.set_value_quiet(om)
        if iv is not None: self.ivol.set_value_quiet(iv * 100); self.imute.set_value_quiet(im)
        for row, items in ((self.dev, d["sinks"]), (self.idev, d["sources"])):
            row.set_visible(len(items) > 1)
            cur = next((i["id"] for i in items if i["default"]), None)
            row.set_options([(i["id"], i["name"]) for i in items], cur)
        self.g_str.clear(); self.stream_rows = []
        st = [s for s in d["streams"] if s["vol"] is not None]
        self.g_str.set_visible(bool(st))
        for s in st:
            r = SliderRow(s["name"], "", 0, 100, 1, s["vol"] * 100, lambda v, sid=s["id"]: self.set_vol(sid, v), fmt=lambda v: f"{v:.0f}%", key="stream-" + s["id"])
            self.g_str.add(r); r.show_all()
    def set_vol(self, target, v):
        su.spawn("wpctl", "set-volume", "-l", "1.0", target, f"{v/100:.2f}")
    def set_default(self, i):
        su.spawn("wpctl", "set-default", i, done=lambda rc, o: self.refresh())

# ---------------------------------------------------------------- Notifications
class NotificationsPage(Page):
    id = "notifications"; title = "Notifications"; icon = "preferences-system-notifications"; color = "#ff3b30"; group = 1
    keywords = "alerts banners dunst do not disturb focus silence popups"
    entries = (("Do Not Disturb", "focus silence quiet pause alerts", "dnd"), ("Show a test notification", "try preview", "test"), ("Notification history", "clear missed", "history"))
    sub = "Choose when Carpathian OS may interrupt you."
    def available(self): return su.which("dunstctl")
    def build(self, pb):
        self.pb = pb
        g = pb.group("Focus", "While Do Not Disturb is on, notifications are kept quietly and appear in the history when you turn it off.")
        paused = su.out("dunstctl", "is-paused") == "true"
        self.dnd = SwitchRow("Do Not Disturb", "Silence pop-ups until you turn it off", paused, self.on_dnd, icon="weather-clear-night", color="#5e5ce6", key="dnd"); g.add(self.dnd)
        h = pb.group("History")
        self.hist = ButtonRow("Notification history", "", "Clear", self.clear_hist, key="history"); self.hist.add_button("Show last", lambda: su.spawn("dunstctl", "history-pop")); h.add(self.hist)
        self.count_hist()
        t = pb.group("Try it")
        t.add(ButtonRow("Show a test notification", "See how alerts look with your colours and font", "Send", self.test, key="test"))
    def on_dnd(self, v): su.spawn("dunstctl", "set-paused", "true" if v else "false")
    def count_hist(self):
        def work():
            try:
                import json; d = json.loads(su.out("dunstctl", "history") or "{}"); return len(d.get("data", [[]])[0])
            except Exception: return None
        def done(n):
            if isinstance(n, int): self.hist.set_sub("Nothing missed." if n == 0 else f"{n} earlier notification" + ("s" if n != 1 else ""))
        su.bg(work, done)
    def clear_hist(self): su.spawn("dunstctl", "history-clear", done=lambda *_: self.count_hist())
    def test(self):
        if su.which("notify-send"): su.spawn("notify-send", "-a", "Settings", "-i", "preferences-system", "This is how notifications look", "Colours and fonts follow your theme.")
    def on_show(self):
        if hasattr(self, "dnd"): self.dnd.set_value_quiet(su.out("dunstctl", "is-paused") == "true")
PAGES = [SoundPage, NotificationsPage]
