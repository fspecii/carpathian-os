#!/usr/bin/env python3
"""Extra sprites for the animated Carpathian Plymouth theme (design/plymouth/carpatic/): three parallax ridge layers, the ember glow,
the progress fill and the two 'motion flag' images. Host tool: python3 + pycairo. Deterministic (fixed seeds).
Does not touch the sprites of design/tools/plymouth-assets.py (logo, text, dialog); it only adds files.

The motion flag trick: a Plymouth script cannot read the kernel command line or any file, but it can ask an image for its width.
initfs-splash.sh copies mflag-reduced.png over mflag.png when `carpatic.reduced-motion` is on the command line; the script reads
mflag.png's width (1 = full motion, 2 = reduced)."""
import importlib.util, os, sys
import cairo

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(REPO, "design", "plymouth", "carpatic")
sys.path.insert(0, os.path.join(REPO, "design", "tools"))
import brand  # noqa: E402

BG_DEEP, BG, ACC, EMBER = "#0b0e13", "#11151c", "#5cc8a8", "#f2a65a"


def mix(a, b, t):
    a, b = brand.hexrgb(a), brand.hexrgb(b)
    return tuple(x * (1 - t) + y * t for x, y in zip(a, b))


def wallpapers():
    spec = importlib.util.spec_from_file_location("wallpapers", os.path.join(REPO, "design", "tools", "wallpapers.py"))
    wp = importlib.util.module_from_spec(spec)
    argv, sys.argv = sys.argv, ["x"]
    try:
        spec.loader.exec_module(wp)
    finally:
        sys.argv = argv
    return wp


def ridge(wp, name, seed, base, amp, sharp, scale, top, bottom, W=1920, H=480):
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    c = cairo.Context(s)
    ys = wp.ridge_profile(seed, W, H * base, H * amp, 0.55, sharp, scale)
    c.move_to(0, H)
    for x, y in enumerate(ys):
        c.line_to(x, y)
    c.line_to(W, H)
    c.close_path()
    top_y = min(ys)
    g = cairo.LinearGradient(0, top_y, 0, H)
    g.add_color_stop_rgb(0, *top)
    g.add_color_stop_rgb(1, *bottom)
    c.set_source(g)
    c.fill()
    s.write_to_png(os.path.join(OUT, name))


def glow(name="glow.png", N=512):
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, N, N)
    c = cairo.Context(s)
    g = cairo.RadialGradient(N / 2, N / 2, 0, N / 2, N / 2, N / 2)
    e = brand.hexrgb(EMBER)
    for stop, a in ((0.0, 0.70), (0.08, 0.46), (0.25, 0.17), (0.5, 0.045), (0.75, 0.01), (1.0, 0.0)):
        g.add_color_stop_rgba(stop, *e, a)
    c.set_source(g)
    c.paint()
    s.write_to_png(os.path.join(OUT, name))


def fill(name="bar-fill.png", W=320, H=4):
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    c = cairo.Context(s)
    r = H / 2
    c.arc(r, r, r, 1.5707963, 4.712389)
    c.arc(W - r, r, r, 4.712389, 1.5707963)
    c.close_path()
    g = cairo.LinearGradient(0, 0, W, 0)
    g.add_color_stop_rgb(0, *brand.hexrgb("#37a085"))
    g.add_color_stop_rgb(1, *brand.hexrgb(ACC))
    c.set_source(g)
    c.fill()
    s.write_to_png(os.path.join(OUT, name))


def flags():
    for n, w in (("mflag-full.png", 1), ("mflag-reduced.png", 2)):
        s = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, 1)
        s.write_to_png(os.path.join(OUT, n))
    # the default state: full motion
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
    s.write_to_png(os.path.join(OUT, "mflag.png"))


if __name__ == "__main__":
    wp = wallpapers()
    ridge(wp, "ridge-far.png", 201, 0.46, 0.40, 0.75, 330, mix(BG, ACC, 0.20), mix(BG, ACC, 0.05))
    ridge(wp, "ridge-mid.png", 202, 0.62, 0.34, 0.50, 280, mix(BG_DEEP, "#37a085", 0.17), mix(BG, "#37a085", 0.03))
    ridge(wp, "ridge-near.png", 203, 0.80, 0.26, 0.25, 230, mix(BG_DEEP, "#26786a", 0.12), mix(BG, BG_DEEP, 0.0))
    glow(); fill(); flags()
    print("motion sprites written to", OUT)
