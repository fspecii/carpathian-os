"""Carpatic theme picker: what exists on this machine (themes, wallpapers, icon packs, cursors, fonts). Pure Python, no GTK.

Every path can be redirected (share, config, home) so the tests run against a fake tree. Nothing here writes."""
import os, re, glob, subprocess

SHARE = os.environ.get("CARPATIC_SHARE", "/usr/local/share/carpatic/configurator")
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp")

# accent sets of the design tokens (name, dark value, light value): same as carpatic_ui.ACCENT_SETS
ACCENT_SETS = [("Spruce", "#5cc8a8", "#16806a"), ("Glacier", "#6cb4f0", "#1e6fb8"), ("Dusk", "#a99bf0", "#6a4fd0"),
               ("Rose", "#f08aa8", "#c2386a"), ("Ember", "#f2a65a", "#b8640f"), ("Moss", "#a3d36b", "#4f8a1c")]
SCENES = [("bucegi", "Bucegi"), ("retezat", "Retezat"), ("fagaras", "Făgăraş"), ("rodna", "Rodna"), ("apuseni", "Apuseni"),
          ("piatra", "Piatra Craiului"), ("ceahlau", "Ceahlău"), ("tatra", "Tatra")]
WINDOW_BUTTONS = [("windows", "Windows"), ("macos", "macOS"), ("gnome", "GNOME"), ("kde", "Breeze"), ("minimal", "Minimal dots"),
                  ("ring", "Rings"), ("squircle", "Squircles"), ("contrast", "High contrast"), ("omarchy", "Omarchy"), ("classic98", "Classic 98"), ("luna", "Luna"), ("none", "None")]
PROFILES = [("windows", "Windows"), ("macos", "macOS"), ("ubuntu", "Ubuntu"), ("tiling", "Tiling"), ("beginner", "Simple")]
UI_FONTS = ["Inter", "Noto Sans", "Cantarell", "Fira Sans", "Roboto", "Open Sans", "Lato", "Source Sans 3", "DejaVu Sans", "Liberation Sans", "JetBrains Mono"]
MONO_FONTS = ["JetBrains Mono", "Fira Mono", "Roboto Mono", "Hack", "Source Code Pro", "IBM Plex Mono", "Iosevka", "Noto Sans Mono", "DejaVu Sans Mono", "Liberation Mono"]
# colour names a window border can take (resolved from the theme palette so it follows theme changes)
BORDER_COLORS = [("foreground", "Text"), ("muted", "Soft grey"), ("red", "Red"), ("orange", "Orange"), ("yellow", "Yellow"),
                 ("green", "Green"), ("cyan", "Cyan"), ("blue", "Blue"), ("magenta", "Magenta")]
# light/dark pairs; any other theme falls back to carpatic / carpatic-light
PAIRS = {"carpatic": "carpatic-light", "catppuccin": "catppuccin-latte", "rose-pine": "rose-pine-dawn", "tokyo-night": "tokyo-night-day",
         "gruvbox": "gruvbox-light", "flexoki-light": "carpatic", "white": "carpatic", "nord": "carpatic-light", "aero": "aero-night", "nothing": "nothing-light"}


def _sh_escape(v):
    """Values written to sourced KEY="value" files: escape \\ " $ ` and drop newlines (docs/SECURITY.md)."""
    import re as _re
    return _re.sub(r'(["\\$`])', r'\\\1', str(v).replace("\n", " ").replace("\r", " "))


def label_for(name):
    if name == "carpatic": return "Carpatic"
    if name == "carpatic-light": return "Carpatic Light"
    return re.sub(r"[-_]+", " ", name).title()


def parse_colors(path):
    c = {}
    try:
        with open(path) as f:
            for line in f:
                m = re.match(r'\s*(\w+)\s*=\s*"([^"]*)"', line)
                if m: c[m.group(1)] = m.group(2)
    except OSError:
        pass
    return c


def lum(h):
    h = h.lstrip("#")
    try: r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError: return 0
    return 0.299 * r + 0.587 * g + 0.114 * b


