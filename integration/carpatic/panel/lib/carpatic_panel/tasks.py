"""Task list model: windows (from EWMH) + pinned launchers + desktop-file catalogue -> ordered buttons. No GTK / X here, so it is unit tested with fakes."""
import configparser, glob, os, re, shlex


class Win:
    __slots__ = ("id", "title", "klass", "instance", "active", "urgent", "minimized", "desktop", "monitor", "icon_name", "pid")

    def __init__(self, id, title="", klass="", instance="", active=False, urgent=False, minimized=False, desktop=0, monitor=0, icon_name="", pid=0):
        self.id, self.title, self.klass, self.instance = id, title, klass, instance
        self.active, self.urgent, self.minimized, self.desktop, self.monitor, self.icon_name, self.pid = active, urgent, minimized, desktop, monitor, icon_name, pid

    def __repr__(self): return f"Win({self.id:#x} {self.klass!r} {self.title!r})"


class App:
    __slots__ = ("id", "name", "exec", "icon", "wmclass", "actions", "hidden", "cats")

    def __init__(self, id, name, exec_, icon="", wmclass="", actions=None, hidden=False, cats=""):
        self.id, self.name, self.exec, self.icon, self.wmclass, self.actions = id, name, exec_, icon, wmclass, actions or []
        self.hidden, self.cats = hidden, cats


class Task:
    """One button: an app (grouped) or a single window. `windows` empty = a pinned launcher that is not running."""
    __slots__ = ("key", "name", "icon", "windows", "pinned", "app")

    def __init__(self, key, name, icon, windows, pinned, app):
        self.key, self.name, self.icon, self.windows, self.pinned, self.app = key, name, icon, windows, pinned, app

    @property
    def active(self): return any(w.active for w in self.windows)
    @property
    def urgent(self): return any(w.urgent for w in self.windows)
    @property
    def running(self): return bool(self.windows)
    @property
    def count(self): return len(self.windows)
    @property
    def all_minimized(self): return bool(self.windows) and all(w.minimized for w in self.windows)

    def __repr__(self): return f"Task({self.key} n={self.count}{' pinned' if self.pinned else ''}{' active' if self.active else ''})"


def _norm(s): return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def read_desktop(path):
    cp = configparser.RawConfigParser(strict=False, interpolation=None); cp.optionxform = str
    try: cp.read(path, encoding="utf-8")
    except (configparser.Error, OSError, UnicodeDecodeError): return None
    if "Desktop Entry" not in cp: return None
    e = cp["Desktop Entry"]
    aid = os.path.basename(path)[:-8]
    # a user/system override that only says "hide this" (NoDisplay=true or Hidden=true, often without Exec) must win over the packaged entry in a
    # later directory: return a hidden stub instead of skipping it, otherwise e.g. "About Xfce" showed up in the Start menu
    low = lambda k: e.get(k, "false").lower() == "true"
    if e.get("Type", "Application") == "Application" and (low("Hidden") or (low("NoDisplay") and "Exec" not in e)):
        return App(aid, e.get("Name", aid), e.get("Exec", ""), "", "", [], True, "")
    if e.get("Type", "Application") != "Application": return None
    if "Name" not in e or "Exec" not in e: return None
    acts = []
    for a in e.get("Actions", "").split(";"):
        if a and f"Desktop Action {a}" in cp and "Name" in cp[f"Desktop Action {a}"] and "Exec" in cp[f"Desktop Action {a}"]:
            acts.append((cp[f"Desktop Action {a}"]["Name"], cp[f"Desktop Action {a}"]["Exec"]))
    return App(aid, e["Name"], e["Exec"], e.get("Icon", ""), e.get("StartupWMClass", ""), acts, e.get("NoDisplay", "false").lower() == "true", e.get("Categories", ""))


