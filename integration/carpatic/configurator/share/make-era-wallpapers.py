#!/usr/bin/env python3
"""Procedural wallpapers for the LinPad-era Carpathian themes (classic-98, luna, aero, aero-night,
platinum, aqua, aqua-metal, berry).

Port of the CC0 generator upstream/themes/desktop-themes/make-wallpapers.py (LinPad,
commit 01246414fe9517d883b9489ba3e9e9f3780f479e) from numpy to pure Pillow, because this
scratch workspace has no numpy. Same scenes and colour script, recomposed with Pillow
primitives (gradient LUTs, low-res masks upscaled and blurred); Carpathian wallpapers are
1920x1080 like every other shipped theme. Everything is drawn from gradients, curves and
noise; no third-party imagery. Output is CC0 1.0 (original Carpathian artwork).

Run from the workspace root:  python3 tests/make-era-wallpapers.py
"""
import math
import os
import random
import sys
from PIL import Image, ImageChops, ImageFilter

W, H = 1920, 1080
Q = 3                      # masks/fields are computed at 1/Q resolution, then upscaled
QW, QH = W // Q, H // Q
HERE = os.path.dirname(os.path.abspath(__file__))
SHARE = os.path.normpath(os.path.join(HERE, "..", "themes"))


def hexrgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def luts(stops):
    """[(pos, '#rrggbb'), ...] -> per-channel 256-entry LUTs (np.interp equivalent)."""
    pos = [p for p, _ in stops]
    cols = [hexrgb(c) for _, c in stops]
    out = [[], [], []]
    for i in range(256):
        t = i / 255.0
        for k in range(2, len(stops) + 1):
            if t <= pos[k - 1] or k == len(stops):
                p0, p1 = pos[k - 2], pos[k - 1]
                f = 0.0 if p1 == p0 else clamp((t - p0) / (p1 - p0))
                for ch in range(3):
                    out[ch].append(int(round(cols[k - 2][ch] + (cols[k - 1][ch] - cols[k - 2][ch]) * f)))
                break
    return out


def gradient(stops, field=None, size=(W, H), axis="v"):
    """Gradient over a 0..255 L field (any size). field=None: plain vertical/horizontal ramp."""
    if field is None:
        n = size[1] if axis == "v" else size[0]
        field = Image.new("L", (1, n) if axis == "v" else (n, 1))
        field.putdata(list(range(n)))
    r, g, b = luts(stops)
    chans = [field.point(lut) for lut in (r, g, b)]
    img = Image.merge("RGB", chans)
    return img.resize(size, Image.BICUBIC)


def up(mask, blur=0.0):
    """Low-res L mask -> full-size, optionally blurred."""
    m = mask.resize((W, H), Image.BICUBIC)
    return m.filter(ImageFilter.GaussianBlur(blur)) if blur else m


def field(fn):
    """fn(u, v) -> 0..1 sampled at low resolution -> L image."""
    data = bytearray()
    for y in range(QH):
        v = y / (QH - 1)
        row = bytearray()
        for x in range(QW):
            row += bytes((int(clamp(fn(x / (QW - 1), v)) * 255),))
        data += row
    m = Image.new("L", (QW, QH))
    m.putdata(list(data))
    return m


def blend(base, color, mask, alpha=1.0):
    """base RGB full-size; mask L full-size (0..255); color (r,g,b)."""
    m = mask if alpha >= 0.999 else mask.point(lambda x: x * alpha)
    base.paste(Image.new("RGB", base.size, color), (0, 0), m)
    return base


def noise(seed, amp, blur=1.0):
    """Deterministic grey noise as an additive RGB image (centred on black)."""
    rng = random.Random(seed)
    m = Image.new("L", (QW, QH))
    m.putdata([int(clamp(rng.gauss(0, amp) / amp) * amp) for _ in range(QW * QH)])
    m = up(m, blur) if blur else up(m)
    return Image.merge("RGB", (m, m, m))


def grain(img, seed, amp, blur=1.0):
    return ImageChops.add(img, noise(seed, 255.0, blur).point(lambda x: int(x * amp / 255.0)))


