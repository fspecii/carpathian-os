"""Setting a wallpaper: settings.conf (what carpatic-apply and the theme picker read), the X root window (feh / xwallpaper), the
light/dark pair, per-theme choice, per-monitor choice, rotation and generated colours. All commands are argv lists (no shell)."""
import json, os, re, shutil, subprocess, time

from . import imageinfo, library, paths, state

FEH_FLAGS = {"fill": "--bg-fill", "fit": "--bg-max", "stretch": "--bg-scale", "center": "--bg-center", "tile": "--bg-tile"}
# Tagged xfdesktop 4.20.1 common/xfdesktop-common.h: CENTERED=1 through ZOOMED=5.
XFDESKTOP_STYLES = {"fill": 5, "fit": 4, "stretch": 3, "center": 1, "tile": 2}
XWALL_FLAGS = {"fill": "--zoom", "fit": "--maximize", "stretch": "--stretch", "center": "--center", "tile": "--tile"}


class WallpaperError(Exception):
    pass


# ----- settings.conf: same KEY="value" format as configurator/bin/carpatic-lib --------------------------------------------
def _sh_escape(v):
    """settings.conf is sourced by shell scripts: escape \\ " $ ` and drop newlines so a value (e.g. a wallpaper file name) can never run code."""
    return re.sub(r'(["\\$`])', r'\\\1', str(v).replace("\n", " ").replace("\r", " "))

def _sh_unescape(v):
    return re.sub(r'\\(["\\$`])', r'\1', v)

def get_setting(key, default=""):
    try:
        for line in open(paths.settings_conf()):
            m = re.match(r'^%s="?(.*?)"?\s*$' % re.escape(key), line)
            if m: return _sh_unescape(m.group(1))
    except OSError:
        pass
    return default

def set_setting(key, value):
    p = paths.settings_conf()
    paths.ensure(os.path.dirname(p))
    lines = []
    try: lines = [l for l in open(p).read().splitlines() if not l.startswith(key + "=")]
    except OSError: pass
    lines.append('%s="%s"' % (key, _sh_escape(value)))
    tmp = p + f".{os.getpid()}.tmp"
    with open(tmp, "w") as f: f.write("\n".join(lines) + "\n")
    os.replace(tmp, p)


def current_theme(): return get_setting("THEME", "carpatic")

def theme_mode(theme=None):
    """'dark' or 'light' for a theme (colors.toml mode)."""
    theme = theme or current_theme()
    for td in paths.theme_dirs()[::-1]:
        d = os.path.join(td, theme)
        if os.path.isfile(os.path.join(d, "colors.toml")): return library._theme_mode(d) or "dark"
    return "dark"

def current_wallpaper():
    wp = get_setting("WALLPAPER", "")
    if wp and os.path.isfile(wp): return wp
    for td in paths.theme_dirs()[::-1]:
        p = os.path.join(td, current_theme(), "wallpaper.jpg")
        if os.path.isfile(p): return p
    return ""


