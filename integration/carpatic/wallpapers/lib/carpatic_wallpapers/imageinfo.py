"""Cheap, safe header checks: what is this file and how big, WITHOUT decoding it. Used before any decoder sees remote data."""
import struct

EXT = {"jpeg": "jpg", "png": "png", "webp": "webp", "gif": "gif", "bmp": "bmp", "avif": "avif", "heic": "heic", "jxl": "jxl", "tiff": "tiff", "svg": "svg"}
MIME = {"image/jpeg": "jpeg", "image/png": "png", "image/webp": "webp", "image/gif": "gif", "image/avif": "avif", "image/heic": "heic", "image/jxl": "jxl", "image/bmp": "bmp"}
ANIMATED = {"gif"}  # webp/apng animation is detected by sniff() below

def sniff(head):
    """Return the image kind from the first bytes (>= 32 recommended), or None."""
    h = bytes(head)
    if h[:3] == b"\xff\xd8\xff": return "jpeg"
    if h[:8] == b"\x89PNG\r\n\x1a\n": return "png"
    if h[:6] in (b"GIF87a", b"GIF89a"): return "gif"
    if h[:4] == b"RIFF" and h[8:12] == b"WEBP": return "webp"
    if h[:2] == b"BM": return "bmp"
    if h[:2] in (b"II", b"MM") and h[2:4] in (b"*\x00", b"\x00*"): return "tiff"
    if h[:2] == b"\xff\x0a" or h[:12] == b"\x00\x00\x00\x0cJXL \r\n\x87\n": return "jxl"
    if h[4:8] == b"ftyp":
        brand = h[8:12]
        if brand in (b"avif", b"avis"): return "avif"
        if brand in (b"heic", b"heix", b"mif1", b"msf1", b"heim", b"heis", b"hevc"): return "heic"
    return None

def dimensions(path):
    """(width, height) read from the header for png/jpeg/gif/webp/bmp; None when unknown (the caller may ask a decoder)."""
    try:
        with open(path, "rb") as f:
            head = f.read(32)
            kind = sniff(head)
            if kind == "png" and len(head) >= 24:
                return struct.unpack(">II", head[16:24])
            if kind == "gif":
                return struct.unpack("<HH", head[6:10])
            if kind == "bmp":
                w, h = struct.unpack("<ii", head[18:26]); return (w, abs(h))
            if kind == "webp":
                f.seek(12); chunk = f.read(30)
                if chunk[:4] == b"VP8 ": 
                    return (struct.unpack("<H", chunk[14:16])[0] & 0x3fff, struct.unpack("<H", chunk[16:18])[0] & 0x3fff)
                if chunk[:4] == b"VP8L":
                    b = struct.unpack("<I", chunk[9:13])[0]; return ((b & 0x3fff) + 1, ((b >> 14) & 0x3fff) + 1)
                if chunk[:4] == b"VP8X":
                    return (int.from_bytes(chunk[12:15], "little") + 1, int.from_bytes(chunk[15:18], "little") + 1)
                return None
            if kind == "jpeg":
                f.seek(2)
                while True:
                    b = f.read(1)
                    while b and b != b"\xff": b = f.read(1)
                    while b == b"\xff": b = f.read(1)
                    if not b: return None
                    m = b[0]
                    if m in (0xd8, 0x01) or 0xd0 <= m <= 0xd7: continue
                    ln = f.read(2)
                    if len(ln) < 2: return None
                    n = struct.unpack(">H", ln)[0]
                    if m in (0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf):
                        d = f.read(5); h, w = struct.unpack(">HH", d[1:5]); return (w, h)
                    f.seek(n - 2, 1)
    except (OSError, struct.error):
        return None
    return None

def exif_orientation(path):
    """EXIF orientation 1..8 of a JPEG (1 when absent); swaps width/height for 5..8."""
    try:
        with open(path, "rb") as f:
            if f.read(2) != b"\xff\xd8": return 1
            while True:
                b = f.read(1)
                if not b: return 1
                if b != b"\xff": continue
                m = f.read(1)
                if not m: return 1
                if m[0] in (0xd8, 0x01) or 0xd0 <= m[0] <= 0xd7 or m == b"\xff": 
                    if m == b"\xff": f.seek(-1, 1)
                    continue
                n = struct.unpack(">H", f.read(2))[0]
                if m[0] == 0xe1:
                    seg = f.read(n - 2)
                    if seg[:6] != b"Exif\0\0": return 1
                    t = seg[6:]; e = "<" if t[:2] == b"II" else ">"
                    off = struct.unpack(e + "I", t[4:8])[0]
                    cnt = struct.unpack(e + "H", t[off:off + 2])[0]
                    for i in range(cnt):
                        ent = t[off + 2 + 12 * i: off + 14 + 12 * i]
                        if struct.unpack(e + "H", ent[:2])[0] == 0x0112:
                            v = struct.unpack(e + "H", ent[8:10])[0]; return v if 1 <= v <= 8 else 1
                    return 1
                if m[0] == 0xda: return 1
                f.seek(n - 2, 1)
    except (OSError, struct.error, IndexError):
        return 1

def oriented_dimensions(path):
    d = dimensions(path)
    if d and sniff(open(path, "rb").read(32)) == "jpeg" and exif_orientation(path) >= 5:
        return (d[1], d[0])
    return d