def save(theme, name, img, quality=87):
    out = os.path.join(SHARE, theme, name)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    img.save(out, quality=quality, optimize=True, progressive=True)
    print(f"{theme}/{name}  {os.path.getsize(out) // 1024} KB")


# --------------------------------------------------------------------------- scenes
def meadow(seed, evening=False, clouds2=False):
    """Luna: a clear sky over one rolling green hill (upstream 'meadow')."""
    rng = random.Random(seed)
    if evening:
        stops = [(0.0, "#27418f"), (0.45, "#7f8fd0"), (0.7, "#f2c98d"), (1.0, "#f2c98d")]
    else:
        stops = [(0.0, "#1f5fcf"), (0.45, "#4f95ea"), (0.7, "#a9d2f7"), (1.0, "#a9d2f7")]
    img = gradient(stops)

    def cloud(u, v):
        m = 0.0
        specs = ([(0.16, 0.24, 0.15, 0.04), (0.25, 0.22, 0.09, 0.032), (0.55, 0.13, 0.18, 0.045),
                  (0.86, 0.18, 0.1, 0.03), (0.62, 0.3, 0.08, 0.024)] if clouds2 else
                 [(0.18, 0.18, 0.13, 0.035), (0.27, 0.16, 0.08, 0.03), (0.66, 0.11, 0.16, 0.04),
                  (0.78, 0.15, 0.09, 0.028), (0.48, 0.27, 0.1, 0.022), (0.9, 0.3, 0.07, 0.02)])
        for cx, cy, rx, ry in specs:
            m = max(m, clamp(1 - ((u - cx) / rx) ** 2 - ((v - cy) / ry) ** 2))
        return m ** 0.6
    img = blend(img, (255, 255, 255), up(field(cloud), 16), 0.85)

    ph = rng.uniform(0.8, 2.2)

    def crest(u, v):
        return 0.62 - 0.11 * clamp(math.sin((u * 1.15 + 0.08) * math.pi)) ** 1.4 + 0.025 * math.sin(u * 7.0 + ph)
    hill = up(field(lambda u, v: 1.0 if v > crest(u, v) else 0.0), 2.5)
    depth = up(field(lambda u, v: clamp((v - crest(u, v)) / 0.45)))
    grass = gradient([(0.0, "#7cc441"), (0.25, "#4fa12a"), (1.0, "#22661a")], depth)
    light = up(field(lambda u, v: clamp(1 - abs(u - 0.38) * 1.6) * clamp(1 - clamp((v - crest(u, v)) / 0.45) * 2.2)))
    grass = blend(grass, (178, 226, 96), light, 0.45)
    grass = grain(grass, seed, 4.0)
    img.paste(grass, (0, 0), hill)

    def far(u, v):
        f = 0.6 - 0.06 * math.sin((u * 1.6 + 0.55) * math.pi)
        return 1.0 if f < v <= crest(u, v) else 0.0
    back = up(field(far), 3)
    farshade = gradient([(0.0, "#9fd16a"), (1.0, "#5f9e3c")], up(field(lambda u, v: clamp((v - (0.6 - 0.06 * math.sin((u * 1.6 + 0.55) * math.pi))) / 0.12))))
    img.paste(farshade, (0, 0), ImageChops.multiply(back, ImageChops.invert(hill)))
    return img


def ribbons(img, specs, glow):
    for cy, amp, freq, phase, width, color, alpha in specs:
        def band(u, v, cy=cy, amp=amp, freq=freq, phase=phase, width=width):
            center = cy + amp * math.sin(u * freq + phase) + 0.04 * math.sin(u * 2.3 + phase * 2)
            d = abs(v - center) / width
            return math.exp(-d * d) * (0.6 + 0.4 * math.sin(u * 5 + phase))
        img = blend(img, color, up(field(band), glow), alpha)
    return img


