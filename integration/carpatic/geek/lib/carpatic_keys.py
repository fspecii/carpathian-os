"""Reads the keyboard shortcuts of a Carpatic profile and renders them: text, search list, HTML, PDF.

The source of truth is the generated hotkeys.toml (what dwm really reads) plus the profile's sxhkd file for the macOS Cmd shortcuts.
Nothing here is hand-written per profile. Python 3.11+ standard library; PDF needs pycairo + PangoCairo (installed with the settings app).
"""
import html
import os
import re
import subprocess
import sys
import tomllib

GROUP_ORDER = ["Apps and tools", "Windows", "Tiling and layout", "Workspaces", "Monitors", "Capture", "Session and power", "Media and hardware keys",
               "Files and previews", "Touchpad gestures", "Mouse", "Cmd shortcuts"]

PROFILE_LABEL = {"windows": "Windows style", "macos": "macOS style", "ubuntu": "Ubuntu style", "tiling": "Tiling style (Omarchy-like)",
                 "beginner": "Beginner style"}
SUPER_NAME = {"windows": "Win", "beginner": "Win", "macos": "Cmd", "ubuntu": "Super", "tiling": "Super"}

KEYNAMES = {"Return": "Enter", "Escape": "Esc", "space": "Space", "comma": ",", "period": ".", "slash": "/", "Left": "←",
            "Right": "→", "Up": "↑", "Down": "↓", "Print": "PrtSc", "BackSpace": "Backspace", "Tab": "Tab",
            "bracketleft": "[", "bracketright": "]", "minus": "-", "equal": "=", "grave": "`", "backslash": "\\", "semicolon": ";",
            "apostrophe": "'", "Delete": "Del", "Home": "Home", "End": "End", "Prior": "PgUp", "Next": "PgDn", "Insert": "Ins",
            "XF86AudioRaiseVolume": "Volume up", "XF86AudioLowerVolume": "Volume down", "XF86AudioMute": "Mute",
            "XF86AudioMicMute": "Mic mute", "XF86AudioPlay": "Play", "XF86AudioPause": "Pause", "XF86AudioNext": "Next track",
            "XF86AudioPrev": "Previous track", "XF86MonBrightnessUp": "Brightness up", "XF86MonBrightnessDown": "Brightness down",
            "XF86KbdBrightnessUp": "Keyboard light up", "XF86KbdBrightnessDown": "Keyboard light down", "XF86WLAN": "Wi-Fi key",
            "XF86RFKill": "Airplane key", "XF86Bluetooth": "Bluetooth key", "XF86PowerOff": "Power key", "XF86Sleep": "Sleep key",
            "XF86Hibernate": "Hibernate key"}

FUNC_DESC = {"togglefloating": "Toggle floating", "killclient": "Close window", "focusstack": "Focus next or previous window",
             "movestack": "Move window in the stack", "zoom": "Promote to master", "view": "Go to workspace",
             "tag": "Send window to workspace", "toggleview": "Show workspace too", "toggletag": "Also show window on workspace",
             "incnmaster": "Windows in master area", "setmfact": "Resize master area", "setlayout": "Change layout",
             "fullscreen": "Fullscreen", "togglebar": "Hide or show the bar", "focusmon": "Focus other monitor",
             "tagmon": "Send window to other monitor", "quit": "Quit the desktop", "minimize": "Minimise window",
             "unminimize": "Restore minimised window", "togglemaximize": "Maximise or restore", "moveorplace": "Move window",
             "resizemouse": "Resize window", "setcfact": "Resize this window in the stack", "togglefakefullscreen": "Fake fullscreen", "togglelayout": "Auto-tiling on or off (this workspace)",
             "viewrel": "Previous or next workspace", "tagrel": "Send window to previous or next workspace", "incgaps": "Gaps between windows"}

CMD_NAMES = {"c": "Copy", "v": "Paste", "x": "Cut", "a": "Select all", "z": "Undo", "s": "Save", "f": "Find", "t": "New tab",
             "n": "New window or document", "o": "Open", "p": "Print", "r": "Reload", "l": "Address bar", "b": "Bold",
             "i": "Italic", "u": "Underline", "k": "Insert link", "d": "Bookmark", "j": "Downloads", "y": "History", "g": "Find next",
             "redo": "Redo", "home": "Start of line", "end": "End of line", "delword": "Delete word",
             "prevtab": "Previous tab", "nexttab": "Next tab"}


