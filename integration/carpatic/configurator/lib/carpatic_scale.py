"""Display scale for Carpathian's GTK3 apps (one place, so every app agrees).

The desktop runs at device pixels with a fractional scale (125%, 150% ...): the font DPI (Xft.dpi = 96 x scale) enlarges text, and everything that
is written in px has to be multiplied by the same factor. GTK3's CSS ignores the font DPI, so an app that loads its own stylesheet would stay small
next to its own text. `install()` fixes that for a whole app in one line:

    import carpatic_scale; carpatic_scale.install()      # right after `from gi.repository import Gtk`

It multiplies every `Npx` of a CssProvider's text, the default size of windows (kept inside the screen), widget size requests and pixel sizes of images.
Hairlines stay at least 1 px. Nothing is done at 100%.

    factor()   -> 1.5          the scale now (live: follows xsettingsd's Xft/DPI, so it is right after a change in Settings)
    px(24)     -> 36           a design-token pixel value at the current scale
    css(text)  -> text         the same text with every Npx multiplied
    watch(cb)  -> cb(factor) is called when the scale changes while the app runs

Order of sources: CARPATIC_UI_SCALE (percent, tests) > GTK's xft-dpi setting > SCALE in ~/.config/carpatic/appearance.env > 100.
Policy and detection: configurator/bin/carpatic-scale. Design rules: docs/DESIGN-SYSTEM.md, "Scale".
"""
import os
import re

_PX = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)px\b")
_installed = False
_cache = None


def _from_env_file():
    p = os.path.join(os.environ.get("CARPATIC_STATE_CONFIG", os.environ.get("CARPATIC_CONFIG", os.path.expanduser("~/.config/carpatic"))), "appearance.env")
    try:
        for line in open(p, encoding="utf-8"):
            if line.startswith("SCALE="):
                return int(line.split("=", 1)[1].strip().strip('"'))
    except (OSError, ValueError):
        pass
    return 100


def percent():
    """Scale in percent, 100..400."""
    v = os.environ.get("CARPATIC_UI_SCALE")
    if v:
        try:
            return max(100, min(400, int(v)))
        except ValueError:
            pass
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
        st = Gtk.Settings.get_default()
        if st is not None:
            dpi = st.get_property("gtk-xft-dpi")      # 1024ths of a dpi; -1 = unset
            if dpi and dpi > 0:
                return max(100, min(400, int(round(dpi / 1024.0 / 96.0 * 100 / 5.0)) * 5))
    except Exception:
        pass
    return max(100, min(400, _from_env_file()))


def factor():
    return percent() / 100.0


def px(n, f=None):
    """n design pixels at the current scale (n >= 1 never becomes 0)."""
    f = factor() if f is None else f
    if f == 1.0 or n in (0, -1):
        return n
    v = int(n * f + 0.5)
    return v if v else (1 if n > 0 else -1)


def css(text, f=None):
    """Multiply every Npx in a stylesheet. Huge values (999px pills) and fractions below 1px are left alone."""
    f = factor() if f is None else f
    if f == 1.0:
        return text

    def one(m):
        n = float(m.group(1))
        if n < 1 or n >= 200:
            return m.group(0)
        return "%dpx" % max(1, int(n * f + 0.5))
    return _PX.sub(one, text)


def screen_size():
    try:
        from gi.repository import Gdk
        d = Gdk.Display.get_default()
        m = d.get_primary_monitor() or d.get_monitor(0)
        g = m.get_geometry()
        return g.width, g.height
    except Exception:
        return 0, 0


# Programs that size and place their windows from the SCREEN (device px: a card that fits the monitor, a preview at 78 % of the work area, widgets on a grid):
# they get the CSS / margin scaling but their window sizes are left alone.
DEVICE_PX_APPS = ("carpatic-theme-picker-ui", "carpatic-quicklook", "carpatic-quicklookd", "carpatic-widgets", "carpatic-intro", "carpatic-screensaver")


def install_for(program):
    """install() with the right options for a program name (basename of argv[0])."""
    install(sizes=program not in DEVICE_PX_APPS)


def _wrap_small_screens(Gtk):
    """On a small screen (QEMU's 640x480, an 800x600 or 1366x768 panel) a window's content may request more than the screen: put the content
    of plain top-level windows into a ScrolledWindow so the window can shrink to the screen and the page scrolls. Dialogs and big screens are untouched."""
    sw, sh = screen_size()
    if not sw or (sw >= 1280 and sh >= 720):
        return
    orig_add = Gtk.Window.add

    def add(self, child):
        if isinstance(self, Gtk.Dialog) or isinstance(child, Gtk.ScrolledWindow) or self.get_child() is not None:
            return orig_add(self, child)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.set_propagate_natural_width(False); scroller.set_propagate_natural_height(False)
        scroller.set_shadow_type(Gtk.ShadowType.NONE)
        orig_add(scroller, child)
        orig_add(self, scroller)
        scroller.show()
    Gtk.Window.add = add


