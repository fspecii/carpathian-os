"""Data providers. Every provider reads from a root/path or a function you can replace, so the unit tests run on fakes and the host never
needs root. No GTK imports here (MPRIS glue lives in host.py, the parsing lives here)."""
import calendar as _cal, datetime, glob, json, os, re, shutil, subprocess, time, urllib.parse
from collections import deque
from . import conf

# ---------------------------------------------------------------- calendar
def month_grid(year, month, first_weekday=0):
    """Rows of 7 day numbers (0 = outside the month). first_weekday 0 = Monday, 6 = Sunday."""
    return _cal.Calendar(first_weekday).monthdayscalendar(year, month)


def weekday_names(first_weekday=0):
    names = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]; return names[first_weekday:] + names[:first_weekday]


def parse_ics(text, today=None, days=30):
    """Very small .ics reader: SUMMARY and DTSTART of VEVENTs in the next `days` days (no recurrence rules; honest and enough for an agenda)."""
    today = today or datetime.date.today(); out = []
    for blk in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text.replace("\r\n ", "").replace("\r", ""), re.S):
        s = re.search(r"^SUMMARY[^:]*:(.*)$", blk, re.M); d = re.search(r"^DTSTART[^:]*:(\d{8})(?:T(\d{4}))?", blk, re.M)
        if not (s and d): continue
        try: day = datetime.datetime.strptime(d.group(1), "%Y%m%d").date()
        except ValueError: continue
        if 0 <= (day - today).days <= days:
            out.append((day, (d.group(2) or "")[:4], s.group(1).strip().replace("\\,", ",")))
    return sorted(out)


def read_events(today=None, path=None):
    try: return parse_ics(open(path or os.path.join(conf.DATA, "calendar.ics"), errors="replace").read(), today)
    except OSError: return []

# ---------------------------------------------------------------- system monitor
class SysMon:
    """CPU %, RAM, disk, network rates and temperature from /proc and /sys. `root` can point at a fake tree."""
    def __init__(self, root="", disk_path="/", clock=time.monotonic):
        self.root, self.disk_path, self.clock = root, disk_path, clock
        self.prev_cpu = None; self.prev_net = None; self.prev_t = None
        self.cpu = 0.0; self.rx = 0.0; self.tx = 0.0
        self.hist_cpu = deque([0.0] * 30, maxlen=30); self.hist_net = deque([0.0] * 30, maxlen=30)

    def _read(self, p):
        try: return open(self.root + p).read()
        except OSError: return ""

    def sample(self):
        t = self.clock()
        parts = (self._read("/proc/stat").split("\n", 1)[0].split()[1:] or ["0"] * 8)
        v = [int(x) for x in parts[:8]]; idle = v[3] + (v[4] if len(v) > 4 else 0); total = sum(v)
        if self.prev_cpu and total > self.prev_cpu[1]:
            self.cpu = max(0.0, min(100.0, 100.0 * (1 - (idle - self.prev_cpu[0]) / (total - self.prev_cpu[1]))))
        self.prev_cpu = (idle, total)
        rx = tx = 0
        for line in self._read("/proc/net/dev").splitlines()[2:]:
            if ":" not in line: continue
            name, rest = line.split(":", 1)
            if name.strip() == "lo": continue
            f = rest.split()
            if len(f) >= 9: rx += int(f[0]); tx += int(f[8])
        if self.prev_net and t > self.prev_t:
            dt = t - self.prev_t; self.rx = max(0.0, (rx - self.prev_net[0]) / dt); self.tx = max(0.0, (tx - self.prev_net[1]) / dt)
        self.prev_net, self.prev_t = (rx, tx), t
        self.hist_cpu.append(self.cpu); self.hist_net.append(self.rx + self.tx)
        return self

    def mem(self):
        d = {}
        for line in self._read("/proc/meminfo").splitlines():
            k, _, rest = line.partition(":"); n = rest.split()
            if n: d[k] = int(n[0]) * 1024
        tot = d.get("MemTotal", 0); av = d.get("MemAvailable", d.get("MemFree", 0)); return tot - av, tot

    def disk(self):
        try: u = shutil.disk_usage(self.root + self.disk_path); return u.used, u.total
        except OSError: return 0, 0

    def temp(self):
        """Hottest sensor in degrees C or None (many VMs have none: the card then says so instead of showing 0)."""
        best = None
        for f in glob.glob(self.root + "/sys/class/hwmon/hwmon*/temp*_input") + glob.glob(self.root + "/sys/class/thermal/thermal_zone*/temp"):
            try: v = int(open(f).read().strip()) / 1000.0
            except (OSError, ValueError): continue
            if 0 < v < 130: best = v if best is None else max(best, v)
        return best


