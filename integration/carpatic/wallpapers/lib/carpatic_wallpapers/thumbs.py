"""Thumbnails: cached under ~/.cache/carpatic/wallpapers/thumbs, generated lazily on worker threads.

Decoding goes through GdkPixbuf (jpg/png/webp/gif/bmp/tiff always; avif/jxl/heic when the gdk-pixbuf loaders exist). When the pixbuf
loader cannot read a format, an installed command line decoder is tried (argv lists, no shell): ImageMagick, vipsthumbnail,
heif-convert, djxl. If nothing can read a file the item still shows (with a plain tile) and says why.
"""
import hashlib, os, shutil, subprocess, tempfile, threading
from concurrent.futures import ThreadPoolExecutor

from . import imageinfo, paths

THUMB_W, THUMB_H = 320, 200   # 16:10, drawn at 1x; HiDPI scales up (grid cells are 160-200 wide)
MAX_PIXELS = 400_000_000      # refuse decompression bombs (about 20000 x 20000)

try:
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf, GLib
except Exception:  # pragma: no cover - host without GTK
    GdkPixbuf = None


def pixbuf_formats():
    if not GdkPixbuf: return set()
    out = set()
    for f in GdkPixbuf.Pixbuf.get_formats():
        out.add(f.get_name())
    return out


def supported_kinds():
    """Which image kinds can be thumbnailed on this machine (for the 'unsupported format' message and the README)."""
    fm = pixbuf_formats()
    k = {"jpeg": "jpeg" in fm, "png": "png" in fm, "webp": "webp" in fm, "gif": "gif" in fm, "bmp": "bmp" in fm, "tiff": "tiff" in fm,
         "avif": "avif" in fm, "jxl": "jxl" in fm, "heic": "heic" in fm or "heif" in fm}
    ext = _external()
    for kind in ("avif", "heic", "jxl"):
        if not k[kind] and ext.get(kind): k[kind] = True
    return k


def _external():
    m = shutil.which("magick") or shutil.which("convert")
    return {"magick": m, "avif": m or shutil.which("heif-convert"), "heic": m or shutil.which("heif-convert"),
            "jxl": shutil.which("djxl") or m, "vips": shutil.which("vipsthumbnail")}


def thumb_key(path, w=THUMB_W, h=THUMB_H):
    try:
        st = os.stat(path)
        sig = f"{os.path.abspath(path)}|{st.st_mtime_ns}|{st.st_size}|{w}x{h}"
    except OSError:
        sig = f"{path}|0|0|{w}x{h}"
    return hashlib.sha1(sig.encode()).hexdigest()[:24]


def thumb_path(path, w=THUMB_W, h=THUMB_H, root=None):
    return os.path.join(root or paths.thumbs_dir(), thumb_key(path, w, h) + ".jpg")


def _external_to_png(src, kind, tmpdir):
    ex = _external()
    out = os.path.join(tmpdir, "x.png")
    cmds = []
    if kind in ("heic", "avif") and shutil.which("heif-convert"): cmds.append([shutil.which("heif-convert"), src, out])
    if kind == "jxl" and shutil.which("djxl"): cmds.append([shutil.which("djxl"), src, out])
    if ex["magick"]: cmds.append([ex["magick"], src + "[0]", "-auto-orient", "-resize", "1600x1600>", out])
    for c in cmds:
        try:
            if subprocess.run(c, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=40).returncode == 0 and os.path.exists(out):
                return out
        except (OSError, subprocess.SubprocessError):
            continue
    return None


