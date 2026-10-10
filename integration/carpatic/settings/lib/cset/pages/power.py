"""Battery and power (carpatic-power) and Lock Screen (carpatic-lockscreen, carpatic-lock)."""
import re, os, glob
from .. import sysutil as su, ui
from ..app import Page
from ..ui import *

def parse_power_status(text):
    d = {}
    for l in text.splitlines():
        if ":" in l:
            k, v = l.split(":", 1); d[k.strip()] = v.strip()
    m = re.match(r"(\d+)%\s*(\w*)", d.get("battery", "")); d["pct"] = int(m.group(1)) if m else None; d["bstate"] = (m.group(2) if m else "").lower()
    d["ac"] = "AC connected" in d.get("battery", ""); d["has_battery"] = bool(m)
    return d

class BatteryPage(Page):
    id = "battery"; title = "Battery"; icon = "battery"; color = "#34c759"; group = 3
    aliases = ("power",)
    keywords = "power energy saver performance profile suspend hibernate sleep lid charge limit laptop"
    entries = (("Power profile", "performance balanced saver energy", "profile"), ("Battery level", "charge percent remaining", "level"), ("Battery health", "capacity wear", "health"),
               ("Stop charging at", "charge limit 80 percent longevity", "limit"), ("Sleep now", "suspend", "suspend"), ("Hibernate", "save to disk swap", "hibernate"),
               ("Hibernate readiness", "swap resume", "hib-state"))
    def available(self): return su.which("carpatic-power")
    def build(self, pb):
        self.pb = pb; d = parse_power_status(su.out("carpatic-power", "status"))
        if d["has_battery"]:
            g = pb.group("Battery")
            self.level = ProgressRow("Battery level", "", (d["pct"] or 0) / 100, f"{d['pct']}%", key="level"); g.add(self.level)
            self.state = InfoRow("Status", self.state_text(d), key="state"); g.add(self.state)
            if "remaining" in d: g.add(InfoRow("Time left", d["remaining"].split(" at ")[0].replace("about ", "About "), key="remaining"))
            if "health" in d: g.add(InfoRow("Battery health", d["health"].replace(" of design capacity", " of its original capacity"), key="health"))
            lim = su.out("carpatic-power", "battery-limit")
            if lim and "not" not in lim.lower() and "unsupported" not in lim.lower() and "no " not in lim.lower()[:4]:
                m = re.search(r"(\d+)", lim)
                sr = SliderRow("Stop charging at", "Keeps the battery healthier over the years", 50, 100, 5, int(m.group(1)) if m else 100, lambda v: self.win.apply(*su.pk("carpatic-power", "battery-limit", str(int(v))), msg="Setting the charge limit..."), fmt=lambda v: f"{v:.0f}%", key="limit")
                g.add(sr)
        prof = d.get("profile", "balanced"); pid = "auto" if prof.startswith("auto") else prof
        g2 = pb.group("Performance", "Automatic uses “performance” when plugged in and “balanced” on battery. Needs your password.")
        self.prof = PopupRow("Power profile", "", [("auto", "Automatic"), ("performance", "Performance"), ("balanced", "Balanced"), ("saver", "Battery saver")], pid, self.set_profile, icon="speedometer", color="#ff9f0a", key="profile")
        g2.add(self.prof)
        g3 = pb.group("Sleep")
        sl = d.get("sleep", "")
        if "suspend" in sl: g3.add(ButtonRow("Sleep now", "Keeps your session in memory", "Sleep", lambda: su.spawn("carpatic-power", "suspend"), key="suspend"))
        ready = d.get("hibernate", "").startswith("ready")
        if "hibernate [yes]" in sl or ready or "hibernate" in sl:
            g3.add(StatusRow("Hibernate readiness", "Ready" if ready else "Not set up", "ok" if ready else "warn", "Saves everything to disk and switches off completely" if ready else "Needs a swap file big enough for your memory", key="hib-state"))
            if ready: g3.add(ButtonRow("Hibernate", "Saves your session to disk and powers off", "Hibernate", lambda: su.spawn("carpatic-power", "hibernate"), key="hibernate"))
            else: g3.add(ButtonRow("Set up hibernate", "Creates the swap file and tells the boot loader (takes a minute)", "Set up", lambda: self.win.apply(*su.pk("carpatic-power", "hibernate-setup"), msg="Setting up hibernate...", done=lambda *_: self.refresh()), "suggested", key="hib-setup"))
        self.dd = d
    def state_text(self, d):
        s = {"charging": "Charging", "discharging": "On battery", "full": "Fully charged"}.get(d["bstate"], "Plugged in" if d["ac"] else "On battery")
        return s
    def set_profile(self, v):
        self.win.apply(*su.pk("carpatic-power", "profile", v), msg="Changing the power profile...")
    def refresh(self):
        pass
    def on_show(self):
        if not self.pb: return
        d = parse_power_status(su.out("carpatic-power", "status"))
        if d["has_battery"] and hasattr(self, "level"): self.level.set_fraction(d["pct"] / 100, f"{d['pct']}%"); self.state.set_value(self.state_text(d))

class LockPage(Page):
    id = "lock"; title = "Lock Screen"; icon = "system-lock-screen"; color = "#8e8e93"; group = 3
    keywords = "password screensaver idle timeout screen off sleep security lock now"
    entries = (("Lock after", "idle automatic timeout minutes", "lock-after"), ("Turn the screen off after", "dpms blank monitor", "off-after"), ("Lock when going to sleep", "suspend lid", "lock-sleep"), ("Lock now", "secure", "lock-now"))
    optional = frozenset({"lock-now", "lock-after", "off-after", "lock-sleep"})
    def available(self): return su.which("carpatic-lockscreen") or su.which("carpatic-lock")
    def build(self, pb):
        st = su.kv_lines("carpatic-lockscreen", "status") if su.which("carpatic-lockscreen") else {}
        opts = [("1", "1 minute"), ("2", "2 minutes"), ("5", "5 minutes"), ("10", "10 minutes"), ("15", "15 minutes"), ("30", "30 minutes"), ("60", "1 hour"), ("never", "Never")]
        g = pb.group("Automatic")
        if su.which("carpatic-lockscreen"):
            la = st.get("lock-after", "10"); oa = st.get("screen-off-after", "5")
            g.add(PopupRow("Lock after", "Ask for your password after no activity for", opts, la if la in dict(opts) else "10", lambda v: self.win.apply("carpatic-lockscreen", "lock-after", v, msg="Saving..."), key="lock-after", icon="system-lock-screen", color="#8e8e93"),
                  PopupRow("Turn the screen off after", "Counted after the screen locks", [o for o in opts if o[0] != "1"] , oa if oa in dict(opts) else "5", lambda v: self.win.apply("carpatic-lockscreen", "screen-off-after", v, msg="Saving..."), key="off-after", icon="video-display", color="#0a84ff"))
        if su.which("carpatic-power"):
            lock_sleep = (st.get("lock-on-sleep", "yes") != "no")
            g.add(InfoRow("Lock when going to sleep", "On" if lock_sleep else "Off", "Always, so nobody can open the lid and see your work" if lock_sleep else "", key="lock-sleep"))
        if su.which("carpatic-lock"):
            g2 = pb.group()
            g2.add(ButtonRow("Lock now", "Super + L", "Lock", lambda: su.spawn("carpatic-lock"), key="lock-now"))

PAGES = [BatteryPage, LockPage]
