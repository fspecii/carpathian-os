"""Paths, the widget catalogue, the saved layout and grid maths. No GTK here: the CLI and the unit tests import this without a display."""
import json, os, tempfile

CFG = os.environ.get("CARPATIC_CONFIG", os.path.expanduser("~/.config/carpatic"))
WDIR = os.path.join(CFG, "widgets")
DATA = os.environ.get("CARPATIC_WIDGETS_DATA", os.path.expanduser("~/.local/share/carpatic/widgets"))
STATE = os.environ.get("CARPATIC_STATE", os.path.expanduser("~/.local/state/carpatic"))
FLAG = os.path.join(WDIR, "enabled")          # present = the user turned the feature on; absent = no widget process, ever
LAYOUT = os.path.join(WDIR, "layout.json")
PIDFILE = os.path.join(STATE, "widgets.pid")
SHARE = os.environ.get("CARPATIC_WIDGETS_SHARE", "/usr/local/share/carpatic/widgets")

PITCH = 88          # one grid cell in px at 96 dpi (cell 76 + gap 12)
GAP = 12
SIZES = ("S", "M", "L")
_DIMS = {"S": (2, 2), "M": (4, 2), "L": (4, 4)}

# id: title, one-line description, size -> (cols, rows), default size, refresh seconds while visible (0 = events only)
CATALOG = {
    "clock":      dict(title="Clock", desc="Analogue, digital or dot-matrix clock.", dims=_DIMS, default="M", period=1),
    "calendar":   dict(title="Calendar", desc="This month, today highlighted; large size lists events from a local .ics file.", dims={"S": (2, 2), "M": (4, 4), "L": (6, 4)}, default="M", period=60),
    "weather":    dict(title="Weather", desc="Open-Meteo forecast, no account or key. Works offline from the last answer.", dims={"S": (2, 2), "M": (4, 2), "L": (4, 4)}, default="M", period=1800),
    "sysmon":     dict(title="System monitor", desc="Processor, memory, disk, network and temperature.", dims={"S": (2, 2), "M": (4, 2), "L": (4, 4)}, default="M", period=2),
    "nowplaying": dict(title="Now playing", desc="Whatever plays music or video (MPRIS): cover, title, play/pause, next.", dims={"S": (2, 2), "M": (4, 2), "L": (4, 4)}, default="M", period=0),
    "battery":    dict(title="Battery and power", desc="Charge, time left and the power profile.", dims={"S": (2, 2), "M": (4, 2), "L": (4, 2)}, default="S", period=30),
    "notes":      dict(title="Notes", desc="A sticky note. Click to edit.", dims={"S": (2, 2), "M": (4, 2), "L": (4, 4)}, default="M", period=0),
    "todo":       dict(title="To-do", desc="A short local list. Click an item to tick it.", dims={"S": (2, 2), "M": (4, 4), "L": (4, 4)}, default="M", period=0),
    "toggles":    dict(title="Quick settings", desc="Wi-Fi, Bluetooth, Do not disturb, night light, volume, brightness.", dims={"S": (2, 2), "M": (4, 2), "L": (4, 4)}, default="M", period=5),
    "photo":      dict(title="Wallpaper", desc="Your current wallpaper as a picture frame.", dims={"S": (2, 2), "M": (4, 2), "L": (4, 4)}, default="M", period=0),
    "shortcuts":  dict(title="App shortcuts", desc="Five apps one click away.", dims={"S": (2, 2), "M": (4, 2), "L": (4, 2)}, default="M", period=0),
    "tip":        dict(title="Carpatic tip", desc="A small tip about your desktop, a new one each day.", dims={"S": (2, 2), "M": (4, 2), "L": (4, 2)}, default="M", period=3600),
}
DEFAULT_ITEMS = [("clock", "M"), ("calendar", "M"), ("weather", "M"), ("sysmon", "L")]   # two columns of six rows each: composed, not a wall
LOOKS = ("auto", "macos", "windows", "ubuntu", "tiling", "nothing")


class Error(Exception):
    """A problem with plain-English text that can be shown to the user as is."""


def dims(wid, size):
    return CATALOG[wid]["dims"][size]


def atomic_write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    try:
        with os.fdopen(fd, "w") as f: f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
        raise


def enabled():
    return os.path.exists(FLAG)


def new_layout():
    items, row = [], 0
    # columns count from the RIGHT edge (anchor "right"): weather + monitor at the edge, clock + calendar next to them
    left = [i for i in DEFAULT_ITEMS[:2]]; right = [i for i in DEFAULT_ITEMS[2:]]
    for col, lst in ((4, left), (0, right)):
        row = 0
        for wid, sz in lst:
            items.append(dict(id=wid, size=sz, col=col, row=row)); row += dims(wid, sz)[1]
    return dict(version=1, look="auto", anchor="right", monitor="primary", items=items, weather={}, shortcuts=[])


def reset_layout(old=None):
    """The default arrangement; the user's own choices (card style, weather place, shortcuts) are kept."""
    d = new_layout()
    for k in ("look", "weather", "shortcuts", "monitor"):
        if old and old.get(k): d[k] = old[k]
    return d