def human_bytes(n):
    n = float(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or u == "TB": return (f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}" if n < 100 else f"{n:.0f} {u}")
        n /= 1000.0


def human_rate(n):
    return human_bytes(n) + "/s"

# ---------------------------------------------------------------- battery
def battery(root=""):
    """(percent, state, minutes_left or None) of the first battery, or None on a desktop PC."""
    for d in sorted(glob.glob(root + "/sys/class/power_supply/BAT*")):
        def rd(n):
            try: return open(os.path.join(d, n)).read().strip()
            except OSError: return ""
        try: pct = int(rd("capacity"))
        except ValueError: continue
        st = rd("status") or "Unknown"; mins = None
        try:
            now = int(rd("energy_now") or rd("charge_now") or 0); full = int(rd("energy_full") or rd("charge_full") or 0)
            rate = int(rd("power_now") or rd("current_now") or 0)
            if rate > 0:
                mins = int(60 * (full - now) / rate) if st == "Charging" else int(60 * now / rate) if st == "Discharging" else None
        except ValueError: pass
        return pct, st, mins
    return None


def power_profile():
    try: out = subprocess.run(["carpatic-power", "profile"], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError): return ""
    m = re.search(r"(performance|balanced|saver|power-saver)", out); return m.group(1) if m else ""

# ---------------------------------------------------------------- weather (Open-Meteo, no key)
WMO = {0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Cloudy", 45: "Fog", 48: "Fog", 51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
       56: "Freezing drizzle", 57: "Freezing drizzle", 61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
       71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains", 80: "Showers", 81: "Showers", 82: "Heavy showers", 85: "Snow showers",
       86: "Snow showers", 95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with hail"}


def wmo_kind(code):
    """Icon family for drawing: sun, cloud, rain, snow, storm, fog."""
    if code in (0, 1): return "sun"
    if code in (2, 3): return "cloud"
    if code in (45, 48): return "fog"
    if code in (71, 73, 75, 77, 85, 86): return "snow"
    if code in (95, 96, 99): return "storm"
    return "rain"


def weather_url(lat, lon, units="c"):
    q = dict(latitude=f"{lat:.3f}", longitude=f"{lon:.3f}", current="temperature_2m,weather_code,wind_speed_10m,is_day",
             daily="weather_code,temperature_2m_max,temperature_2m_min", timezone="auto", forecast_days=4)
    if units == "f": q.update(temperature_unit="fahrenheit", wind_speed_unit="mph")
    return "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(q)


def parse_weather(js):
    cur = js["current"]; dl = js["daily"]
    return dict(temp=round(cur["temperature_2m"]), code=int(cur["weather_code"]), wind=round(cur.get("wind_speed_10m", 0)), day=bool(cur.get("is_day", 1)),
                days=[dict(date=dl["time"][i], code=int(dl["weather_code"][i]), hi=round(dl["temperature_2m_max"][i]), lo=round(dl["temperature_2m_min"][i]))
                      for i in range(len(dl["time"]))])


def http_get(url, timeout=8):
    import urllib.request          # imported on first use: ssl + http.client cost about 3 MB the host does not need until a forecast is fetched
    req = urllib.request.Request(url, headers={"User-Agent": "carpatic-widgets/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r: return r.read().decode("utf-8", "replace")


class Weather:
    """Fetch + cache. Offline-safe: a failed fetch keeps the last good answer and says how old it is. `fetch` and `now` are replaceable."""
    def __init__(self, cfg, fetch=http_get, now=time.time, cache=None):
        self.cfg, self.fetch, self.now = cfg, fetch, now
        self.cache = cache or os.path.join(conf.DATA, "weather.json"); self.data = None; self.stamp = 0; self.error = ""
        try:
            d = json.load(open(self.cache)); self.data, self.stamp = d["data"], d["stamp"]
        except (OSError, ValueError, KeyError): pass

    def located(self): return "lat" in self.cfg and "lon" in self.cfg

    def refresh(self, force=False):
        """Blocking network call: run it off the UI thread. Returns True when fresh data arrived."""
        if not self.located(): self.error = "nolocation"; return False
        if not force and self.data and self.now() - self.stamp < 1500: return False
        try:
            self.data = parse_weather(json.loads(self.fetch(weather_url(self.cfg["lat"], self.cfg["lon"], self.cfg.get("units", "c")))))
            self.stamp = self.now(); self.error = ""
            conf.atomic_write(self.cache, json.dumps(dict(data=self.data, stamp=self.stamp)))
            return True
        except (OSError, ValueError, KeyError, TypeError):
            self.error = "offline"; return False

    def age_text(self):
        if not self.data: return ""
        m = int((self.now() - self.stamp) / 60)
        return "just now" if m < 2 else f"{m} min ago" if m < 90 else f"{m // 60} h ago"


def geocode(city, fetch=http_get):
    """City name -> (name, lat, lon, country) with Open-Meteo's geocoder (no key). Raises conf.Error with friendly text."""
    try:
        js = json.loads(fetch("https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(dict(name=city, count=1, language="en", format="json"))))
    except (OSError, ValueError): raise conf.Error("Could not reach the weather service. Check your internet connection and try again.")
    r = (js.get("results") or [None])[0]
    if not r: raise conf.Error(f"No place called '{city}' was found. Try the city name only.")
    return r["name"], r["latitude"], r["longitude"], r.get("country", "")


def locate_by_ip(fetch=http_get):
    """Approximate location from the IP address. Only ever called after the user said yes (Settings > Widgets or `weather locate --yes`)."""
    try: js = json.loads(fetch("https://ipwho.is/"))
    except (OSError, ValueError): raise conf.Error("Could not work out where you are. Type your city instead.")
    if not js.get("success", True) or "latitude" not in js: raise conf.Error("Could not work out where you are. Type your city instead.")
    return js.get("city", "Here"), js["latitude"], js["longitude"], js.get("country", "")

# ---------------------------------------------------------------- notes, to-do, tips
def notes_path(): return os.path.join(conf.DATA, "notes.txt")
def todo_path(): return os.path.join(conf.DATA, "todo.json")


def read_notes():
    try: return open(notes_path()).read()
    except OSError: return ""


def write_notes(t): conf.atomic_write(notes_path(), t)


def read_todo():
    try:
        d = json.load(open(todo_path()))
        return [dict(t=str(i["t"]), done=bool(i.get("done"))) for i in d if isinstance(i, dict) and "t" in i]
    except (OSError, ValueError, TypeError): return []


def write_todo(items): conf.atomic_write(todo_path(), json.dumps(items, indent=1) + "\n")


def toggle_todo(i):
    items = read_todo()
    if 0 <= i < len(items): items[i]["done"] = not items[i]["done"]; write_todo(items)
    return items


TIPS = [
    "Super+Space opens the launcher. Type a few letters of any app or file.",
    "Super+F1 shows every keyboard shortcut of your desktop style.",
    "Super+F2 opens Carpathian Settings: style, colours, fonts, icons and more.",
    "Run `carpatic theme` in a terminal to try any colour theme in one command.",
    "Super+Ctrl+Space changes the wallpaper; the colours follow if you want them to.",
    "Press Print Screen for a region screenshot, Shift+Print for the whole screen.",
    "`carpatic install <app>` installs from Alpine or Flathub; `carpatic remove` takes it away.",
    "Your files stay yours: nothing leaves this computer unless you start it.",
    "The power profile (performance, balanced, saver) is one click in Battery and power.",
    "Drag a widget in edit mode; it snaps to the grid and remembers its place.",
    "Super+Alt+Space opens the Carpathian menu with everything in one list.",
    "Light or dark? `carpatic theme set carpatic-light` switches the whole desktop.",
    "Hold Super and drag a window to move it; Super+right-drag resizes it.",
    "`carpatic widgets disable` turns every widget off and leaves no process behind.",
    "Notes and to-dos are plain files in ~/.local/share/carpatic/widgets: back them up like any file.",
    "The Nothing theme draws its clock with dots, just like the Nothing phones.",
]


def tip_of_day(day=None, offset=0):
    day = day or datetime.date.today(); return TIPS[(day.toordinal() + offset) % len(TIPS)]

# ---------------------------------------------------------------- now playing (parsing only)
def parse_mpris(meta, status, position_us=0, identity=""):
    """MPRIS Metadata (plain dict of Python values) -> what the card needs."""
    title = str(meta.get("xesam:title", "") or ""); art = meta.get("xesam:artist", "")
    artist = ", ".join(art) if isinstance(art, (list, tuple)) else str(art or "")
    length = int(meta.get("mpris:length", 0) or 0); url = str(meta.get("mpris:artUrl", "") or "")
    art_path = urllib.parse.unquote(url[7:]) if url.startswith("file://") else ""
    return dict(title=title or identity or "Unknown", artist=artist or identity, album=str(meta.get("xesam:album", "") or ""), art=art_path,
                playing=(status == "Playing"), status=status, length=length / 1e6, position=position_us / 1e6, player=identity)

# ---------------------------------------------------------------- quick toggles
def _run(cmd, timeout=3):
    try: r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout); return r.returncode, r.stdout.strip()
    except (OSError, subprocess.SubprocessError): return 127, ""


def _have(c): return shutil.which(c) is not None


class Toggle:
    def __init__(self, tid, label, probe, act, kind="switch"):
        self.id, self.label, self.probe, self.act, self.kind = tid, label, probe, act, kind
    def state(self):
        """True/False for switches, 0..100 for sliders, None when this computer cannot do it."""
        try: return self.probe()
        except Exception: return None


def _wifi():
    if not _have("nmcli"): return None
    rc, o = _run(["nmcli", "radio", "wifi"]); return o == "enabled" if rc == 0 else None
def _bt():
    if not _have("rfkill"): return None
    rc, o = _run(["rfkill", "list", "bluetooth"]); return None if rc or not o else ("Soft blocked: yes" not in o)
def _dnd():
    if not _have("dunstctl"): return None
    rc, o = _run(["dunstctl", "is-paused"]); return o == "true" if rc == 0 else None
def _night():
    if not (_have("redshift") or _have("sct") or _have("gammastep")): return None
    return os.path.exists(os.path.join(conf.STATE, "nightlight"))
def _vol():
    if _have("wpctl"):
        rc, o = _run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"]); m = re.search(r"([\d.]+)", o)
        return int(float(m.group(1)) * 100) if rc == 0 and m else None
    if _have("pactl"):
        rc, o = _run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"]); m = re.search(r"(\d+)%", o); return int(m.group(1)) if rc == 0 and m else None
    return None
def _bright():
    if not _have("brightnessctl"): return None
    rc, o = _run(["brightnessctl", "-m"]); p = o.split(",")
    return int(p[3].rstrip("%")) if rc == 0 and len(p) > 3 and p[3].rstrip("%").isdigit() else None


def _act_night(_v=None):
    flag = os.path.join(conf.STATE, "nightlight"); os.makedirs(conf.STATE, exist_ok=True)
    if os.path.exists(flag):
        os.unlink(flag); _run(["sct"]) if _have("sct") else _run(["redshift", "-x"])
    else:
        open(flag, "w").close(); _run(["sct", "3500"]) if _have("sct") else _run(["redshift", "-O", "3500"])


def _setvol(v):
    if _have("wpctl"): _run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{int(v)}%"])
    elif _have("pactl"): _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{int(v)}%"])


TOGGLES = [
    Toggle("wifi", "Wi-Fi", _wifi, lambda v=None: _run(["nmcli", "radio", "wifi", "off" if _wifi() else "on"])),
    Toggle("bluetooth", "Bluetooth", _bt, lambda v=None: _run(["rfkill", "unblock" if not _bt() else "block", "bluetooth"])),
    Toggle("dnd", "Quiet mode", _dnd, lambda v=None: _run(["dunstctl", "set-paused", "toggle"])),
    Toggle("night", "Night light", _night, _act_night),
    Toggle("volume", "Volume", _vol, _setvol, "slider"),
    Toggle("brightness", "Brightness", _bright, lambda v: _run(["brightnessctl", "-q", "set", f"{int(v)}%"]), "slider"),
]