def aurora(seed, alt=False):
    """Aero: soft glass ribbons over a deep blue (upstream 'aurora')."""
    t = field(lambda u, v: v * 0.8 + u * 0.2)
    img = gradient([(0.0, "#06286e"), (0.55, "#0f5bb5"), (1.0, "#2b8fe0")], up(t))
    if alt:
        specs = [(0.34, 0.09, 2.7, 1.2, 0.045, (200, 240, 255), 0.5),
                 (0.52, 0.13, 3.4, 3.6, 0.03, (130, 200, 255), 0.55),
                 (0.63, 0.07, 2.2, 5.1, 0.06, (235, 248, 255), 0.45),
                 (0.44, 0.05, 5.0, 0.8, 0.02, (255, 255, 255), 0.5)]
    else:
        specs = [(0.42, 0.1, 3.2, 0.4, 0.05, (190, 235, 255), 0.55),
                 (0.5, 0.12, 2.6, 1.9, 0.03, (255, 255, 255), 0.6),
                 (0.6, 0.08, 3.8, 3.0, 0.07, (120, 210, 255), 0.4),
                 (0.35, 0.06, 4.6, 2.2, 0.02, (220, 245, 255), 0.5)]
    img = ribbons(img, specs, 8)
    fx, fy = (0.28, 0.6) if alt else (0.72, 0.47)
    img = blend(img, (255, 255, 255), up(field(lambda u, v: math.exp(-(((u - fx) / 0.12) ** 2 + ((v - fy) / 0.09) ** 2))), 6), 0.5)
    return grain(img, seed, 1.5)


