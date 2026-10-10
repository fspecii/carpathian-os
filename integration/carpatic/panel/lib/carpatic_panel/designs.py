"""Panel designs: what surfaces a design has (bars, docks), where each item sits and the per-design defaults for every option.

A *surface* is one X window (a bar or a dock). `main` surfaces are full-width bars that dwm treats as THE bar (the built-in bar retires);
`dock` surfaces reserve their strip through _NET_WM_STRUT_PARTIAL under the name `carpatic-dock-*`. All numbers are px at 1x."""
import copy

# option -> (type, allowed/min/max, description). Settings app and `carpatic-panel set` validate against this.
OPTIONS = {
    "design":      ("enum", ("windows11", "macos", "ubuntu", "zorin", "kylin", "floating", "minimal", "classic"), "Panel design"),
    "position":    ("enum", ("auto", "top", "bottom", "left", "right"), "Edge of the main panel or dock (auto = the design's own)"),
    "size":        ("int", (24, 96), "Panel thickness in px (0 = design default)"),
    "icon_size":   ("int", (16, 64), "App icon size in px (0 = design default)"),
    "align":       ("enum", ("auto", "center", "left"), "Where the app icons sit"),
    "autohide":    ("enum", ("off", "on"), "Hide the panel until the pointer touches its edge"),
    "margin":      ("int", (0, 24), "Gap between a floating panel and the screen edge (-1 = design default)"),
    "radius":      ("int", (0, 28), "Corner radius of the panel (-1 = design default)"),
    "labels":      ("enum", ("auto", "on", "off"), "Show window titles next to icons"),
    "grouping":    ("enum", ("auto", "on", "off"), "One button per app instead of per window"),
    "clock_format": ("str", None, "strftime format of the clock, empty = design default"),
    "clock_24h":   ("bool", None, "24-hour clock"),
    "date_in_clock": ("enum", ("auto", "on", "off"), "Show the date under the time"),
    "show_search": ("enum", ("auto", "on", "off"), "Search button"),
    "show_taskview": ("enum", ("auto", "on", "off"), "Task view / overview button"),
    "show_widgets": ("enum", ("auto", "on", "off"), "Widgets button"),
    "show_desktop": ("enum", ("auto", "on", "off"), "Show-desktop strip at the end"),
    "tags":        ("enum", ("auto", "on", "off"), "Workspace (tag) indicator"),
    "tray":        ("enum", ("on", "off"), "System tray"),
    "monitors":    ("enum", ("primary", "all"), "Panel on the main monitor or on every monitor"),
    "previews":    ("enum", ("on", "off"), "Hover previews and tooltips"),
    "indicator":   ("enum", ("auto", "pill", "dot", "line", "dots"), "Running-app indicator style"),
    "pinned":      ("str", None, "Comma separated .desktop ids of pinned launchers"),
    "theme":       ("enum", ("auto", "dark", "light"), "Force dark or light panel colours"),
}

DEFAULT_PINNED = "org.xfce.Thunar,thunar,firefox,carpatic-terminal,carpatic-settings,carpatic-store"

# design -> defaults, applied when an option is 'auto' / 0 / -1
DESIGNS = {
    "windows11": dict(label="Windows 11", flyout="win", start="win", position="bottom", size=48, icon_size=24, align="center", margin=0, radius=0, labels="off", grouping="on",
                      indicator="pill", show_search="on", show_taskview="on", show_widgets="off", show_desktop="on", tags="on", date_in_clock="on", clock_format="%H:%M"),
    "classic":   dict(label="Windows 10", flyout="win", start="win", position="bottom", size=40, icon_size=24, align="left", margin=0, radius=0, labels="on", grouping="off",
                      indicator="line", show_search="on", show_taskview="on", show_widgets="off", show_desktop="on", tags="on", date_in_clock="on", clock_format="%H:%M"),
    "macos":     dict(label="macOS", flyout="mac", start="launchpad", position="bottom", size=70, icon_size=48, align="center", margin=8, radius=18, labels="off", grouping="on",
                      indicator="dot", show_search="off", show_taskview="off", show_widgets="off", show_desktop="off", tags="on", date_in_clock="off", clock_format="%a %-d %b  %H:%M"),
    "ubuntu":    dict(label="Ubuntu", flyout="ubuntu", start="launchpad", position="left", size=62, icon_size=44, align="left", margin=0, radius=0, labels="off", grouping="on",
                      indicator="dots", show_search="off", show_taskview="off", show_widgets="off", show_desktop="off", tags="on", date_in_clock="off", clock_format="%a %-d %b  %H:%M"),
    "zorin":     dict(label="Zorin (Zen)", flyout="win", start="twopane", position="bottom", size=48, icon_size=28, align="left", margin=0, radius=0, labels="off", grouping="on",
                      indicator="line", show_search="off", show_taskview="off", show_widgets="off", show_desktop="on", tags="on", date_in_clock="on", clock_format="%H:%M"),
    "kylin":     dict(label="Kylin (UKUI)", flyout="kylin", start="twopane", position="bottom", size=48, icon_size=32, align="left", margin=0, radius=0, labels="off", grouping="on",
                      indicator="pill", show_search="on", show_taskview="on", show_widgets="off", show_desktop="on", tags="on", date_in_clock="on", clock_format="%H:%M"),
    "floating":  dict(label="Floating dock", flyout="win", start="win", position="bottom", size=60, icon_size=40, align="center", margin=10, radius=16, labels="off", grouping="on",
                      indicator="dot", show_search="off", show_taskview="off", show_widgets="off", show_desktop="off", tags="on", date_in_clock="off", clock_format="%H:%M"),
    "minimal":   dict(label="Minimal / tiling", flyout="win", start="win", position="top", size=30, icon_size=16, align="left", margin=0, radius=0, labels="on", grouping="off",
                      indicator="line", show_search="off", show_taskview="off", show_widgets="off", show_desktop="off", tags="on", date_in_clock="off", clock_format="%a %-d %b  %H:%M"),
}