class Binding:
    def __init__(self, mods, key, desc, group, func="", exec_=None, source="hotkeys"):
        self.mods, self.key, self.desc, self.group = mods, key, desc, group
        self.func, self.exec, self.source = func, exec_ or [], source

    def chord(self, super_name="Super"):
        mods = [{"SUPER": super_name, "ALT": "Alt", "CTRL": "Ctrl", "SHIFT": "Shift", "MOD4": super_name}.get(m, m.capitalize()) for m in self.mods]
        order = {super_name: 0, "Ctrl": 1, "Alt": 2, "Shift": 3}
        mods.sort(key=lambda m: order.get(m, 9))
        key = KEYNAMES.get(self.key, self.key.upper() if len(self.key) == 1 else self.key)
        return mods + [key]

    def xdotool_chord(self):
        """Key combination for `xdotool key` (to try a binding from the cheat sheet)."""
        m = {"SUPER": "super", "ALT": "alt", "CTRL": "ctrl", "SHIFT": "shift"}
        return "+".join([m.get(x, x.lower()) for x in self.mods] + [self.key])

    def tryable(self):
        if self.source != "hotkeys" or self.func in ("quit",) or self.key.startswith("XF86"):
            return False
        e = " ".join(self.exec)
        return not re.search(r"poweroff|reboot|--choose", e)


def classify(func, key, execs):
    e = " ".join(execs)
    if key.startswith("XF86"):
        return "Media and hardware keys"
    if func in ("view", "tag", "toggleview", "toggletag", "viewrel", "tagrel"):
        return "Workspaces"
    if func in ("setlayout", "togglelayout", "togglefloating", "focusstack", "movestack", "zoom", "incnmaster", "setmfact", "setcfact", "incgaps"):
        return "Tiling and layout"
    if func in ("focusmon", "tagmon"):
        return "Monitors"
    if func == "spawn":
        if "screenshot" in e or key == "Print":
            return "Capture"
        if re.search(r"powermenu|carpatic-lock|carpatic-power|loginctl|slock", e):
            return "Session and power"
        if "carpatic-snap" in e or "carpatic-switch" in e:
            return "Windows"
        return "Apps and tools"
    if func == "quit":
        return "Session and power"
    return "Windows"


def describe(d, func, execs):
    if d:
        return d
    if func == "spawn" and execs:
        return execs[0].split("/")[-1]
    return FUNC_DESC.get(func, func)


def parse_hotkeys(path):
    with open(path, "rb") as f:
        doc = tomllib.load(f)
    out = []

    def section(name):
        # dwm's own reader ignores [vars]; in strict TOML the arrays after it belong to that table, so look in both places
        return doc.get(name) or doc.get("vars", {}).get(name) or []
    for k in section("keys"):
        mods = k.get("mod", "").split()
        func = k.get("func", "")
        ex = k.get("exec", [])
        key = k.get("key", "")
        if "used by carpatic-layout" in k.get("desc", ""):
            continue      # internal binding of the layout switcher
        out.append(Binding(mods, key, describe(k.get("desc", ""), func, ex), classify(func, key, ex), func, ex))
    if section("tag_keys"):
        keys = [t["key"] for t in section("tag_keys") if "key" in t]
        rng = f"{keys[0]}-{keys[-1]}" if len(keys) > 1 else keys[0]
        for mods, desc, func in ((["SUPER"], "Go to workspace", "view"), (["SUPER", "SHIFT"], "Send window to workspace", "tag"),
                                 (["SUPER", "CTRL"], "Show workspace as well", "toggleview"),
                                 (["SUPER", "CTRL", "SHIFT"], "Also show window on workspace", "toggletag")):
            out.append(Binding(mods, rng, desc, "Workspaces", func))
    for b in section("buttons"):
        func = b.get("func", "")
        if b.get("click") == "ClkClientWin":
            btn = {1: "Left-drag", 2: "Middle-click", 3: "Right-drag"}.get(b.get("button"), f"Button {b.get('button')}")
            out.append(Binding(b.get("mod", "").split(), btn, FUNC_DESC.get(func, func) + " (on a window)", "Mouse", func, source="mouse"))
        elif b.get("click") == "ClkTagBar" and b.get("mod"):
            btn = {1: "Click", 3: "Right-click"}.get(b.get("button"), "Click")
            what = {"tag": "Send window to that workspace (click its number)",
                    "toggletag": "Also show window there (click its number)"}.get(func, FUNC_DESC.get(func, func))
            out.append(Binding(b.get("mod", "").split(), btn, what, "Mouse", func, source="mouse"))
    return out


