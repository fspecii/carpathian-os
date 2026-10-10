"""The wallpaper library: built-in Carpatic pictures, the user's local folders and files, with hashing and folder watching."""
import ctypes, ctypes.util, hashlib, json, os, re, shutil, struct, urllib.parse
from dataclasses import dataclass, field

from . import imageinfo, paths

EXTS = (".jpg", ".jpeg", ".png", ".webp", ".avif", ".jxl", ".heic", ".heif", ".gif", ".bmp", ".tif", ".tiff")
ANIMATED_EXTS = (".gif",)
MAX_FILES = 6000
MAX_DEPTH = 4
MIN_W, MIN_H = 1280, 720   # below this, a warning chip (a wallpaper is stretched over the whole screen)


@dataclass
class Item:
    id: str
    source: str            # carpatic | local | wallhaven
    path: str
    title: str
    group: str = ""        # scene name / folder
    mode: str = ""         # dark | light | "" (unknown)
    width: int = 0
    height: int = 0
    size: int = 0
    mtime: float = 0
    sha: str = ""
    dup_of: str = ""       # path of the first file with identical content
    animated: bool = False

    def small_for(self, dw, dh):
        """True when the picture is clearly smaller than the screen (it would be blown up)."""
        return bool(self.width and self.height and (self.width < dw * 0.9 or self.height < dh * 0.9))

    def to_dict(self): return self.__dict__.copy()


def item_id(source, path):
    return source[:1] + hashlib.sha1(os.path.realpath(path).encode()).hexdigest()[:12]


def is_image_name(name):
    return name.lower().endswith(EXTS) and not name.startswith(".")


# ----- built-in ---------------------------------------------------------------------------------------------------------
SCENE_TITLES = {"apuseni": "Apuseni", "bucegi": "Bucegi", "ceahlau": "Ceahlau", "fagaras": "Fagaras", "piatra": "Piatra Craiului",
                "retezat": "Retezat", "rodna": "Rodna", "tatra": "Tatra"}

def _theme_mode(theme_dir):
    try:
        for line in open(os.path.join(theme_dir, "colors.toml")):
            m = re.match(r'\s*mode\s*=\s*"(\w+)"', line)
            if m: return m.group(1)
    except OSError:
        pass
    return ""

def builtin_items():
    """The 16 design wallpapers first (8 scenes x dark/light), then the pictures that come with each theme."""
    out, seen = [], set()
    def add(it):
        rp = os.path.realpath(it.path)
        sig = (it.group, os.path.basename(it.path), it.size or os.path.getsize(it.path))
        if rp in seen or sig in seen: return   # the same picture shipped in two places is listed once
        seen.add(rp); seen.add(sig); out.append(it)
    for d in paths.builtin_dirs():
        for name in sorted(os.listdir(d)):
            m = re.match(r"^([a-z]+)-(dark|light)\.(jpg|png|webp)$", name)
            if not m: continue
            p = os.path.join(d, name)
            add(_fill(Item(item_id("carpatic", p), "carpatic", p, SCENE_TITLES.get(m.group(1), m.group(1).title()), "Carpathians", m.group(2))))
    for td in paths.theme_dirs():
        for theme in sorted(os.listdir(td)):
            tdir = os.path.join(td, theme)
            if not os.path.isdir(tdir): continue
            mode = _theme_mode(tdir)
            files = sorted(f for f in os.listdir(tdir) if f.startswith("wallpaper") and is_image_name(f))
            bg = os.path.join(tdir, "backgrounds")
            if os.path.isdir(bg): files += sorted(os.path.join("backgrounds", f) for f in os.listdir(bg) if is_image_name(f))
            for i, f in enumerate(files):
                p = os.path.join(tdir, f)
                label = theme.replace("-", " ").title()
                add(_fill(Item(item_id("carpatic", p), "carpatic", p, label if len(files) == 1 else f"{label} {i + 1}", "Themes", mode)))
    # an installed-system fallback when nothing above exists
    return out


def _fill(it):
    try:
        st = os.stat(it.path); it.size, it.mtime = st.st_size, st.st_mtime
    except OSError:
        return it
    d = imageinfo.oriented_dimensions(it.path)
    if d: it.width, it.height = d
    it.animated = it.path.lower().endswith(ANIMATED_EXTS)
    return it


