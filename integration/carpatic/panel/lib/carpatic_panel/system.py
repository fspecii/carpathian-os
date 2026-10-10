"""System backends for the quick settings (Wi-Fi, Bluetooth, volume, brightness, battery, power profile, do not disturb, dark mode, night light).

Every method returns None (or an empty list) when the hardware or tool is missing, so the UI simply hides that control. All shelling out goes
through `self.run` so tests and screenshots use `FakeSystem` and never touch the real machine. No GTK imports here."""
import os, re, shutil, subprocess, glob, json, time


def have(cmd): return shutil.which(cmd) is not None


def _run(cmd, timeout=4, env=None):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except (OSError, subprocess.TimeoutExpired):
        return 127, "", ""


# ----------------------------------------------------------------------------- pure parsers (unit tested)
def split_nmcli(line):
    """nmcli -t escapes ':' as '\\:' and '\\' as '\\\\'."""
    out, cur, i = [], "", 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line): cur += line[i + 1]; i += 2; continue
        if ch == ":": out.append(cur); cur = ""
        else: cur += ch
        i += 1
    out.append(cur)
    return out


def parse_wifi_list(text):
    """`nmcli -t -f IN-USE,SSID,SIGNAL,SECURITY,BSSID dev wifi list` -> strongest AP per SSID, active first, then by signal."""
    best = {}
    for line in text.splitlines():
        f = split_nmcli(line)
        if len(f) < 4 or not f[1].strip(): continue
        ssid = f[1]; sig = int(f[2]) if f[2].isdigit() else 0
        ap = dict(ssid=ssid, signal=sig, secure=f[3].strip() not in ("", "--"), active=f[0].strip() == "*", security=f[3].strip())
        old = best.get(ssid)
        if old is None or ap["active"] or (not old["active"] and sig > old["signal"]): best[ssid] = ap
    return sorted(best.values(), key=lambda a: (not a["active"], -a["signal"], a["ssid"].lower()))


def signal_level(pct):
    """0..3 bars for the wifi glyph."""
    return 0 if pct < 5 else 1 if pct < 35 else 2 if pct < 65 else 3


def parse_wpctl_volume(text):
    """'Volume: 0.45 [MUTED]' -> (45, muted)"""
    m = re.search(r"Volume:\s*([0-9.]+)", text)
    if not m: return None
    return int(round(float(m.group(1)) * 100)), "[MUTED]" in text


def parse_wpctl_sinks(text):
    """Sinks block of `wpctl status` -> [(id, name, is_default)]."""
    out, in_sinks = [], False
    for line in text.splitlines():
        if re.match(r"\s*[├└│\s]*─?\s*Sinks:", line) or re.search(r"Sinks:\s*$", line): in_sinks = True; continue
        if in_sinks and re.search(r"(Sources|Filters|Streams|Video|Settings):", line): break
        if in_sinks:
            m = re.search(r"(\*)?\s*(\d+)\.\s+(.+?)\s*(\[vol:.*\])?\s*$", line.replace("│", " ").replace("├", " ").replace("└", " ").replace("─", " "))
            if m: out.append((int(m.group(2)), m.group(3).strip(), bool(m.group(1))))
    return out


def parse_bt_devices(text, info):
    """`bluetoothctl devices` lines plus a {mac: info-text} map -> [dict(mac,name,connected,paired,icon)]"""
    devs = []
    for line in text.splitlines():
        m = re.match(r"Device\s+([0-9A-F:]{17})\s+(.+)$", line.strip(), re.I)
        if not m: continue
        mac, name = m.group(1), m.group(2)
        inf = info.get(mac, "")
        devs.append(dict(mac=mac, name=name, connected="Connected: yes" in inf, paired="Paired: yes" in inf,
                         icon=(re.search(r"Icon:\s*(\S+)", inf) or [None, ""])[1]))
    return sorted(devs, key=lambda d: (not d["connected"], not d["paired"], d["name"].lower()))


def read_battery(root=""):
    """Returns dict(percent, charging, full, time) from /sys/class/power_supply, or None on a desktop."""
    base = root + "/sys/class/power_supply"
    bats = sorted(glob.glob(base + "/BAT*"))
    if not bats: return None
    def rd(p, d=""):
        try:
            with open(p) as f: return f.read().strip()
        except OSError: return d
    b = bats[0]
    cap = rd(b + "/capacity"); st = rd(b + "/status", "Unknown")
    pct = int(cap) if cap.isdigit() else None
    if pct is None: return None
    t = None
    try:
        now = int(rd(b + "/energy_now") or rd(b + "/charge_now") or 0); rate = int(rd(b + "/power_now") or rd(b + "/current_now") or 0)
        full = int(rd(b + "/energy_full") or rd(b + "/charge_full") or 0)
        if rate > 0:
            t = (full - now) / rate * 3600 if st == "Charging" else now / rate * 3600
    except ValueError:
        t = None
    return dict(percent=pct, charging=st == "Charging", full=st == "Full" or (pct >= 99 and st != "Discharging"), seconds=t, status=st)


