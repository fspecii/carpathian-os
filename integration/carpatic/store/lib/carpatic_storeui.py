"""Carpathian App Store GUI (GTK3, no webkit). Looks come from the OS style layer: the user's ~/.config/gtk-3.0/gtk.css defines the
@cp_* colours and the shared cp-* classes (cp-card, cp-primary, cp-sidebar, cp-sidebar-row, cp-section, cp-search, cp-pill, cp-badge) for the
six styles x light/dark; this module only adds store-specific layout classes (st-*) that use those colours, so a style switch restyles
the store live. Spacing grid 4/8, type scale 11/12/14/18/28 (docs/DESIGN-SYSTEM.md)."""
import json
import os
import re
import subprocess
import sys
import threading
import urllib.request

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango  # noqa: E402

import carpatic_store as cs  # noqa: E402
import carpatic_ai as ai  # noqa: E402
import carpatic_drivers as drv  # noqa: E402

HERE = os.path.dirname(os.path.realpath(__file__))
GUI_DIR = next((d for d in (os.path.join(HERE, "..", "gui"), "/usr/local/share/carpatic/store/gui") if os.path.isdir(d)), "")
CACHE = os.path.expanduser("~/.cache/carpatic/store")
FLATHUB_API = "https://flathub.org/api/v2/appstream/"
USER_GTK_CSS = os.path.expanduser("~/.config/gtk-3.0/gtk.css")

# ---------------------------------------------------------------------------------------------- store-only CSS
CSS = """
.st-content { background-color: @cp_view; }
flowboxchild { padding: 0; }
.st-title { font-size: 28px; font-weight: 700; letter-spacing: -0.4px; }
.st-lead { font-size: 14px; color: @cp_text2; }
.st-h2 { font-size: 18px; font-weight: 600; }
.st-cap { font-size: 12px; color: @cp_text2; }
.st-cap11 { font-size: 11px; font-weight: 600; color: @cp_text2; letter-spacing: 0.4px; }
.st-name { font-size: 14px; font-weight: 600; }
.st-brand { font-size: 17px; font-weight: 700; letter-spacing: -0.2px; }
.st-mono { font-family: "JetBrains Mono", "DejaVu Sans Mono", monospace; font-size: 13px; }
list.st-nav { background-color: transparent; }
.st-nav row { padding: 0; min-height: 36px; }
.st-nav-ico { color: @cp_text2; }
.st-nav row.selected .st-nav-ico { color: @cp_fg; }
.st-count { background-color: @cp_accent; color: @cp_accent_fg; border-radius: 999px; padding: 0 7px; font-size: 11px; font-weight: 700; min-height: 18px; }
.st-side-search { margin: 12px 12px 8px 12px; }
.st-tile { padding: 14px; }
.st-tile-flat { padding: 12px 0; }
.st-row { padding: 12px 16px; }
.st-icon-mono { border-radius: 22%; color: #ffffff; font-weight: 700; }
.st-glyph image { color: #ffffff; -gtk-icon-shadow: none; }
.st-glyph-mono { color: #ffffff; font-weight: 700; letter-spacing: 0.3px; }
tooltip, tooltip.background { border-radius: 0; box-shadow: none; text-shadow: none; background-image: none; background-color: @cp_menu_bg; color: @cp_fg; border: 1px solid @cp_line_strong; padding: 0; }
tooltip *, tooltip label { text-shadow: none; box-shadow: none; background-color: transparent; color: @cp_fg; padding: 4px 8px; }
.st-src { background-color: @cp_field; color: @cp_text2; border-radius: 999px; padding: 1px 8px; font-size: 11px; font-weight: 600; }
.st-src.good { background-color: alpha(@cp_green, 0.18); color: @cp_fg; }
.st-src.ai { background-color: alpha(@cp_accent, 0.2); color: @cp_fg; }
.st-installed { color: @cp_text2; font-size: 12px; font-weight: 600; }
.st-installed-ico { color: @cp_green; }
button.st-get { min-width: 72px; min-height: 28px; padding: 0 16px; font-weight: 600; }
button.st-open { min-width: 72px; min-height: 28px; padding: 0 16px; font-weight: 600; background-image: none; background-color: @cp_field; color: @cp_fg; border-color: transparent; }
button.st-open:hover { background-color: @cp_hover; }
button.st-big { min-height: 36px; min-width: 112px; font-size: 14px; }
button.st-link { background-image: none; background-color: transparent; border-color: transparent; box-shadow: none; color: @cp_accent; padding: 0 4px; min-height: 24px; }
button.st-link:hover { background-color: @cp_hover; }
button.st-remove { background-image: none; background-color: transparent; border-color: transparent; box-shadow: none; color: @cp_red; min-height: 28px; padding: 0 12px; }
button.st-remove:hover { background-color: alpha(@cp_red, 0.14); }
progressbar.st-prog trough { min-height: 6px; min-width: 96px; border-radius: 999px; background-color: @cp_track; border: none; }
progressbar.st-prog progress { min-height: 6px; border-radius: 999px; background-color: @cp_accent; border: none; background-image: none; }
.st-busy { font-size: 12px; font-weight: 600; }
.st-hero { padding: 28px 32px; min-height: 176px; }
.st-hero-title { font-size: 28px; font-weight: 700; letter-spacing: -0.4px; }
.st-hero-sub { font-size: 14px; color: @cp_text2; }
.st-kicker { font-size: 11px; font-weight: 700; letter-spacing: 0.8px; color: @cp_accent; }
button.st-arrow { min-width: 32px; min-height: 32px; padding: 0; border-radius: 999px; background-image: none; background-color: @cp_field; border-color: transparent; box-shadow: none; }
button.st-arrow:hover { background-color: @cp_hover; }
button.st-dot { min-width: 8px; min-height: 8px; padding: 0; border-radius: 999px; background-image: none; background-color: @cp_line_strong; border-color: transparent; box-shadow: none; margin: 0 3px; }
button.st-dot.on { background-color: @cp_accent; min-width: 20px; }
.st-cat { padding: 14px 16px; }
.st-cat label { font-weight: 600; }
.st-fact { padding: 14px 16px; }
.st-fact-sep { background-color: @cp_line; min-width: 1px; }
.st-note { background-color: alpha(@cp_yellow, 0.13); border: 1px solid alpha(@cp_yellow, 0.45); border-radius: 8px; padding: 10px 14px; }
.st-alert { background-color: alpha(@cp_red, 0.12); border: 1px solid alpha(@cp_red, 0.5); border-radius: 10px; padding: 12px 16px; }
.st-alert.ok { background-color: alpha(@cp_green, 0.12); border-color: alpha(@cp_green, 0.5); }
.st-code { background-color: @cp_field; border-radius: 8px; padding: 6px 6px 6px 12px; }
.st-step { min-width: 24px; min-height: 24px; border-radius: 999px; background-color: @cp_field; font-size: 12px; font-weight: 700; }
.st-step.done { background-color: @cp_green; color: @cp_accent_fg; }
.st-empty { padding: 48px 16px; }
.st-dot-s { border-radius: 999px; min-width: 10px; min-height: 10px; }
.st-dot-s.ok { background-color: @cp_green; } .st-dot-s.warn { background-color: @cp_yellow; } .st-dot-s.off { background-color: @cp_text3; }
.st-status { padding: 6px 16px; color: @cp_text2; font-size: 12px; border-top: 1px solid @cp_line; background-color: @cp_chrome; }
"""

_THEME = {}      # @define-color cp_* hex values of the active style layer (python side: monogram colours)
_dyn = {"provider": None, "known": set(), "rules": ""}


def appearance_mode():
    try:
        for ln in open(os.path.expanduser("~/.config/carpatic/appearance.env")):
            if ln.startswith("MODE="):
                return "light" if "light" in ln else "dark"
    except OSError:
        pass
    return "dark"


def style_layer_text():
    """The user's rendered gtk.css when it carries the cp_* layer, otherwise the bundled Carpathian style (first boot, tests, other desktops)."""
    over = os.environ.get("CARPATIC_STYLE_CSS")
    cands = [over] if over else [USER_GTK_CSS]
    for p in cands:
        try:
            t = open(p).read()
            if "cp_accent" in t:
                return t, p
        except (OSError, TypeError):
            pass
    mode = os.environ.get("CARPATIC_THEME") or appearance_mode()
    for d in (os.path.join(GUI_DIR, "theme"), "/usr/local/share/carpatic/store/gui/theme"):
        p = os.path.join(d, f"style-{mode}.css")
        if os.path.exists(p):
            return open(p).read(), None
    return "", None


