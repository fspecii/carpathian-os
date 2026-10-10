#!/usr/bin/env python3
"""theme-port: host checks for the LinPad era theme/profile data port (docs/LINPAD-THEME-PORT.md).

Validates, without launching any GUI:
  1. every ported palette parses (TOML), has the keys carpatic-render needs, well-formed colours;
  2. the ported colour data is faithful to the upstream CC0 palettes (pinned commit
     01246414fe9517d883b9489ba3e9e9f3780f479e, upstream/themes/desktop-themes/colors/...);
  3. every profile .conf sources as POSIX sh and every id it references really exists:
     key/sxhkd files, tint2/rofi templates, panel designs and options, GTK style templates,
     window-button styles drawn by crates/wm/src/decoration.rs, icon/cursor/font packs;
  4. every theme's look.conf uses only supported ids, and both wallpapers are readable
     1920x1080 JPEGs;
  5. the real renderer (configurator/bin/carpatic-render + templates/dwm-themes.toml.tpl)
     turns each (theme, profile) pair into valid TOML with the expected native button style.

Usage: python3 tests/theme-port.py  (from anywhere; paths resolve from __file__)
"""
import os
import json
import tempfile
import re
import subprocess
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
CONF = os.path.join(ROOT, "integration", "carpatic", "configurator")
REFERENCE = json.loads(open(os.path.join(ROOT, "tests", "fixtures", "linpad-palettes.json"), encoding="utf-8").read())
COMMIT = "01246414fe9517d883b9489ba3e9e9f3780f479e"

# theme id -> (upstream palette name, profile id); the Carpatic theme id is the registry key
PORTED = {
    "classic-98": ("classic-98", "classic-98"),
    "luna": ("luna", "luna"),
    "aero": ("aero", "aero"),
    "aero-night": ("aero-night", "aero-night"),
    "platinum": ("platinum", "platinum"),
    "aqua": ("aqua", "aqua"),
    "aqua-metal": ("aqua", "aqua-metal"),   # same CC0 palette by design (brushed metal is native chrome)
    "berry": ("berry", "berry"),
    "nothing": ("dot-matrix-dark", "nothing"),
    "nothing-light": ("dot-matrix", "nothing"),
}
PALETTE_KEYS = ["mode", "accent", "selection", "muted", "background", "dark_background", "darker_background",
                "lighter_background", "foreground", "dark_foreground", "light_foreground", "bright_foreground",
                "red", "yellow", "orange", "green", "cyan", "blue", "magenta", "brown",
                "bright_red", "bright_yellow", "bright_green", "bright_cyan", "bright_blue", "bright_magenta"]

failures = []
checks = 0


def check(cond, msg):
    global checks
    checks += 1
    if not cond:
        failures.append(msg)
    return bool(cond)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------- supported ids (from the real consumers)
def decoration_styles():
    """Window-button styles the Rust WM actually draws (crates/wm/src/decoration.rs metrics())."""
    src = read(os.path.join(ROOT, "crates", "wm", "src", "decoration.rs"))
    m = re.search(r"fn metrics\(style: &str\).*?\n    \}", src, re.S)
    return set(re.findall(r'"([a-z0-9]+)"\s*=>', m.group(0))) | {"none"}


def appearance_styles():
    """Window-button values carpatic-appearance accepts (bin/carpatic-appearance validation)."""
    src = read(os.path.join(CONF, "bin", "carpatic-appearance"))
    m = re.search(r"WINDOW_BUTTONS\)\s*case\s+\$2\s+in\s+([^)]*)\)", src)
    return set(m.group(1).strip().split("|")) if m else set()


def panel_options():
    """designs.OPTIONS imported from the real panel package (pure Python, no GTK)."""
    sys.path.insert(0, os.path.join(ROOT, "integration", "carpatic", "panel", "lib"))
    import carpatic_panel.designs as designs
    return designs.OPTIONS, set(designs.DESIGNS)


def pack_ids():
    """pack ids + the theme dirs they install (share/packs.list), plus what packages.txt ships."""
    ids, dirs = set(), set()
    for line in read(os.path.join(CONF, "share", "packs.list")).splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            f = line.split("|")
            ids.add(f[0])
            dirs.update(f[7].split())
    shipped = set(re.findall(r"[\w-]+", read(os.path.join(CONF, "packages.txt"))))
    return ids, dirs, shipped


