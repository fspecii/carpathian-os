"""Colour sampling: a median-cut palette from a downscaled copy, and 'accent from wallpaper' (macOS-like).
Pure Python on a 48x48 RGB sample; the sample comes from GdkPixbuf (thumbs.load_pixbuf) or any RGB byte string."""
import colorsys

def median_cut(pixels, n=6):
    """pixels: list of (r,g,b). Returns [(count, (r,g,b))] sorted by population, n boxes."""
    if not pixels: return []
    boxes = [pixels]
    def spread(box): return max(max(p[i] for p in box) - min(p[i] for p in box) for i in range(3))
    while len(boxes) < n:
        cand = [b for b in boxes if len(b) > 1 and spread(b) > 0]
        if not cand: break
        box = max(cand, key=len)
        rng = [max(p[i] for p in box) - min(p[i] for p in box) for i in range(3)]
        ch = rng.index(max(rng))
        box.sort(key=lambda p: p[ch])
        mid = len(box) // 2
        gap, at = max(((box[k][ch] - box[k - 1][ch], k) for k in range(1, len(box))), default=(0, mid))
        if gap >= 40: mid = at   # clearly separate colour clusters split there, smooth gradients at the median
        i = boxes.index(box)
        boxes[i:i + 1] = [box[:mid], box[mid:]]
    out = []
    for b in boxes:
        k = len(b)
        out.append((k, tuple(round(sum(p[i] for p in b) / k) for i in range(3))))
    return sorted(out, reverse=True)

def sample_pixels(rgb_bytes, width, height, rowstride=None, channels=3):
    rowstride = rowstride or width * channels
    px = []
    for y in range(height):
        base = y * rowstride
        for x in range(width):
            o = base + x * channels
            px.append((rgb_bytes[o], rgb_bytes[o + 1], rgb_bytes[o + 2]))
    return px

def palette_of_file(path, n=6, side=48):
    from . import thumbs
    pb = thumbs.load_pixbuf(path, side)
    from gi.repository import GdkPixbuf
    pb = pb.scale_simple(min(side, pb.get_width()), min(side, pb.get_height()), GdkPixbuf.InterpType.BILINEAR)
    ch = pb.get_n_channels()
    return median_cut(sample_pixels(pb.get_pixels(), pb.get_width(), pb.get_height(), pb.get_rowstride(), ch), n)

def hexof(rgb): return "#%02x%02x%02x" % tuple(rgb)

def luminance(rgb):
    def f(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)

def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)

def suggest_accent(palette, dark=True):
    """Pick the most vivid colour that still has a visible share of the picture, then lift/lower its lightness so it works as a
    UI accent on the dark (#11151c) or light (#ffffff) surface (contrast >= 3:1). Returns '#rrggbb' or None for a grey picture."""
    if not palette: return None
    total = sum(c for c, _ in palette)
    best, score = None, 0.0
    for cnt, rgb in palette:
        h, l, s = colorsys.rgb_to_hls(*(v / 255 for v in rgb))
        if s < 0.18 or l < 0.06 or l > 0.95: continue
        sc = s * (0.35 + min(cnt / total, 0.35)) * (1 - abs(l - 0.55))
        if sc > score: best, score = (h, l, s), sc
    if best is None: return None
    h, l, s = best
    bg = (0x11, 0x15, 0x1c) if dark else (255, 255, 255)
    s = min(max(s, 0.45), 0.85)
    l = min(max(l, 0.55), 0.72) if dark else min(max(l, 0.30), 0.45)
    for _ in range(14):
        rgb = tuple(round(v * 255) for v in colorsys.hls_to_rgb(h, l, s))
        if contrast(rgb, bg) >= 3.0: break
        l = min(0.9, l + 0.03) if dark else max(0.1, l - 0.03)
    return hexof(rgb)

def accent_for(path, dark=True):
    return suggest_accent(palette_of_file(path), dark)
