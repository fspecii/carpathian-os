#!/usr/bin/env python3
"""Carpatic Quick Look decoder worker.

Runs in its own process (optionally inside bubblewrap, see carpatic-quicklookd) so a broken PNG, PDF, font or media file can only
crash THIS process, never the preview window. Memory, CPU time and file size are capped with rlimits; the daemon also enforces a wall-clock timeout
and restarts the worker. It speaks JSON lines on stdin/stdout:  {"id":1,"op":"image","path":"/x.png",...} -> {"id":1,"ok":true,...}.
Everything it produces is written as PNG files into the output directory; the window only ever loads those.
"""
import os, sys, json, resource, shutil, subprocess, hashlib, io

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ql_logic as L

OUT = os.environ.get("QL_OUT", "/tmp/carpatic-quicklook")
MAX_PIXELS = 160_000_000

def limits():
    try:
        resource.setrlimit(resource.RLIMIT_AS, (3 << 30, 3 << 30))
        resource.setrlimit(resource.RLIMIT_CPU, (40, 40))
        resource.setrlimit(resource.RLIMIT_FSIZE, (64 << 20, 64 << 20))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ValueError, OSError):
        pass

import gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib
try:
    gi.require_version("cairo", "1.0")
    import cairo
except Exception:
    cairo = None
try:
    gi.require_version("Poppler", "0.18")
    from gi.repository import Poppler
except Exception:
    Poppler = None
try:
    gi.require_version("Pango", "1.0"); gi.require_version("PangoCairo", "1.0")
    from gi.repository import Pango, PangoCairo
except Exception:
    Pango = PangoCairo = None

_counter = 0
def outfile(ext="png"):
    global _counter
    _counter += 1
    return os.path.join(OUT, "%d-%d.%s" % (os.getpid(), _counter, ext))

def run(cmd, timeout=8, cap=4_000_000):
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
        return r.returncode, r.stdout[:cap], r.stderr[-400:]
    except (subprocess.TimeoutExpired, OSError) as e:
        return -1, b"", str(e).encode()

def hexcol(h, a=1.0):
    h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)) + (a,)

# ------------------------------------------------------------------ images
def op_image(req):
    path, maxd = req["path"], int(req.get("max", 2400))
    fmt, w, h = GdkPixbuf.Pixbuf.get_file_info(path)
    res = {"format": fmt.get_name() if fmt else ""}
    if fmt and w * h > MAX_PIXELS:
        return {"error": "This image is very large (%d x %d pixels). Open it with an image viewer." % (w, h), "w": w, "h": h}
    pb = None
    if fmt:
        try:
            if w > maxd or h > maxd:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, maxd, maxd, True)
            else:
                pb = GdkPixbuf.Pixbuf.new_from_file(path)
            pb = pb.apply_embedded_orientation() or pb
        except GLib.Error:
            pb = None
    if pb is None:                                # AVIF/HEIC/JXL/PSD... through external decoders when installed
        pb, w, h = _external_image(path, maxd)
        if pb is None:
            return {"error": "Quick Look cannot show this kind of image yet."}
        res["format"] = res["format"] or "converted"
    else:
        w, h = (w, h) if fmt else (pb.get_width(), pb.get_height())
    f = outfile()
    pb.savev(f, "png", [], [])
    res.update(file=f, w=w, h=h, shown_w=pb.get_width(), shown_h=pb.get_height(), exif=L.exif(path))
    return res

def _external_image(path, maxd):
    tmp = outfile()
    for cmd in (["heif-convert", "-q", "90", path, tmp.replace(".png", ".jpg")],
                ["ffmpeg", "-v", "error", "-y", "-i", path, "-frames:v", "1", "-vf", "scale='min(%d,iw)':-2" % maxd, tmp]):
        if not shutil.which(cmd[0]): continue
        rc, _, _ = run(cmd, 10)
        for cand in (tmp, tmp.replace(".png", ".jpg"), tmp.replace(".png", "-1.jpg")):
            if rc == 0 and os.path.exists(cand):
                try:
                    pb = GdkPixbuf.Pixbuf.new_from_file(cand)
                    return pb, pb.get_width(), pb.get_height()
                except GLib.Error:
                    pass
    return None, 0, 0

# ------------------------------------------------------------------ PDF
_pdf = {"key": None, "doc": None}
def _pdf_open(path):
    st = os.stat(path)
    key = (path, st.st_mtime_ns, st.st_size)
    if _pdf["key"] != key:
        _pdf.update(key=None, doc=None)
        if Poppler:
            doc = Poppler.Document.new_from_file(GLib.filename_to_uri(path, None), None)
            _pdf.update(key=key, doc=doc)
    return _pdf["doc"]