def expand_braces(s):
    m = re.search(r"\{([^{}]*)\}", s)
    if not m:
        return [s]
    return [r for part in m.group(1).split(",") for r in expand_braces(s[:m.start()] + part + s[m.end():])]


def parse_sxhkd(path):
    out = []
    try:
        lines = open(path).read().splitlines()
    except OSError:
        return out
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip() and not line.startswith(("#", " ", "\t")) and i + 1 < len(lines):
            cmd = lines[i + 1].strip()
            keys = expand_braces(line.strip())
            cmds = expand_braces(cmd)
            if len(keys) == len(cmds):
                for kk, cc in zip(keys, cmds):
                    parts = [p.strip() for p in kk.split("+")]
                    mods = [p.upper() for p in parts[:-1]]
                    last = cc.split()[-1] if cc.startswith("carpatic-cmd") else cc
                    if cc.startswith("carpatic-cmd") and last in CMD_NAMES:
                        desc = CMD_NAMES[last]
                    else:
                        desc = cc
                    out.append(Binding(mods, parts[-1], desc, "Cmd shortcuts", "sxhkd", source="sxhkd"))
            i += 2
        else:
            i += 1
    return out


# ---------------------------------------------------------------------------------------------------- where the data is
def cfg_dir():
    return os.environ.get("CARPATIC_CONFIG", os.path.join(os.environ.get("HOME", "/root"), ".config", "carpatic"))


def here():
    return os.path.dirname(os.path.realpath(__file__))


def first_existing(*paths):
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


def active_profile():
    prof = ""
    try:
        for line in open(os.path.join(cfg_dir(), "settings.conf")):
            m = re.match(r'PROFILE="?([^"\n]*)"?', line)
            if m:
                prof = m.group(1)
    except OSError:
        pass
    return prof or "tiling"


def profile_dir():
    return first_existing(os.environ.get("CARPATIC_PROFILES"), os.path.join(here(), "..", "..", "configurator", "profiles"),
                          "/usr/local/share/carpatic/configurator/profiles")


def profiles():
    d = profile_dir()
    return sorted(f[:-5] for f in os.listdir(d) if f.endswith(".conf")) if d else []


def profile_conf(profile, key):
    d = profile_dir()
    try:
        for line in open(os.path.join(d, profile + ".conf")):
            m = re.match(rf'{key}="?([^"#\n]*?)"?\s*(#.*)?$', line)
            if m:
                return m.group(1).strip()
    except OSError:
        pass
    return ""


def app_shortcuts():
    """Keys that belong to apps rather than to dwm. Quick Look (Space in Files) is shown when it is installed; they are listed, not 'tried'."""
    if not any(os.path.exists(p) for p in ("/usr/local/bin/carpatic-quicklook", "/usr/bin/carpatic-quicklook")) and not os.environ.get("CARPATIC_SHEET_ALL"):
        return []
    rows = [("Space", "Quick Look: preview the selected file in Files"), ("Space", "Close the preview (Esc works too)"),
            ("Left", "In a preview: previous file"), ("Right", "In a preview: next file"), ("Return", "In a preview: open the file in its app"),
            ("K", "In a preview: play or pause audio and video")]
    return [Binding([], k, d, "Files and previews", "quicklook", source="app") for k, d in rows]


