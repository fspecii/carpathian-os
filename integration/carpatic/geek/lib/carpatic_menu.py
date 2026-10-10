"""Engine of carpatic-menu: a keyboard-first menu tree shown with rofi.

Idea from Omarchy's omarchy-menu (MIT, see NOTICE): the tree is data (share/menu.toml, extended by ~/.config/carpatic/menu.d/*.toml),
entries can be hidden by context (laptop, Bluetooth ...), Esc goes back one level, typing filters. Rebuilt for rofi on X11 and the
Carpathian design system. Python 3.11+ standard library only.
"""
import glob
import html
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tomllib

SCALARS = ("label", "icon", "hint", "action", "term", "confirm", "when", "provider", "hidden")


def home():
    return os.environ.get("HOME", "/root")


def cfg_dir():
    return os.environ.get("CARPATIC_CONFIG", os.path.join(home(), ".config", "carpatic"))


def state_dir():
    return os.environ.get("CARPATIC_STATE", os.path.join(home(), ".local", "state", "carpatic"))


def share_dirs():
    out = []
    if os.environ.get("CARPATIC_GEEK_SHARE"):
        out.append(os.environ["CARPATIC_GEEK_SHARE"])
    here = os.path.dirname(os.path.realpath(__file__))
    out += [os.path.join(here, "..", "share"), "/usr/local/share/carpatic/geek"]
    return out


def find_share(name):
    for d in share_dirs():
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


# ---------------------------------------------------------------------------------------------------------------- tree
class Item:
    def __init__(self, key, parent=None):
        self.key = key
        self.parent = parent
        self.fields = {}
        self.children = []

    @property
    def path(self):
        return (self.parent.path if self.parent and self.parent.key else ()) + ((self.key,) if self.key else ())

    @property
    def id(self):
        return ".".join(self.path)

    @property
    def label(self):
        return self.fields.get("label") or self.key.replace("_", " ").capitalize()

    def get(self, k, d=None):
        return self.fields.get(k, d)

    def is_submenu(self):
        return bool(self.children) or bool(self.fields.get("provider"))

    def crumbs(self):
        items, it = [], self
        while it is not None and it.key:
            items.append(it.label)
            it = it.parent
        return list(reversed(items))


def _merge(node, data):
    """Merge a parsed TOML dict into the Item tree: scalars replace, tables recurse, order of first appearance wins."""
    for k, v in data.items():
        if isinstance(v, dict):
            child = next((c for c in node.children if c.key == k), None)
            if child is None:
                child = Item(k, node)
                node.children.append(child)
            _merge(child, v)
        elif k in SCALARS:
            node.fields[k] = v


def menu_files():
    files = []
    base = find_share("menu.toml")
    if base:
        files.append(base)
    files += sorted(glob.glob(os.path.join(cfg_dir(), "menu.d", "*.toml")))
    return files


def load_tree(files=None, errors=None):
    root = Item("")
    for f in files if files is not None else menu_files():
        try:
            with open(f, "rb") as fh:
                _merge(root, tomllib.load(fh))
        except (OSError, tomllib.TOMLDecodeError) as e:
            if errors is not None:
                errors.append(f"{f}: {e}")
    prune(root)
    return root


def prune(node):
    node.children = [c for c in node.children if not c.fields.get("hidden")]
    for c in node.children:
        prune(c)


def find(root, route):
    """Find an entry by route 'style.theme' (or just 'theme' when unique)."""
    if route in ("", "root", None):
        return root
    parts = route.split(".")
    node = root
    for p in parts:
        nxt = next((c for c in node.children if c.key == p), None)
        if nxt is None:
            nxt = next((c for c in node.children if c.label.lower() == p.lower()), None)
        if nxt is None:
            break
        node = nxt
    else:
        return node
    hits = []

    def walk(n):
        for c in n.children:
            if c.key == parts[-1]:
                hits.append(c)
            walk(c)
    walk(root)
    return hits[0] if len(hits) == 1 else None