def op_pdf_info(req):
    path = req["path"]
    if Poppler:
        try:
            doc = _pdf_open(path)
        except GLib.Error as e:
            msg = e.message.lower()
            if "encrypt" in msg or "password" in msg:
                return {"error": "This PDF is protected with a password.", "locked": True}
            return {"error": "This PDF is damaged and cannot be shown."}
        n = doc.get_n_pages()
        if n < 1: return {"error": "This PDF has no pages."}
        pw, ph = doc.get_page(0).get_size()
        return {"pages": n, "title": doc.get_title() or "", "author": doc.get_author() or "", "page_w": pw, "page_h": ph}
    rc, out, _ = run(["pdfinfo", path], 6)
    if rc != 0:
        return {"error": "This PDF is damaged or protected and cannot be shown."}
    d = {}
    for l in out.decode("utf-8", "replace").split("\n"):
        k, _, v = l.partition(":"); d[k.strip()] = v.strip()
    try:
        pw, ph = [float(x) for x in d.get("Page size", "612 x 792").split()[0:3:2]]
    except ValueError:
        pw, ph = 612.0, 792.0
    return {"pages": int(d.get("Pages", "1") or 1), "title": d.get("Title", ""), "author": d.get("Author", ""), "page_w": pw, "page_h": ph}

def op_pdf_page(req):
    path, n, width = req["path"], int(req["page"]), int(req.get("width", 900))
    bg = hexcol(req.get("paper", "#ffffff"))
    if Poppler:
        doc = _pdf_open(path)
        if doc is None: return {"error": "This PDF cannot be shown."}
        page = doc.get_page(n)
        if page is None: return {"error": "That page is not available."}
        pw, ph = page.get_size()
        sc = width / pw
        if ph * sc > 6000: sc = 6000 / ph
        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, max(1, int(pw * sc)), max(1, int(ph * sc)))
        cr = cairo.Context(surf)
        cr.set_source_rgba(*bg); cr.paint(); cr.scale(sc, sc)
        page.render(cr)
        f = outfile(); surf.write_to_png(f)
        return {"file": f, "w": surf.get_width(), "h": surf.get_height()}
    tmp = outfile("")[:-1]
    rc, _, err = run(["pdftoppm", "-f", str(n + 1), "-l", str(n + 1), "-scale-to-x", str(width), "-scale-to-y", "-1", "-png", "-singlefile", path, tmp], 15)
    f = tmp + ".png"
    if rc != 0 or not os.path.exists(f):
        return {"error": "This page cannot be shown."}
    pb = GdkPixbuf.Pixbuf.new_from_file(f)
    return {"file": f, "w": pb.get_width(), "h": pb.get_height()}

# ------------------------------------------------------------------ fonts
def op_font(req):
    path, pal = req["path"], req["palette"]
    if not (Pango and PangoCairo and cairo):
        return {"error": "Quick Look cannot draw font samples on this system."}
    import ctypes
    fc = ctypes.CDLL("libfontconfig.so.1")
    fc.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    fc.FcConfigAppFontAddFile(None, path.encode())
    rc, out, _ = run(["fc-scan", "--format", "%{family[0]}\t%{style[0]}\t%{weight}\t%{fullname[0]}\t%{fontversion}\t%{lang}\n", path], 6)
    parts = out.decode("utf-8", "replace").split("\n")[0].split("\t") if rc == 0 else []
    if len(parts) < 2 or not parts[0]:
        return {"error": "This font file cannot be read."}
    fam, style = parts[0], parts[1]
    W, H = 880, 600
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    cr = cairo.Context(surf)
    cr.set_source_rgba(*hexcol(pal["bg"])); cr.paint()
    y = 28
    def put(text, size, color, weight=None, italic=False, family=fam):
        nonlocal y
        lay = PangoCairo.create_layout(cr)
        fd = Pango.FontDescription()
        fd.set_family(family); fd.set_absolute_size(size * Pango.SCALE)
        if family == fam and style.lower().startswith(("bold",)): fd.set_weight(Pango.Weight.BOLD)
        lay.set_font_description(fd); lay.set_width((W - 64) * Pango.SCALE); lay.set_wrap(Pango.WrapMode.WORD_CHAR)
        lay.set_text(text, -1)
        cr.set_source_rgba(*hexcol(color)); cr.move_to(32, y); PangoCairo.show_layout(cr, lay)
        y += lay.get_pixel_size()[1] + 14
    put("Aa", 112, pal["accent"]); y -= 20
    put(fam + (" " + style if style and style != "Regular" else ""), 30, pal["fg"])
    put("ABCDEFGHIJKLMNOPQRSTUVWXYZ", 30, pal["fg"])
    put("abcdefghijklmnopqrstuvwxyz", 30, pal["fg"])
    put("0123456789  .,:;!?&@#%()[]{}", 30, pal["fg"])
    put("The quick brown fox jumps over the lazy dog", 22, pal["fg"])
    put("Pack my box with five dozen liquor jugs", 16, pal["muted"])
    put("Sphinx of black quartz, judge my vow", 12, pal["muted"])
    if y > H: pass
    f = outfile(); surf.write_to_png(f)
    return {"file": f, "w": W, "h": H, "family": fam, "style": style, "full": parts[3] if len(parts) > 3 else fam}