def gesture_rows():
    """Touchpad swipes (carpatic-gestures): the defaults, plus anything the user set in gestures.conf."""
    rows = {"swipe-left": "Next workspace", "swipe-right": "Previous workspace", "swipe-up": "Workspace overview"}
    names = {"left": "left", "right": "right", "up": "up", "down": "down"}
    try:
        for line in open(os.path.join(cfg_dir(), "gestures.conf")):
            m = re.match(r"\s*(swipe\d?-(?:left|right|up|down))\s*=\s*(.+)", line)
            if m:
                rows[m.group(1)] = "Runs: " + m.group(2).strip()
    except OSError:
        pass
    out = []
    for k, d in rows.items():
        fingers, _, direction = k.partition("-")
        n = fingers[5:] or "3 or 4"
        out.append(Binding([], f"{n} fingers swipe {names[direction]}", d, "Touchpad gestures", "gesture", source="gesture"))
    return out


def load(profile=None):
    """Bindings of the profile. No profile = the one in use (read from the file dwm reads, so it is always truthful)."""
    active = active_profile()
    profile = profile or active
    home = os.environ.get("HOME", "/root")
    if profile == active and os.path.exists(os.path.join(home, ".config", "dwm-titus", "hotkeys.toml")):
        hk = os.path.join(home, ".config", "dwm-titus", "hotkeys.toml")
        sx = os.path.join(os.environ.get("CARPATIC_STATE", os.path.join(home, ".local", "state", "carpatic")), "current", "sxhkdrc")
        binds = parse_hotkeys(hk) + parse_sxhkd(sx)
        return profile, binds + app_shortcuts() + gesture_rows()
    # another profile: merge the same way carpatic-apply does (carpatic-genkeys)
    pd = profile_dir()
    default = first_existing(os.environ.get("CARPATIC_DEFAULT_HOTKEYS"), os.path.join(here(), "..", "..", "desktop", "config", "hotkeys.toml"),
                             os.path.join(home, ".local", "share", "dwm-titus", "config", "hotkeys.toml"))
    genkeys = first_existing(os.path.join(here(), "..", "..", "configurator", "bin", "carpatic-genkeys"), "/usr/local/bin/carpatic-genkeys")
    if not (pd and default and genkeys and os.path.exists(os.path.join(pd, profile + ".conf"))):
        raise SystemExit(f"carpatic keys: I cannot find the shortcuts of '{profile}' on this computer.")
    keyfile = profile_conf(profile, "KEYS") or f"{profile}.keys"
    res = subprocess.run(["sh", genkeys, default, os.path.join(pd, "common.keys"), os.path.join(pd, keyfile)],
                         capture_output=True, text=True)
    if res.returncode != 0:
        raise SystemExit("carpatic keys: could not combine the shortcut files: " + res.stderr.strip())
    tmp = os.path.join(os.environ.get("TMPDIR", "/tmp"), f"carpatic-keys-{os.getpid()}.toml")
    with open(tmp, "w") as f:
        f.write(res.stdout)
    try:
        binds = parse_hotkeys(tmp)
    finally:
        os.unlink(tmp)
    sx = profile_conf(profile, "SXHKD")
    if sx and sx != "none":
        binds += parse_sxhkd(os.path.join(pd, sx))
    return profile, binds + app_shortcuts() + gesture_rows()


def grouped(binds):
    seen, out = set(), {}
    for b in binds:
        sig = (tuple(sorted(b.mods)), b.key, b.desc)
        if sig in seen:
            continue
        seen.add(sig)
        out.setdefault(b.group, []).append(b)
    return [(g, out[g]) for g in GROUP_ORDER if g in out] + [(g, v) for g, v in out.items() if g not in GROUP_ORDER]


# ------------------------------------------------------------------------------------------------------------- renderers
def chord_text(b, sup):
    return " + ".join(b.chord(sup))


def text_lines(profile, binds):
    sup = SUPER_NAME.get(profile, "Super")
    w = max((len(chord_text(b, sup)) for b in binds), default=10)
    lines = []
    for g, bs in grouped(binds):
        lines.append(f"{g}")
        for b in bs:
            lines.append(f"  {chord_text(b, sup):<{w}}  {b.desc}")
        lines.append("")
    return lines


def search_rows(profile, binds):
    """One row per binding: (display text, Binding). Used by the rofi popup and `search`."""
    sup = SUPER_NAME.get(profile, "Super")
    return [(chord_text(b, sup), b) for _, bs in grouped(binds) for b in bs]


