"""Display scale for the panel and its flyouts. Everything inside a View is drawn in logical px (the design tokens of docs/DESIGN-SYSTEM.md); the
Canvas multiplies by the scale when it draws and divides pointer positions, and the window code converts to device px with `dev()`.
Source of the number: configurator/lib/carpatic_scale.py (CARPATIC_UI_SCALE, then GTK's Xft DPI, then appearance.env)."""
import math, os, sys

for _p in ("/usr/local/lib/carpatic", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "configurator", "lib")):
    if os.path.isdir(_p) and _p not in sys.path: sys.path.append(_p)
try:
    import carpatic_scale as _cs
except ImportError:               # panel without the configurator: no scaling
    _cs = None

_f = [None]


def factor():
    """Current scale as a float (1.0 = 100%). Cached; call refresh() after the desktop scale changed."""
    if _f[0] is None: refresh()
    return _f[0]


def refresh():
    old = _f[0]
    _f[0] = _cs.factor() if _cs else 1.0
    return old != _f[0]


def set_factor(f):
    _f[0] = float(f)


def dev(v):
    """Logical px -> device px (rounded up, so a scaled box never loses its last row)."""
    return int(math.ceil(v * factor() - 1e-6))


def devr(v):
    """Logical px -> device px, nearest."""
    return int(round(v * factor()))


def logical(v):
    """Device px -> logical px (float)."""
    return v / factor()


def css(text):
    """A stylesheet with every Npx multiplied by the scale."""
    return _cs.css(text, factor()) if _cs else text
