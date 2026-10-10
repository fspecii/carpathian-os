"""The quick-settings model: which tiles exist on this machine, what they say and what a click does. No GTK, tested with FakeSystem."""
from .system import signal_level, fmt_remaining


class Tile:
    __slots__ = ("id", "kind", "title", "subtitle", "glyph", "on", "drill", "toggles", "level")

    def __init__(self, id, kind, title, subtitle="", glyph="dot", on=False, drill=None, toggles=True, level=3):
        self.id, self.kind, self.title, self.subtitle, self.glyph, self.on, self.drill, self.toggles, self.level = id, kind, title, subtitle, glyph, on, drill, toggles, level

    def __repr__(self): return f"Tile({self.id}, on={self.on}, {self.subtitle!r})"


PROFILE_NAMES = {"saver": "Power saver", "balanced": "Balanced", "performance": "Performance"}
PROFILE_GLYPH = {"saver": "leaf", "balanced": "gauge", "performance": "bolt"}


class QuickModel:
    """Snapshot of the system. `refresh()` reads everything cheap; panes load their own data (`load_wifi`, `load_bt`)."""

    def __init__(self, system, media=None, now=None):
        self.sys = system; self.media = media
        self.caps = {}
        self.v = {}
        self.networks = []; self.bt_devices = []; self.sinks = []; self.known = set()
        self.media_state = None
        self.refresh(first=True)

    # ------------------------------------------------------------------ reading
    def refresh(self, first=False):
        s = self.sys
        if first:
            self.caps = dict(wifi=s.has_wifi(), bt=s.has_bluetooth(), dnd=s.dnd() is not None, night=s.night() is not None,
                             airplane=s.airplane() is not None and s.has_wifi(), capture=s.can_screenshot(), profile=s.power_profile() is not None,
                             volume=s.volume() is not None, brightness=s.brightness() is not None, battery=s.battery() is not None)
        v = self.v
        if self.caps["wifi"]:
            v["wifi_on"] = s.wifi_enabled(); a = s.wifi_active() if v["wifi_on"] else None
            v["ssid"] = a["ssid"] if a else ""; v["signal"] = a["signal"] if a else 0
        v["wired"] = s.wired_active() if self.caps["wifi"] or True else False
        if self.caps["bt"]:
            v["bt_on"] = bool(s.bt_enabled())
            v["bt_connected"] = [d["name"] for d in s.bt_devices() if d["connected"]] if v["bt_on"] else []
        if self.caps["dnd"]: v["dnd"] = bool(s.dnd())
        v["dark"] = s.dark()
        if self.caps["night"]: v["night"] = bool(s.night())
        if self.caps["airplane"]: v["airplane"] = bool(s.airplane())
        if self.caps["profile"]: v["profile"] = s.power_profile()
        if self.caps["volume"]: v["vol"], v["muted"] = s.volume()
        if self.caps["brightness"]: v["bright"] = s.brightness()
        v["battery"] = s.battery() if self.caps["battery"] else None
        self.media_state = self.media.state() if self.media else None

    def load_wifi(self, rescan=False):
        self.networks = self.sys.wifi_networks(rescan); self.known = self.sys.wifi_known()
        return self.networks

    def load_bt(self): self.bt_devices = self.sys.bt_devices(); return self.bt_devices
    def load_sinks(self): self.sinks = self.sys.sinks(); return self.sinks

    # ------------------------------------------------------------------ tiles
    def tiles(self):
        v, c = self.v, self.caps; out = []
        if c["wifi"]:
            on = v.get("wifi_on", False)
            sub = v["ssid"] if (on and v.get("ssid")) else ("Not connected" if on else "Off")
            out.append(Tile("wifi", "wide", "Wi-Fi", sub, "wifi" if on else "wifi_off", on, "wifi", True, signal_level(v.get("signal", 0)) if on else 0))
        elif v.get("wired"):
            out.append(Tile("wired", "wide", "Network", "Wired connection", "ethernet", True, None, False))
        if c["bt"]:
            on = v.get("bt_on", False); con = v.get("bt_connected", [])
            sub = (con[0] if len(con) == 1 else f"{len(con)} devices") if con else ("On" if on else "Off")
            out.append(Tile("bt", "wide", "Bluetooth", sub, "bluetooth", on, "bt", True))
        if c["profile"]:
            p = v.get("profile") or "balanced"
            out.append(Tile("power", "wide", "Power mode", PROFILE_NAMES.get(p, p.title()), PROFILE_GLYPH.get(p, "gauge"), p != "balanced", "power", False))
        if c["dnd"]:
            on = v.get("dnd", False)
            out.append(Tile("dnd", "wide", "Do not disturb", "Silenced" if on else "Off", "bell_off" if on else "bell", on, None, True))
        out.append(Tile("dark", "small", "Dark mode", "", "contrast", bool(v.get("dark")), None, True))
        if c["night"]: out.append(Tile("night", "small", "Night light", "", "nightlight", v.get("night", False), None, True))
        if c["airplane"]: out.append(Tile("airplane", "small", "Airplane", "", "airplane", v.get("airplane", False), None, True))
        if c["capture"]: out.append(Tile("capture", "small", "Screenshot", "", "capture", False, None, True))
        return out

    # ------------------------------------------------------------------ actions (optimistic: update snapshot, then talk to the system)
    def toggle(self, tid):
        s, v = self.sys, self.v
        if tid == "wifi": v["wifi_on"] = not v["wifi_on"]; s.wifi_set(v["wifi_on"]); v["ssid"] = v["ssid"] if v["wifi_on"] else ""
        elif tid == "bt": v["bt_on"] = not v["bt_on"]; s.bt_set(v["bt_on"])
        elif tid == "dnd": v["dnd"] = not v["dnd"]; s.dnd_set(v["dnd"])
        elif tid == "dark": v["dark"] = not v["dark"]; s.dark_set(v["dark"])
        elif tid == "night": v["night"] = not v["night"]; s.night_set(v["night"])
        elif tid == "airplane": v["airplane"] = not v["airplane"]; s.airplane_set(v["airplane"]); self.refresh()
        elif tid == "capture": s.screenshot()

    def set_volume(self, pct): self.v["vol"] = int(pct); self.v["muted"] = False if pct > 0 else self.v.get("muted"); self.sys.volume_set(pct)
    def toggle_mute(self): self.v["muted"] = not self.v.get("muted"); self.sys.mute_toggle()
    def set_brightness(self, pct): self.v["bright"] = int(pct); self.sys.brightness_set(pct)
    def set_profile(self, name): self.v["profile"] = name; self.sys.power_profile_set(name)
    def set_sink(self, id_): self.sys.sink_set(id_); self.load_sinks()

    # ------------------------------------------------------------------ text
    def battery_text(self):
        b = self.v.get("battery")
        if not b: return ""
        if b.get("full"): return f"{b['percent']}%  ·  Fully charged"
        rem = fmt_remaining(b.get("seconds"))
        if b["charging"]: return f"{b['percent']}%  \u00b7  " + (f"{rem} to full" if rem else "Charging")
        return f"{b['percent']}%" + (f"  \u00b7  {rem} left" if rem else "")

    def volume_glyph(self):
        if self.v.get("muted") or self.v.get("vol", 0) == 0: return "volume_mute"
        return "volume"

    def volume_level(self):
        vol = self.v.get("vol", 0); return 1 if vol < 34 else 2