def read_env(path):
    d = {}
    try:
        with open(path) as f:
            for line in f:
                m = re.match(r'\s*(\w+)="?(.*?)"?\s*$', line)
                if m: d[m.group(1)] = m.group(2)
    except OSError:
        pass
    return d


class Catalog:
    def __init__(self, share=None, cfg=None, home=None):
        self.share = share or SHARE
        self.home = home or os.path.expanduser("~")
        self.cfg = cfg or os.environ.get("CARPATIC_CONFIG") or os.path.join(self.home, ".config", "carpatic")
        self._themes = None
        self._cache = {}

    # ---- themes ----
    def theme_dir(self, name):
        u = os.path.join(self.cfg, "themes", name)
        return u if os.path.isfile(os.path.join(u, "colors.toml")) else os.path.join(self.share, "themes", name)

    def theme_names(self):
        if self._themes is None:
            names = set()
            for base in (os.path.join(self.share, "themes"), os.path.join(self.cfg, "themes")):
                if os.path.isdir(base):
                    names |= {d for d in os.listdir(base) if os.path.isfile(os.path.join(base, d, "colors.toml"))}
            # dark themes first, carpatic first, then alphabetical: left/right then walks a calm order
            self._themes = sorted(names, key=lambda n: (not n.startswith("carpatic"), n))
        return self._themes

    def colors(self, name):
        k = ("c", name)
        if k not in self._cache:
            c = parse_colors(os.path.join(self.theme_dir(name), "colors.toml"))
            c.setdefault("mode", "dark")
            self._cache[k] = c
        return self._cache[k]

    def mode(self, name):
        return self.colors(name).get("mode", "dark")

    def counterpart(self, name, want):
        """The theme to use when the user flips Light/Dark: the pair when one exists, otherwise Carpatic's own."""
        if self.mode(name) == want: return name
        names = self.theme_names()
        cand = PAIRS.get(name)
        if cand in names and self.mode(cand) == want: return cand
        for k, v in PAIRS.items():
            if v == name and k in names and self.mode(k) == want: return k
        fallback = "carpatic" if want == "dark" else "carpatic-light"
        if fallback in names: return fallback
        for n in names:
            if self.mode(n) == want: return n
        return name

    # ---- wallpapers ----
    def wallpapers(self, theme):
        """[(path, label)] for a theme: its own pictures, the Carpathian scenes in the theme's mode, the user's folders."""
        mode = self.mode(theme)
        out, seen = [], set()

        def add(path, label):
            try: rp = os.path.realpath(path)
            except OSError: return
            if rp in seen or not os.path.isfile(rp): return
            seen.add(rp); out.append((path, label))

        td = self.theme_dir(theme)
        own = [f for pat in ("wallpaper*", "backgrounds/*") for f in sorted(glob.glob(os.path.join(td, pat))) if f.lower().endswith(IMG_EXT)]
        for i, f in enumerate(own):
            add(f, label_for(theme) if i == 0 else f"{label_for(theme)} {i + 1}")
        for key, name in SCENES:
            add(os.path.join(self.share, "wallpapers", f"{key}-{mode}.jpg"), name)
        for d in (os.path.join(self.cfg, "backgrounds", theme), os.path.join(self.home, "Pictures", "Wallpapers")):
            for f in sorted(glob.glob(os.path.join(d, "*")))[:40]:
                if f.lower().endswith(IMG_EXT): add(f, os.path.splitext(os.path.basename(f))[0].replace("-", " ").replace("_", " "))
        return out

    def default_wallpaper(self, theme):
        for f in (os.path.join(self.theme_dir(theme), "wallpaper.jpg"),):
            if os.path.isfile(f): return f
        w = self.wallpapers(theme)
        return w[0][0] if w else ""

    # ---- icons, cursors, fonts ----
    def _icon_dirs(self):
        return ["/usr/share/icons", os.path.join(self.home, ".local/share/icons"), os.path.join(self.home, ".icons")]

    def icon_themes(self):
        if "icons" not in self._cache:
            names = set()
            for d in self._icon_dirs():
                for t in glob.glob(os.path.join(d, "*", "index.theme")):
                    n = os.path.basename(os.path.dirname(t))
                    if n in ("hicolor", "default") or re.match(r"^(Faenza-|ePapirus|Breeze_Light|Paper-Mono-Dark|Adwaita-xfce|Papirus-(Light|Dark)$)", n): continue
                    try: txt = open(t, errors="ignore").read()
                    except OSError: continue
                    if re.search(r"^Directories=.+", txt, re.M): names.add(n)
            self._cache["icons"] = sorted(names, key=str.lower)
        return self._cache["icons"]

    def cursor_themes(self):
        if "cursors" not in self._cache:
            names = set()
            for d in self._icon_dirs():
                for t in glob.glob(os.path.join(d, "*", "cursors")):
                    if os.path.isdir(t): names.add(os.path.basename(os.path.dirname(t)))
            self._cache["cursors"] = sorted(names, key=str.lower)
        return self._cache["cursors"]

    def families(self):
        if "families" not in self._cache:
            try:
                out = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True, timeout=5).stdout
                fam = {f.strip() for line in out.splitlines() for f in line.split(",")}
            except (OSError, subprocess.SubprocessError):
                fam = set()
            self._cache["families"] = fam
        return self._cache["families"]

    def ui_fonts(self):
        fam = self.families()
        return [f for f in UI_FONTS if f in fam] if fam else list(UI_FONTS[:6])

    def mono_fonts(self):
        fam = self.families()
        return [f for f in MONO_FONTS if f in fam] if fam else list(MONO_FONTS[:4])