def load_theme(screen):
    """Returns the mode. The user's gtk.css is loaded by GTK itself (USER priority); a bundled copy is only added when it is absent."""
    text, path = style_layer_text()
    for m in re.finditer(r"@define-color\s+(cp_\w+)\s+(#[0-9a-fA-F]{6})", text):
        _THEME[m.group(1)] = m.group(2)
    mode = os.environ.get("CARPATIC_THEME") or appearance_mode()
    if text and (path is None or os.environ.get("CARPATIC_STYLE_CSS")):   # override = tests/sheets; the user's own gtk.css is loaded by GTK itself
        p = Gtk.CssProvider()
        try:
            p.load_from_data(text.encode())
            Gtk.StyleContext.add_provider_for_screen(screen, p, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        except GLib.Error:
            pass
    st = Gtk.Settings.get_default()
    adw = "adw-gtk3" + ("-dark" if mode == "dark" else "")
    if st is not None and not str(st.get_property("gtk-theme-name")).startswith("adw-gtk3") and not os.environ.get("CARPATIC_NO_ADW"):
        st.set_property("gtk-theme-name", adw)
    if st is not None:
        st.set_property("gtk-application-prefer-dark-theme", mode == "dark")
    prov = Gtk.CssProvider()
    prov.load_from_data(CSS.encode())
    Gtk.StyleContext.add_provider_for_screen(screen, prov, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
    _dyn["provider"] = Gtk.CssProvider()
    Gtk.StyleContext.add_provider_for_screen(screen, _dyn["provider"], Gtk.STYLE_PROVIDER_PRIORITY_USER + 2)
    return mode


# ---------------------------------------------------------------------------------------------- colour helpers
def _rgb(h):
    return [int(h[i:i + 2], 16) for i in (1, 3, 5)]


def mix(a, b, t):
    """a*(1-t) + b*t as hex."""
    x, y = _rgb(a), _rgb(b)
    return "#" + "".join(f"{round(p * (1 - t) + q * t):02x}" for p, q in zip(x, y))


def lum(h):
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (f(v / 255) for v in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(x, y):
    return (max(lum(x), lum(y)) + 0.05) / (min(lum(x), lum(y)) + 0.05)



def clean_status(line):
    """One readable status line from apk/flatpak output: no progress-bar block characters, no control characters (they show as empty boxes)."""
    line = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[()][A-Za-z0-9]", "", line)
    return "".join(c for c in line if c.isprintable() and not "\u2580" <= c <= "\u259f" and c != "\u2026").strip()

# ANSI hues from design/tokens/tokens.toml [ansi] (blue, magenta); the rest come from the active style layer
BLUE, MAGENTA = "#4a8fd6", "#9a6bd0"


def hues():
    base = [_THEME.get(k, "#5cc8a8") for k in ("cp_accent", "cp_orange", "cp_red", "cp_green")]
    return [base[0], base[1], base[2], BLUE, MAGENTA, base[3]]


def app_hue(name):
    h = hues()
    return h[sum(map(ord, name)) % len(h)]


def dyn_class(prefix, css_body, key):
    """Create (once) a CSS class prefix-<key> with the given rule body and return its name."""
    cls_ = f"{prefix}-{key}"
    if cls_ not in _dyn["known"] and _dyn["provider"] is not None:
        _dyn["known"].add(cls_)
        _dyn["rules"] += f".{cls_} {{ {css_body} }}\n"
        _dyn["provider"].load_from_data(_dyn["rules"].encode())
    return cls_


def add_cls(w, *names):
    ctx = w.get_style_context()
    for n in names:
        for x in n.split():
            ctx.add_class(x)
    return w


def label(text="", css="", xalign=0.0, wrap=False, lines=0, ellipsize=False, chars=0, selectable=False):
    l = Gtk.Label(label=text, xalign=xalign)
    if wrap:
        l.set_line_wrap(True); l.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if lines:
        l.set_lines(lines)
    if ellipsize:
        l.set_ellipsize(Pango.EllipsizeMode.END)
    if chars:
        l.set_max_width_chars(chars)
    l.set_selectable(selectable)
    return add_cls(l, css) if css else l


ICON_ALT = {"object-select-symbolic": ("emblem-ok-symbolic", "emblem-default-symbolic"), "dialog-warning-symbolic": ("dialog-warning",)}


def symbolic(name, size=16, css=""):
    th = Gtk.IconTheme.get_default()
    for n in (name,) + ICON_ALT.get(name, ()):
        if th.has_icon(n):
            name = n; break
    i = Gtk.Image.new_from_icon_name(name, Gtk.IconSize.BUTTON)
    i.set_pixel_size(size)
    return add_cls(i, css) if css else i


def vbox(spacing=0):
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)


def hbox(spacing=0):
    return Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)


class Clamp(Gtk.Bin):
    """Centres its child and limits the width (readable line length on wide windows)."""
    __gtype_name__ = "CarpaticStoreClamp"

    def __init__(self, max_width=980):
        super().__init__(); self.max_width = max_width; self.set_has_window(False)

    def do_get_preferred_width(self):
        c = self.get_child()
        if c is None or not c.get_visible():
            return 0, 0
        mn, nat = c.get_preferred_width(); return min(mn, self.max_width), min(nat, self.max_width)

    def do_get_preferred_height_for_width(self, w):
        c = self.get_child()
        if c is None or not c.get_visible():
            return 0, 0
        return c.get_preferred_height_for_width(min(w, self.max_width))

    def do_get_preferred_height(self):
        c = self.get_child()
        if c is None or not c.get_visible():
            return 0, 0
        return c.get_preferred_height()

    def do_size_allocate(self, a):
        self.set_allocation(a)
        c = self.get_child()
        if c is None or not c.get_visible():
            return
        w = min(a.width, self.max_width); r = Gdk.Rectangle()
        r.x = a.x + (a.width - w) // 2; r.y = a.y; r.width = w; r.height = a.height
        c.size_allocate(r)


class TileGrid(Gtk.Container):
    """Equal-width columns that adapt to the width: as many columns (up to max_cols) as fit the children's MINIMUM width, so a 1280 px window
    gets two columns even when a tile's natural width is larger (GtkFlowBox decides by natural width and drops to one column too early)."""
    __gtype_name__ = "CarpaticTileGrid"

    def __init__(self, max_cols=2, gap=12):
        super().__init__(); self.max_cols = max_cols; self.gap = gap; self.kids = []; self.set_has_window(False); self.set_redraw_on_allocate(False)

    def add(self, w):
        self.kids.append(w); w.set_parent(self)

    def do_add(self, w):
        self.add(w)

    def do_remove(self, w):
        self.kids.remove(w); w.unparent()

    def do_forall(self, include_internals, cb, data=None):
        for k in list(getattr(self, "kids", [])):
            cb(k)

    def do_child_type(self):
        return Gtk.Widget.__gtype__

    def _vis(self):
        return [k for k in self.kids if k.get_visible()]

    def _cols(self, width):
        v = self._vis()
        if not v:
            return 1
        mw = max(k.get_preferred_width()[0] for k in v)
        return max(1, min(self.max_cols, (width + self.gap) // (mw + self.gap)))

    def do_get_request_mode(self):
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def do_get_preferred_width(self):
        v = self._vis()
        mw = max((k.get_preferred_width()[0] for k in v), default=0)
        return mw, mw

    def do_get_preferred_height_for_width(self, width):
        v = self._vis(); c = self._cols(width)
        if not v:
            return 0, 0
        cw = (width - self.gap * (c - 1)) // c; total = 0
        for i in range(0, len(v), c):
            total += max(k.get_preferred_height_for_width(cw)[0] for k in v[i:i + c]) + (self.gap if i else 0)
        return total, total

    def do_get_preferred_height(self):
        h = self.do_get_preferred_height_for_width(max(self.do_get_preferred_width()[0], 1))
        return h

    def do_size_allocate(self, a):
        self.set_allocation(a)
        v = self._vis(); c = self._cols(a.width)
        if not v:
            return
        cw = (a.width - self.gap * (c - 1)) // c; y = a.y
        for i in range(0, len(v), c):
            row = v[i:i + c]; rh = max(k.get_preferred_height_for_width(cw)[0] for k in row)
            for j, k in enumerate(row):
                r = Gdk.Rectangle(); r.x = a.x + j * (cw + self.gap); r.y = y; r.width = cw; r.height = rh
                k.size_allocate(r)
            y += rh + self.gap


class RoundPix(Gtk.DrawingArea):
    """A pixbuf drawn with rounded corners (screenshots, downloaded icons)."""

    def __init__(self, pb, w, h, radius=10):
        super().__init__(); self.pb = pb; self.rad = radius
        self.set_size_request(w, h); self.set_halign(Gtk.Align.START); self.set_valign(Gtk.Align.CENTER)

    def do_draw(self, cr):
        w, h, r = self.get_allocated_width(), self.get_allocated_height(), self.rad
        cr.new_sub_path(); cr.arc(w - r, r, r, -1.5708, 0); cr.arc(w - r, h - r, r, 0, 1.5708); cr.arc(r, h - r, r, 1.5708, 3.1416); cr.arc(r, r, r, 3.1416, 4.7124); cr.close_path()
        cr.clip()
        Gdk.cairo_set_source_pixbuf(cr, self.pb, 0, 0); cr.paint()
        # hairline so pale screenshots keep an edge on a light page
        cr.reset_clip(); cr.new_sub_path(); cr.arc(w - r, r, r, -1.5708, 0); cr.arc(w - r, h - r, r, 0, 1.5708); cr.arc(r, h - r, r, 1.5708, 3.1416); cr.arc(r, r, r, 3.1416, 4.7124); cr.close_path()
        cr.set_source_rgba(0.5, 0.5, 0.5, 0.35); cr.set_line_width(1); cr.stroke()
        return False


# ---------------------------------------------------------------------------------------------- app facts
SOURCE = {
    "apk": ("Alpine", "System package from the Alpine repositories. Installing it needs your administrator password."),
    "flatpak": ("Flathub", "Flatpak from Flathub. Runs in its own sandbox and installs in your home folder, no password needed."),
    "ai": ("AI tool", "Installed by Carpathian into your home folder. No administrator rights, nothing runs in the background."),
    "compat": ("Ubuntu box", "Runs inside the Ubuntu compatibility box for software that is not built for Alpine."),
}


def source_name(a):
    return SOURCE.get(a["source"], ("Built in", ""))[0]


def monogram(name):
    words = [w for w in re.split(r"[\s._-]+", name) if w]
    if len(words) == 1:
        return words[0][:1].upper()
    s = "".join(w[0] for w in words[:2]).upper()
    return s


def tagline(a, limit=72):
    """Short preview of the description for tiles: first sentence, technical (parenthesised) notes dropped, cut at a natural break.
    The detail page always shows the whole text."""
    if a.get("tagline"):
        return a["tagline"]
    d = re.sub(r"\s*\([^)]*\)", "", a["description"]).strip()
    m = re.match(r"(.{12,}?[.!?])(\s|$)", d)
    t = (m.group(1) if m else d).rstrip(".")
    if len(t) > limit:
        cut = max((t.rfind(x, 0, limit) for x in (", ", ": ")), default=-1)
        t = t[:cut] if cut > 24 else t[:limit].rsplit(" ", 1)[0]
    return t


def installs_to(a):
    if a["source"] in ("apk",):
        return "System", "Needs your password"
    if a["source"] == "flatpak":
        return "Your home folder", "Sandboxed, no password"
    if a["source"] == "ai":
        t = ai.get_tool(a["pkg"])
        if t["kind"] in ("github-tarball", "native-script", "npm", "uv"):
            return "Your home folder", "No password needed"
        return "System", "Needs your password"
    return "Ubuntu box", "Isolated from your system"


def strip_html(s):
    s = re.sub(r"</p>\s*", "\n\n", s); s = re.sub(r"<li>\s*", "\n- ", s)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def api_info(a):
    """Flathub appstream record, cached on disk. {} when offline or not a Flatpak."""
    if a["source"] != "flatpak":
        return {}
    fp = os.path.join(CACHE, "api-" + re.sub(r"[^A-Za-z0-9.]", "_", a["pkg"]) + ".json")
    try:
        return json.load(open(fp))
    except (OSError, ValueError):
        pass
    try:
        d = json.load(urllib.request.urlopen(FLATHUB_API + a["pkg"], timeout=8))
        slim = {k: d.get(k) for k in ("summary", "developer_name", "project_license", "icon", "screenshots", "is_free_license")}
        os.makedirs(CACHE, exist_ok=True); tmp = fp + f".{os.getpid()}.{threading.get_ident()}.part"
        json.dump(slim, open(tmp, "w")); os.replace(tmp, fp)
        return slim
    except (OSError, ValueError):
        return {}


_dl_lock = threading.Lock()


def fetch_file(url, timeout=15):
    """Download once into the cache (atomic, so two threads asking for the same icon never read a half-written file)."""
    if not url.startswith("https://"):
        raise OSError("refusing a non-https address")   # icons/screenshots come from Flathub metadata: encrypted only
    fp = os.path.join(CACHE, re.sub(r"[^A-Za-z0-9.]", "_", url)[-120:])
    with _dl_lock:
        if not os.path.exists(fp):
            os.makedirs(CACHE, exist_ok=True)
            data = urllib.request.urlopen(url, timeout=timeout).read()
            tmp = fp + f".{os.getpid()}.part"
            open(tmp, "wb").write(data); os.replace(tmp, fp)
    return fp


def apk_facts(pkg):
    """licence and webpage of an Alpine package (works for packages that are not installed yet)."""
    out = cs.capture(["apk", "info", "-a", pkg]) if cs.shutil.which("apk") else ""
    lic = re.search(r"license:\n(.+)", out)
    return (lic.group(1).strip() if lic else "")


# ---------------------------------------------------------------------------------------------- the window
NAV_ICONS = {"home": "starred-symbolic", "ai": "applications-science-symbolic", "bundles": "package-x-generic-symbolic",
             "browsers": "web-browser-symbolic", "gaming": "input-gaming-symbolic", "chat": "user-available-symbolic",
             "media": "multimedia-player-symbolic", "creative": "applications-graphics-symbolic", "devtools": "utilities-terminal-symbolic",
             "office": "x-office-document-symbolic", "utilities": "applications-utilities-symbolic",
             "drivers": "computer-symbolic", "installed": "object-select-symbolic", "updates": "view-refresh-symbolic"}
CAT_TINT = {"browsers": 3, "gaming": 4, "ai": 0, "chat": 5, "media": 2, "creative": 4, "devtools": 1, "office": 3, "utilities": 5}
AI_GROUPS = [("Coding agents", "Work in your terminal: read your project, edit files, run commands.", ["claude-code", "codex", "opencode", "gemini-cli", "goose", "aider"]),
             ("Run models on this computer", "Private, offline, free. Your hardware does the thinking.", ["ollama", "llama-cpp", "open-webui"]),
             ("Chat apps", "A friendly window for local or cloud models.", ["jan", "gpt4all", "lm-studio"]),
             ("Advanced", "For software that is not built for Alpine.", ["compat-container"])]
HOME_AI = ["claude-code", "codex", "opencode", "gemini-cli", "ollama", "llama-cpp"]
FEATURED = ["claude-code", "steam", "ollama", "discord", "firefox", "libreoffice"]


def safe_icon_name(theme, *names):
    for n in names:
        if n and theme.has_icon(n):
            return n
    return None


class StatusLabel(Gtk.Label):
    """Bottom status line; takes no space while empty."""
    def __init__(self):
        super().__init__(label="", xalign=0.0); add_cls(self, "st-status"); self.set_no_show_all(True); self.set_ellipsize(Pango.EllipsizeMode.END)

    def set_text(self, t):
        super().set_text(t or ""); self.set_visible(bool(t))


class Store(Gtk.Window):
    def __init__(self, firstrun=False, page=None, size=(1200, 760)):
        super().__init__(title="App Store")
        scr = Gdk.Screen.get_default()      # fit small screens and leave room for a taskbar (the first-run footer must stay visible)
        self.set_default_size(min(size[0], scr.get_width() - 80), min(size[1], scr.get_height() - 140))
        self.cat = cs.Catalog()
        self.cat_name = {c["id"]: c["name"] for c in self.cat.categories}
        self.state = cs.State.__new__(cs.State); self.state.fp = set(); self.state.apk = set(); self.state.ai = set()
        self.busy = {}             # key -> {"text", "frac"}
        self.busy_w = {}           # key -> [(label, bar)]
        self.password = None
        self.firstrun = firstrun
        self.page = "home"
        self.detail = None
        self.history = []
        self.hero_i = 0
        self.alert = None
        self.pending = None        # (apk list, flatpak list) after an update check
        self.checks = []
        self.remote_hits = None
        self.mode = load_theme(self.get_screen())
        try:
            self.set_icon_from_file(os.path.join(GUI_DIR, "carpatic-icon-64.png"))
        except GLib.Error:
            pass
        self.icon_theme = Gtk.IconTheme.get_default()
        add_cls(self, "st-win")
        root = vbox(); Gtk.Window.add(self, root)
        body = hbox(); root.pack_start(body, True, True, 0)
        self.sidebar = self.build_sidebar(); body.pack_start(self.sidebar, False, False, 0)
        main = vbox(); add_cls(main, "st-content"); body.pack_start(main, True, True, 0)
        sw = Gtk.ScrolledWindow(); sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); self.scroller = sw
        clamp = Clamp(980); sw.add(clamp)
        self.content = vbox(16)
        self.content.set_margin_start(32); self.content.set_margin_end(32); self.content.set_margin_top(24); self.content.set_margin_bottom(32)
        clamp.add(self.content)
        main.pack_start(sw, True, True, 0)
        self.footer = hbox(8); add_cls(self.footer, "st-status")
        self.footer_note = label("", "st-cap"); self.footer.pack_start(self.footer_note, True, True, 0)
        self.skip_btn = Gtk.Button(label="Skip for now"); self.go_btn = Gtk.Button(label="Install selected"); add_cls(self.go_btn, "cp-primary")
        self.skip_btn.connect("clicked", lambda *_: self.finish_firstrun()); self.go_btn.connect("clicked", self.firstrun_go)
        self.footer.pack_end(self.go_btn, False, False, 0); self.footer.pack_end(self.skip_btn, False, False, 0)
        main.pack_start(self.footer, False, False, 0)
        self.status = StatusLabel(); root.pack_start(self.status, False, False, 0)
        self.connect("destroy", Gtk.main_quit)
        self.connect("key-press-event", self.on_key)
        self.show_all()
        self.footer.hide()
        if firstrun:
            self.sidebar.set_no_show_all(True); self.sidebar.hide()      # the first-run picker is a focused step, not the whole store
        self.select_nav(page if page in self.nav_ids else "home")
        self.render()
        self.set_focus(None)
        threading.Thread(target=self.refresh_state, daemon=True).start()
        GLib.timeout_add_seconds(9, self.rotate_hero)
        GLib.timeout_add(180, self.pulse_bars)
        GLib.timeout_add_seconds(4, self.check_updates_quietly)

    # ------------------------------------------------------------ sidebar
    def build_sidebar(self):
        side = vbox(); add_cls(side, "cp-sidebar"); side.set_size_request(236, -1)
        head = hbox(10); head.set_margin_start(20); head.set_margin_end(16); head.set_margin_top(18); head.set_margin_bottom(4)
        mk = self.mark(22)
        if mk is not None:
            head.pack_start(mk, False, False, 0)
        head.pack_start(label("App Store", "st-brand"), False, False, 0)
        side.pack_start(head, False, False, 0)
        self.search = Gtk.SearchEntry(); self.search.set_placeholder_text("Search the store"); add_cls(self.search, "cp-search st-side-search")
        self.search.connect("search-changed", self.on_search_changed)
        self.search.connect("stop-search", lambda *_: self.search.set_text(""))
        side.pack_start(self.search, False, False, 0)
        self.nav = Gtk.ListBox(); self.nav.set_selection_mode(Gtk.SelectionMode.NONE); self.nav_rows = {}; self.nav_cur = None   # selection is drawn by the shared .selected class (styles paint :selected rows differently when focused); add_cls(self.nav, "st-nav")
        self.nav_ids = []; self.count_lbl = {}
        def add(nid, text, section=False):
            r = Gtk.ListBoxRow()
            if section:
                r.set_activatable(False)
                l = label(text.upper(), "cp-section"); l.set_margin_top(14); l.set_margin_bottom(4); r.add(l)
            else:
                add_cls(r, "cp-sidebar-row")
                b = hbox(10); b.set_margin_start(2); b.set_margin_end(2)
                n = NAV_ICONS.get(nid, "application-x-executable-symbolic")
                b.pack_start(symbolic(n if any(self.icon_theme.has_icon(x) for x in (n,) + ICON_ALT.get(n, ())) else "application-x-executable-symbolic", 16, "st-nav-ico"), False, False, 0)
                b.pack_start(label(text), True, True, 0)
                c = label("", "st-count"); c.set_no_show_all(True); c.set_valign(Gtk.Align.CENTER); b.pack_end(c, False, False, 0)
                self.count_lbl[nid] = c
                r.add(b); self.nav_rows[nid] = r
            self.nav.add(r); self.nav_ids.append("-" if section else nid)
        add("home", "Discover"); add("ai", "AI & Agents"); add("bundles", "Bundles")
        add("-", "Categories", True)
        for c in self.cat.categories:
            if c["id"] != "ai":
                add(c["id"], c["name"])
        add("-", "Library", True)
        add("installed", "Installed"); add("updates", "Updates"); add("drivers", "Drivers & Hardware")
        self.nav.connect("row-activated", self.on_nav)
        sc = Gtk.ScrolledWindow(); sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); sc.add(self.nav)
        side.pack_start(sc, True, True, 0)
        return side

    def mark(self, size):
        try:
            svg = open(os.path.join(GUI_DIR, "carpatic-symbolic.svg")).read().replace("currentColor", _THEME.get("cp_accent", "#5cc8a8"))
            ld = GdkPixbuf.PixbufLoader.new_with_type("svg"); ld.set_size(size, size); ld.write(svg.encode()); ld.close()
            return Gtk.Image.new_from_pixbuf(ld.get_pixbuf())
        except (OSError, GLib.Error, AttributeError):
            return None

    def select_nav(self, nid):
        if nid in self.nav_rows:
            self.on_nav(self.nav, self.nav_rows[nid])

    def mark_nav(self, nid):
        for k, r in self.nav_rows.items():
            ctx = r.get_style_context()
            ctx.add_class("selected") if k == nid else ctx.remove_class("selected")

    def on_nav(self, lb, row):
        if row is None:
            return
        nid = self.nav_ids[row.get_index()]
        if nid == "-":
            return
        self.detail = None; self.history = []; self.page = nid; self.mark_nav(nid)
        if self.search.get_text():
            self.search.handler_block_by_func(self.on_search_changed); self.search.set_text(""); self.search.handler_unblock_by_func(self.on_search_changed)
        self.render()

    def on_key(self, w, ev):
        if ev.keyval == Gdk.KEY_f and ev.state & Gdk.ModifierType.CONTROL_MASK:
            self.search.grab_focus(); return True
        if ev.keyval == Gdk.KEY_Escape and self.detail:
            self.back(); return True
        return False

    def on_search_changed(self, *_):
        self.detail = None; self.history = []; self.remote_hits = None
        if self.search.get_text().strip():
            self.mark_nav(None)
            self.render()
        else:
            self.select_nav(self.page)

    def open_detail(self, a):
        self.history.append((self.page, self.search.get_text(), self.detail))
        self.detail = a
        self.render()

    def back(self, *_):
        if self.history:
            self.page, q, self.detail = self.history.pop()
        else:
            self.detail = None
        self.render()

    # ------------------------------------------------------------ rendering skeleton
    def clear(self):
        self.busy_w.clear()
        for c in self.content.get_children():
            c.destroy()      # destroy (not just remove): pending icon/screenshot downloads see the destroy signal and skip

    def put(self, w, expand=False):
        self.content.pack_start(w, expand, expand, 0); return w

    def page_head(self, title, lead=""):
        v = vbox(4)
        v.pack_start(label(title, "st-title"), False, False, 0)
        if lead:
            v.pack_start(label(lead, "st-lead", wrap=True), False, False, 0)
        self.put(v)

    def section(self, title, lead="", action=None):
        h = hbox(8); h.set_margin_top(12)
        v = vbox(2); v.pack_start(label(title, "st-h2"), False, False, 0)
        if lead:
            v.pack_start(label(lead, "st-cap", wrap=True), False, False, 0)
        h.pack_start(v, True, True, 0)
        if action:
            b = Gtk.Button(label=action[0]); add_cls(b, "st-link"); b.set_valign(Gtk.Align.START); b.connect("clicked", lambda *_: action[1]()); h.pack_end(b, False, False, 0)
        self.put(h)

    def render(self):
        self.clear()
        q = self.search.get_text().strip()
        self.show_alert()
        if self.detail:
            self.render_detail(self.detail)
        elif q:
            self.render_search(q)
        elif self.page == "home":
            self.render_firstrun() if self.firstrun else self.render_home()
        elif self.page == "bundles":
            self.page_head("Bundles", "One click installs a whole set of apps that belong together.")
            self.bundle_grid(self.cat.bundles, 2)
        elif self.page == "installed":
            self.render_installed()
        elif self.page == "updates":
            self.render_updates()
        elif self.page == "drivers":
            self.render_drivers()
        elif self.page == "ai":
            self.render_ai()
        else:
            c = next((c for c in self.cat.categories if c["id"] == self.page), None)
            if c:
                self.page_head(c["name"], c.get("blurb", ""))
                self.tile_grid([self.cat.apps[i] for i in c["apps"]])
        self.content.show_all()
        show_footer = self.firstrun and self.page == "home" and not self.detail and not q
        self.footer.set_visible(show_footer)
        self.update_counts()

    def update_counts(self):
        n = sum(1 for a in self.cat.apps.values() if self.state.installed(a))
        for nid, num in (("installed", n), ("updates", (len(self.pending[0]) + len(self.pending[1])) if self.pending else 0)):
            l = self.count_lbl.get(nid)
            if l is not None:
                l.set_text(str(num)); l.set_visible(bool(num) and nid == "updates")
        if self.pending and not (len(self.pending[0]) + len(self.pending[1])):
            pass

    # ------------------------------------------------------------ alerts (inline, never a raw traceback)
    def show_alert(self):
        a = self.alert
        if not a:
            return
        box = hbox(12); add_cls(box, "st-alert" + (" ok" if a.get("ok") else ""))
        box.pack_start(symbolic("object-select-symbolic" if a.get("ok") else "dialog-warning-symbolic", 20), False, False, 0)
        v = vbox(4)
        v.pack_start(label(a["title"], "st-name", wrap=True), False, False, 0)
        v.pack_start(label(a["text"], "st-mono" if a.get("mono") else "", wrap=True, selectable=a.get("mono", False)), False, False, 0)
        if a.get("details"):
            ex = Gtk.Expander(label="Show details"); l = label(a["details"], "st-cap st-mono", wrap=True, selectable=True); ex.add(l); v.pack_start(ex, False, False, 2)
        box.pack_start(v, True, True, 0)
        btns = vbox(6)
        if a.get("retry"):
            r = Gtk.Button(label="Try again"); add_cls(r, "cp-primary"); r.connect("clicked", lambda *_: (self.dismiss(), a["retry"]())); btns.pack_start(r, False, False, 0)
        if a.get("action"):
            r = Gtk.Button(label=a["action"][0]); r.connect("clicked", lambda *_: (self.dismiss(), a["action"][1]())); btns.pack_start(r, False, False, 0)
        d = Gtk.Button(label="Dismiss"); add_cls(d, "st-link"); d.connect("clicked", lambda *_: (self.dismiss(), self.render())); btns.pack_start(d, False, False, 0)
        box.pack_end(btns, False, False, 0)
        self.put(box)

    def dismiss(self):
        self.alert = None

    def error(self, text, retry=None):
        short = text.split(" Last message:")[0].split(" (exit")[0]
        tip = ""
        low = short.lower()
        if not any(k in low for k in ("internet", "space", "password", "not found", "administrator")):
            tip = " Check your internet connection and try again."
        self.alert = {"title": "That did not work", "text": short + tip, "details": text if text != short else "", "retry": retry}
        self.status.set_text(short[:120])
        self.render()

    def notice(self, title, text, mono=False, action=None):
        self.alert = {"title": title, "text": text, "ok": True, "mono": mono, "action": action}
        self.render()

    # ------------------------------------------------------------ icons and actions
    def icon_for(self, a, size=56):
        box = Gtk.Box(); box.set_size_request(size, size); box.set_halign(Gtk.Align.START); box.set_valign(Gtk.Align.CENTER)
        n = safe_icon_name(self.icon_theme, a["pkg"] if a["source"] not in ("ai", "compat") else "", a["pkg"].split(".")[-1].lower() if a["source"] == "flatpak" else "",
                           a.get("icon") if a.get("icon") != "utilities-terminal" and a.get("icon") != "applications-science" and a.get("icon") != "web-browser" else "")
        if n:
            img = Gtk.Image.new_from_icon_name(n, Gtk.IconSize.DIALOG); img.set_pixel_size(size); box.pack_start(img, True, True, 0)
            return box
        box.pack_start(self.mono_icon(a, size), True, True, 0)
        if a["source"] == "flatpak" and not os.environ.get("CARPATIC_STORE_OFFLINE"):
            alive = [True]
            box.connect("destroy", lambda *_: alive.__setitem__(0, False))     # the page may be rebuilt before the download ends
            threading.Thread(target=self.fetch_icon, args=(a, box, size, alive), daemon=True).start()
        return box

    def ai_family(self, a):
        """(hue, glyph) of the designed icon family for AI tools: one hue and glyph per kind, small lightness shift per tool."""
        i = a["id"]
        if i in ("ollama", "llama-cpp", "open-webui"): hue, glyph = BLUE, "applications-science-symbolic"
        elif i in ("jan", "gpt4all", "lm-studio"): hue, glyph = MAGENTA, "user-available-symbolic"
        elif i == "compat-container": hue, glyph = _THEME.get("cp_orange", "#c0661a"), "package-x-generic-symbolic"
        else: hue, glyph = _THEME.get("cp_accent", "#16806a"), "utilities-terminal-symbolic"
        return hue, glyph

    def glyph_icon(self, a, size):
        """Original icon family for AI tools: gradient squircle in the kind's hue, white glyph on top, monogram under it (no brand logos)."""
        hue, glyph = self.ai_family(a)
        shift = (sum(map(ord, a["id"])) % 5) * 0.06          # tools of one kind stay related but tell apart
        base = mix(hue, "#000000", 0.22 + shift)
        while contrast("#ffffff", base) < 4.5:
            base = mix(base, "#000000", 0.1)
        k = dyn_class("gi", f"background-image: linear-gradient(to bottom, {mix(base, '#ffffff', 0.16)}, {base}); background-color: {base}; border-radius: 22%; color: #ffffff;", base.lstrip("#"))
        box = vbox(0); add_cls(box, f"st-glyph {k}"); box.set_size_request(size, size); box.set_halign(Gtk.Align.CENTER); box.set_valign(Gtk.Align.CENTER)
        gsz = int(size * 0.42)
        g = symbolic(glyph if self.icon_theme.has_icon(glyph) else "application-x-executable-symbolic", gsz); g.set_valign(Gtk.Align.CENTER); g.set_halign(Gtk.Align.CENTER)
        txt = monogram(a["name"])
        fs = max(9, int(size * 0.2))
        m = label(txt, "st-glyph-mono " + dyn_class("mf", f"font-size: {fs}px;", str(fs)), xalign=0.5)
        box.pack_start(Gtk.Box(), True, True, 0); box.pack_start(g, False, False, 0); box.pack_start(m, False, False, int(size * 0.04)); box.pack_start(Gtk.Box(), True, True, 0)
        return box

    def mono_icon(self, a, size):
        if a["source"] == "ai" or a["category"] == "ai":
            return self.glyph_icon(a, size)
        base = app_hue(a["name"])
        col = base
        for t in (0.0, 0.15, 0.3, 0.4, 0.5, 0.6):
            col = mix(base, "#000000", t)
            if contrast("#ffffff", col) >= 4.5:
                break
        top = mix(col, "#ffffff", 0.14)
        k = dyn_class("mc", f"background-image: linear-gradient(to bottom, {top}, {col}); background-color: {col};", col.lstrip("#"))
        txt = monogram(a["name"])
        l = label(txt, f"st-icon-mono {k}", xalign=0.5)
        l.set_size_request(size, size); l.set_halign(Gtk.Align.CENTER); l.set_valign(Gtk.Align.CENTER)
        fs = int(size * (0.42 if len(txt) == 1 else 0.34))
        add_cls(l, dyn_class("mf", f"font-size: {fs}px;", str(fs)))
        return l

    def fetch_icon(self, a, box, size, alive):
        d = api_info(a)
        url = d.get("icon") if d else None
        if not url:
            return
        try:
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(fetch_file(url), size, size, True)
        except (OSError, GLib.Error):
            return
        def swap():
            if not alive[0]:
                return
            for c in box.get_children():
                box.remove(c)
            img = Gtk.Image.new_from_pixbuf(pb); box.pack_start(img, True, True, 0); img.show()
        GLib.idle_add(swap)

    def src_pill(self, a):
        cls_ = "st-src" + (" ai" if a["source"] == "ai" else "")
        l = label(source_name(a), cls_); l.set_tooltip_text(SOURCE.get(a["source"], ("", ""))[1]); l.set_valign(Gtk.Align.CENTER)
        return l

    def action_box(self, a, big=False):
        act = vbox(6); act.set_valign(Gtk.Align.CENTER); act.set_halign(Gtk.Align.END)
        k = a["id"]
        if k in self.busy:
            l = label(self.busy[k]["text"], "st-busy", xalign=1.0); bar = Gtk.ProgressBar(); add_cls(bar, "st-prog"); bar.set_fraction(self.busy[k]["frac"] or 0)
            act.pack_start(l, False, False, 0); act.pack_start(bar, False, False, 0)
            self.busy_w.setdefault(k, []).append((l, bar))
        elif self.state.installed(a):
            if cs.can_open(a):
                b = Gtk.Button(label="Open"); add_cls(b, "st-open" + (" st-big" if big else "")); b.connect("clicked", lambda *_: self.launch(a)); act.pack_start(b, False, False, 0)
            else:
                h = hbox(6); h.set_halign(Gtk.Align.END); h.pack_start(symbolic("object-select-symbolic", 14, "st-installed-ico"), False, False, 0); h.pack_start(label("Installed", "st-installed"), False, False, 0)
                act.pack_start(h, False, False, 0)
        else:
            b = Gtk.Button(label="Get"); add_cls(b, "cp-primary st-get" + (" st-big" if big else "")); b.set_tooltip_text(f"Install {a['name']}")
            b.connect("clicked", lambda *_: self.run_queue([a], "install"))
            act.pack_start(b, False, False, 0)
        return act

    # ------------------------------------------------------------ tiles, rows, grids
    def app_tile(self, a, flat=False, badge=True):
        ev = Gtk.EventBox(); ev.set_visible_window(False)
        ev.connect("button-release-event", lambda w, e: self.open_detail(a) if e.button == 1 and not isinstance(self.get_focus(), Gtk.Button) else None)
        box = hbox(14); add_cls(box, "st-tile-flat" if flat else "cp-card st-tile"); ev.add(box)
        box.pack_start(self.icon_for(a, 56), False, False, 0)
        v = vbox(2); v.set_valign(Gtk.Align.CENTER)
        v.pack_start(label(a["name"], "st-name", wrap=True, chars=26), False, False, 0)
        v.pack_start(label(tagline(a), "st-cap", wrap=True, lines=2, ellipsize=True, chars=30), False, False, 0)
        meta = hbox(8); meta.set_margin_top(2); meta.pack_start(self.src_pill(a), False, False, 0)
        if a.get("newcomer") and badge:
            meta.pack_start(label("Good start", "cp-badge"), False, False, 0)
        if a.get("size_mb"):
            meta.pack_start(label(f'{a["size_mb"]} MB', "st-cap"), False, False, 0)
        v.pack_start(meta, False, False, 0)
        box.pack_start(v, True, True, 0)
        box.pack_end(self.action_box(a), False, False, 0)
        return ev

    def tile_grid(self, apps, cols=2):
        if not apps:
            return
        fb = TileGrid(cols)
        for a in apps:
            fb.add(self.app_tile(a))
        self.put(fb)

    def app_list(self, apps, extra=None, badge=False):
        card = vbox(); add_cls(card, "cp-card"); card.set_margin_bottom(0)
        first = True
        for a in apps:
            if not first:
                s = Gtk.Separator(); s.set_margin_start(86); card.pack_start(s, False, False, 0)
            first = False
            row = self.app_tile(a, flat=True, badge=badge); row.get_child().set_margin_start(0); card.pack_start(row, False, False, 0)
            if extra:
                extra(a, row.get_child())
        card.get_style_context().add_class("st-list")
        self.put(card)

    def bundle_grid(self, bundles, cols=3):
        fb = TileGrid(cols)
        for b in bundles:
            fb.add(self.bundle_card(b))
        self.put(fb)

    def bundle_card(self, b):
        card = vbox(10); add_cls(card, "cp-card st-tile")
        apps = [self.cat.apps[i] for i in b["apps"] if i in self.cat.apps]
        top = hbox(0)
        for a in apps[:4]:       # overlapping icon stack
            ic = self.icon_for(a, 32); ic.set_margin_end(4); top.pack_start(ic, False, False, 0)
        if len(apps) > 4:
            top.pack_start(label(f"+{len(apps) - 4}", "st-cap"), False, False, 4)
        card.pack_start(top, False, False, 0)
        card.pack_start(label(b["name"], "st-name"), False, False, 0)
        card.pack_start(label(b["description"], "st-cap", wrap=True, lines=3, ellipsize=True, chars=30), True, True, 0)
        mb = sum(a.get("size_mb", 0) for a in apps)
        todo = [a for a in apps if not self.state.installed(a)]
        foot = hbox(8); foot.pack_start(label(f"{len(apps)} apps, about {mb} MB" if mb else f"{len(apps)} apps", "st-cap"), True, True, 0)
        bz = [i for i in b["apps"] if i in self.busy]
        if bz:
            foot.pack_end(label("Installing...", "st-busy"), False, False, 0)
        elif todo:
            btn = Gtk.Button(label=f"Get {len(todo)}" if len(todo) > 1 else "Get"); add_cls(btn, "cp-primary st-get"); btn.connect("clicked", lambda *_, b=b, todo=todo: self.bundle_go(b, todo)); foot.pack_end(btn, False, False, 0)
        else:
            h = hbox(6); h.pack_start(symbolic("object-select-symbolic", 14, "st-installed-ico"), False, False, 0); h.pack_start(label("All installed", "st-installed"), False, False, 0); foot.pack_end(h, False, False, 0)
        card.pack_start(foot, False, False, 0)
        return card

    def bundle_go(self, b, todo):
        models = b.get("models", [])
        if models:
            info = {m["id"]: m for m in ai.models()}
            mb = sum(info[m]["size_mb"] for m in models if m in info)
            d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.NONE, text=f"{b['name']} includes a model download")
            d.format_secondary_text(f"{', '.join(models)} is about {mb} MB. Free space: {ai.free_mb()} MB. Download it too?")
            d.add_button("Apps only", 1); d.add_button("Apps and model", 2); d.add_button("Cancel", 0)
            r = d.run(); d.destroy()
            if r == 0:
                return
            models = models if r == 2 else []
        self.run_queue(todo, "install", models)

    # ------------------------------------------------------------ home
    def featured(self):
        return [self.cat.apps[i] for i in FEATURED if i in self.cat.apps]

    def render_home(self):
        self.page_head("Discover", "Free apps, checked by Carpathian. One click installs, no terminal needed.")
        self.hero_box = vbox(10); self.put(self.hero_box); self.fill_hero()
        # AI one-click strip
        self.section("AI tools, one click", "Coding agents and local models. Installed into your home folder, no password.", ("See all", lambda: self.select_nav("ai")))
        self.tile_grid([self.cat.apps[i] for i in HOME_AI if i in self.cat.apps])
        self.section("Browse by category")
        self.category_grid()
        # games and drivers
        self.section("Games", "Steam, Lutris and friends install in their own sandbox.", ("See all", lambda: self.select_nav("gaming")))
        self.tile_grid([self.cat.apps[i] for i in ("steam", "lutris") if i in self.cat.apps])
        self.drivers_card()
        self.section("Bundles", "Sets of apps that go well together.", ("See all", lambda: self.select_nav("bundles")))
        self.bundle_grid([b for b in (self.cat.bundle(i) for i in ("essentials", "ai-developer", "gaming")) if b], 3)
        self.section("Good first picks", "Safe, popular and easy.")
        self.tile_grid([a for a in self.cat.apps.values() if a.get("newcomer") and a["category"] != "ai"][:8])

    def drivers_card(self):
        card = hbox(16); add_cls(card, "cp-card st-tile")
        card.pack_start(self.tint_icon("computer-symbolic", hues()[0], 44), False, False, 0)
        v = vbox(2); v.set_valign(Gtk.Align.CENTER)
        v.pack_start(label("Drivers and hardware", "st-name"), False, False, 0)
        v.pack_start(label("Carpathian looks at your graphics, Wi-Fi, Bluetooth, printer and fingerprint reader and installs what is missing.", "st-cap", wrap=True), False, False, 0)
        card.pack_start(v, True, True, 0)
        b = Gtk.Button(label="Check my computer"); add_cls(b, "st-open"); b.set_valign(Gtk.Align.CENTER); b.connect("clicked", lambda *_: self.select_nav("drivers")); card.pack_end(b, False, False, 0)
        self.put(card)

    def tint_icon(self, name, colour, size=36, radius=10):
        k = dyn_class("ti", f"background-color: alpha({colour}, 0.18); color: {colour}; border-radius: {radius}px;", colour.lstrip("#") + str(radius))
        b = Gtk.Box(); add_cls(b, k); b.set_size_request(size, size); b.set_halign(Gtk.Align.START); b.set_valign(Gtk.Align.CENTER)
        n = name if self.icon_theme.has_icon(name) else "application-x-executable-symbolic"
        img = symbolic(n, int(size * 0.5)); img.set_halign(Gtk.Align.CENTER); img.set_valign(Gtk.Align.CENTER); b.set_center_widget(img)
        return b

    def category_grid(self):
        fb = TileGrid(4)
        for c in [c for c in self.cat.categories if c["id"] != "ai"]:
            ev = Gtk.EventBox(); ev.set_visible_window(False)
            ev.connect("button-release-event", lambda w, e, cid=c["id"]: self.select_nav(cid) if e.button == 1 else None)
            hue = hues()[CAT_TINT.get(c["id"], 0)]
            box = hbox(12); add_cls(box, "cp-card st-cat " + dyn_class("cg", f"background-image: linear-gradient(135deg, alpha({hue}, 0.20), alpha({hue}, 0.04));", hue.lstrip("#"))); ev.add(box)
            box.pack_start(self.tint_icon(NAV_ICONS.get(c["id"], "application-x-executable-symbolic"), hue, 40), False, False, 0)
            v = vbox(0); v.set_valign(Gtk.Align.CENTER); v.pack_start(label(c["name"], "st-name", ellipsize=True, chars=14), False, False, 0)
            v.pack_start(label(f'{len(c["apps"])} apps', "st-cap"), False, False, 0)
            box.pack_start(v, True, True, 0)
            fb.add(ev)
        self.put(fb)

    def fill_hero(self):
        for c in self.hero_box.get_children():
            c.destroy()
        feats = self.featured()
        if not feats:
            return
        a = feats[self.hero_i % len(feats)]
        col = app_hue(a["name"])
        k = dyn_class("hg", f"background-image: linear-gradient(120deg, alpha({col}, 0.34), alpha({col}, 0.05) 70%);", col.lstrip("#"))
        card = hbox(16); add_cls(card, f"cp-card st-hero {k}")
        prev = Gtk.Button(); prev.add(symbolic("go-previous-symbolic", 16)); add_cls(prev, "st-arrow"); prev.set_valign(Gtk.Align.CENTER); prev.set_tooltip_text("Previous"); prev.connect("clicked", lambda *_: self.hero_step(-1))
        nxt = Gtk.Button(); nxt.add(symbolic("go-next-symbolic", 16)); add_cls(nxt, "st-arrow"); nxt.set_valign(Gtk.Align.CENTER); nxt.set_tooltip_text("Next"); nxt.connect("clicked", lambda *_: self.hero_step(1))
        card.pack_start(prev, False, False, 0)
        v = vbox(6); v.set_valign(Gtk.Align.CENTER)
        v.pack_start(label("FEATURED", "st-kicker"), False, False, 0)
        v.pack_start(label(a["name"], "st-hero-title"), False, False, 0)
        v.pack_start(label(a["description"], "st-hero-sub", wrap=True, chars=52), False, False, 0)
        row = hbox(10); row.set_margin_top(10); row.pack_start(self.action_box(a, True), False, False, 0)
        det = Gtk.Button(label="Details"); add_cls(det, "st-link st-big"); det.connect("clicked", lambda *_: self.open_detail(a)); det.set_valign(Gtk.Align.CENTER); row.pack_start(det, False, False, 0)
        v.pack_start(row, False, False, 0)
        card.pack_start(v, True, True, 0)
        ic = self.icon_for(a, 112); ic.set_valign(Gtk.Align.CENTER); card.pack_start(ic, False, False, 8)
        card.pack_start(nxt, False, False, 0)
        self.hero_box.pack_start(card, False, False, 0)
        dots = hbox(0); dots.set_halign(Gtk.Align.CENTER)
        for i in range(len(feats)):
            d = Gtk.Button(); add_cls(d, "st-dot" + (" on" if i == self.hero_i % len(feats) else "")); d.set_tooltip_text(feats[i]["name"]); d.connect("clicked", lambda *_, i=i: self.hero_set(i)); dots.pack_start(d, False, False, 0)
        self.hero_box.pack_start(dots, False, False, 0)
        self.hero_box.show_all()

    def hero_step(self, d):
        self.hero_i = (self.hero_i + d) % len(self.featured()); self.fill_hero()

    def hero_set(self, i):
        self.hero_i = i; self.fill_hero()

    def rotate_hero(self):
        if self.page == "home" and not self.detail and not self.search.get_text() and not self.firstrun and getattr(self, "hero_box", None) is not None and self.hero_box.get_parent() is not None and not self.busy:
            self.hero_step(1)
        return True

    # ------------------------------------------------------------ AI page
    def render_ai(self):
        self.page_head("AI & Agents", "Install the tools, then follow the short note on each page to sign in. Carpathian never stores your keys.")
        have_all = [self.cat.apps[i] for i in HOME_AI if i in self.cat.apps and not self.state.installed(self.cat.apps[i])]
        for title, lead, ids in AI_GROUPS:
            apps = [self.cat.apps[i] for i in ids if i in self.cat.apps]
            if apps:
                self.section(title, lead)
                self.tile_grid(apps)
        self.render_models()

    def render_models(self):
        self.section("Local models", "Download a model once, then use it offline with Ollama or llama.cpp.")
        has = cs.shutil.which("ollama")
        up = ai.ollama_up() if has else False
        if not has:
            self.put(label("Install Ollama above to download models.", "st-cap"))
        elif not up:
            self.put(label("The Ollama service is not running yet. It starts with: doas rc-service ollama start", "st-cap", wrap=True))
        have = {}
        if up:
            try:
                have = dict(ai.local_models())
            except (cs.StoreError, OSError):
                pass
        fb = TileGrid(3)
        for m in ai.models():
            box = vbox(4); add_cls(box, "cp-card st-tile")
            t = hbox(8); t.pack_start(label(m["name"], "st-name"), False, False, 0)
            if m.get("good"):
                t.pack_start(label("Good start", "cp-badge"), False, False, 0)
            box.pack_start(t, False, False, 0)
            box.pack_start(label(m["description"], "st-cap", wrap=True, lines=2, ellipsize=True, chars=28), False, False, 0)
            box.pack_start(label(f'{m["size_mb"]} MB, needs about {m["ram_gb"]} GB RAM', "st-cap"), False, False, 0)
            key = "model:" + m["id"]
            foot = hbox(8); foot.set_margin_top(6)
            if key in self.busy:
                l = label(self.busy[key]["text"], "st-busy"); bar = Gtk.ProgressBar(); add_cls(bar, "st-prog"); bar.set_fraction(self.busy[key]["frac"] or 0); bar.set_valign(Gtk.Align.CENTER)
                foot.pack_start(l, False, False, 0); foot.pack_end(bar, False, False, 0); self.busy_w.setdefault(key, []).append((l, bar))
            elif m["id"] in have:
                foot.pack_start(symbolic("object-select-symbolic", 14, "st-installed-ico"), False, False, 0); foot.pack_start(label("Downloaded", "st-installed"), False, False, 0)
            else:
                b = Gtk.Button(label="Download"); add_cls(b, "cp-primary st-get"); b.set_sensitive(up); b.set_tooltip_text("" if up else "Start the Ollama service first")
                b.connect("clicked", lambda *_, m=m: self.pull_model(m)); foot.pack_start(b, False, False, 0)
            box.pack_start(foot, False, False, 0)
            fb.add(box)
        self.put(fb)

    def pull_model(self, m):
        mem = ai.mem_mb()
        if m["ram_gb"] * 1024 > mem:
            d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.OK_CANCEL, text="This model may be too big")
            d.format_secondary_text(f'{m["name"]} likes about {m["ram_gb"]} GB of RAM; this computer has {mem // 1024} GB. It may be very slow. Download anyway?')
            r = d.run(); d.destroy()
            if r != Gtk.ResponseType.OK:
                return
        self.task("model:" + m["id"], f'Downloading {m["name"]}', lambda cb, pw: ai.pull_model(m["id"], cb))

    # ------------------------------------------------------------ detail
    def render_detail(self, a):
        prev = self.history[-1][0] if self.history else self.page
        pn = {"home": "Discover", "ai": "AI & Agents", "bundles": "Bundles", "installed": "Installed", "updates": "Updates"}.get(prev) or self.cat_name.get(prev, "Back")
        bk = Gtk.Button(); bh = hbox(4); bh.pack_start(symbolic("go-previous-symbolic", 16), False, False, 0); bh.pack_start(label(pn), False, False, 0); bk.add(bh)
        add_cls(bk, "st-link"); bk.set_halign(Gtk.Align.START); bk.connect("clicked", self.back); bk.set_tooltip_text("Back (Esc)")
        self.put(bk)
        head = hbox(24); head.set_margin_top(4)
        head.pack_start(self.icon_for(a, 112), False, False, 0)
        v = vbox(6); v.set_valign(Gtk.Align.CENTER)
        v.pack_start(label(a["name"], "st-title"), False, False, 0)
        self.d_sub = label(a["description"], "st-lead", wrap=True, chars=60); v.pack_start(self.d_sub, False, False, 0)
        pills = hbox(8); pills.set_margin_top(4); pills.pack_start(self.src_pill(a), False, False, 0)
        if a.get("newcomer"):
            pills.pack_start(label("Good start", "cp-badge"), False, False, 0)
        if self.state.installed(a):
            pills.pack_start(label("Installed", "st-src good"), False, False, 0)
        v.pack_start(pills, False, False, 0)
        head.pack_start(v, True, True, 0)
        act = hbox(8); act.set_valign(Gtk.Align.CENTER)
        act.pack_start(self.action_box(a, True), False, False, 0)
        if self.state.installed(a) and a["id"] not in self.busy:
            rm = Gtk.Button(label="Remove"); add_cls(rm, "st-remove"); rm.connect("clicked", lambda *_: self.confirm_remove(a)); act.pack_start(rm, False, False, 0)
        head.pack_end(act, False, False, 0)
        self.put(head)
        # facts strip
        where, where2 = installs_to(a)
        size = f'{a["size_mb"]} MB' if a.get("size_mb") else "Small"
        lic, lic2 = "", ""
        if a["source"] == "ai":
            lic = ai.get_tool(a["pkg"])["license"]; lic2 = "Open source" if any(x in lic.lower() for x in ("mit", "apache", "bsd", "gpl")) else "Not open source"
        facts = [("SOURCE", source_name(a), SOURCE.get(a["source"], ("", ""))[1].split(".")[0]), ("DOWNLOAD", size, "about, before install"), ("INSTALLS TO", where, where2), ("LICENCE", lic or "...", lic2)]
        strip = hbox(0); add_cls(strip, "cp-card"); self.fact_lbls = {}
        for i, (cap, val, sub) in enumerate(facts):
            if i:
                sp = Gtk.Box(); add_cls(sp, "st-fact-sep"); strip.pack_start(sp, False, False, 0)
            c = vbox(2); add_cls(c, "st-fact")
            c.pack_start(label(cap, "st-cap11"), False, False, 0)
            vl = label(val, "st-name", wrap=True, chars=20); sl = label(sub, "st-cap", wrap=True, chars=22)
            c.pack_start(vl, False, False, 0); c.pack_start(sl, False, False, 0)
            self.fact_lbls[cap] = (vl, sl)
            strip.pack_start(c, True, True, 0)
        self.put(strip)
        # screenshots
        self.shots_box = hbox(12)
        self.shots_sw = Gtk.ScrolledWindow(); self.shots_sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER); self.shots_sw.set_min_content_height(268)
        self.shots_sw.add(self.shots_box); self.shots_sw.set_no_show_all(True); self.put(self.shots_sw)
        # about
        self.section("About")
        self.put(label(a.get("detail", a["description"]), "", wrap=True, selectable=True))
        if a.get("note"):
            self.put(add_cls(label(a["note"], "", wrap=True), "st-note"))
        if a["source"] == "ai":
            self.render_getting_started(a)
        threading.Thread(target=self.load_facts, args=(a,), daemon=True).start()

    def render_getting_started(self, a):
        t = ai.get_tool(a["pkg"])
        self.section("Getting started")
        card = vbox(14); add_cls(card, "cp-card st-tile")
        done = self.state.installed(a)
        def step(n, title, body=None, code=None, ok=False):
            r = hbox(12)
            num = label("✓" if ok else str(n), "st-step" + (" done" if ok else ""), xalign=0.5); num.set_valign(Gtk.Align.START); num.set_size_request(24, 24)
            r.pack_start(num, False, False, 0)
            c = vbox(4); c.pack_start(label(title, "st-name"), False, False, 0)
            if body:
                c.pack_start(label(body, "st-cap", wrap=True), False, False, 0)
            if code:
                cb = hbox(8); add_cls(cb, "st-code"); cb.pack_start(label(code, "st-mono", selectable=True), True, True, 0)
                cp = Gtk.Button(label="Copy"); add_cls(cp, "st-link"); cp.connect("clicked", lambda *_: (Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(code, -1), self.status.set_text("Copied to the clipboard")))
                cb.pack_end(cp, False, False, 0); c.pack_start(cb, False, False, 2)
            r.pack_start(c, True, True, 0); card.pack_start(r, False, False, 0)
        step(1, "Install " + a["name"], f"Press Get. About {a.get('size_mb', '?')} MB, installed in your home folder." if not done else "Done. It is installed.", ok=done)
        if a.get("term"):
            step(2, "Start it in a terminal", "Open a terminal and type:", code=a["term"])
        step(3 if a.get("term") else 2, "Sign in or add a key", t["post"])
        self.put(card)

    def load_facts(self, a):
        d = api_info(a) if not os.environ.get("CARPATIC_STORE_OFFLINE") else {}
        lic = None; lic2 = ""
        if a["source"] == "flatpak":
            lic = (d.get("project_license") or "").replace("LicenseRef-proprietary", "Proprietary") or "Not listed"
            lic2 = "Open source" if d.get("is_free_license") else "Not open source"
            if d.get("developer_name"):
                GLib.idle_add(self.set_sub, a, f'{d["developer_name"]}. ' + a["description"])
        elif a["source"] == "apk":
            lic = apk_facts(a["pkg"]) or "Not listed"; lic2 = "Alpine package"
        elif a["source"] == "compat":
            lic, lic2 = "Third party", "Runs in the Ubuntu box"
        if lic is not None:
            GLib.idle_add(self.set_fact, a, "LICENCE", lic, lic2)
        if os.environ.get("CARPATIC_STORE_OFFLINE") and not a.get("screenshots"):
            return
        self.load_shots(a, d)

    def set_sub(self, a, text):
        if self.detail is a and getattr(self, "d_sub", None) is not None and self.d_sub.get_parent() is not None:
            self.d_sub.set_text(text)

    def set_fact(self, a, cap, val, sub):
        if self.detail is a and cap in getattr(self, "fact_lbls", {}):
            l1, l2 = self.fact_lbls[cap]
            if l1.get_parent() is not None:
                l1.set_text(val); l2.set_text(sub)

    def load_shots(self, a, d):
        urls = list(a.get("screenshots", []))
        if not urls and d:
            for s in (d.get("screenshots") or [])[:4]:
                szs = s.get("sizes", [])
                pick = next((z for z in szs if z.get("width") == "752"), None) or next((z for z in szs if z.get("width") == "624"), szs[0] if szs else None)
                if pick:
                    urls.append(pick["src"])
        for u in urls[:4]:
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(fetch_file(u), 460, 260, True)
            except (OSError, GLib.Error):
                continue
            GLib.idle_add(self.add_shot, a, pb)

    def add_shot(self, a, pb):
        if self.detail is not a or not isinstance(self.shots_box.get_toplevel(), Gtk.Window):
            return
        w, h = pb.get_width(), pb.get_height()
        r = RoundPix(pb, w, h, 10); self.shots_box.pack_start(r, False, False, 0); r.show()
        self.shots_sw.set_no_show_all(False); self.shots_sw.show_all()

    def confirm_remove(self, a):
        d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.NONE, text=f"Remove {a['name']}?")
        d.format_secondary_text("The app is removed. Your own files and settings in your home folder stay.")
        d.add_button("Cancel", 0); rb = d.add_button("Remove", 1); add_cls(rb, "st-remove")
        r = d.run(); d.destroy()
        if r == 1:
            self.run_queue([a], "remove")

    # ------------------------------------------------------------ search
    def render_search(self, q):
        self.page_head(f"Results for “{q}”")
        res = self.cat.search(q)
        for c in self.cat.categories:
            if q.lower() in c["name"].lower():
                res += [self.cat.apps[i] for i in c["apps"] if self.cat.apps[i] not in res]
        if res:
            self.app_list(res)
        else:
            self.empty("edit-find-symbolic", "Nothing in the catalog matches", "Try a shorter word, or look through everything in Alpine and Flathub.")
        # honest escape hatch: search all of Alpine + Flathub from here
        if self.remote_hits is None:
            b = Gtk.Button(label="Search all of Alpine and Flathub"); add_cls(b, "st-open"); b.set_halign(Gtk.Align.START)
            b.connect("clicked", lambda *_: self.remote_search(q)); self.put(b)
        else:
            self.section("From Alpine and Flathub", "Not in the Carpathian catalog. Not checked by us.")
            hits = [h for h in self.remote_hits if h["id"] not in self.cat.apps]
            if hits:
                self.app_list(hits[:30])
            else:
                self.put(label(getattr(self, "remote_err", "") or "Nothing found there either.", "st-cap", wrap=True))

    def remote_search(self, q):
        self.status.set_text("Searching Alpine and Flathub...")
        self.remote_err = ""
        def work():
            try:
                hits = cs.search_remote(q, lambda t: GLib.idle_add(self.status.set_text, t))
            except cs.StoreError as e:
                hits = []; self.remote_err = str(e)
            except OSError:
                hits = []
            def done():
                self.remote_hits = hits; self.status.set_text(""); self.render()
            GLib.idle_add(done)
        threading.Thread(target=work, daemon=True).start()

    def empty(self, icon, title, text):
        v = vbox(8); add_cls(v, "st-empty"); v.set_halign(Gtk.Align.CENTER)
        i = symbolic(icon, 48); i.set_opacity(0.5); v.pack_start(i, False, False, 0)
        v.pack_start(label(title, "st-h2", xalign=0.5), False, False, 0)
        v.pack_start(label(text, "st-lead", xalign=0.5, wrap=True, chars=48), False, False, 0)
        self.put(v)

    # ------------------------------------------------------------ installed / updates / drivers
    def render_installed(self):
        apps = [a for a in self.cat.apps.values() if self.state.installed(a)]
        self.page_head("Installed", f"{len(apps)} from the Carpathian catalog." if apps else "")
        if not apps:
            self.empty("package-x-generic-symbolic", "Nothing installed from here yet", "Apps you install from the store show up here. Open Discover to find something you like.")
            return
        order = [("ai", "AI tools"), ("flatpak", "Flathub apps"), ("apk", "System apps"), ("compat", "Ubuntu box")]
        for src, title in order:
            grp = sorted([a for a in apps if a["source"] == src], key=lambda a: a["name"].lower())
            if grp:
                self.section(title)
                def extra(a, row):
                    if a["id"] not in self.busy:
                        rm = Gtk.Button(label="Remove"); add_cls(rm, "st-remove"); rm.set_valign(Gtk.Align.CENTER); rm.connect("clicked", lambda *_: self.confirm_remove(a)); row.pack_end(rm, False, False, 0); rm.show()
                self.app_list(grp, extra)

    def check_updates_quietly(self):
        if self.pending is None and not self.busy:
            threading.Thread(target=self.fetch_pending, args=(False,), daemon=True).start()
        return False

    def fetch_pending(self, rerender=True):
        try:
            apk, fp = cs.pending_updates()
        except (cs.StoreError, OSError):
            apk, fp = [], []
        def done():
            self.pending = (apk, fp); self.update_counts()
            if rerender and self.page == "updates" and not self.detail:
                self.render()
        GLib.idle_add(done)

    def render_updates(self):
        self.page_head("Updates")
        if self.pending is None:
            self.put(label("Checking for updates...", "st-lead"))
            sp = Gtk.Spinner(); sp.start(); sp.set_halign(Gtk.Align.START); self.put(sp)
            threading.Thread(target=self.fetch_pending, daemon=True).start()
            return
        apk, fp = self.pending; n = len(apk) + len(fp)
        if "update" in self.busy:
            self.put(label("Updating your apps...", "st-lead"))
            l = label(self.busy["update"]["text"], "st-busy"); bar = Gtk.ProgressBar(); add_cls(bar, "st-prog"); bar.set_fraction(self.busy["update"]["frac"] or 0)
            self.put(l); self.put(bar); self.busy_w.setdefault("update", []).append((l, bar))
            return
        if not n:
            self.empty("object-select-symbolic", "Everything is up to date", "AI tools are checked when you press the button below.")
        else:
            self.put(label(f"{n} update{'s are' if n != 1 else ' is'} ready.", "st-lead"))
            card = vbox(); add_cls(card, "cp-card")
            items = [(x, "System") for x in apk] + [(x, "Flathub") for x in fp]
            for i, (name, src) in enumerate(items[:40]):
                if i:
                    s = Gtk.Separator(); s.set_margin_start(16); card.pack_start(s, False, False, 0)
                r = hbox(8); add_cls(r, "st-row"); r.pack_start(label(name, "st-name"), True, True, 0); r.pack_end(label(src, "st-src"), False, False, 0); card.pack_start(r, False, False, 0)
            self.put(card)
            if len(items) > 40:
                self.put(label(f"and {len(items) - 40} more", "st-cap"))
        row = hbox(8)
        b = Gtk.Button(label="Update everything" if n else "Check AI tools too"); add_cls(b, "cp-primary st-get" if n else "st-open"); b.connect("clicked", lambda *_: self.do_update_all())
        row.pack_start(b, False, False, 0)
        rc = Gtk.Button(label="Check again"); add_cls(rc, "st-link"); rc.connect("clicked", lambda *_: (setattr(self, "pending", None), self.render())); row.pack_start(rc, False, False, 0)
        self.put(row)

    def do_update_all(self):
        if self.need_password(True) and not self.ask_password():
            return
        self.task("update", "Updating", lambda cb, pw: cs.update_all(cb, pw), done=lambda: setattr(self, "pending", None), retry=self.do_update_all)

    def render_drivers(self):
        self.page_head("Drivers & Hardware", "Carpathian looked at your computer. Install only what you need; each card says what it does.")
        finds = drv.detect()
        card = vbox(); add_cls(card, "cp-card")
        for i, f in enumerate(finds):
            if i:
                s = Gtk.Separator(); s.set_margin_start(52); card.pack_start(s, False, False, 0)
            r = hbox(14); add_cls(r, "st-row")
            stl = f["status"].lower()
            kind = "off" if stl.startswith(("n/a", "not detected")) else ("ok" if stl.startswith(("installed", "working", "ok")) or not f["packages"] or all(drv.apk_installed(x) for x in f["packages"]) else "warn")
            sd = Gtk.Box(); add_cls(sd, "st-dot-s " + kind); sd.set_valign(Gtk.Align.CENTER); sd.set_size_request(10, 10); r.pack_start(sd, False, False, 6)
            v = vbox(2)
            v.pack_start(label(f["title"], "st-name", wrap=True), False, False, 0)
            v.pack_start(label(f"{f['status'][:1].upper()}{f['status'][1:]}. {f['detail']}", "st-cap", wrap=True), False, False, 0)
            if f["honest"]:
                v.pack_start(label(f["honest"], "st-cap", wrap=True), False, False, 0)
            if f["packages"]:
                v.pack_start(label("Packages: " + " ".join(f["packages"]), "st-cap st-mono", wrap=True), False, False, 0)
            r.pack_start(v, True, True, 0)
            key = "drv:" + f["id"]
            if key in self.busy:
                c = vbox(4); c.set_valign(Gtk.Align.CENTER); l = label(self.busy[key]["text"], "st-busy", xalign=1.0); bar = Gtk.ProgressBar(); add_cls(bar, "st-prog"); bar.set_fraction(self.busy[key]["frac"] or 0)
                c.pack_start(l, False, False, 0); c.pack_start(bar, False, False, 0); r.pack_end(c, False, False, 0); self.busy_w.setdefault(key, []).append((l, bar))
            elif f["packages"]:
                miss = [x for x in f["packages"] if not drv.apk_installed(x)]
                if miss and (f["status"].startswith(("missing", "not installed")) or f["id"].startswith("gpu-")):
                    b = Gtk.Button(label="Install"); add_cls(b, "cp-primary st-get"); b.set_valign(Gtk.Align.CENTER)
                    b.connect("clicked", lambda *_, f=f, miss=miss: self.install_drivers(dict(f, packages=miss))); r.pack_end(b, False, False, 0)
                elif not miss:
                    h = hbox(6); h.set_valign(Gtk.Align.CENTER); h.pack_start(symbolic("object-select-symbolic", 14, "st-installed-ico"), False, False, 0); h.pack_start(label("Installed", "st-installed"), False, False, 0); r.pack_end(h, False, False, 0)
            card.pack_start(r, False, False, 0)
        self.put(card)

    def install_drivers(self, f):
        if self.need_password(True) and not self.ask_password():
            return
        self.task("drv:" + f["id"], "Installing", lambda cb, pw: drv.install_packages(f["packages"], cb, pw), retry=lambda: self.install_drivers(f))

    # ------------------------------------------------------------ first run
    def render_firstrun(self):
        self.page_head("Choose your apps", "Pick what you would like on this computer. You can change this any time in the App Store.")
        self.checks = []
        for b in self.cat.bundles:
            card = hbox(14); add_cls(card, "cp-card st-tile")
            chk = Gtk.CheckButton(); chk.set_active(bool(b.get("default"))); chk.set_valign(Gtk.Align.CENTER)
            self.checks.append((b, chk)); card.pack_start(chk, False, False, 0)
            apps = [self.cat.apps[i] for i in b["apps"] if i in self.cat.apps]
            ics = hbox(4)
            for a in apps[:3]:
                ics.pack_start(self.icon_for(a, 36), False, False, 0)
            card.pack_start(ics, False, False, 0)
            v = vbox(2); v.set_valign(Gtk.Align.CENTER)
            v.pack_start(label(b["name"], "st-name"), False, False, 0)
            v.pack_start(label(b["description"], "st-cap", wrap=True), False, False, 0)
            mb = sum(a.get("size_mb", 0) for a in apps); mm = sum(m["size_mb"] for m in ai.models() if m["id"] in b.get("models", []))
            v.pack_start(label(f"{len(apps)} apps, about {mb + mm} MB", "st-cap", wrap=True), False, False, 0)
            card.pack_start(v, True, True, 0)
            self.put(card)
        self.footer_note.set_text("You can change this any time in the App Store.")

    def firstrun_go(self, *_):
        apps, seen, models = [], set(), []
        for b, chk in self.checks:
            if chk.get_active():
                models += [m for m in b.get("models", []) if m not in models]
                for i in b["apps"]:
                    if i in self.cat.apps and i not in seen and not self.state.installed(self.cat.apps[i]):
                        seen.add(i); apps.append(self.cat.apps[i])
        self.finish_firstrun(mark_only=not apps)
        if apps:
            self.run_queue(apps, "install", models)

    def finish_firstrun(self, mark_only=True):
        try:
            os.makedirs(os.path.expanduser("~/.config/carpatic"), exist_ok=True)
            open(os.path.expanduser("~/.config/carpatic/store-firstrun-done"), "w").write("done\n")
        except OSError:
            pass
        self.firstrun = False
        self.sidebar.set_no_show_all(False); self.sidebar.show_all()
        self.render()

    # ------------------------------------------------------------ actions / tasks
    def refresh_state(self):
        try:
            self.state.refresh()
        except (cs.StoreError, OSError):
            pass
        GLib.idle_add(self.render_if_idle)

    def render_if_idle(self):
        if not self.busy:
            self.render()

    def need_password(self, apk_involved):
        return (not cs.is_root()) and apk_involved and self.password is None and subprocess.run(["doas", "-n", "true"], capture_output=True).returncode != 0

    def ask_password(self):
        d = Gtk.Dialog(title="Administrator password", transient_for=self, modal=True)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL); ok = d.add_button("Continue", Gtk.ResponseType.OK); add_cls(ok, "cp-primary")
        e = Gtk.Entry(); e.set_visibility(False); e.set_activates_default(True); e.set_placeholder_text("Password"); d.set_default_response(Gtk.ResponseType.OK)
        box = d.get_content_area(); box.set_spacing(10); box.set_border_width(20)
        box.add(label("System changes need your password", "st-name"))
        box.add(label("It is used for this install only and never saved.", "st-cap", wrap=True))
        box.add(e); d.show_all()
        okr = d.run() == Gtk.ResponseType.OK; pw = e.get_text(); d.destroy()
        if okr:
            self.password = pw
        return okr

    def set_busy(self, key, text, frac=None):
        self.busy[key] = {"text": text, "frac": frac}
        GLib.idle_add(self.paint_busy, key)

    def paint_busy(self, key):
        b = self.busy.get(key)
        for l, bar in self.busy_w.get(key, []):
            if b:
                l.set_text(b["text"])
                if b["frac"] is not None:
                    bar.set_fraction(b["frac"])

    def pulse_bars(self):
        for key, ws in self.busy_w.items():
            if self.busy.get(key, {}).get("frac") is None:
                for _, bar in ws:
                    bar.pulse()
        return True

    def progress_cb(self, key, word, name):
        def cb(line):
            m = re.search(r"(\d+)%", line)
            m2 = re.match(r"\s*\((\d+)/(\d+)\)", line)
            if m:
                p = int(m.group(1)); self.set_busy(key, f"{word} {p}%", p / 100)
            elif m2:
                p = int(m2.group(1)) * 100 // max(1, int(m2.group(2))); self.set_busy(key, f"{word} {p}%", p / 100)
            else:
                self.set_busy(key, f"{word}...", self.busy.get(key, {}).get("frac"))
            GLib.idle_add(self.status.set_text, f"{name}: " + clean_status(line)[:100])
        return cb

    def task(self, key, word, fn, done=None, retry=None):
        self.busy[key] = {"text": word + "...", "frac": None}
        self.render()
        def work():
            try:
                pw = self.password if (self.password and not cs.is_root()) else None
                fn(self.progress_cb(key, word, key.split(":")[-1]), pw)
                GLib.idle_add(self.status.set_text, f"Done: {word}")
            except (cs.StoreError, OSError) as e:
                GLib.idle_add(self.error, str(e), retry)
            self.busy.pop(key, None)
            try:
                self.state.refresh()
            except (cs.StoreError, OSError):
                pass
            if done:
                GLib.idle_add(done)
            GLib.idle_add(self.render)
        threading.Thread(target=work, daemon=True).start()

    def run_queue(self, apps, action, models=()):
        apps = [a for a in apps if a["id"] not in self.busy]
        if not apps:
            return
        if self.need_password(any(a["source"] in ("apk", "ai") for a in apps)) and not self.ask_password():
            return
        for a in apps:
            self.busy[a["id"]] = {"text": "Waiting...", "frac": None}
        self.alert = None
        self.render()
        def work():
            post = []
            for i, a in enumerate(apps, 1):
                word = "Installing" if action == "install" else "Removing"
                self.set_busy(a["id"], f"{word}...")
                GLib.idle_add(self.status.set_text, f"{word} {a['name']} ({i}/{len(apps)})...")
                try:
                    pw = self.password if (self.password and not cs.is_root()) else None
                    cb = self.progress_cb(a["id"], word, a["name"])
                    (cs.install if action == "install" else cs.remove)(a, cb, pw)
                    if action == "install" and a["source"] == "ai":
                        post.append((a, ai.get_tool(a["pkg"])["post"]))
                    GLib.idle_add(self.status.set_text, f"Done: {a['name']}")
                except cs.StoreError as e:
                    GLib.idle_add(self.error, str(e), lambda a=a: self.run_queue([a], action))
                self.busy.pop(a["id"], None)
                self.state.refresh()
                GLib.idle_add(self.render)
            for m in models:
                key = "model:" + m
                self.busy[key] = {"text": "Downloading...", "frac": None}
                try:
                    ai.pull_model(m, self.progress_cb(key, "Downloading", m))
                except cs.StoreError as e:
                    GLib.idle_add(self.error, str(e), None)
                self.busy.pop(key, None)
            if post and not self.alert:
                a0, note = post[0]
                more = f" (and {len(post) - 1} more)" if len(post) > 1 else ""
                GLib.idle_add(self.notice, f"{a0.name if hasattr(a0, 'name') else a0['name']} is ready{more}", note)
        threading.Thread(target=work, daemon=True).start()

    def launch(self, a):
        cmd = cs.launch_command(a)
        if not cmd:
            return
        try:
            subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.status.set_text(f"Starting {a['name']}...")
        except OSError as e:
            self.error(f"Could not start {a['name']}: {e}")


def main():
    page = sys.argv[sys.argv.index("--page") + 1] if "--page" in sys.argv else None
    Store(firstrun="--firstrun" in sys.argv, page=page)
    Gtk.main()