# ----- configuration (folders the user added) ----------------------------------------------------------------------------
def _cfg_path(): return os.path.join(paths.wp_config_dir(), "library.json")

def load_config():
    try:
        d = json.load(open(_cfg_path()))
    except (OSError, ValueError):
        d = {}
    d.setdefault("folders", []); d.setdefault("files", []); d.setdefault("default_folder", True)
    return d

def save_config(d):
    paths.ensure(os.path.dirname(_cfg_path()))
    tmp = _cfg_path() + f".{os.getpid()}.tmp"
    json.dump(d, open(tmp, "w"), indent=1)
    os.replace(tmp, _cfg_path())

def folders():
    d = load_config()
    out = []
    if d["default_folder"]: out.append(paths.pictures_dir())
    out += [f for f in d["folders"] if f not in out]
    return out

def add_folder(path):
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(path): raise ValueError("That folder does not exist.")
    d = load_config()
    if path == paths.pictures_dir(): d["default_folder"] = True
    elif path not in d["folders"]: d["folders"].append(path)
    save_config(d)
    return path

def remove_folder(path):
    path = os.path.abspath(os.path.expanduser(path))
    d = load_config()
    if path == paths.pictures_dir(): d["default_folder"] = False
    d["folders"] = [f for f in d["folders"] if f != path]
    save_config(d)

def add_file(path):
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(path): raise ValueError("That file does not exist.")
    if not is_image_name(os.path.basename(path)): raise ValueError("That is not a picture type Carpatic can use (jpg, png, webp, avif, jxl, heic, gif, bmp, tiff).")
    with open(path, "rb") as f:
        if imageinfo.sniff(f.read(32)) is None: raise ValueError("That file does not look like a picture.")
    d = load_config()
    if path not in d["files"] and not any(path.startswith(f.rstrip("/") + "/") for f in folders()): d["files"].append(path)
    save_config(d)
    return path

def remove_file(path):
    path = os.path.abspath(os.path.expanduser(path))
    d = load_config()
    d["files"] = [f for f in d["files"] if f != path]
    save_config(d)


# ----- scanning / hashing -----------------------------------------------------------------------------------------------
def scan_folder(root, limit=MAX_FILES):
    out = []
    root = os.path.abspath(root)
    def walk(d, depth):
        if len(out) >= limit or depth > MAX_DEPTH: return
        try:
            with os.scandir(d) as it:
                entries = sorted(it, key=lambda e: e.name.lower())
        except OSError:
            return
        for e in entries:
            if len(out) >= limit: return
            try:
                if e.is_dir(follow_symlinks=False):
                    if not e.name.startswith("."): walk(e.path, depth + 1)
                elif e.is_file() and is_image_name(e.name):
                    out.append(e.path)
            except OSError:
                continue
    walk(root, 0)
    return out


def _index_path(): return os.path.join(paths.cache_dir(), "index.json")

class Index:
    """Per-file facts (size, dimensions, sha256) cached by (mtime, size) so rescans cost a stat per file."""
    def __init__(self):
        try: self.d = json.load(open(_index_path()))
        except (OSError, ValueError): self.d = {}
        self.dirty = False

    def get(self, path, want_hash=False):
        try: st = os.stat(path)
        except OSError: return None
        e = self.d.get(path)
        sig = [st.st_mtime_ns, st.st_size]
        if not e or e.get("sig") != sig:
            e = {"sig": sig}; self.d[path] = e; self.dirty = True
        if "wh" not in e:
            dim = imageinfo.oriented_dimensions(path)
            e["wh"] = list(dim) if dim else [0, 0]; self.dirty = True
        if want_hash and "sha" not in e:
            e["sha"] = file_sha256(path); self.dirty = True
        return e

    def save(self):
        if not self.dirty: return
        try:
            paths.ensure(os.path.dirname(_index_path()), 0o700)
            tmp = _index_path() + f".{os.getpid()}.tmp"
            json.dump(self.d, open(tmp, "w")); os.replace(tmp, _index_path()); self.dirty = False
        except OSError:
            pass


def file_sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b: break
            h.update(b)
    return h.hexdigest()


