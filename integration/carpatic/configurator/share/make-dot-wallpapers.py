#!/usr/bin/env python3
"""Original dot-matrix wallpapers for the Nothing themes (procedural, CC0): a halftone grid that fades towards the edges, one red dot,
and a 5x7 dot-matrix clock-style word. Usage: make-dot-wallpapers.py OUTDIR  (needs Pillow)"""
import sys, os, math
from PIL import Image, ImageDraw
W, H = 1920, 1080
FONT = {"C": ["01110", "10001", "10000", "10000", "10000", "10001", "01110"], "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
        "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"], "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
        "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"], "I": ["01110", "00100", "00100", "00100", "00100", "00100", "01110"]}
def make(path, bg, dot, accent, strong, seed):
    im = Image.new("RGB", (W, H), bg); d = ImageDraw.Draw(im)
    step = 30
    for gy in range(step // 2, H, step):
        for gx in range(step // 2, W, step):
            dx, dy = (gx - W / 2) / (W / 2), (gy - H / 2) / (H / 2)
            r = math.hypot(dx, dy)
            k = max(0.0, 1.0 - r ** 1.6)
            rad = 1.2 + 4.2 * k * (0.55 + 0.45 * math.sin(gx / 140 + seed) * math.cos(gy / 110 - seed))
            d.ellipse((gx - rad, gy - rad, gx + rad, gy + rad), fill=dot)
    # word in bigger dots, centred a bit above the middle
    word = "CARPATIC"; cell = 22; gap = 3; cw = 5 * cell + cell; x0 = (W - len(word) * cw + cell) // 2; y0 = H // 2 - 7 * cell // 2 - 40
    for i, ch in enumerate(word):
        for ry, row in enumerate(FONT[ch]):
            for rx, v in enumerate(row):
                if v == "1":
                    cx, cy = x0 + i * cw + rx * cell + cell // 2, y0 + ry * cell + cell // 2
                    d.ellipse((cx - cell // 2 + gap, cy - cell // 2 + gap, cx + cell // 2 - gap, cy + cell // 2 - gap), fill=strong)
    rx0 = W - 150; ry0 = H - 150; d.ellipse((rx0 - 16, ry0 - 16, rx0 + 16, ry0 + 16), fill=accent)
    im.save(path, quality=88)
out = sys.argv[1]; os.makedirs(out, exist_ok=True)
make(f"{out}/dots-dark.jpg", "#000000", "#2a2a2a", "#d71921", "#e8e8e8", 0.0)
make(f"{out}/dots-dark-2.jpg", "#0b0b0b", "#303030", "#d71921", "#ffffff", 2.0)
make(f"{out}/dots-light.jpg", "#f4f4f4", "#cfcfcf", "#d71921", "#111111", 1.0)
make(f"{out}/dots-light-2.jpg", "#ffffff", "#d8d8d8", "#d71921", "#000000", 3.0)