def load_pixbuf(path, max_side):
    """Load scaled so the longer side is at most max_side, EXIF-rotated. Returns a GdkPixbuf or raises ValueError(user message)."""
    if not GdkPixbuf: raise ValueError("Pictures cannot be previewed here (GTK image support is missing).")
    try:
        with open(path, "rb") as f: head = f.read(32)
    except OSError:
        raise ValueError("This file cannot be read.")
    kind = imageinfo.sniff(head)
    if kind is None: raise ValueError("This is not a picture type Carpathian can use.")
    dim = imageinfo.dimensions(path)
    if dim and dim[0] * dim[1] > MAX_PIXELS: raise ValueError("This picture is too large to preview safely.")
    try:
        info, w, h = GdkPixbuf.Pixbuf.get_file_info(path)
        if info is None: raise GLib.Error("no loader")
        s = min(1.0, max_side / max(w, h, 1))
        if w * h > MAX_PIXELS: raise ValueError("This picture is too large to preview safely.")
        pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, max(1, int(w * s)), max(1, int(h * s)), True)
        return pb.apply_embedded_orientation() or pb
    except GLib.Error:
        pass
    with tempfile.TemporaryDirectory() as td:
        png = _external_to_png(path, kind, td)
        if not png:
            raise ValueError(f"This {kind.upper()} picture cannot be previewed on this system (no decoder installed).")
        pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(png, max_side, max_side, True)
        return pb


def make_thumb(src, w=THUMB_W, h=THUMB_H, root=None):
    """Create (or reuse) the cached thumbnail; returns its path. Raises ValueError with a friendly message."""
    dest = thumb_path(src, w, h, root)
    if os.path.exists(dest): return dest
    pb = load_pixbuf(src, max(w, h) * 3)
    # cover-crop to the cell ratio
    sw, sh = pb.get_width(), pb.get_height()
    scale = max(w / sw, h / sh)
    nw, nh = max(w, round(sw * scale)), max(h, round(sh * scale))
    pb = pb.scale_simple(nw, nh, GdkPixbuf.InterpType.BILINEAR if scale > 0.5 else GdkPixbuf.InterpType.HYPER)
    pb = pb.new_subpixbuf((nw - w) // 2, (nh - h) // 2, w, h)
    paths.ensure(os.path.dirname(dest), 0o700)
    tmp = dest + f".{os.getpid()}.{threading.get_ident()}.tmp"
    pb.savev(tmp, "jpeg", ["quality"], ["85"])
    os.replace(tmp, dest)
    return dest


class ThumbService:
    """Background thumbnail generation. request(path, cb) returns the cached path at once when it exists, else queues work and calls
    cb(path_or_None, error) from a worker thread (UI code marshals to the main loop)."""
    def __init__(self, workers=2, root=None):
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="wp-thumb")
        self.root = root
        self.pending = {}
        self.lock = threading.Lock()
        self.generated = 0
        self.errors = {}

    def cached(self, src, w=THUMB_W, h=THUMB_H):
        p = thumb_path(src, w, h, self.root)
        return p if os.path.exists(p) else None

    def request(self, src, cb, w=THUMB_W, h=THUMB_H, prepare=None):
        p = self.cached(src, w, h)
        if p: return p
        key = (src, w, h)
        with self.lock:
            if key in self.pending:
                self.pending[key].append(cb); return None
            self.pending[key] = [cb]
        def work():
            err = None; out = None
            try:
                out = make_thumb(src, w, h, self.root); self.generated += 1
            except ValueError as e:
                err = str(e); self.errors[src] = err
            except Exception as e:  # never let a damaged file kill a worker
                err = "This picture is damaged or in an unsupported format."; self.errors[src] = err
            with self.lock: cbs = self.pending.pop(key, [])
            for c in cbs:
                try: c(out, err)
                except Exception: pass
        self.pool.submit(work)
        return None

    def shutdown(self):
        self.pool.shutdown(wait=False, cancel_futures=True)


def cache_stats(root=None):
    root = root or paths.thumbs_dir()
    n = size = 0
    for f in os.listdir(root) if os.path.isdir(root) else []:
        try: size += os.path.getsize(os.path.join(root, f)); n += 1
        except OSError: pass
    return {"files": n, "bytes": size}


def prune_cache(max_bytes=200 * 1024 * 1024, root=None):
    """Keep the cache under max_bytes: oldest-accessed thumbnails go first."""
    root = root or paths.thumbs_dir()
    files = []
    for f in os.listdir(root) if os.path.isdir(root) else []:
        p = os.path.join(root, f)
        try: st = os.stat(p); files.append((st.st_atime, st.st_size, p))
        except OSError: pass
    total = sum(s for _, s, _ in files)
    for _, s, p in sorted(files):
        if total <= max_bytes: break
        try: os.unlink(p); total -= s
        except OSError: pass
    return total
