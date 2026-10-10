#!/usr/bin/env python3
"""Original procedural wallpapers for the Zen and Kylin style packs (MIT, generated, no third-party artwork).
Usage: make-wallpapers.py OUTDIR   (needs python3 pycairo + PyGObject GdkPixbuf for the JPEG step)
Writes OUTDIR/{zen-dark,zen-light,kylin-dark,kylin-light}/wallpaper.jpg and wallpaper-2.jpg (1920x1080)."""
import math, os, random, sys
import cairo

W, H = 1920, 1080

def hexrgb(h, a=1.0):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)) + (a,)

def ribbon(ctx, rnd, y0, amp, colours, alpha, tilt):
    """one soft sweeping band: two bezier edges filled with a horizontal gradient"""
    pts = []
    n = 5
    for i in range(n + 1):
        x = -100 + (W + 200) * i / n
        pts.append((x, y0 + tilt * (x - W / 2) + amp * math.sin(i * 1.3 + rnd.random() * 2)))
    thick = amp * (1.6 + rnd.random())
    ctx.move_to(*pts[0])
    for i in range(1, len(pts)):
        px, py = pts[i - 1]; x, y = pts[i]
        ctx.curve_to(px + (x - px) / 2, py, px + (x - px) / 2, y, x, y)
    for i in range(len(pts) - 1, -1, -1):
        x, y = pts[i]; y += thick * (0.7 + 0.3 * math.sin(i))
        if i == len(pts) - 1:
            ctx.line_to(x, y)
        else:
            px, py = pts[i + 1][0], pts[i + 1][1] + thick * (0.7 + 0.3 * math.sin(i + 1))
            ctx.curve_to(px + (x - px) / 2, py, px + (x - px) / 2, y, x, y)
    ctx.close_path()
    g = cairo.LinearGradient(0, 0, W, 0)
    for k, c in enumerate(colours):
        g.add_color_stop_rgba(k / (len(colours) - 1), *hexrgb(c, alpha))
    ctx.set_source(g); ctx.fill()

def glow(ctx, x, y, r, colour, alpha):
    g = cairo.RadialGradient(x, y, 0, x, y, r)
    g.add_color_stop_rgba(0, *hexrgb(colour, alpha)); g.add_color_stop_rgba(1, *hexrgb(colour, 0))
    ctx.set_source(g); ctx.arc(x, y, r, 0, 2 * math.pi); ctx.fill()

def make(path, top, bottom, ribbons, glows, seed, tilt):
    s = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H); ctx = cairo.Context(s)
    g = cairo.LinearGradient(0, 0, W * 0.35, H)
    g.add_color_stop_rgb(0, *hexrgb(top)[:3]); g.add_color_stop_rgb(1, *hexrgb(bottom)[:3])
    ctx.set_source(g); ctx.paint()
    rnd = random.Random(seed)
    for (x, y, r, c, a) in glows:
        glow(ctx, x * W, y * H, r, c, a)
    for i, (cols, alpha) in enumerate(ribbons):
        ribbon(ctx, rnd, H * (0.30 + 0.17 * i), 70 + 25 * i, cols, alpha, tilt)
    s.write_to_png(path + ".png")
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    GdkPixbuf.Pixbuf.new_from_file(path + ".png").savev(path, "jpeg", ["quality"], ["90"])
    os.remove(path + ".png")

SETS = {
    # Zen: layered soft sweeps in the Zorin-blue family
    "zen-dark": [("#0d1b25", "#1d3d52", [(["#15a6f0", "#2dd0c6", "#7a5cf0"], 0.22), (["#0a82c8", "#15a6f0", "#58c8f8"], 0.20), (["#3c7ef0", "#15a6f0"], 0.16)],
                  [(0.78, 0.18, 620, "#15a6f0", 0.30)], 11, -0.05),
                 ("#101a24", "#26324a", [(["#7a5cf0", "#15a6f0"], 0.20), (["#15a6f0", "#2dd0c6"], 0.18), (["#58c8f8", "#7a5cf0"], 0.14)],
                  [(0.2, 0.8, 700, "#7a5cf0", 0.25)], 12, 0.06)],
    "zen-light": [("#f7fbfe", "#cfe5f4", [(["#9ad4f5", "#c0e4f9", "#d9cdf8"], 0.55), (["#7cc4f0", "#9ad4f5", "#b6ece6"], 0.45), (["#ffffff", "#e4f2fb"], 0.60)],
                   [(0.8, 0.2, 640, "#ffffff", 0.7)], 21, -0.05),
                  ("#fbf9fe", "#d3e6f6", [(["#c9b9f5", "#9ad4f5"], 0.45), (["#b6ece6", "#9ad4f5"], 0.40), (["#ffffff", "#ebf5fc"], 0.55)],
                   [(0.25, 0.75, 700, "#ffffff", 0.7)], 22, 0.06)],
    # Kylin: calm blue "light" gradients with soft waves (inspired by the idea of a light-seeking wave, not copying the shipped artwork)
    "kylin-light": [("#eaf3ff", "#9cc8ff", [(["#ffffff", "#bcdcff"], 0.55), (["#6aa9fb", "#3790fa", "#8fc4ff"], 0.35), (["#ffffff", "#d6e8ff"], 0.50)],
                     [(0.85, 0.1, 700, "#ffffff", 0.9)], 31, -0.04),
                    ("#f2f8ff", "#a9d3ff", [(["#ffffff", "#c8e2ff"], 0.5), (["#7cb6fd", "#3790fa"], 0.35), (["#e4f0ff", "#ffffff"], 0.5)],
                     [(0.15, 0.2, 650, "#ffffff", 0.85)], 32, 0.05)],
    "kylin-dark": [("#10161f", "#1c3354", [(["#3790fa", "#06c0c7"], 0.20), (["#1f5fbf", "#3790fa"], 0.22), (["#2c4a74", "#3790fa"], 0.16)],
                    [(0.82, 0.15, 650, "#3790fa", 0.28)], 41, -0.04),
                   ("#121820", "#223a5e", [(["#06c0c7", "#3790fa"], 0.18), (["#3790fa", "#1f5fbf"], 0.22), (["#2c4a74", "#06c0c7"], 0.14)],
                    [(0.2, 0.85, 700, "#3790fa", 0.25)], 42, 0.05)],
}

if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    for name, variants in SETS.items():
        os.makedirs(os.path.join(out, name), exist_ok=True)
        top, bottom, rib, gl, seed, tilt = variants[0]
        make(os.path.join(out, name, "wallpaper.jpg"), top, bottom, rib, gl, seed, tilt)
        top, bottom, rib, gl, seed, tilt = variants[1]
        make(os.path.join(out, name, "wallpaper-2.jpg"), top, bottom, rib, gl, seed, tilt)
        print("wrote", name)
