"""Tiny image helpers for carpatic trigger colorpicker. No imaging library needed.
usage: pixel.py hex FILE.png       print the #rrggbb of a 1x1 PNG
       pixel.py swatch #rrggbb OUT.png    write a 48x48 PNG of that colour"""
import struct
import sys
import zlib


def hex_of(path):
    d = open(path, "rb").read()
    pos, idat, bpp = 8, b"", 3
    while pos < len(d):
        n, t = struct.unpack(">I4s", d[pos:pos + 8])
        body = d[pos + 8:pos + 8 + n]
        if t == b"IHDR":
            bpp = {2: 3, 6: 4, 0: 1, 4: 2}.get(body[9], 3)
        if t == b"IDAT":
            idat += body
        pos += 12 + n
    px = zlib.decompress(idat)[1:1 + bpp]
    if bpp < 3:
        px = bytes([px[0]] * 3)
    return "#%02x%02x%02x" % tuple(px[:3])


def swatch(hexv, out, size=48):
    c = bytes.fromhex(hexv.lstrip("#"))
    raw = b"".join(b"\x00" + c * size for _ in range(size))

    def ch(t, b):
        return struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b) & 0xffffffff)
    with open(out, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)) + ch(b"IDAT", zlib.compress(raw)) + ch(b"IEND", b""))


if __name__ == "__main__":
    if sys.argv[1] == "hex":
        print(hex_of(sys.argv[2]))
    elif sys.argv[1] == "swatch":
        swatch(sys.argv[2], sys.argv[3])