def html_doc(profile, binds, brand_svg=""):
    sup = SUPER_NAME.get(profile, "Super")
    label = PROFILE_LABEL.get(profile, profile)
    parts = []
    for g, bs in grouped(binds):
        rows = []
        for b in bs:
            caps = "".join(f"<kbd>{html.escape(k)}</kbd>" for k in b.chord(sup))
            rows.append(f"<tr><td class=k>{caps}</td><td>{html.escape(b.desc)}</td></tr>")
        parts.append(f"<section><h2>{html.escape(g)}</h2><table>{''.join(rows)}</table></section>")
    note = ""
    if profile == "macos":
        note = "<p class=note>Cmd is the Super key. Cmd shortcuts are emulated: they send the matching Ctrl shortcut to the active app.</p>"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Carpatic keyboard shortcuts: {html.escape(label)}</title>
<style>
:root {{ --bg:#f6f7f9; --surface:#ffffff; --fg:#172029; --muted:#4e5b6c; --border:#d8dee6; --accent:#16806a; --cap:#eef1f5; --capb:#c2cad5; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#11151c; --surface:#171c25; --fg:#e7ecf3; --muted:#a3aec0; --border:#2c3442; --accent:#5cc8a8; --cap:#1e2430; --capb:#3a4455; }} }}
@media print {{ :root {{ --bg:#ffffff; --surface:#ffffff; --fg:#172029; --muted:#4e5b6c; --border:#d8dee6; --accent:#16806a; --cap:#eef1f5; --capb:#c2cad5; }} @page {{ size: A4 landscape; margin: 12mm; }} }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:14px/1.4 Inter, "Noto Sans", "DejaVu Sans", sans-serif; }}
main {{ max-width:1180px; margin:0 auto; padding:24px 16px 48px; }}
header {{ display:flex; align-items:center; gap:16px; margin-bottom:24px; }}
header svg, header img {{ width:48px; height:48px; }}
h1 {{ font-size:24px; line-height:1.15; margin:0; font-weight:600; letter-spacing:-0.01em; }}
.sub {{ color:var(--muted); margin:2px 0 0; }}
.grid {{ columns:3 300px; column-gap:16px; }}
section {{ break-inside:avoid; background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:16px; margin:0 0 16px; }}
h2 {{ font-size:12px; letter-spacing:.04em; text-transform:uppercase; color:var(--accent); margin:0 0 8px; font-weight:600; }}
table {{ width:100%; border-collapse:collapse; }}
td {{ padding:4px 0; vertical-align:top; border-top:1px solid var(--border); }}
tr:first-child td {{ border-top:0; }}
td.k {{ white-space:nowrap; padding-right:12px; width:1%; }}
kbd {{ font:600 11px "JetBrains Mono","DejaVu Sans Mono",monospace; background:var(--cap); border:1px solid var(--capb); border-bottom-width:2px; border-radius:4px; padding:1px 6px; margin-right:3px; display:inline-block; }}
.note {{ color:var(--muted); font-size:12px; }}
footer {{ color:var(--muted); font-size:12px; margin-top:8px; }}
</style></head>
<body><main>
<header>{brand_svg}<div><h1>Keyboard shortcuts</h1><p class=sub>Carpatic OS, {html.escape(label)}. Press {sup}+Alt+Space for the menu.</p></div></header>
{note}<div class=grid>{''.join(parts)}</div>
<footer>Generated from the profile's hotkeys by <code>carpatic keys html</code>. Your own changes in ~/.config/carpatic are included when you generate it on your computer.</footer>
</main></body></html>
"""


def pdf_doc(profile, binds, path):
    """A4 landscape cheat sheet drawn with PangoCairo (Inter and JetBrains Mono when installed)."""
    import cairo
    import gi
    gi.require_foreign("cairo")
    gi.require_version("Pango", "1.0")
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import Pango, PangoCairo
    sup = SUPER_NAME.get(profile, "Super")
    label = PROFILE_LABEL.get(profile, profile)
    W, H = 842.0, 595.0
    M, TOP, GAP = 36.0, 78.0, 18.0
    cols = 3
    colw = (W - 2 * M - GAP * (cols - 1)) / cols
    ROW, TITLE = 17.0, 26.0
    surf = cairo.PDFSurface(path, W, H)
    surf.set_metadata(cairo.PDF_METADATA_TITLE, f"Carpatic keyboard shortcuts: {label}")
    surf.set_metadata(cairo.PDF_METADATA_CREATOR, "carpatic keys pdf")
    cr = cairo.Context(surf)

    def rgb(h):
        h = h.lstrip("#")
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    FG, MUTED, ACC, BORDER, CAP, CAPB = rgb("#172029"), rgb("#4e5b6c"), rgb("#16806a"), rgb("#d8dee6"), rgb("#eef1f5"), rgb("#c2cad5")

    def layout(text, font, size, weight=Pango.Weight.NORMAL):
        lay = PangoCairo.create_layout(cr)
        fd = Pango.FontDescription(font)
        fd.set_absolute_size(size * Pango.SCALE)
        fd.set_weight(weight)
        lay.set_font_description(fd)
        lay.set_text(text, -1)
        return lay

    def text(x, y, s, font, size, color, weight=Pango.Weight.NORMAL):
        lay = layout(s, font, size, weight)
        cr.set_source_rgb(*color)
        cr.move_to(x, y)
        PangoCairo.show_layout(cr, lay)
        return lay.get_pixel_size()[0]

    def header(page):
        text(M, 28, "carpatic", "Inter", 22, FG, Pango.Weight.SEMIBOLD)
        text(M + 104, 33, f"Keyboard shortcuts, {label}", "Inter", 13, MUTED)
        cr.set_source_rgb(*ACC)
        cr.rectangle(M, 62, 28, 2)
        cr.fill()
        text(W - M - 220, 34, f"{sup}+Alt+Space: menu    {sup}+K or F1: this sheet" if profile == "tiling" else f"{sup}+Alt+Space: menu    {sup}+F1: this sheet",
             "Inter", 9, MUTED)
        text(W - M - 40, H - 28, f"{page}", "Inter", 8, MUTED)
        text(M, H - 28, "carpatic keys pdf. Made from the profile's hotkeys.toml. Super is the Windows/Cmd key.", "Inter", 8, MUTED)

    def caps(x, y, keys):
        for k in keys:
            lay = layout(k, "JetBrains Mono", 7.5, Pango.Weight.BOLD)
            w, h = lay.get_pixel_size()
            bw = w + 8
            cr.set_source_rgb(*CAP)
            rr(x, y - 1, bw, 13, 3)
            cr.fill_preserve()
            cr.set_source_rgb(*CAPB)
            cr.set_line_width(0.7)
            cr.stroke()
            cr.set_source_rgb(*FG)
            cr.move_to(x + 4, y + 1.5)
            PangoCairo.show_layout(cr, lay)
            x += bw + 3
        return x

    def rr(x, y, w, h, r):
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -1.5708, 0)
        cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
        cr.arc(x + r, y + h - r, r, 1.5708, 3.1416)
        cr.arc(x + r, y + r, r, 3.1416, 4.7124)
        cr.close_path()

    page = 1
    header(page)
    col, y = 0, TOP
    bottom = H - 48
    for g, bs in grouped(binds):
        first = True
        for i, b in enumerate(bs):
            need = ROW + (TITLE if first else 0) + (ROW if first else 0)
            if y + need > bottom:
                col += 1
                y = TOP
                first = True
                if col >= cols:
                    surf.show_page()
                    page += 1
                    header(page)
                    col = 0
            x = M + col * (colw + GAP)
            if first:
                y += 4
                text(x, y, (g if i == 0 else g + " (continued)").upper(), "Inter", 8, ACC, Pango.Weight.BOLD)
                y += TITLE - 4
                first = False
            end = caps(x, y, b.chord(sup))
            dx = x + colw * 0.53
            if end - x + 6 > colw * 0.53:        # a very long chord: the text follows it directly
                dx = end + 6
            desc = b.desc
            lay = layout(desc, "Inter", 8.5)
            lay.set_width(int((x + colw - dx) * Pango.SCALE))
            lay.set_ellipsize(Pango.EllipsizeMode.END)
            cr.set_source_rgb(*FG)
            cr.move_to(dx, y - 0.5)
            PangoCairo.show_layout(cr, lay)
            y += ROW
        y += 8
    surf.finish()
    return page