def conf_get(path, key):
    """The carpatic-lib profile_get / look.conf tl() chain, replicated for validation."""
    text = read(path)
    m = re.search(rf'^{re.escape(key)}="([^"]*)"', text, re.M) or re.search(rf"^{re.escape(key)}=([^\s#\"]+)", text, re.M)
    return m.group(1) if m else ""


def sh_quote(s):
    return "'" + s.replace("'", "'\\''") + "'"


def sh_source(path, keys):
    """Source a .conf in POSIX sh and print KEY=VALUE lines (checks sh-parseability for real)."""
    lines = ['. "$1"']
    for k in keys:
        lines.append('printf "%s=%s\\n" ' + sh_quote(k) + ' "${' + k + ':-}"')
    script = "\n".join(lines) + "\n"
    out = subprocess.run(["sh", "-c", script, "sh", path], capture_output=True, text=True)
    if out.returncode != 0:
        return None, out.stderr.strip()
    vals = {}
    for line in out.stdout.splitlines():
        k, _, v = line.partition("=")
        if k in keys:
            vals[k] = v
    return vals, None


# ---------------------------------------------------------------- 1+2: palettes
def hexok(v):
    return bool(re.fullmatch(r"#[0-9a-fA-F]{6}", v))


def luminance(hx):
    r, g, b = (int(hx[i:i + 2], 16) for i in (1, 3, 5))
    return 0.299 * r + 0.587 * g + 0.114 * b


def check_palette(theme, upstream_name):
    colors_path = os.path.join(CONF, "themes", theme, "colors.toml")
    if not check(os.path.isfile(colors_path), f"theme {theme}: colors.toml missing"):
        return None
    text = read(colors_path)
    check(COMMIT in text, f"theme {theme}: attribution comment must name the pinned upstream commit {COMMIT}")
    data = tomllib.loads(text)
    for k in PALETTE_KEYS:
        check(k in data, f"theme {theme}: palette key '{k}' missing")
    check(data.get("mode") in ("light", "dark"), f"theme {theme}: mode must be light or dark")
    for k, v in data.items():
        if k != "mode" and not k.startswith("_"):
            check(isinstance(v, str) and hexok(v) or k == "neutral_title",
                  f"theme {theme}: '{k}' must be #rrggbb (got {v!r})")
    # readability: text on background and accent as selection-ish contrast
    if "foreground" in data and "background" in data:
        d = abs(luminance(data["foreground"]) - luminance(data["background"]))
        check(d > 100, f"theme {theme}: foreground/background contrast too low ({d:.0f})")
    # fidelity: every colour equals the upstream CC0 palette (aqua-metal reuses aqua by design)
    up = REFERENCE["palettes"][upstream_name]
    ours = {k: v.lower() for k, v in data.items() if isinstance(v, str) and hexok(v)}
    theirs = {k: v.lower() for k, v in up.items() if isinstance(v, str) and hexok(v)}
    for k, v in theirs.items():
        check(k in ours and ours[k] == v, f"theme {theme}: '{k}' drifted from upstream {upstream_name}: {ours.get(k)} != {v}")
    check(data.get("mode") == up.get("mode"), f"theme {theme}: mode must match upstream")
    for k in ("background", "foreground", "accent"):
        check(ours.get(k) == theirs.get(k), f"theme {theme}: '{k}' must match upstream {upstream_name}")
    return data