def load(path=None):
    """Read the layout; a missing or damaged file gives the defaults (a bad file must never stop the desktop)."""
    try:
        d = json.load(open(path or LAYOUT))
        if not isinstance(d, dict) or not isinstance(d.get("items"), list): raise ValueError
    except (OSError, ValueError):
        return new_layout()
    good = []
    for it in d["items"]:
        if isinstance(it, dict) and it.get("id") in CATALOG:
            sz = it.get("size") if it.get("size") in CATALOG[it["id"]]["dims"] else CATALOG[it["id"]]["default"]
            try: col, row = max(0, int(it.get("col", 0))), max(0, int(it.get("row", 0)))
            except (TypeError, ValueError): col, row = 0, 0
            good.append(dict(id=it["id"], size=sz, col=col, row=row, opts=it.get("opts") if isinstance(it.get("opts"), dict) else {}))
    d["items"] = good
    d.setdefault("look", "auto"); d.setdefault("weather", {}); d.setdefault("shortcuts", []); d.setdefault("anchor", "right"); d.setdefault("monitor", "primary")
    return d


def save(d, path=None):
    atomic_write(path or LAYOUT, json.dumps(d, indent=1, sort_keys=True) + "\n")


def snap(col, row, cols_total, rows_total, w, h):
    """Snap to the grid and keep the whole card on the screen."""
    return max(0, min(int(round(col)), max(0, cols_total - w))), max(0, min(int(round(row)), max(0, rows_total - h)))


def overlaps(items, it, ignore=None):
    w, h = dims(it["id"], it["size"])
    for o in items:
        if o is ignore or o["id"] == it["id"]: continue
        ow, oh = dims(o["id"], o["size"])
        if it["col"] < o["col"] + ow and o["col"] < it["col"] + w and it["row"] < o["row"] + oh and o["row"] < it["row"] + h: return o
    return None


def free_spot(items, wid, size, cols_total, rows_total):
    """First free place scanning from the anchored edge inwards (new cards appear next to the others, never on top of one)."""
    w, h = dims(wid, size)
    cand = dict(id=wid, size=size, col=0, row=0)
    for col in range(0, max(1, cols_total - w + 1)):
        for row in range(0, max(1, rows_total - h + 1)):
            cand["col"], cand["row"] = col, row
            if not overlaps(items, cand): return col, row
    return 0, 0


def add(d, wid, size=None, cols_total=12, rows_total=6):
    if wid not in CATALOG: raise Error(f"There is no widget called '{wid}'. Try: {' '.join(CATALOG)}")
    if any(i["id"] == wid for i in d["items"]): raise Error(f"{CATALOG[wid]['title']} is already on your desktop.")
    size = size or CATALOG[wid]["default"]
    if size not in CATALOG[wid]["dims"]: raise Error("Sizes are S, M or L.")
    col, row = free_spot(d["items"], wid, size, cols_total, rows_total)
    d["items"].append(dict(id=wid, size=size, col=col, row=row)); return d


def remove(d, wid):
    n = len(d["items"]); d["items"] = [i for i in d["items"] if i["id"] != wid]
    if len(d["items"]) == n: raise Error(f"{CATALOG.get(wid, {}).get('title', wid)} is not on your desktop.")
    return d


def cell_rect(area, it, anchor="right", scale=1.0):
    """Pixel rectangle (x, y, w, h) of a card inside the work area (x, y, w, h). Columns count from the anchored edge."""
    ax, ay, aw, ah = area; cw, ch = dims(it["id"], it["size"]); p = PITCH * scale; g = GAP * scale; m = 12 * scale
    px, py, pw, ph = cw * p - g, ch * p - g, 0, 0
    y = ay + m + it["row"] * p
    x = (ax + aw - m + g - (it["col"] + cw) * p) if anchor == "right" else (ax + m + it["col"] * p)
    return int(x), int(y), int(px), int(ch * p - g)


def grid_size(area, anchor="right", scale=1.0):
    """How many columns and rows fit the work area."""
    return max(2, int((area[2] - 24 * scale) // (PITCH * scale))), max(2, int((area[3] - 24 * scale) // (PITCH * scale)))


def px_to_cell(area, x, y, it, anchor="right", scale=1.0):
    ax, ay, aw, ah = area; cw, ch = dims(it["id"], it["size"]); p = PITCH * scale; g = GAP * scale; m = 12 * scale
    row = (y - ay - m) / p
    col = ((ax + aw - m + g - x) / p - cw) if anchor == "right" else (x - ax - m) / p
    return col, row


def scale_for(dpi, scale_factor=1):
    """Card scale. With a GDK integer scale factor GTK multiplies logical pixels itself (cards stay at 1.0); on plain X11 a high Xft.dpi scales the cards in quarter steps."""
    if scale_factor and scale_factor > 1: return 1.0
    if not dpi or dpi <= 0: dpi = 96.0
    return max(1.0, round(dpi / 96.0 * 4) / 4)


def auto_arrange(items, cols_total, rows_total):
    """Pack the cards tightly from the anchored edge, tall ones first inside each pass, keeping the current reading order. Changes items in place."""
    order = sorted(items, key=lambda i: (i["col"], i["row"]))
    placed = []
    for it in order:
        col, row = free_spot(placed, it["id"], it["size"], cols_total, rows_total); it["col"], it["row"] = col, row; placed.append(it)
    return items


def in_carpatic_session():
    """True only on a Carpatic desktop (our dwm is running for this user) or when CARPATIC_FORCE=1 (tests on a private Xvfb).
    Widgets never start on someone else's desktop, even when the flag file exists."""
    if os.environ.get("CARPATIC_FORCE") == "1": return True
    me = os.getuid()
    try:
        for d in os.listdir("/proc"):
            if d.isdigit():
                try:
                    if os.stat(f"/proc/{d}").st_uid == me and open(f"/proc/{d}/comm").read().strip() == "dwm": return True
                except OSError: pass
    except OSError: pass
    return False