# ------------------------------------------------------------------ media
def _probe(path):
    if not shutil.which("ffprobe"): return {}
    rc, out, _ = run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", path], 8)
    try: return json.loads(out.decode("utf-8", "replace")) if rc == 0 else {}
    except ValueError: return {}

def op_media(req):
    path, pal, video = req["path"], req["palette"], req.get("video", False)
    d = _probe(path)
    fmt = d.get("format", {})
    tags = {k.lower(): v for k, v in fmt.get("tags", {}).items()}
    for s in d.get("streams", []):
        for k, v in s.get("tags", {}).items(): tags.setdefault(k.lower(), v)
    res = {"duration": float(fmt["duration"]) if fmt.get("duration") not in (None, "N/A") else 0.0,
           "title": tags.get("title", ""), "artist": tags.get("artist", "") or tags.get("album_artist", ""), "album": tags.get("album", ""),
           "bitrate": int(fmt.get("bit_rate") or 0), "codec": "", "w": 0, "h": 0}
    for s in d.get("streams", []):
        if s.get("codec_type") == "audio" and not res["codec"]: res["codec"] = s.get("codec_name", ""); res["rate"] = s.get("sample_rate", "")
        if s.get("codec_type") == "video" and not (s.get("disposition", {}).get("attached_pic")) and not res["w"]:
            res["w"], res["h"] = s.get("width", 0), s.get("height", 0); res["vcodec"] = s.get("codec_name", "")
    if not video and shutil.which("ffmpeg"):
        cover = outfile("jpg")
        rc, _, _ = run(["ffmpeg", "-v", "error", "-y", "-i", path, "-an", "-frames:v", "1", "-vf", "scale='min(900,iw)':-2", cover], 8)
        if rc == 0 and os.path.exists(cover) and os.path.getsize(cover) > 0:
            res["cover"] = cover
        rc, pcm, _ = run(["ffmpeg", "-v", "error", "-t", "600", "-i", path, "-vn", "-ac", "1", "-ar", "4000", "-f", "s16le", "-"], 14, cap=6_000_000)
        if rc == 0 and len(pcm) > 4000:
            import array
            a = array.array("h"); a.frombytes(pcm[:len(pcm) // 2 * 2])
            n, step = 220, max(1, len(a) // 220)
            peaks = [max(abs(min(a[i * step:(i + 1) * step] or [0])), max(a[i * step:(i + 1) * step] or [0])) / 32768 for i in range(n)]
            top = max(peaks) or 1
            res["peaks"] = [round((x / top) ** 0.8, 3) for x in peaks]
    if video:
        poster = outfile()
        if shutil.which("ffmpegthumbnailer"):
            run(["ffmpegthumbnailer", "-i", path, "-o", poster, "-s", "900", "-t", "10%", "-f"], 10)
        elif shutil.which("ffmpeg"):
            run(["ffmpeg", "-v", "error", "-y", "-ss", "2", "-i", path, "-frames:v", "1", "-vf", "scale='min(900,iw)':-2", poster], 10)
        if os.path.exists(poster) and os.path.getsize(poster): res["poster"] = poster
    res["have_ffprobe"] = bool(d)
    return res

# ------------------------------------------------------------------ the rest, thin wrappers
def op_archive(req):
    r = L.archive_listing(req["path"], req.get("mime", ""))
    r["entries"] = [list(e) for e in r["entries"]]
    return r

def op_office(req):
    r = L.office_info(req["path"])
    th = r.pop("thumb")
    if th:
        try:
            ld = GdkPixbuf.PixbufLoader(); ld.write(th); ld.close(); pb = ld.get_pixbuf()
            f = outfile(); pb.savev(f, "png", [], []); r["thumb_file"] = f
        except GLib.Error:
            pass
    return r

def op_ping(req):
    return {"pong": True, "poppler": bool(Poppler), "pango": bool(PangoCairo), "ffmpeg": bool(shutil.which("ffmpeg")), "pid": os.getpid()}

OPS = {"image": op_image, "pdf_info": op_pdf_info, "pdf_page": op_pdf_page, "font": op_font, "media": op_media, "archive": op_archive,
       "office": op_office, "ping": op_ping}

def main():
    os.makedirs(OUT, mode=0o700, exist_ok=True)
    limits()
    out = sys.stdout
    for line in sys.stdin:
        try:
            req = json.loads(line)
            r = OPS[req["op"]](req)
            r["ok"] = "error" not in r
        except GLib.Error as e:
            r = {"ok": False, "error": "This file cannot be read (%s)." % e.message.split(":")[0]}
        except MemoryError:
            r = {"ok": False, "error": "This file is too big to preview."}
        except Exception as e:                         # never die on one bad file
            r = {"ok": False, "error": "Quick Look could not read this file.", "detail": "%s: %s" % (type(e).__name__, e)}
        r["id"] = req.get("id") if isinstance(req, dict) else None
        out.write(json.dumps(r) + "\n"); out.flush()

if __name__ == "__main__":
    main()