def aurora_night(seed, alt=False):
    """Aero Night: green and teal light over a black-blue sky (upstream 'aurora-night')."""
    img = gradient([(0.0, "#020409"), (0.6, "#06141f"), (1.0, "#0b2a36")])
    if alt:
        img = ribbons(img, [(0.3, 0.08, 3.0, 2.0, 0.05, (60, 200, 240), 0.45),
                            (0.44, 0.11, 2.2, 4.4, 0.035, (180, 255, 200), 0.5),
                            (0.58, 0.06, 4.4, 0.6, 0.07, (40, 160, 190), 0.4)], 12)
    else:
        img = ribbons(img, [(0.38, 0.09, 2.4, 0.9, 0.06, (40, 220, 170), 0.5),
                            (0.46, 0.1, 3.1, 2.6, 0.03, (150, 255, 220), 0.45),
                            (0.55, 0.07, 2.0, 4.1, 0.08, (30, 140, 200), 0.4)], 12)
    stars = Image.new("L", (QW, QH))
    rng = random.Random(seed)
    for _ in range(QW * QH // (600 if alt else 900)):
        stars.putpixel((rng.randrange(QW), rng.randrange(QH)), 255)
    img = blend(img, (255, 255, 255), up(stars, 1.2), 1.0)
    return grain(img, seed + 1, 1.5)


def platinum(seed, vertical=False):
    """Platinum: a quiet periwinkle texture (upstream 'platinum')."""
    t = field((lambda u, v: v) if vertical else (lambda u, v: v * 0.6 + u * 0.4))
    img = gradient([(0.0, "#6d76bb"), (1.0, "#5a63a6")], up(t))
    img = grain(img, seed, 14.0, 0.6)
    cell = 16  # low-res px; 48 at full size, as upstream
    img = blend(img, (140, 150, 215), up(field(lambda u, v: 1.0 if abs((u * QW % cell) / cell - 0.5) < 0.32 and abs((v * QH % cell) / cell - 0.5) < 0.32 else 0.0), 2), 0.12)
    return img


def aqua(seed):
    """Aqua: luminous blue swooshes (upstream 'aqua')."""
    t = field(lambda u, v: v * 0.7 + (1 - u) * 0.3)
    img = gradient([(0.0, "#031a52"), (0.5, "#0a3a8c"), (1.0, "#1062c2")], up(t))
    for k, (cy, amp, w, col, a) in enumerate([(0.55, 0.22, 0.09, (60, 170, 255), 0.55),
                                              (0.62, 0.25, 0.04, (170, 225, 255), 0.6),
                                              (0.7, 0.2, 0.12, (20, 110, 230), 0.5),
                                              (0.5, 0.18, 0.02, (235, 250, 255), 0.55)]):
        def band(u, v, cy=cy, amp=amp, w=w, k=k):
            center = cy - amp * math.sin((u * 0.9 + 0.15 * k) * math.pi)
            return math.exp(-((v - center) / w) ** 2)
        img = blend(img, col, up(field(band), 7), a)
    return grain(img, seed, 1.2)


def pinstripes():
    """Aqua wallpaper-2: the title-bar pinstripe pattern as a desktop."""
    img = Image.new("RGB", (W, H), (246, 246, 248))
    line = Image.new("RGB", (W, 1), (233, 236, 242))
    for y in range(3, H, 6):
        img.paste(line, (0, y))
    top = gradient([(0.0, "#dfe6f2"), (1.0, "#f6f6f8")], None, (W, 240))
    img.paste(top, (0, 0))
    glow = up(field(lambda u, v: math.exp(-(((u - 0.5) / 0.35) ** 2 + ((v - 0.55) / 0.3) ** 2))), 40)
    return blend(img, (164, 196, 240), glow, 0.5)


def brushed_metal():
    """Aqua Metal wallpaper-2: a grey ramp with fine horizontal grain."""
    img = gradient([(0.0, "#c9ccd1"), (0.5, "#e8eaee"), (1.0, "#b7bbc2")])
    rng = random.Random(7)
    rows = Image.new("L", (1, H))
    rows.putdata([rng.randrange(236, 255) for _ in range(H)])
    streaks = rows.resize((W, H))
    percol = Image.new("L", (W, 1))
    percol.putdata([rng.randrange(248, 255) for _ in range(W)])
    streaks = ImageChops.multiply(streaks, percol.resize((W, H)))
    streaks = streaks.filter(ImageFilter.GaussianBlur(0.6))
    img = ImageChops.multiply(img, Image.merge("RGB", (streaks, streaks, streaks)).point(lambda x: 128 + x // 2))
    return img


def berry(seed, cx=0.5, cy=1.35, rad=0.95, color=(30, 139, 255)):
    """Berry: carbon weave under an arc of light (upstream 'berry')."""
    cell = 5  # low-res px; 14-15 at full size, as upstream

    def weave(u, v):
        gx, gy = int(u * QW) // cell, int(v * QH) // cell
        fx, fy = (int(u * QW) % cell) / cell, (int(v * QH) % cell) / cell
        w = math.sin(fx * math.pi) if (gx + gy) % 2 == 0 else math.sin(fy * math.pi)
        return (14 + w * 14) / 255.0
    img = gradient([(0.0, "#0e0e0e"), (1.0, "#3a3a3a")], up(field(weave)))
    img = blend(img, (0, 0, 0), up(field(lambda u, v: clamp(v * 0.6 + abs(u - 0.5) * 0.4, 0, 0.8))))

    def arc(u, v):
        d = abs(math.sqrt(((u - cx) * 1.33) ** 2 + (v - cy) ** 2) - rad)
        return math.exp(-(d / 0.012) ** 2)
    img = blend(img, color, up(field(arc), 1), 0.9)

    def halo(u, v):
        d = abs(math.sqrt(((u - cx) * 1.33) ** 2 + (v - cy) ** 2) - rad)
        return math.exp(-(d / 0.05) ** 2)
    img = blend(img, color, up(field(halo), 14), 0.45)
    return grain(img, seed, 2.0, 0.5)


def teal(variant):
    """Classic 98: the solid teal desktop (upstream uses wallpaper colour 0x008080)."""
    if variant == 0:
        return Image.new("RGB", (W, H), hexrgb("#008080"))
    img = gradient([(0.0, "#008079"), (0.75, "#008080"), (1.0, "#00666b")])
    return grain(img, 98, 2.0, 1.5)


ALL = {
    "classic-98": lambda: (teal(0), teal(1)),
    "luna": lambda: (meadow(1998), meadow(2003, evening=True, clouds2=True)),
    "aero": lambda: (aurora(7), aurora(11, alt=True)),
    "aero-night": lambda: (aurora_night(21), aurora_night(33, alt=True)),
    "platinum": lambda: (platinum(5), platinum(9, vertical=True)),
    "aqua": lambda: (aqua(3), pinstripes()),
    "aqua-metal": lambda: (aqua(3), brushed_metal()),
    "berry": lambda: (berry(13), berry(17, cx=0.32, cy=-0.3, rad=1.05, color=(61, 155, 255))),
}

if __name__ == "__main__":
    for theme, make in ALL.items():
        for n, img in enumerate(make()):
            save(theme, "wallpaper.jpg" if n == 0 else "wallpaper-2.jpg", img)