# ---------------------------------------------------------------- 3: profiles
def check_profile(profile, theme):
    path = os.path.join(CONF, "profiles", f"{profile}.conf")
    if not check(os.path.isfile(path), f"profile {profile}: .conf missing"):
        return
    text = read(path)
    shkeys = ["LABEL", "DESC", "BAR", "BAR_TEMPLATES", "PANEL_DESIGN", "PANEL_OPTS", "LAUNCHER", "LAYOUT",
              "KEYS", "SXHKD", "SUPERTAP", "TITLEBARS", "TITLEBAR_BUTTONS", "TITLEBAR_STYLE", "GTK_STYLE",
              "CURSOR", "BUTTON_LAYOUT", "FONT_UI", "ACCENT_dark", "ACCENT_light"]
    vals, err = sh_source(path, shkeys)
    check(err is None, f"profile {profile}: does not source in POSIX sh: {err}")
    if err is not None:
        return
    for k in shkeys[:5] + ["LAUNCHER", "TITLEBAR_STYLE", "GTK_STYLE", "FONT_UI", "CURSOR", "BUTTON_LAYOUT"]:
        check(vals.get(k, "") != "", f"profile {profile}: key {k} empty or unset after sourcing")
    # key/template/daemon references must exist
    keys_file = conf_get(path, "KEYS")
    check(keys_file and os.path.isfile(os.path.join(CONF, "profiles", keys_file)),
          f"profile {profile}: KEYS file profiles/{keys_file} missing")
    sx = conf_get(path, "SXHKD")
    check(sx in ("", "none") or os.path.isfile(os.path.join(CONF, "profiles", sx)),
          f"profile {profile}: SXHKD file profiles/{sx} missing")
    for tpl in conf_get(path, "BAR_TEMPLATES").split():
        check(os.path.isfile(os.path.join(CONF, "templates", "tint2", f"{tpl}.tint2rc.tpl")),
              f"profile {profile}: tint2 template {tpl}.tint2rc.tpl missing (invented panel id?)")
    launcher = conf_get(path, "LAUNCHER")
    check(launcher and os.path.isfile(os.path.join(CONF, "templates", "rofi", f"{launcher}.rasi.tpl")),
          f"profile {profile}: rofi launcher template {launcher}.rasi.tpl missing")
    # panel: real designs and real option keys/values
    options, designs = panel_options()
    design = conf_get(path, "PANEL_DESIGN")
    check(design in designs, f"profile {profile}: PANEL_DESIGN '{design}' is not a carpatic-panel design")
    toks = conf_get(path, "PANEL_OPTS").split()
    check(len(toks) % 2 == 0, f"profile {profile}: PANEL_OPTS must be KEY VALUE pairs")
    for k, v in zip(toks[0::2], toks[1::2]):
        check(k in options, f"profile {profile}: PANEL_OPTS key '{k}' is not a panel option")
        if k in options:
            typ, rng, _ = options[k]
            ok = (v in rng) if typ == "enum" else (v.lstrip("-").isdigit() and (int(v) in (0, -1) or rng[0] <= int(v) <= rng[1])) if typ == "int" else True
            check(ok, f"profile {profile}: PANEL_OPTS {k}={v} out of range {rng}")
    # window buttons: drawn by the Rust WM and accepted by carpatic-appearance
    styles = decoration_styles()
    app_styles = appearance_styles()
    for style, where in ((conf_get(path, "TITLEBAR_STYLE"), f"profile {profile} TITLEBAR_STYLE"),
                         (conf_get(os.path.join(CONF, "themes", theme, "look.conf"), "TITLEBAR_STYLE"), f"theme {theme} look.conf TITLEBAR_STYLE")):
        check(style in styles, f"{where}: '{style}' is not drawn by decoration.rs {sorted(styles)}")
        if app_styles:
            check(style in app_styles, f"{where}: '{style}' is not accepted by carpatic-appearance")
    # GTK template for both modes of the style family
    gtk = conf_get(path, "GTK_STYLE")
    for mode in ("light", "dark"):
        check(gtk and os.path.isfile(os.path.join(CONF, "templates", "gtk", f"{gtk}-{mode}.css.tpl")),
              f"profile {profile}: GTK template gtk/{gtk}-{mode}.css.tpl missing")
    # packs: referenced downloadables exist in the catalogue; icons/cursors exist or are shipped
    packs, pack_dirs, shipped = pack_ids()
    for p in conf_get(path, "PACKS").split():
        check(p in packs, f"profile {profile}: PACKS id '{p}' not in share/packs.list")
    look = os.path.join(CONF, "themes", theme, "look.conf")
    for f, where in ((path, f"profile {profile}"), (look, f"theme {theme} look.conf")):
        if not os.path.isfile(f):
            continue
        for key in conf_all_keys(f):
            m = re.fullmatch(r"ICON(?:_PREFERRED)?_(light|dark)", key)
            if m:
                name = conf_get(f, key)
                if name and not name.startswith("Papirus"):
                    check(name in pack_dirs or name in shipped,
                          f"{where}: icon theme '{name}' is not an installed dir of any pack nor shipped")
    for acc in ("ACCENT_dark", "ACCENT_light"):
        v = conf_get(path, acc)
        check(v == "" or re.fullmatch(r"#[0-9a-fA-F]{6}", v), f"profile {profile}: {acc} must be #rrggbb")
    check(conf_get(path, "LAYOUT") in ("tile", "float"), f"profile {profile}: LAYOUT must be tile|float")
    check(conf_get(path, "TITLEBARS") in ("on", "off"), f"profile {profile}: TITLEBARS must be on|off")
    check(conf_get(path, "TITLEBAR_BUTTONS") in ("left", "right"), f"profile {profile}: TITLEBAR_BUTTONS must be left|right")