def catalogue(dirs=None):
    dirs = dirs or [os.path.expanduser("~/.local/share/applications"), "/usr/local/share/applications", "/usr/share/applications",
                    "/var/lib/flatpak/exports/share/applications", os.path.expanduser("~/.local/share/flatpak/exports/share/applications")]
    apps = {}
    for d in dirs:
        for f in sorted(glob.glob(os.path.join(d, "**", "*.desktop"), recursive=True)):
            a = read_desktop(f)
            if a and a.id not in apps: apps[a.id] = a
    return apps


def exec_argv(exec_line):
    """Desktop Exec line -> argv without field codes."""
    try: parts = shlex.split(exec_line)
    except ValueError: parts = exec_line.split()
    return [p for p in parts if not re.fullmatch(r"%[a-zA-Z%]", p)] if parts else []


def match_app(win, apps):
    """Best desktop entry for a window (StartupWMClass, desktop id, executable name), or None."""
    keys = {_norm(win.klass), _norm(win.instance)} - {""}
    keys |= {k.replace("256color", "") for k in keys if "256color" in k}      # st-256color, xterm-256color ...
    best = None
    cands = [a for a in apps.values() if a.wmclass and _norm(a.wmclass) in keys]
    if cands:    # several entries share one class (terminal-hosted apps like Mail all say st-256color): the terminal itself wins the tie
        return next((a for a in cands if "TerminalEmulator" in (a.cats or "")), cands[0])
    for a in apps.values():
        if _norm(a.id.split(".")[-1]) in keys or _norm(a.id) in keys: best = best or a
    if best: return best
    for a in apps.values():
        argv = exec_argv(a.exec)
        if argv and _norm(os.path.basename(argv[0])) in keys: return a
    return best


def build_tasks(wins, pinned, apps, group=True, order=None, filter_monitor=None):
    """wins: list[Win] (skip-taskbar windows already removed). pinned: list of app ids. order: dict key->index that remembers first-seen order
    (mutated). Returns list[Task]: pinned first in the user's order, then running apps in the order they first appeared."""
    order = order if order is not None else {}
    tasks = {}; seq = []
    pin_ids = [p for p in pinned if p]
    pin_app = {}
    for p in pin_ids:
        a = apps.get(p) or apps.get(p.lower())
        if a is None:
            for k, v in apps.items():
                if k.lower().endswith("." + p.lower()) or k.lower() == p.lower(): a = v; break
        if a: pin_app[a.id] = a
    ordered_pins = [a for a in (pin_app[k] for k in pin_app)]
    for a in ordered_pins:
        t = Task(a.id, a.name, a.icon, [], True, a); tasks[a.id] = t; seq.append(t)
    for w in wins:
        if filter_monitor is not None and w.monitor != filter_monitor: continue
        a = match_app(w, apps)
        key = a.id if a else (_norm(w.klass) or f"win{w.id:x}")
        if group:
            t = tasks.get(key)
            if t is None:
                t = Task(key, a.name if a else (w.klass or w.title or "Application"), (a.icon if a else (w.icon_name or w.klass.lower())), [], False, a)
                tasks[key] = t; seq.append(t)
            t.windows.append(w)
        else:
            if key in tasks and tasks[key].pinned and not tasks[key].windows:
                tasks[key].windows.append(w)           # first window takes over the launcher slot
            else:
                tk = f"{key}#{w.id:x}"
                t = Task(tk, w.title or (a.name if a else w.klass), a.icon if a else (w.icon_name or w.klass.lower()), [w], False, a); tasks[tk] = t; seq.append(t)
    for t in seq:
        if t.key not in order and not t.pinned: order[t.key] = len(order)
    pinned_part = [t for t in seq if t.pinned]
    run_part = sorted([t for t in seq if not t.pinned], key=lambda t: order.get(t.key, 1e9))
    return pinned_part + run_part


def move_pin(pinned, src, dst):
    """Reorder the pinned id list (drag and drop): move element at index src to index dst."""
    p = list(pinned); 
    if not (0 <= src < len(p)): return p
    item = p.pop(src); dst = max(0, min(len(p), dst)); p.insert(dst, item); return p


def toggle_pin(pinned, app_id):
    p = list(pinned)
    if app_id in p: p.remove(app_id)
    else: p.append(app_id)
    return p
