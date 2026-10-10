#!/usr/bin/env python3
"""mkgif.py OUT.gif WIDTH FPS frame1 frame2 ... : animated GIF from PNG or PPM frames, pure Python (pycairo only for PNG reading and scaling).
Global palette (256 colours, popularity on 5-bit colour bins), no dithering, LZW written by hand. Keep previews small: 480 px wide, 12-20 fps."""
import io, os, struct, subprocess, sys
import cairo

def load(path, W):
    if path.endswith(".ppm"):
        png = path[:-4] + ".tmp.png"
        subprocess.run([sys.executable, "-I", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "desktop", "ppm2png.py"), path, png], check=True)
        s = cairo.ImageSurface.create_from_png(png); os.unlink(png)
    else: s = cairo.ImageSurface.create_from_png(path)
    k = W / s.get_width(); H = int(round(s.get_height() * k))
    o = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H); c = cairo.Context(o); c.scale(k, k); c.set_source_surface(s, 0, 0); c.get_source().set_filter(cairo.FILTER_BEST); c.paint()
    d = bytes(o.get_data()); st = o.get_stride(); rgb = bytearray(W * H * 3)
    for y in range(H):
        row = d[y * st:y * st + W * 4]; rgb[y * W * 3:(y + 1) * W * 3:3] = row[2::4]; rgb[y * W * 3 + 1:(y + 1) * W * 3:3] = row[1::4]; rgb[y * W * 3 + 2:(y + 1) * W * 3:3] = row[0::4]
    return W, H, bytes(rgb)

def lzw(indices, mcs=8):
    clear, end = 1 << mcs, (1 << mcs) + 1; out = bytearray(); bits = 0; nb = 0
    def emit(code, size):
        nonlocal bits, nb
        bits |= code << nb; nb += size
        while nb >= 8: out.append(bits & 255); bits >>= 8; nb -= 8
    table = {bytes([i]): i for i in range(clear)}; nxt = end + 1; size = mcs + 1; emit(clear, size); w = b""
    for b in indices:
        wc = w + bytes([b])
        if wc in table: w = wc; continue
        emit(table[w], size); table[wc] = nxt; nxt += 1
        if nxt > (1 << size) and size < 12: size += 1
        if nxt >= 4096: emit(clear, size); table = {bytes([i]): i for i in range(clear)}; nxt = end + 1; size = mcs + 1
        w = bytes([b])
    emit(table[w], size); emit(end, size)
    if nb: out.append(bits & 255)
    return bytes(out)

def main():
    out, W, fps = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]); frames = [load(p, W) for p in sys.argv[4:]]
    H = frames[0][1]; hist = {}
    for _, _, rgb in frames[::max(1, len(frames) // 8)]:
        for i in range(0, len(rgb), 3 * 3):
            k = (rgb[i] >> 3, rgb[i + 1] >> 3, rgb[i + 2] >> 3); hist[k] = hist.get(k, 0) + 1
    top = sorted(hist, key=hist.get, reverse=True)[:255]; pal = [(r << 3 | 4, g << 3 | 4, b << 3 | 4) for r, g, b in top]; pal += [(0, 0, 0)] * (256 - len(pal))
    cache = {}
    def idx(r, g, b):
        k = (r >> 3, g >> 3, b >> 3)
        v = cache.get(k)
        if v is None:
            v = min(range(len(top)), key=lambda j: (pal[j][0] - r) ** 2 + (pal[j][1] - g) ** 2 + (pal[j][2] - b) ** 2); cache[k] = v
        return v
    g = io.BytesIO(); g.write(b"GIF89a" + struct.pack("<HHBBB", W, H, 0xF7, 0, 0)); g.write(b"".join(bytes(c) for c in pal))
    g.write(b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00")
    delay = max(2, round(100 / fps))
    for _, _, rgb in frames:
        ix = bytes(idx(rgb[i], rgb[i + 1], rgb[i + 2]) for i in range(0, len(rgb), 3))
        g.write(b"\x21\xf9\x04\x04" + struct.pack("<H", delay) + b"\x00\x00"); g.write(b"\x2c" + struct.pack("<HHHHB", 0, 0, W, H, 0) + b"\x08")
        data = lzw(ix)
        for i in range(0, len(data), 255): chunk = data[i:i + 255]; g.write(bytes([len(chunk)]) + chunk)
        g.write(b"\x00")
    g.write(b"\x3b"); open(out, "wb").write(g.getvalue()); print(out, os.path.getsize(out) // 1024, "KB,", len(frames), "frames")
main()