def fmt_remaining(sec):
    if not sec or sec <= 0 or sec > 48 * 3600: return ""
    h, m = int(sec // 3600), int(sec % 3600 // 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


# ----------------------------------------------------------------------------- real backend
class System:
    """Real machine. Cheap probes; callers run them off the UI thread (see flyout_quick)."""

    def __init__(self, run=None, root="", state=None, cfg=None):
        self.run = run or _run
        self.root = root
        self.state = state or os.environ.get("CARPATIC_STATE", os.path.expanduser("~/.local/state/carpatic"))
        self.cfg = cfg or os.environ.get("CARPATIC_CONFIG", os.path.expanduser("~/.config/carpatic"))

    # ---- capabilities (what to show)
    def has_wifi(self):
        if not have("nmcli"): return False
        rc, out, _ = self.run(["nmcli", "-t", "-f", "TYPE", "device"])
        return "wifi" in out.split()

    def has_bluetooth(self):
        if not (have("rfkill") or have("bluetoothctl")): return False
        rc, out, _ = self.run(["rfkill", "list", "bluetooth"]) if have("rfkill") else (1, "", "")
        return bool(out)

    # ---- wifi
    def wifi_enabled(self):
        rc, out, _ = self.run(["nmcli", "radio", "wifi"]); return out == "enabled"

    def wifi_set(self, on): self.run(["nmcli", "radio", "wifi", "on" if on else "off"])

    def wifi_networks(self, rescan=False):
        rc, out, _ = self.run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list", "--rescan", "yes" if rescan else "no"], timeout=12)
        return parse_wifi_list(out) if rc == 0 else []

    def wifi_active(self):
        for a in self.wifi_networks():
            if a["active"]: return a
        return None

    def wifi_known(self):
        rc, out, _ = self.run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"])
        return {split_nmcli(l)[0] for l in out.splitlines() if "wireless" in l}

    def wifi_connect(self, ssid, password=None):
        cmd = ["nmcli", "--wait", "20", "dev", "wifi", "connect", ssid] + (["password", password] if password else [])
        rc, out, err = self.run(cmd, timeout=30)
        if rc == 0: return True, f"Connected to {ssid}."
        low = (err + out).lower()
        if "secrets" in low or "password" in low or "802.1x" in low: return False, "That password did not work. Check it and try again."
        if "no network" in low or "not found" in low: return False, f"{ssid} is out of range."
        return False, "Could not connect. Try again in a moment."

    def wifi_disconnect(self):
        rc, out, _ = self.run(["nmcli", "-t", "-f", "DEVICE,TYPE", "device"])
        for l in out.splitlines():
            f = split_nmcli(l)
            if len(f) > 1 and f[1] == "wifi": self.run(["nmcli", "device", "disconnect", f[0]])

    def wired_active(self):
        rc, out, _ = self.run(["nmcli", "-t", "-f", "TYPE,STATE", "device"])
        return any(split_nmcli(l)[:2] == ["ethernet", "connected"] for l in out.splitlines())

    # ---- bluetooth
    def bt_enabled(self):
        rc, out, _ = self.run(["rfkill", "list", "bluetooth"])
        if not out: return None
        return "Soft blocked: no" in out and "Hard blocked: no" in out

    def bt_set(self, on):
        self.run(["rfkill", "unblock" if on else "block", "bluetooth"])
        if on and have("bluetoothctl"): self.run(["bluetoothctl", "power", "on"])

    def bt_devices(self):
        if not have("bluetoothctl"): return []
        rc, out, _ = self.run(["bluetoothctl", "devices"])
        info = {}
        for l in out.splitlines():
            m = re.match(r"Device\s+([0-9A-F:]{17})", l.strip(), re.I)
            if m: info[m.group(1)] = self.run(["bluetoothctl", "info", m.group(1)])[1]
        return parse_bt_devices(out, info)

    def bt_toggle_device(self, mac, connect):
        rc, out, err = self.run(["bluetoothctl", "connect" if connect else "disconnect", mac], timeout=15)
        return rc == 0 and "Failed" not in out

    # ---- do not disturb, dark mode, night light, airplane
    def dnd(self):
        if not have("dunstctl"): return None
        return self.run(["dunstctl", "is-paused"])[1] == "true"

    def dnd_set(self, on): self.run(["dunstctl", "set-paused", "true" if on else "false"])

    def dark(self):
        pal = {}
        try:
            for line in open(os.path.join(self.state, "current", "colors.toml")):
                m = re.match(r'\s*mode\s*=\s*"(\w+)"', line)
                if m: return m.group(1) != "light"
        except OSError:
            pass
        return True

    def dark_set(self, dark): self.run(["carpatic-theme", "set", "carpatic" if dark else "carpatic-light"]) if have("carpatic-theme") else None

    def night(self):
        if not (have("redshift") or have("sct") or have("gammastep")): return None
        return os.path.exists(os.path.join(self.state, "nightlight"))

    def night_set(self, on):
        flag = os.path.join(self.state, "nightlight"); os.makedirs(self.state, exist_ok=True)
        if on:
            open(flag, "w").close(); self.run(["sct", "3500"]) if have("sct") else self.run(["redshift", "-O", "3500", "-P"])
        else:
            try: os.unlink(flag)
            except OSError: pass
            self.run(["sct"]) if have("sct") else self.run(["redshift", "-x"])

    def airplane(self):
        if not have("nmcli"): return None
        w = self.run(["nmcli", "radio", "wifi"])[1]
        if not w: return None
        return w != "enabled" and self.bt_enabled() is not True

    def airplane_set(self, on): self.run(["carpatic-radio", "airplane"]) if have("carpatic-radio") else self.run(["nmcli", "radio", "all", "off" if on else "on"])

    # ---- power
    def battery(self): return read_battery(self.root)

    def power_profile(self):
        if have("carpatic-power"):
            rc, out, _ = self.run(["carpatic-power", "status"])
            m = re.search(r"profile\W+(performance|balanced|saver)", out, re.I)
            if m: return m.group(1).lower()
        if have("powerprofilesctl"):
            out = self.run(["powerprofilesctl", "get"])[1]
            return {"power-saver": "saver", "balanced": "balanced", "performance": "performance"}.get(out)
        return None

    def power_profile_set(self, name):
        if have("carpatic-power"): self.run(["carpatic-power", "profile", name], timeout=10)
        elif have("powerprofilesctl"): self.run(["powerprofilesctl", "set", {"saver": "power-saver"}.get(name, name)])

    # ---- audio
    def volume(self):
        if have("wpctl"):
            r = parse_wpctl_volume(self.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])[1])
            if r: return r
        if have("pamixer"):
            v = self.run(["pamixer", "--get-volume"])[1]
            if v.isdigit(): return int(v), self.run(["pamixer", "--get-mute"])[1] == "true"
        return None

    def volume_set(self, pct):
        if have("wpctl"): self.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{max(0, min(100, int(pct)))}%"])
        elif have("pamixer"): self.run(["pamixer", "--set-volume", str(int(pct))])

    def mute_toggle(self):
        if have("wpctl"): self.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"])
        elif have("pamixer"): self.run(["pamixer", "-t"])

    def sinks(self):
        if not have("wpctl"): return []
        return parse_wpctl_sinks(self.run(["wpctl", "status"])[1])

    def sink_set(self, id_): self.run(["wpctl", "set-default", str(id_)])

    # ---- display
    def brightness(self):
        if not have("brightnessctl"): return None
        try: return int(self.run(["brightnessctl", "-c", "backlight", "-m"])[1].split(",")[3].rstrip("%"))
        except (IndexError, ValueError): return None

    def brightness_set(self, pct): self.run(["brightnessctl", "-c", "backlight", "set", f"{max(int(pct), 3)}%"])

    # ---- capture
    def screenshot(self): self.run(["carpatic-screenshot", "region"]) if have("carpatic-screenshot") else None
    def can_screenshot(self): return have("carpatic-screenshot") or have("maim")

    # ---- session
    def spawn(self, *cmd):
        try: subprocess.Popen(list(cmd), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError: pass


class FakeSystem:
    """Deterministic stand-in: used by unit tests and the screenshot harness."""

    def __init__(self, **kw):
        self.log = []
        self.s = dict(wifi=True, wifi_on=True, ssid="Carpathian-5G", signal=78, bt=True, bt_on=True, dnd=False, dark=True, night=False, airplane=False,
                      vol=(42, False), bright=64, battery=dict(percent=84, charging=True, full=False, seconds=2400, status="Charging"),
                      profile="balanced", sinks=[(51, "Built-in Audio Analog Stereo", True), (62, "HDMI / DisplayPort 1", False), (70, "WH-1000XM5", False)],
                      nets=[dict(ssid="Carpathian-5G", signal=78, secure=True, active=True, security="WPA2"), dict(ssid="Cafe Bucegi", signal=61, secure=False, active=False, security=""),
                            dict(ssid="Vecini_2.4", signal=44, secure=True, active=False, security="WPA2"), dict(ssid="DIRECT-roku-8F3", signal=20, secure=True, active=False, security="WPA2")],
                      btdevs=[dict(mac="AA:BB:CC:00:11:22", name="WH-1000XM5", connected=True, paired=True, icon="audio-headphones"),
                              dict(mac="AA:BB:CC:00:11:33", name="MX Keys", connected=False, paired=True, icon="input-keyboard"),
                              dict(mac="AA:BB:CC:00:11:44", name="Pixel Buds", connected=False, paired=True, icon="audio-headset")],
                      capture=True, known={"Carpathian-5G", "Cafe Bucegi"})
        self.s.update(kw)

    def _l(self, *a): self.log.append(a)
    def has_wifi(self): return self.s["wifi"]
    def has_bluetooth(self): return self.s["bt"]
    def wifi_enabled(self): return self.s["wifi_on"]
    def wifi_set(self, on): self.s["wifi_on"] = on; self._l("wifi", on)
    def wifi_networks(self, rescan=False): return list(self.s["nets"]) if self.s["wifi_on"] else []
    def wifi_active(self): return next((n for n in self.wifi_networks() if n["active"]), None)
    def wifi_known(self): return set(self.s["known"])
    def wifi_connect(self, ssid, password=None):
        self._l("connect", ssid, password)
        net = next((n for n in self.s["nets"] if n["ssid"] == ssid), None)
        if net is None: return False, f"{ssid} is out of range."
        if net["secure"] and ssid not in self.s["known"] and password != "correct-horse": return False, "That password did not work. Check it and try again."
        for n in self.s["nets"]: n["active"] = n["ssid"] == ssid
        self.s["known"].add(ssid); return True, f"Connected to {ssid}."
    def wifi_disconnect(self):
        for n in self.s["nets"]: n["active"] = False
        self._l("wifi-disconnect")
    def wired_active(self): return False
    def bt_enabled(self): return self.s["bt_on"] if self.s["bt"] else None
    def bt_set(self, on): self.s["bt_on"] = on; self._l("bt", on)
    def bt_devices(self): return [dict(d) for d in self.s["btdevs"]] if self.s["bt_on"] else []
    def bt_toggle_device(self, mac, connect):
        for d in self.s["btdevs"]:
            if d["mac"] == mac: d["connected"] = connect
        self._l("btdev", mac, connect); return True
    def dnd(self): return self.s["dnd"]
    def dnd_set(self, on): self.s["dnd"] = on; self._l("dnd", on)
    def dark(self): return self.s["dark"]
    def dark_set(self, d): self.s["dark"] = d; self._l("dark", d)
    def night(self): return self.s["night"]
    def night_set(self, on): self.s["night"] = on; self._l("night", on)
    def airplane(self): return self.s["airplane"]
    def airplane_set(self, on): self.s["airplane"] = on; self._l("airplane", on)
    def battery(self): return self.s["battery"]
    def power_profile(self): return self.s["profile"]
    def power_profile_set(self, n): self.s["profile"] = n; self._l("profile", n)
    def volume(self): return self.s["vol"]
    def volume_set(self, p): self.s["vol"] = (int(p), self.s["vol"][1]); self._l("vol", int(p))
    def mute_toggle(self): self.s["vol"] = (self.s["vol"][0], not self.s["vol"][1]); self._l("mute")
    def sinks(self): return list(self.s["sinks"])
    def sink_set(self, i): self.s["sinks"] = [(a, b, a == i) for a, b, _ in self.s["sinks"]]; self._l("sink", i)
    def brightness(self): return self.s["bright"]
    def brightness_set(self, p): self.s["bright"] = int(p); self._l("bright", int(p))
    def can_screenshot(self): return self.s["capture"]
    def screenshot(self): self._l("screenshot")
    def spawn(self, *cmd): self._l("spawn", *cmd)