def conf_all_keys(path):
    return re.findall(r"^(\w+)=", read(path), re.M)


# ---------------------------------------------------------------- 4: look.conf + wallpapers
def check_theme_files(theme):
    td = os.path.join(CONF, "themes", theme)
    look = os.path.join(td, "look.conf")
    if check(os.path.isfile(look), f"theme {theme}: look.conf missing"):
        styles = decoration_styles()
        for key in conf_all_keys(look):
            v = conf_get(look, key)
            if key == "TITLEBAR_STYLE":
                check(v in styles, f"theme {theme}: look.conf TITLEBAR_STYLE '{v}' not drawn by decoration.rs")
            elif key in ("CORNER_RADIUS", "INNER_GAP", "OUTER_GAP", "BORDER_WIDTH", "BORDER_HIGHLIGHT"):
                check(v.isdigit(), f"theme {theme}: look.conf {key} must be a non-negative integer")
            elif key == "BORDER_ACTIVE":
                check(v == "" or hexok(v), f"theme {theme}: look.conf BORDER_ACTIVE must be #rrggbb")
    try:
        from PIL import Image
    except ImportError:
        check(False, "Pillow is required for the wallpaper checks (python3 -m pip install pillow)")
        return
    for name in ("wallpaper.jpg", "wallpaper-2.jpg"):
        p = os.path.join(td, name)
        if not check(os.path.isfile(p), f"theme {theme}: {name} missing"):
            continue
        try:
            with Image.open(p) as im:
                im.verify()
            with Image.open(p) as im:
                check(im.format == "JPEG", f"theme {theme}: {name} is {im.format}, expected JPEG")
                check(im.size == (1920, 1080), f"theme {theme}: {name} is {im.size[0]}x{im.size[1]}, expected 1920x1080")
        except Exception as e:
            check(False, f"theme {theme}: {name} unreadable: {e}")


# ---------------------------------------------------------------- 5: real render through the registry template
def render_dwm(theme, profile):
    colors = os.path.join(CONF, "themes", theme, "colors.toml")
    look = os.path.join(CONF, "themes", theme, "look.conf")
    pconf = os.path.join(CONF, "profiles", f"{profile}.conf")
    mode = tomllib.loads(read(colors))["mode"]
    chain = lambda lookkey, profkey, dflt: (conf_get(look, lookkey) if os.path.isfile(look) else "") or conf_get(pconf, profkey) or dflt
    layout = conf_get(pconf, "LAYOUT") or "tile"
    tray = "1" if (conf_get(pconf, "BAR") or "dwm") == "dwm" else "0"
    tb = "0" if conf_get(pconf, "TITLEBARS") == "off" else "1"
    extras = ["BORDER_WIDTH=" + (chain("BORDER_WIDTH", "BORDER_WIDTH", "2")),
              "BORDER_ACTIVE=" + chain("BORDER_ACTIVE", "BORDER_ACTIVE", ""),
              "BORDER_INACTIVE=" + chain("BORDER_INACTIVE", "BORDER_INACTIVE", ""),
              "BORDER_HIGHLIGHT=0", "SMART_GAPS=0", "DRAG_TILED=float",
              "CORNER_RADIUS=" + chain("CORNER_RADIUS", "CORNER_RADIUS", "0"),
              "INNER_GAP=" + chain("INNER_GAP", "INNER_GAP", "8"),
              "OUTER_GAP=" + chain("OUTER_GAP", "OUTER_GAP", "8"),
              "UI_SCALE=100", "DEFLAYOUT=" + layout, "WORKSPACES=4", "WS_NAMES=",
              "TRAY_INT=" + tray, "TITLEBARS_INT=" + tb,
              "TITLEBAR_BUTTONS=" + (conf_get(pconf, "TITLEBAR_BUTTONS") or "right"),
              "BSTYLE=" + chain("TITLEBAR_STYLE", "TITLEBAR_STYLE", "windows"),
              "BSIDE=auto", "BSHOWN=all", "TALIGN=auto",
              "DARKMODE=" + ("false" if mode == "light" else "true")]
    out = subprocess.run(["sh", os.path.join(CONF, "bin", "carpatic-render"), colors,
                          os.path.join(CONF, "templates", "dwm-themes.toml.tpl"), *extras],
                         capture_output=True, text=True)
    if not check(out.returncode == 0, f"render {theme}: carpatic-render failed: {out.stderr.strip()}"):
        return None
    text = out.stdout
    check("{{" not in text, f"render {theme}: unresolved template tokens remain")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        check(False, f"render {theme}: generated themes.toml is not valid TOML: {e}")
        return None
    tb_style = data.get("titlebar", {}).get("button_style")
    expected = chain("TITLEBAR_STYLE", "TITLEBAR_STYLE", "windows")
    check(tb_style == expected, f"render {theme}: button_style is {tb_style!r}, expected {expected!r}")
    if theme == "classic-98":
        native = data["theme"]["carpatic"]
        check(native["selbgcolor"] == "#000080" and native["selfgcolor"] == "#ffffff", "Classic 98 must have a legible white title on navy")
    if theme == "luna":
        native = data["theme"]["carpatic"]
        palette = tomllib.loads(read(colors))
        check(native["selbgcolor"] == palette["accent"] and native["selfgcolor"] == "#ffffff", "Luna must use its blue accent with legible white title text")
    check(data.get("theme", {}).get("carpatic", {}).get("dark_mode") is (mode == "dark"),
          f"render {theme}: dark_mode does not follow palette mode {mode}")
    return data