# Items: start search taskview widgets tasks tags appname activities title spacer tray quick bell clock showdesktop
#        (a name with a trailing ':sep' draws a divider after the item)


class Surface:
    def __init__(self, role, edge, thickness, kind="main", left=(), center=(), right=(), style="bar", margin=0, radius=0, length=None, align_tasks="center"):
        self.role, self.edge, self.thickness, self.kind = role, edge, thickness, kind
        self.left, self.center, self.right = list(left), list(center), list(right)
        self.style, self.margin, self.radius, self.length, self.align_tasks = style, margin, radius, length, align_tasks

    @property
    def horizontal(self): return self.edge in ("top", "bottom")

    def __repr__(self): return f"Surface({self.role} {self.edge} {self.thickness} {self.left}|{self.center}|{self.right})"


def resolve(cfg):
    """cfg: dict of options (strings/ints from the config file) -> effective values (design defaults filled in)."""
    d = DESIGNS.get(cfg.get("design", "windows11"), DESIGNS["windows11"])
    v = dict(d)
    for k, val in cfg.items():
        if k in ("design",): v["design"] = val; continue
        if k not in OPTIONS: continue
        if val in ("auto", "", None): continue
        if k in ("size", "icon_size") and int(val) == 0: continue
        if k in ("margin", "radius") and int(val) < 0: continue
        v[k] = val
    v.setdefault("design", "windows11")
    for k in ("size", "icon_size", "margin", "radius"): v[k] = int(v[k])
    return v


def surfaces(cfg):
    """The surfaces of the chosen design for the effective options `resolve(cfg)`."""
    v = resolve(cfg); name = v["design"]; pos = v["position"]; th = v["size"]
    def on(k): return v.get(k) in ("on", True, "true", "1")
    tray = ["tray"] if v.get("tray", "on") != "off" else []
    left, center, right = [], [], []
    pager = ["tags"] if on("tags") else []; side = pos in ("left", "right")   # workspace indicator: dots, filled when the workspace has windows
    if name in ("windows11", "classic"):
        grp = ["start"] + (["search"] if on("show_search") else []) + (["taskview"] if on("show_taskview") else []) + (["widgets"] if on("show_widgets") else []) + ["tasks"]
        if v["align"] == "center": center = grp
        else: left = grp
        right = ([] if side else pager) + tray + ["quick", "clock", "bell"] + (["showdesktop"] if on("show_desktop") else [])
        if pos in ("left", "right"): left, center, right = ["start", "tasks"], [], ["quick", "clock", "bell"]
        return [Surface("main", pos, th, "main", left, center, right, "win11" if name == "windows11" else "classic", 0, v["radius"], align_tasks=v["align"])]
    if name == "kylin":
        left = ["start"] + (["search"] if on("show_search") else []) + (["taskview"] if on("show_taskview") else []) + ["sep", "tasks"]
        right = ([] if side else pager) + tray + ["quick", "clock", "bell"] + (["showdesktop"] if on("show_desktop") else [])
        return [Surface("main", pos, th, "main", left, [], right, "kylin", 0, 0)]
    if name == "zorin":
        left = ["start", "tasks"]; right = ([] if side else pager) + tray + ["quick", "clock", "bell"] + (["showdesktop"] if on("show_desktop") else [])
        return [Surface("main", pos, th, "main", left, [], right, "zorin", v["margin"], v["radius"])]
    if name == "macos":
        bar = Surface("menubar", "top", 28, "main", ["logo", "appname"], [], pager + tray + ["quick", "bell", "clock"], "mac-menubar")
        dock = Surface("dock", "bottom" if pos in ("auto", "bottom") else pos, th, "dock", [], ["tasks"], [], "mac-dock", v["margin"], v["radius"])
        return [bar, dock]
    if name == "ubuntu":
        bar = Surface("topbar", "top", 30, "main", ["activities"] + pager, ["clock"], tray + ["quick"], "ubuntu-top")
        dock = Surface("dock", pos if pos in ("left", "right") else "left", th, "dock", ["tasks"], [], ["apps"], "ubuntu-dock", 0, 0)
        return [bar, dock]
    if name == "floating":
        dock = Surface("main", pos, th, "main", ["start"], ["tasks"], ([] if side else pager) + ["quick", "clock"], "floating", v["margin"], v["radius"])
        return [dock]
    if name == "minimal":
        return [Surface("main", pos, th, "main", ["tags", "title"], [], tray + ["quick", "clock"], "minimal")]
    raise ValueError(name)