# ------------------------------------------------------------------------------------------------------ context guards
def have(cmd):
    return shutil.which(cmd) is not None


def sh_ok(cmd):
    try:
        return subprocess.run(["sh", "-c", cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def sysroot():
    return os.environ.get("CARPATIC_SYSROOT", "")


def read(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def profile_name():
    v = ""
    for line in read(os.path.join(cfg_dir(), "settings.conf")).splitlines():
        m = re.match(r'PROFILE="?([^"]*)"?', line)
        if m:
            v = m.group(1)
    return v or "tiling"


def is_laptop():
    if os.environ.get("CARPATIC_FORCE_LAPTOP") in ("0", "1"):
        return os.environ["CARPATIC_FORCE_LAPTOP"] == "1"
    return bool(glob.glob(sysroot() + "/sys/class/power_supply/BAT*"))


def has_bluetooth():
    if os.environ.get("CARPATIC_FORCE_BLUETOOTH") in ("0", "1"):
        return os.environ["CARPATIC_FORCE_BLUETOOTH"] == "1"
    return bool(glob.glob(sysroot() + "/sys/class/bluetooth/hci*")) or have("blueman-manager") and sh_ok("rfkill list bluetooth | grep -q .")


def has_wifi():
    if os.environ.get("CARPATIC_FORCE_WIFI") in ("0", "1"):
        return os.environ["CARPATIC_FORCE_WIFI"] == "1"
    return bool(glob.glob(sysroot() + "/sys/class/net/*/wireless"))


def has_snapshots():
    if os.environ.get("CARPATIC_FORCE_SNAPSHOTS") in ("0", "1"):
        return os.environ["CARPATIC_FORCE_SNAPSHOTS"] == "1"
    if not have("carpatic-rollback"):
        return False
    for line in read(sysroot() + "/proc/mounts").splitlines():
        p = line.split()
        if len(p) > 2 and p[1] == "/" and p[2] == "btrfs":
            return True
    return False


def can_hibernate():
    if os.environ.get("CARPATIC_FORCE_HIBERNATE") in ("0", "1"):
        return os.environ["CARPATIC_FORCE_HIBERNATE"] == "1"
    return have("carpatic-power") and sh_ok("carpatic-power hibernate-ready")


def check(rule):
    """Evaluate a `when` rule. Unknown rules are false (the entry stays hidden) so typos never show a dead entry."""
    rule = (rule or "").strip()
    if not rule:
        return True
    if rule.startswith("not:"):
        return not check(rule[4:])
    if rule.startswith("has:"):
        return have(rule[4:])
    if rule.startswith("sh:"):
        return sh_ok(rule[3:])
    return {
        "laptop": is_laptop, "desktop": lambda: not is_laptop(), "bluetooth": has_bluetooth, "wifi": has_wifi,
        "snapshots": has_snapshots, "hibernate": can_hibernate, "tiling": lambda: profile_name() == "tiling",
        "x11": lambda: bool(os.environ.get("DISPLAY")), "always": lambda: True,
    }.get(rule, lambda: False)()


def visible(item):
    return check(item.get("when", ""))


# ---------------------------------------------------------------------------------------------------------------- rows
class Row:
    def __init__(self, label, action=None, icon=None, hint="", checked=False, term=False, confirm=False, node=None, enter=None):
        self.label, self.action, self.icon, self.hint = label, action, icon, hint
        self.checked, self.term, self.confirm, self.node, self.enter = checked, term, confirm, node, enter


def run_out(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def q(s):
    return shlex.quote(str(s))


def pfield(line, n, sep="|"):
    parts = line.split(sep)
    return parts[n].strip() if len(parts) > n else ""


class Providers:
    """Run-time row sources. Each returns a list of Row. They only call the carpatic-* CLIs, so scripts and the menu stay in step."""

    def themes(self):
        cur = run_out(["carpatic-theme", "current"]).strip()
        rows = []
        for line in run_out(["carpatic-theme", "list"]).splitlines():
            p = line.split()
            if p:
                rows.append(Row(p[0], f"carpatic-theme set {q(p[0])}", "preferences-desktop-theme",
                                p[1] if len(p) > 1 else "", checked=(p[0] == cur)))
        return rows

    def themes_remove(self):
        rows = []
        for line in run_out(["carpatic-themepack", "list", "--imported"]).splitlines():
            if line.strip():
                n = line.split()[0]
                rows.append(Row(n, f"carpatic theme remove {q(n)}", "edit-delete", "", confirm=True, term=True))
        return rows or [Row("Nothing imported yet", None, "dialog-information", "Import one with: carpatic theme import")]

    def wallpapers(self):
        rows = [Row("Next wallpaper", "carpatic theme wallpaper next", "go-next", "Same as Super+Ctrl+Space")]
        for line in run_out(["carpatic-themepack", "wallpaper", "list"]).splitlines():
            if line.strip():
                p = line.split("|")
                rows.append(Row(p[1] if len(p) > 1 else os.path.basename(p[0]), f"carpatic theme wallpaper set {q(p[0])}",
                                "image-x-generic", p[2] if len(p) > 2 else ""))
        return rows

    def accents(self):
        mode = "dark"
        t = run_out(["carpatic-theme", "current"]).strip()
        if t:
            for line in run_out(["carpatic-theme", "list"]).splitlines():
                p = line.split()
                if p and p[0] == t and len(p) > 1:
                    mode = p[1]
        sets = [("Spruce", "#5cc8a8", "#16806a"), ("Glacier", "#6cb4f0", "#1e6fb8"), ("Dusk", "#a99bf0", "#6a4fd0"),
                ("Rose", "#f08aa8", "#c2386a"), ("Ember", "#f2a65a", "#b8640f"), ("Moss", "#a3d36b", "#4f8a1c")]
        rows = []
        for name, d, l in sets:
            hexv = l if mode == "light" else d
            rows.append(Row(name, f"carpatic-theme set {q(t or 'carpatic')} --accent {hexv}", "preferences-desktop-color", hexv))
        rows.append(Row("Theme default", f"carpatic-theme set {q(t or 'carpatic')} --accent default", "edit-undo"))
        return rows

    def fonts(self):
        rows = []
        for line in run_out(["carpatic-appearance", "list", "presets"]).splitlines():
            p = line.split("|")
            if len(p) >= 4:
                rows.append(Row(p[3], f"carpatic-appearance preset {q(p[0])}", "preferences-desktop-font", ""))
        return rows

    def icons(self):
        cur = ""
        for line in run_out(["carpatic-appearance", "get"]).splitlines():
            if line.startswith("ICON_THEME="):
                cur = line.split("=", 1)[1].strip('"')
        return [Row(n, f"carpatic-appearance set icons {q(n)}", "preferences-desktop-icons", checked=(n == cur))
                for n in run_out(["carpatic-appearance", "list", "icons"]).split()]

    def profiles(self):
        cur = run_out(["carpatic-profile", "current"]).strip()
        rows = []
        for line in run_out(["carpatic-profile", "list"]).splitlines():
            p = line.split(None, 1)
            if p:
                rows.append(Row(p[1] if len(p) > 1 else p[0], f"carpatic-profile set {q(p[0])}", "preferences-desktop",
                                p[0], checked=(p[0] == cur)))
        return rows

    def power_profiles(self):
        cur = ""
        for line in run_out(["carpatic-power", "status"]).splitlines():
            m = re.search(r"profile\W+(\w+)", line, re.I)
            if m:
                cur = m.group(1).lower()
        labels = {"performance": "Performance", "balanced": "Balanced", "saver": "Battery saver", "auto": "Automatic"}
        return [Row(v, f"carpatic power profile {k}", "battery", k, checked=(k == cur)) for k, v in labels.items()]

    def snapshots(self):
        rows = []
        for line in run_out(["carpatic-rollback", "list"]).splitlines():
            p = line.split(None, 1)
            if p and re.match(r"^[0-9@]", p[0]):
                rows.append(Row(p[0], f"carpatic rollback restore {q(p[0])}", "edit-undo", p[1] if len(p) > 1 else "",
                                confirm=True, term=True))
        return rows or [Row("No snapshots yet", None, "dialog-information", "Update the system and one is taken for you")]

    def webapps(self):
        return [Row(n, f"carpatic-webapp launch {q(n)}", "internet-web-browser", u)
                for n, u in self._pairs(["carpatic-webapp", "list", "--plain"])] or \
               [Row("No web apps yet", None, "dialog-information", "Add one under Install")]

    def webapp_presets(self):
        have_n = {n for n, _ in self._pairs(["carpatic-webapp", "list", "--plain"])}
        rows = []
        for n, desc in self._pairs(["carpatic-webapp", "presets", "--plain"]):
            rows.append(Row(n, f"carpatic webapp preset {q(n)}", "internet-web-browser", "Added" if n in have_n else desc,
                            checked=n in have_n))
        rows.append(Row("Your own site", "@webapp-custom", "list-add", "Name and address"))
        return rows

    def webapp_remove(self):
        return [Row(n, f"carpatic webapp remove {q(n)}", "edit-delete", u, confirm=True)
                for n, u in self._pairs(["carpatic-webapp", "list", "--plain"])] or \
               [Row("No web apps yet", None, "dialog-information")]

    def tui_apps(self):
        return [Row(n, f"carpatic-tui launch {q(n)}", "utilities-terminal", u)
                for n, u in self._pairs(["carpatic-tui", "list", "--plain"])] or \
               [Row("No terminal apps yet", None, "dialog-information", "Add one under Install")]

    def tui_presets(self):
        have_n = {n for n, _ in self._pairs(["carpatic-tui", "list", "--plain"])}
        return [Row(n, f"carpatic tui preset {q(n)}", "utilities-terminal", "Added" if n in have_n else d, checked=n in have_n)
                for n, d in self._pairs(["carpatic-tui", "presets", "--plain"])]

    def tui_remove(self):
        return [Row(n, f"carpatic tui remove {q(n)}", "edit-delete", u, confirm=True)
                for n, u in self._pairs(["carpatic-tui", "list", "--plain"])] or [Row("No terminal apps yet", None, "dialog-information")]

    def dev_envs(self):
        rows = []
        for line in run_out(["carpatic-dev", "list", "--plain"]).splitlines():
            p = line.split("|")
            if len(p) >= 3:
                done = p[1] == "installed"
                rows.append(Row(p[3] if len(p) > 3 else p[0], f"carpatic install dev {q(p[0])}", "applications-development",
                                "Installed" if done else p[2], checked=done, term=True))
        return rows

    def dev_remove(self):
        rows = []
        for line in run_out(["carpatic-dev", "list", "--plain"]).splitlines():
            p = line.split("|")
            if len(p) >= 3 and p[1] == "installed":
                rows.append(Row(p[3] if len(p) > 3 else p[0], f"carpatic remove dev {q(p[0])}", "edit-delete", p[2], confirm=True, term=True))
        return rows or [Row("No dev environments installed", None, "dialog-information")]

    def apps_installed(self):
        rows = []
        out = run_out(["carpatic-store", "-y", "list", "--installed"], timeout=30)
        for line in out.splitlines():
            m = re.match(r"\[x\]\s+(\S+)\s+(.{1,22}?)\s{2,}", line)
            if m:
                rows.append(Row(m.group(2).strip(), f"carpatic store remove {q(m.group(1))}", "edit-delete", m.group(1),
                                confirm=True, term=True))
        return rows or [Row("Nothing from the store is installed", None, "dialog-information")]

    def ai_tools(self):
        rows = []
        for line in run_out(["carpatic-ai", "status"]).splitlines()[1:]:
            p = line.split()
            if len(p) >= 2:
                done = p[1].lower().startswith("install") or p[1].lower() in ("ready", "ok", "running")
                rows.append(Row(p[0], f"carpatic ai install {q(p[0])}", "applications-science",
                                p[1] if done else "Not installed", checked=done, term=True))
        return rows

    def layouts(self):
        cur = ""
        for line in run_out(["setxkbmap", "-query"]).splitlines():
            if line.startswith("layout:"):
                cur = line.split(":", 1)[1].strip()
        keys = [("us", "English (US)"), ("gb", "English (UK)"), ("de", "German"), ("fr", "French"), ("es", "Spanish"),
                ("it", "Italian"), ("ro", "Romanian"), ("pl", "Polish"), ("pt", "Portuguese"), ("se", "Swedish"),
                ("cz", "Czech"), ("ru", "Russian"), ("ua", "Ukrainian"), ("tr", "Turkish"), ("us -variant dvorak", "Dvorak"),
                ("us -variant colemak", "Colemak")]
        return [Row(name, f"setxkbmap {code} && mkdir -p ~/.config/carpatic && echo {q(code)} > ~/.config/carpatic/kbd-layout",
                    "input-keyboard", code, checked=(code == cur)) for code, name in keys]

    @staticmethod
    def _pairs(cmd):
        out = []
        for line in run_out(cmd).splitlines():
            p = line.split("|", 1)
            if p[0].strip():
                out.append((p[0].strip(), p[1].strip() if len(p) > 1 else ""))
        return out


PROVIDERS = {name.replace("_", "-"): name for name in
             ("themes themes_remove wallpapers accents fonts icons profiles power_profiles snapshots webapps webapp_presets "
              "webapp_remove tui_apps tui_presets tui_remove dev_envs dev_remove apps_installed ai_tools layouts").split()}


def rows_of(node, providers=None):
    """Rows of a submenu node: visible children first, or the provider's rows."""
    providers = providers or Providers()
    if node.get("provider"):
        name = PROVIDERS.get(node.get("provider"))
        if not name:
            return [Row("This list is not available", None, "dialog-warning", node.get("provider"))]
        return getattr(providers, name)()
    rows = []
    for c in node.children:
        if not visible(c):
            continue
        if c.is_submenu():
            rows.append(Row(c.label, None, c.get("icon"), c.get("hint", ""), node=c))
        else:
            rows.append(Row(c.label, c.get("action"), c.get("icon"), c.get("hint", ""), term=bool(c.get("term")),
                            confirm=bool(c.get("confirm")), node=c))
    return rows


def flatten(root, providers=None):
    """Every runnable entry with its breadcrumb, for 'Find anything'. Provider lists are skipped (they hit the system)."""
    out = []

    def walk(n):
        for c in n.children:
            if not visible(c):
                continue
            if c.get("provider"):
                out.append(Row(c.label, None, c.get("icon"), " > ".join(c.crumbs()[:-1]) or c.get("hint", ""), node=c))
            elif c.children:
                walk(c)
            else:
                out.append(Row(c.label, c.get("action"), c.get("icon"), " > ".join(c.crumbs()[:-1]), term=bool(c.get("term")),
                               confirm=bool(c.get("confirm")), node=c))
    walk(root)
    return out


# ---------------------------------------------------------------------------------------------------------------- UI
def read_colors():
    c = {"bg": "#11151c", "bg-alt": "#171c25", "fg": "#e7ecf3", "muted": "#6b778c", "accent": "#5cc8a8", "accent-fg": "#08241d",
         "border-col": "#2c3442"}
    p = os.path.join(state_dir(), "current", "rofi", "colors.rasi")
    for line in read(p).splitlines():
        m = re.match(r"\s*([\w-]+)\s*:\s*(#[0-9a-fA-F]{3,8})\s*;", line)
        if m:
            c[m.group(1)] = m.group(2)
    return c


def read_font():
    f = "Inter 10"
    for line in read(os.path.join(cfg_dir(), "appearance.env")).splitlines():
        m = re.match(r'UI_FONT="(.+)"', line)
        if m:
            f = m.group(1)
        m = re.match(r'ROFI_ICONS="(.+)"', line)
        if m:
            os.environ.setdefault("CARPATIC_ROFI_ICONS", m.group(1))
    return f


def write_theme():
    """Generate the rofi theme for the menu next to colors.rasi, in the active palette and font."""
    font = read_font()
    icons = os.environ.get("CARPATIC_ROFI_ICONS", "Papirus")
    size = re.search(r"(\d+(?:\.\d+)?)\s*$", font)
    fam = font[:size.start()].strip() if size else font
    sz = float(size.group(1)) if size else 10.0
    css = f'''/* generated by carpatic-menu: do not edit (palette and font come from the active theme) */
@import "colors.rasi"
* {{ background-color: transparent; text-color: @fg; font: "{fam} {sz + 1:g}"; }}
configuration {{ show-icons: true; icon-theme: "{icons}"; }}
window {{ location: center; anchor: center; width: 560px; background-color: @bg-alt; border: 1px; border-color: @border-col; border-radius: 0; }}
mainbox {{ children: [ inputbar, message, listview ]; padding: 12px; spacing: 8px; }}
inputbar {{ padding: 10px 12px; background-color: @bg; border-radius: 6px; children: [ prompt, entry ]; spacing: 10px; }}
prompt {{ text-color: @accent; }}
entry {{ placeholder: "Type to search"; placeholder-color: @muted; text-color: @fg; }}
message {{ padding: 0 4px; background-color: transparent; }}
textbox {{ text-color: @muted; font: "{fam} {max(sz - 1, 8):g}"; }}
listview {{ lines: 11; scrollbar: false; fixed-height: false; dynamic: true; spacing: 2px; }}
element {{ padding: 8px 12px; spacing: 12px; border-radius: 6px; text-color: @fg; }}
element-icon {{ size: 22px; }}
element selected {{ background-color: @accent; text-color: @accent-fg; }}
element-text {{ text-color: inherit; vertical-align: 0.5; }}
'''
    d = os.path.join(state_dir(), "current", "rofi")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "menu.rasi")
    old = read(p)
    if old != css.strip():
        with open(p, "w") as f:
            f.write(css)
    if not os.path.exists(os.path.join(d, "colors.rasi")):
        with open(os.path.join(d, "colors.rasi"), "w") as f:
            f.write("* { bg: #11151c; bg-alt: #171c25; fg: #e7ecf3; muted: #6b778c; accent: #5cc8a8; accent-fg: #08241d; border-col: #2c3442; }\n")
    return p


def markup(row, colors):
    """Row text: label, then a dim hint. A row that is in use says so in bold (colours inherit, so it reads on the selected row too)."""
    label = html.escape(row.label)
    hint = html.escape(row.hint) if row.hint else ""
    if row.checked:
        extra = f"  \u00b7  {hint}" if hint and hint not in ("Installed", "In use") else ""
        word = "Installed" if hint == "Installed" else "In use"
        return f"{label}   <span size='small' alpha='80%'><b>{word}</b></span><span size='small' alpha='55%'>{extra}</span>"
    if hint:
        return f"{label}   <span size='small' alpha='60%'>{hint}</span>"
    return label


class Backend:
    """choose(title, rows, message) -> index | None (back/cancel)."""

    def choose(self, title, rows, message):
        raise NotImplementedError

    def ask(self, prompt, message=""):
        raise NotImplementedError


class RofiBackend(Backend):
    def __init__(self):
        self.theme = write_theme()
        self.colors = read_colors()

    def _cmd(self, prompt, message):
        cmd = ["rofi", "-dmenu", "-i", "-no-custom", "-markup-rows", "-p", prompt, "-format", "i", "-theme", self.theme,
               "-kb-custom-1", "Alt+Left", "-no-lazy-grab"]
        if message:
            cmd += ["-mesg", message]
        return cmd

    def choose(self, title, rows, message):
        lines = []
        for r in rows:
            line = markup(r, self.colors)
            if r.icon:
                line += f"\0icon\x1f{r.icon}"
            lines.append(line)
        res = subprocess.run(self._cmd(title, message) + ["-selected-row", str(next((i for i, r in enumerate(rows) if r.checked), 0))],
                             input="\n".join(lines) + "\n", capture_output=True, text=True)
        if res.returncode != 0:
            return None
        try:
            return int(res.stdout.strip())
        except ValueError:
            return None

    def ask(self, prompt, message=""):
        cmd = ["rofi", "-dmenu", "-p", prompt, "-theme", self.theme, "-l", "0", "-theme-str", "listview { enabled: false; }"]
        if message:
            cmd += ["-mesg", message]
        res = subprocess.run(cmd, input="", capture_output=True, text=True)
        return res.stdout.strip() if res.returncode == 0 else None


class ScriptBackend(Backend):
    """For tests and for demos without a display: choices come from CARPATIC_MENU_SCRIPT (one label per line; '<back>' goes up)."""

    def __init__(self, path):
        self.lines = [l.rstrip("\n") for l in open(path)] if path and os.path.exists(path) else []
        self.log = []

    def next(self):
        return self.lines.pop(0) if self.lines else "<quit>"

    def choose(self, title, rows, message):
        print(f"== {title}" + (f"  [{message}]" if message else ""))
        for r in rows:
            print(f"   {r.label}" + (f"  ({r.hint})" if r.hint else "") + ("  *" if r.checked else ""))
        want = self.next()
        if want in ("<back>", "<quit>"):
            return None
        for i, r in enumerate(rows):
            if r.label == want:
                return i
        print(f"!! no row called '{want}'")
        return None

    def ask(self, prompt, message=""):
        v = self.next()
        return None if v in ("<back>", "<quit>") else v


# --------------------------------------------------------------------------------------------------------- actions
def term_title(text):
    return "Carpathian: " + text


def term_command(action, title="menu"):
    """Command line that runs `action` in a small floating terminal and waits for Enter. The title starts with 'Carpathian' so the
    window rules float it (configurator/bin/carpatic-genrules)."""
    cfg = cfg_dir()
    font = read(os.path.join(cfg, "term-font")) or "JetBrains Mono:size=10"
    osc = os.path.join(state_dir(), "current", "osc")
    wrapped = (f'cat {q(osc)} 2>/dev/null; {action}; rc=$?; echo; '
               'if [ "$rc" = 0 ]; then echo "Done."; else echo "That did not finish (code $rc). The lines above say why."; fi; '
               'printf "Press Enter to close. "; read -r _')
    return ["st", "-t", term_title(title), "-g", "100x30", "-f", font, "-e", "sh", "-c", wrapped]


def run_detached(argv):
    subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def execute(row, backend, dry=False):
    action = row.action
    if not action:
        return 0
    if action.startswith("@"):
        return builtin(action, backend, dry)
    if dry:
        print(("RUN-TERM: " if row.term else "RUN: ") + action)
        return 0
    if row.term:
        run_detached(term_command(action, row.label))
    else:
        run_detached(["sh", "-c", action])
    return 0


def builtin(name, backend, dry=False):
    if name == "@webapp-custom":
        n = backend.ask("Name of the web app")
        if not n:
            return 1
        u = backend.ask("Address", "For example https://example.com")
        if not u:
            return 1
        return execute(Row("Add web app", f"carpatic webapp add {q(n)} {q(u)}", term=True), backend, dry)
    if name == "@search-install":
        words = backend.ask("Search packages", "Part of a name, for example: gimp")
        if not words:
            return 1
        out = run_out(["carpatic-store", "-y", "search", words], timeout=40)
        rows = []
        for line in out.splitlines():
            m = re.match(r"\[( |x)\]\s+(\S+)\s+(.{1,22}?)\s{2,}\S+\s*\*?\s*(.*)$", line)
            if m:
                rows.append(Row(m.group(3).strip(), f"carpatic install app {q(m.group(2))}", "system-software-install",
                                "Installed" if m.group(1) == "x" else m.group(4)[:50], term=True))
        if not rows:
            rows = [Row("Nothing found", None, "dialog-information", "Try fewer words")]
        i = backend.choose("Install", rows, "Pick one to install it")
        if i is not None and rows[i].action:
            return execute(rows[i], backend, dry)
        return 1
    print(f"carpatic-menu: unknown built-in {name}", file=sys.stderr)
    return 1


def confirm(backend, what):
    rows = [Row("Cancel", icon="process-stop"), Row(f"Yes, {what.lower()}", icon="dialog-ok")]
    i = backend.choose(what, rows, "Are you sure?")
    return i == 1


def navigate(root, route, backend, dry=False, providers=None):
    """Show `route`, follow choices, Esc goes up. Returns the exit status."""
    providers = providers or Providers()
    node = find(root, route)
    if node is None:
        print(f"carpatic-menu: I do not know the place '{route}'. Try one of: "
              + ", ".join(c.key for c in root.children), file=sys.stderr)
        return 2
    stack = [node]
    search = False
    while stack:
        cur = stack[-1]
        crumb = " › ".join(cur.crumbs()) if cur.key else "Carpathian"
        rows = rows_of(cur, providers) if not search else flatten(root)
        if cur is root and not search:
            rows.append(Row("Find anything", None, "edit-find", "Type a few letters", enter="search"))
        if not rows:
            rows = [Row("Nothing here yet", None, "dialog-information")]
        msg = "Enter opens   Esc goes back   Type to search"
        i = backend.choose(crumb if not search else "Find", rows, msg)
        if i is None:
            if search:
                search = False
                continue
            stack.pop()
            continue
        r = rows[i]
        if r.enter == "search":
            search = True
            continue
        if r.node is not None and r.node.is_submenu() and not r.action:
            search = False
            stack.append(r.node)
            continue
        if not r.action:
            continue            # info row: stay
        if r.confirm and not confirm(backend, r.label if not cur.get("provider") else cur.label):
            continue
        return execute(r, backend, dry)
    return 0


def check_tree(root):
    """Validate a tree: every runnable entry has a known command, providers exist, no duplicates. Returns list of problems."""
    problems = []

    def first_word(a):
        try:
            return shlex.split(a)[0]
        except (ValueError, IndexError):
            return ""

    def walk(n):
        for c in n.children:
            f = c.fields
            if not c.children and not f.get("provider") and not f.get("action"):
                problems.append(f"{c.id}: has nothing to do (no action, provider or sub-entries)")
            if f.get("provider") and f["provider"] not in PROVIDERS:
                problems.append(f"{c.id}: unknown provider '{f['provider']}'")
            if f.get("action"):
                a = f["action"]
                if a.startswith("@") and a not in ("@webapp-custom", "@search-install"):
                    problems.append(f"{c.id}: unknown built-in {a}")
                elif not a.startswith("@") and "||" not in a and "|" not in a and "&&" not in a and "$(" not in a and not first_word(a):
                    problems.append(f"{c.id}: empty action")
            if f.get("when") and not re.match(r"^(not:)*(laptop|desktop|bluetooth|wifi|snapshots|hibernate|tiling|x11|always|has:\S+|sh:.+)$", f["when"]):
                problems.append(f"{c.id}: unknown 'when' rule '{f['when']}'")
            if not f.get("label"):
                problems.append(f"{c.id}: no label (using '{c.label}')")
            walk(c)
    walk(root)
    return problems


def action_commands(root):
    """(id, first command word) of each runnable entry, to test that the tools exist."""
    out = []

    def walk(n):
        for c in n.children:
            a = c.fields.get("action")
            if a and not a.startswith("@"):
                m = re.match(r"\s*(?:\$\{\w+:-[^}]*\}|\S+)", a)
                w = m.group(0) if m else ""
                out.append((c.id, w))
            walk(c)
    walk(root)
    return out


def dump(root, indent=0, out=None, only_visible=True):
    out = out if out is not None else []
    for c in root.children:
        if only_visible and not visible(c):
            continue
        kind = "provider:" + c.get("provider") if c.get("provider") else ("menu" if c.children else "action")
        out.append("  " * indent + f"{c.label}  [{c.id}] ({kind})")
        dump(c, indent + 1, out, only_visible)
    return out