def install(sizes=True):
    """Patch the GTK3 calls that carry pixel sizes so a whole app follows the scale. Safe to call twice; at 100% it only clamps default window sizes to the screen.
    sizes=False leaves default window sizes, size requests and image pixel sizes alone (programs that size windows from the screen)."""
    global _installed
    if _installed:
        return
    _installed = True
    f = factor()
    if f == 1.0:
        # 100 %: nothing to scale, but default window sizes must still never exceed a small screen (QEMU's 640x480, a 1366x768 laptop)
        if sizes:
            import gi
            try: gi.require_version("Gtk", "3.0")
            except ValueError: pass
            from gi.repository import Gtk
            if Gtk.MAJOR_VERSION != 3: return
            orig_def1 = Gtk.Window.set_default_size

            def clamp_default_size(self, w, h):
                sw, sh = screen_size()
                if sw and w > sw - 24: w = max(sw - 24, 200)
                if sh and h > sh - 48: h = max(sh - 48, 150)
                return orig_def1(self, w, h)
            Gtk.Window.set_default_size = clamp_default_size
            _wrap_small_screens(Gtk)
        return
    import gi
    try: gi.require_version("Gtk", "3.0")
    except ValueError: pass
    from gi.repository import Gtk
    if Gtk.MAJOR_VERSION != 3: return

    orig_load = Gtk.CssProvider.load_from_data

    def load_from_data(self, data, *a):
        if isinstance(data, (bytes, bytearray)):
            data = css(bytes(data).decode("utf-8", "replace"), f).encode("utf-8")
        else:
            data = css(data, f)
        return orig_load(self, data, *a)
    Gtk.CssProvider.load_from_data = load_from_data

    orig_def = Gtk.Window.set_default_size
    orig_req = Gtk.Widget.set_size_request
    orig_pix = Gtk.Image.set_pixel_size

    def set_default_size(self, w, h):
        sw, sh = screen_size()
        w2 = px(w, f) if w > 0 else w
        h2 = px(h, f) if h > 0 else h
        if sw and w2 > sw - 24:
            w2 = max(sw - 24, min(w, sw))
        if sh and h2 > sh - 48:
            h2 = max(sh - 48, min(h, sh))
        return orig_def(self, w2, h2)
    if sizes:
        Gtk.Window.set_default_size = set_default_size
        _wrap_small_screens(Gtk)


    def set_size_request(self, w, h):
        return orig_req(self, px(w, f) if w > 0 else w, px(h, f) if h > 0 else h)
    if sizes: Gtk.Widget.set_size_request = set_size_request

    # margins, borders and spacing are px too (the apps write set_margin_top(8), Gtk.Box(spacing=12) ...)
    def scaled_setter(cls, name):
        orig = getattr(cls, name, None)
        if orig is None: return

        def setter(self, n, *a):
            return orig(self, px(n, f) if isinstance(n, int) and n > 0 else n, *a)
        setattr(cls, name, setter)
    for nm in ("set_margin_top", "set_margin_bottom", "set_margin_start", "set_margin_end", "set_margin_left", "set_margin_right"):
        scaled_setter(Gtk.Widget, nm)
    scaled_setter(Gtk.Container, "set_border_width")
    scaled_setter(Gtk.Box, "set_spacing")
    scaled_setter(Gtk.Grid, "set_row_spacing"); scaled_setter(Gtk.Grid, "set_column_spacing")
    orig_box_init = Gtk.Box.__init__

    def box_init(self, *a, **kw):
        if isinstance(kw.get("spacing"), int): kw["spacing"] = px(kw["spacing"], f)
        return orig_box_init(self, *a, **kw)
    Gtk.Box.__init__ = box_init

    def set_pixel_size(self, n):
        return orig_pix(self, px(n, f) if n > 0 else n)
    if sizes: Gtk.Image.set_pixel_size = set_pixel_size


def watch(callback):
    """Call callback(factor) whenever the desktop scale changes under a running app (xsettingsd updates gtk-xft-dpi). Returns the Gtk.Settings."""
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
    st = Gtk.Settings.get_default()
    last = [percent()]

    def changed(*_):
        p = percent()
        if p != last[0]:
            last[0] = p
            callback(p / 100.0)
    st.connect("notify::gtk-xft-dpi", changed)
    return st