def local_items(with_hashes=False, index=None):
    """Every local picture: files in the folders (recursive) plus single files, newest first. Duplicates (same sha256) are flagged
    with dup_of when with_hashes=True (hash only files that share a size with another, so the common case costs nothing)."""
    index = index or Index()
    cfg = load_config()
    paths_seen, items = set(), []
    for root in folders():
        for p in scan_folder(root):
            paths_seen.add(p); items.append((p, root))
    for p in cfg["files"]:
        if os.path.isfile(p) and p not in paths_seen: paths_seen.add(p); items.append((p, os.path.dirname(p)))
    out = []
    for p, root in items:
        e = index.get(p)
        if not e: continue
        wh = e["wh"]
        out.append(Item(item_id("local", p), "wallhaven" if "/Wallhaven/" in p + "/" or os.path.dirname(p).endswith("/Wallhaven") else "local", p,
                        os.path.splitext(os.path.basename(p))[0].replace("_", " ").replace("-", " "), os.path.basename(root.rstrip("/")) or "/",
                        "", wh[0], wh[1], e["sig"][1], e["sig"][0] / 1e9, e.get("sha", ""), "", p.lower().endswith(ANIMATED_EXTS)))
    out.sort(key=lambda i: -i.mtime)
    if with_hashes:
        by_size = {}
        for it in out: by_size.setdefault(it.size, []).append(it)
        for grp in by_size.values():
            if len(grp) < 2: continue
            first = {}
            for it in sorted(grp, key=lambda i: (len(i.path), i.path)):
                it.sha = index.get(it.path, want_hash=True)["sha"]
                if it.sha in first: it.dup_of = first[it.sha]
                else: first[it.sha] = it.path
    index.save()
    return out


# ----- inotify watcher --------------------------------------------------------------------------------------------------
IN_MODIFY, IN_ATTRIB, IN_CLOSE_WRITE, IN_MOVED_FROM, IN_MOVED_TO, IN_CREATE, IN_DELETE, IN_DELETE_SELF, IN_ISDIR = \
    0x2, 0x4, 0x8, 0x40, 0x80, 0x100, 0x200, 0x400, 0x40000000
IN_NONBLOCK = 0o4000
WATCH_MASK = IN_CLOSE_WRITE | IN_MOVED_FROM | IN_MOVED_TO | IN_CREATE | IN_DELETE | IN_DELETE_SELF


class Watcher:
    """inotify on folders (recursive to MAX_DEPTH). fileno() goes into a GLib IO watch (or select); read() returns the set of
    changed paths, empty when nothing happened. Debounce in the caller."""
    def __init__(self, roots):
        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
        self._add, self._rm = libc.inotify_add_watch, libc.inotify_rm_watch
        self.fd = libc.inotify_init1(IN_NONBLOCK)
        if self.fd < 0: raise OSError(ctypes.get_errno(), "inotify unavailable")
        self.wd = {}
        for r in roots: self._watch_tree(r, 0)

    def _watch_tree(self, d, depth):
        if depth > MAX_DEPTH or len(self.wd) > 2000 or not os.path.isdir(d): return
        wd = self._add(self.fd, os.fsencode(d), WATCH_MASK)
        if wd >= 0:
            self.wd[wd] = d
            try:
                for e in os.scandir(d):
                    if e.is_dir(follow_symlinks=False) and not e.name.startswith("."): self._watch_tree(e.path, depth + 1)
            except OSError:
                pass

    def fileno(self): return self.fd

    def read(self):
        try: buf = os.read(self.fd, 65536)
        except BlockingIOError: return set()
        except OSError: return set()
        changed, off = set(), 0
        while off + 16 <= len(buf):
            wd, mask, _, ln = struct.unpack_from("iIII", buf, off)
            name = buf[off + 16: off + 16 + ln].split(b"\0", 1)[0].decode(errors="replace")
            off += 16 + ln
            base = self.wd.get(wd)
            if base is None: continue
            p = os.path.join(base, name) if name else base
            if mask & IN_ISDIR and mask & (IN_CREATE | IN_MOVED_TO): self._watch_tree(p, 1)
            if (name and is_image_name(name)) or mask & (IN_ISDIR | IN_DELETE_SELF): changed.add(p)
        return changed

    def close(self):
        try: os.close(self.fd)
        except OSError: pass