def _conf(path):
    d = {}
    try:
        with open(path) as f:
            for line in f:
                m = re.match(r'^(\w+)=(?:"([^"]*)"|([^\s#"]*))', line)
                if m: d[m.group(1)] = (m.group(2) if m.group(2) is not None else m.group(3)).strip()
    except OSError:
        pass
    return d


# Profile data is the registry: era presets and style packs become selectable
# without duplicating their labels in each GUI.
for _profile_path in sorted(glob.glob(os.path.join(SHARE, "profiles", "*.conf"))):
    _profile_id = os.path.basename(_profile_path)[:-5]
    _profile = _conf(_profile_path)
    if _profile_id not in {pid for pid, _ in PROFILES} and (_profile.get("DEFAULT_THEME") or _profile.get("STYLEPACK")):
        PROFILES.append((_profile_id, _profile.get("LABEL", _profile_id)))

# settings.conf key -> the key the configurator reads in a theme's look.conf / a profile conf (configurator/bin/carpatic-apply: S KEY LOOKKEY)
LOOK_MAP = {"UI_FONT": "FONT_UI", "UI_SIZE": "FONT_UI_SIZE", "MONO_FONT": "FONT_MONO", "CURSOR_THEME": "CURSOR", "WINDOW_BUTTONS": "TITLEBAR_STYLE",
            "CORNER_RADIUS": "CORNER_RADIUS", "INNER_GAP": "INNER_GAP", "OUTER_GAP": "OUTER_GAP", "BORDER_WIDTH": "BORDER_WIDTH", "BORDER_ACTIVE": "BORDER_ACTIVE"}
BUILTIN = {"BORDER_WIDTH": "2", "BORDER_ACTIVE": "", "CORNER_RADIUS": "0", "INNER_GAP": "8", "OUTER_GAP": "8", "UI_SIZE": "10", "WINDOW_BUTTONS": "windows"}


def look_conf(cat, name):
    """The theme's own look file (themes/<name>/look.conf), as {settings key: value}; ICON_<mode> maps to ICON_THEME."""
    d = _conf(os.path.join(cat.theme_dir(name), "look.conf"))
    out = {sk: d[lk] for sk, lk in LOOK_MAP.items() if lk in d}
    ik = d.get("ICON_" + cat.mode(name))
    if ik: out["ICON_THEME"] = ik
    return out


def profile_conf(cat, profile):
    return _conf(os.path.join(cat.share, "profiles", profile + ".conf"))