def main():
    # uniqueness: one theme dir and one profile per ported id; no palette collisions except the documented aqua pair
    ids = list(PORTED)
    check(len(ids) == len(set(ids)), "theme ids must be unique")
    check(REFERENCE["commit"] == COMMIT, "palette fixture must identify the pinned upstream commit")
    sigs = {}
    for theme, (upstream_name, profile) in PORTED.items():
        data = check_palette(theme, upstream_name)
        if data:
            sig = tuple(sorted((k, v) for k, v in data.items() if isinstance(v, str) and hexok(v)))
            twin = "aqua" if theme == "aqua-metal" else None  # documented same-palette pair
            if sig in sigs:
                check(sigs[sig] == twin, f"theme {theme}: palette identical to {sigs[sig]} (only aqua/aqua-metal may share)")
            else:
                sigs[sig] = theme
        check_profile(profile, theme)
        check_theme_files(theme)
        render_dwm(theme, profile)
    # Exercise the actual preset CLI with isolated state; selecting a new era
    # chooses its palette, while reselecting it preserves a colour customization.
    with tempfile.TemporaryDirectory() as temporary:
        env = dict(os.environ, CARPATIC_SHARE=CONF, CARPATIC_CONFIG=temporary + "/config", CARPATIC_STATE=temporary + "/state")
        for profile in dict.fromkeys(profile for _, profile in PORTED.values()):
            result = subprocess.run(["sh", CONF + "/bin/carpatic-profile", "set", profile, "--no-apply"], env=env, capture_output=True, text=True)
            check(result.returncode == 0, f"profile {profile}: CLI preset failed: {result.stderr}")
            state = read(temporary + "/config/settings.conf")
            check(f'PROFILE="{profile}"' in state and f'THEME="{profile}"' in state, f"profile {profile}: matching palette was not selected")
        subprocess.run(["sh", CONF + "/bin/carpatic-theme", "set", "nothing-light", "--no-apply"], env=env, check=True)
        subprocess.run(["sh", CONF + "/bin/carpatic-profile", "set", "nothing", "--no-apply"], env=env, check=True)
        check('THEME="nothing-light"' in read(temporary + "/config/settings.conf"), "reselecting profile must preserve chosen light palette")
    # the nothing fix: native TITLEBAR_STYLE=nothing is actually used
    for t in ("nothing", "nothing-light"):
        check(conf_get(os.path.join(CONF, "themes", t, "look.conf"), "TITLEBAR_STYLE") == "nothing",
              f"theme {t}: look.conf must use the native TITLEBAR_STYLE=nothing (decoration.rs supports it)")
    print(f"{checks} checks, {len(failures)} failures")
    for f in failures:
        print("FAIL:", f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