# ----- display ----------------------------------------------------------------------------------------------------------
def monitors(run=subprocess.run):
    """[(name, w, h, x, y)] from xrandr --listmonitors; [] without X."""
    if not os.environ.get("DISPLAY") or not shutil.which("xrandr"): return []
    try: out = run(["xrandr", "--listmonitors"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError): return []
    res = []
    for line in out.splitlines():
        m = re.search(r"(\d+)/\d+x(\d+)/\d+(\+-?\d+|-\d+)(\+-?\d+|-\d+)\s+(\S+)$", line)
        if m: res.append((m.group(5), int(m.group(1)), int(m.group(2)), int(m.group(3).lstrip("+")), int(m.group(4).lstrip("+"))))
    return res

def display_size(run=subprocess.run):
    ms = monitors(run)
    if ms:
        n, w, h, *_ = ms[0]
        return w, h
    try:
        from gi.repository import Gdk
        s = Gdk.Screen.get_default()
        if s: return s.get_width(), s.get_height()
    except Exception:
        pass
    return 1920, 1080


# ----- X root window ----------------------------------------------------------------------------------------------------
def desktop_surface_active(run=subprocess.run):
    """Trusted prestart marker or a live xfdesktop owner on this session bus."""
    if os.environ.get("CARPATIC_DESKTOP_SURFACE") == "1":
        return True
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS") or not shutil.which("gdbus"):
        return False
    try:
        result = run(["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus",
                      "--object-path", "/org/freedesktop/DBus", "--method",
                      "org.freedesktop.DBus.NameHasOwner", "org.xfce.xfdesktop"],
                     capture_output=True, text=True, timeout=3)
        return result.returncode == 0 and result.stdout.strip() == "(true,)"
    except (OSError, subprocess.SubprocessError):
        return False


def build_commands(default, fill="fill", per_monitor=None, mons=None, have=shutil.which, desktop=False):
    """The command(s) that paint the root window. per_monitor {name: path}, mons [(name,...)] in xrandr order."""
    fill = fill if fill in FEH_FLAGS else "fill"
    mons = mons or []
    per_monitor = {k: v for k, v in (per_monitor or {}).items() if os.path.isfile(v)}
    if desktop:
        if not have("xfconf-query") or not mons:
            return []
        def setting(prop, kind, value):
            return ["xfconf-query", "--channel", "xfce4-desktop", "--property", prop,
                    "--create", "--type", kind, "--set", str(value)]
        # Carpathian stores one global wallpaper per monitor, across workspaces.
        cmds = [setting("/backdrop/single-workspace-number", "int", 0),
                setting("/backdrop/single-workspace-mode", "bool", "true")]
        for name, *_ in mons:
            prefix = "/backdrop/screen0/monitor" + name + "/workspace0/"
            cmds += [setting(prefix + "last-image", "string", per_monitor.get(name, default)),
                     setting(prefix + "image-style", "int", XFDESKTOP_STYLES[fill])]
        return cmds
    if have("xwallpaper"):
        if per_monitor and mons:
            cmd = ["xwallpaper"]
            for n, *_ in mons: cmd += ["--output", n, XWALL_FLAGS[fill], per_monitor.get(n, default)]
            return [cmd]
        return [["xwallpaper", XWALL_FLAGS[fill], default]]
    if have("feh"):
        if per_monitor and mons:  # feh assigns files to screens in order
            return [["feh", "--no-fehbg", FEH_FLAGS[fill]] + [per_monitor.get(n, default) for n, *_ in mons]]
        return [["feh", "--no-fehbg", FEH_FLAGS[fill], default]]
    return []

def paint(default, fill=None, run=subprocess.run):
    if not os.environ.get("DISPLAY") and run is subprocess.run: return False
    st = state.load()
    desktop = desktop_surface_active(run)
    cmds = build_commands(default, fill or st["fill"], st["monitors"],
                          monitors(run) if desktop or st["monitors"] else [],
                          have=shutil.which, desktop=desktop)
    ok = bool(cmds)
    for c in cmds:
        try: ok = run(c, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20).returncode == 0 and ok
        except (OSError, subprocess.SubprocessError): ok = False
    return ok


# ----- set --------------------------------------------------------------------------------------------------------------
def validate(path):
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(path): raise WallpaperError("That picture is not there any more.")
    with open(path, "rb") as f:
        k = imageinfo.sniff(f.read(32))
    if k is None: raise WallpaperError("That file is not a picture Carpathian can use.")
    return path

def set_wallpaper(path, fill=None, monitor=None, for_theme=False, pair=None, paint_now=True, run=subprocess.run):
    """Make `path` the wallpaper.
    monitor: output name, set only that screen.   for_theme: remember it for the current theme.
    pair: 'light' / 'dark' remembers it in the light/dark pair (and turns the pair on). Returns the path."""
    path = validate(path)
    st = state.load()
    if fill:
        if fill not in FEH_FLAGS: raise WallpaperError("Unknown fill mode (fill, fit, stretch, center, tile).")
        st["fill"] = fill
    if monitor:
        st["monitors"][monitor] = path
    else:
        st["monitors"] = {}
        set_setting("WALLPAPER", path)
        paths.ensure(paths.config_dir())
        with open(os.path.join(paths.config_dir(), "wallpaper"), "w") as f: f.write(path + "\n")
    if for_theme: st["per_theme"][current_theme()] = path
    if pair in ("light", "dark"):
        st["pair"][pair] = path
        st["pair"]["enabled"] = bool(st["pair"]["light"] and st["pair"]["dark"])
    st["current"] = {"path": path, "time": int(time.time())}
    st["last_theme"] = current_theme()
    state.save(st)
    set_setting("WALLPAPER_MODE", st["fill"])
    if paint_now: paint(path, st["fill"], run)
    return path

def resolve_for_theme(theme=None, st=None):
    """What the wallpaper should be for this theme: the light/dark pair if on, else a per-theme choice, else None (leave as is)."""
    st = st or state.load()
    theme = theme or current_theme()
    if st["pair"]["enabled"]:
        p = st["pair"].get(theme_mode(theme), "")
        if p and os.path.isfile(p): return p
    p = st["per_theme"].get(theme, "")
    return p if p and os.path.isfile(p) else None

def sync(run=subprocess.run):
    """Run after a theme/mode change (the theme-set hook): switch to the paired / per-theme wallpaper if there is one."""
    p = resolve_for_theme()
    if p and p != get_setting("WALLPAPER"):
        set_wallpaper(p, run=run)
        return p
    return None

def advance(run=subprocess.run, rng=None):
    """Next picture of the rotation collection (also used by `carpatic wallpaper next`)."""
    st = state.load()
    kw = {"rng": rng} if rng else {}
    p = state.next_in_rotation(st, theme_mode(), **kw)
    state.save(st)
    if not p: raise WallpaperError("The rotation collection has no pictures.")
    set_wallpaper(p, run=run)
    return p

def rotation_due(st=None, now=time.time):
    st = st or state.load()
    r = st["rotation"]
    return r["enabled"] and now() - r.get("last", 0) >= max(1, int(r["every"])) * 60

def set_rotation(on, every=None, collection=None, shuffle=None, on_login=None):
    def f(d):
        r = d["rotation"]
        r["enabled"] = bool(on)
        if every is not None: r["every"] = max(1, min(int(every), 24 * 60))
        if collection: r["collection"] = collection
        if shuffle is not None: r["shuffle"] = bool(shuffle)
        if on_login is not None: r["on_login"] = bool(on_login)
        r["last"] = int(time.time())
    return state.update(f)

def rotate_loop(stop=lambda: False, sleep=time.sleep, run=subprocess.run):
    """Daemon body: wake every 20 s, advance when due. Reads state each time so `rotate off` takes effect at once."""
    while not stop():
        try:
            if rotation_due(): advance(run=run)
        except (WallpaperError, KeyError, OSError):
            pass
        sleep(20)


# ----- generated colours ------------------------------------------------------------------------------------------------
def generate_colour(name, stops, angle=135, size=(1920, 1080)):
    """Render a solid colour (one stop) or a linear gradient (2-3 stops, angle in degrees) to a PNG; returns the file path."""
    import cairo, math
    for s in stops:
        if not re.match(r"^#[0-9a-fA-F]{6}$", s): raise WallpaperError("Colours must look like #1a2b3c.")
    d = paths.ensure(os.path.join(os.path.dirname(paths.wp_config_dir()), "wallpapers-generated"))
    fn = os.path.join(d, re.sub(r"[^A-Za-z0-9_-]", "_", name)[:40] + ".png")
    w, h = size
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, w, h)
    cr = cairo.Context(surf)
    rgb = lambda c: tuple(int(c[i:i + 2], 16) / 255 for i in (1, 3, 5))
    if len(stops) == 1:
        cr.set_source_rgb(*rgb(stops[0]))
    else:
        a = math.radians(angle); dx, dy = math.sin(a), -math.cos(a)
        half = (abs(dx) * w + abs(dy) * h) / 2
        g = cairo.LinearGradient(w / 2 - dx * half, h / 2 - dy * half, w / 2 + dx * half, h / 2 + dy * half)
        for i, s in enumerate(stops): g.add_color_stop_rgb(i / (len(stops) - 1), *rgb(s))
        cr.set_source(g)
    cr.paint()
    surf.write_to_png(fn)
    return fn

PRESET_COLOURS = [("Spruce", ["#0f3d33"]), ("Slate", ["#1e2430"]), ("Graphite", ["#2a2d33"]), ("Snow", ["#eef1f5"]), ("Sand", ["#e9dfcf"]),
                  ("Glacier", ["#1d3557", "#457b9d"]), ("Dusk", ["#2b1b4a", "#c2527a"]), ("Ember", ["#3b1d12", "#e5703a"]),
                  ("Moss", ["#14291d", "#4a7c59"]), ("Dawn", ["#f6d3b0", "#e58fa6", "#7a6bb5"]), ("Aurora", ["#0b2a2f", "#2ec4a0", "#5c4fc9"]),
                  ("Ink", ["#0b0e13"])]