def default_for(cat, state, key):
    """What `key` is when the user chose nothing: theme look file > desktop style conf > built-in (the configurator's own chain)."""
    theme = state.get("THEME") or "carpatic"; profile = state.get("PROFILE") or "tiling"; mode = cat.mode(theme)
    v = look_conf(cat, theme).get(key)
    if v: return v
    p = profile_conf(cat, profile)
    pk = {"UI_FONT": "FONT_UI", "UI_SIZE": "FONT_UI_SIZE", "MONO_FONT": "FONT_MONO", "CURSOR_THEME": "CURSOR", "WINDOW_BUTTONS": "TITLEBAR_STYLE",
          "ICON_THEME": "ICON_" + mode, "ACCENT": "ACCENT_" + mode}.get(key, key)
    if p.get(pk): return p[pk]
    return BUILTIN.get(key, "")


def theme_accent(cat, state, theme=None):
    """The accent a theme really shows: the user's pick, else (Carpatic themes only) the desktop style's accent, else the palette's."""
    theme = theme or state.get("THEME") or "carpatic"
    if theme == (state.get("THEME") or "carpatic") and state.get("ACCENT"): return state["ACCENT"]
    if theme in ("carpatic", "carpatic-light"):
        v = profile_conf(cat, state.get("PROFILE") or "tiling").get("ACCENT_" + cat.mode(theme))
        if v: return v
    return cat.colors(theme).get("accent", "#5cc8a8")


def profile_defaults(cat, profile, mode):
    """What a desktop style gives when the user chose nothing: used by the mock so 'default' rows still draw the real thing."""
    p = profile_conf(cat, profile)
    return {"bar": p.get("BAR", "dwm"), "buttons": p.get("TITLEBAR_STYLE", "windows"), "titlebars": p.get("TITLEBARS", "on") != "off",
            "layout": p.get("LAYOUT", "float"), "ui_font": p.get("FONT_UI", "Inter"), "ui_size": p.get("FONT_UI_SIZE", "10"),
            "mono": p.get("FONT_MONO", "JetBrains Mono"), "icons": p.get("ICON_" + mode, "Papirus"), "cursor": p.get("CURSOR", "Adwaita"),
            "side": p.get("TITLEBAR_BUTTONS", "right")}


def save_user_theme(cat, name, state, wallpaper_path=None):
    """'Save as my theme': a new folder in ~/.config/carpatic/themes with the current palette (accent included), the chosen wallpaper and a
    look.conf in the configurator's own format (so Settings and carpatic-apply honour it) plus the border keys the picker reads.
    Returns the theme id, or None when the name is empty. Never overwrites a system theme."""
    import shutil
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not slug: return None
    if os.path.isfile(os.path.join(cat.share, "themes", slug, "colors.toml")): slug += "-mine"
    theme = state.get("THEME") or "carpatic"
    base = cat.theme_dir(theme)
    dest = os.path.join(cat.cfg, "themes", slug)
    os.makedirs(dest, exist_ok=True)
    try:
        with open(os.path.join(base, "colors.toml")) as f: txt = f.read()
    except OSError:
        txt = ""
    acc = theme_accent(cat, state)
    if acc:
        if re.search(r'^accent\s*=', txt, re.M): txt = re.sub(r'^accent\s*=.*$', 'accent = "%s"' % acc, txt, count=1, flags=re.M)
        else: txt += '\naccent = "%s"\n' % acc
    with open(os.path.join(dest, "colors.toml"), "w") as f: f.write(txt)
    wp = wallpaper_path or state.get("WALLPAPER") or cat.default_wallpaper(theme)
    if wp and os.path.isfile(wp):
        for old in glob.glob(os.path.join(dest, "wallpaper.*")): os.remove(old)
        shutil.copyfile(wp, os.path.join(dest, "wallpaper" + (os.path.splitext(wp)[1].lower() or ".jpg")))
    mode = cat.mode(theme)
    with open(os.path.join(dest, "look.conf"), "w") as f:
        f.write("# written by carpatic-theme-picker (Save as my theme). Same keys as a style conf; Settings and carpatic-apply read it.\n")
        for sk, lk in LOOK_MAP.items():
            v = state.get(sk, "")
            if v: f.write('%s="%s"\n' % (lk, _sh_escape(v)))   # look.conf is sourced by shell
        if state.get("ICON_THEME"): f.write('ICON_%s="%s"\n' % (mode, _sh_escape(state["ICON_THEME"])))
    cat._themes = None; cat._cache.pop(("c", slug), None)
    return slug
