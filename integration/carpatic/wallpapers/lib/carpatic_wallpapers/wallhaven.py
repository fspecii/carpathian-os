"""Wallhaven (https://wallhaven.cc/help/api) client. SFW ONLY: every request carries purity=100, the parser drops anything
that is not 'sfw', and there is no setting to change either. Standard library only (urllib).

Safety rules enforced here (tests/test-wallhaven.py proves them):
  * https to wallhaven.cc, w.wallhaven.cc and th.wallhaven.cc only, also across redirects
  * the API key travels in the X-API-Key header, never in a URL, and is never logged
  * image bytes are sniffed (type) and size-limited BEFORE any decoder sees them
  * remote strings are never put into a shell command; ids are matched against ^[a-z0-9]{4,10}$
  * client-side token bucket (40/min, the API allows about 45) + disk cache with ETag / Last-Modified revalidation
  * thumbnails load on demand; a full-size image is downloaded only when download() is called (a click)
"""
import hashlib, json, os, re, socket, ssl, time, urllib.error, urllib.parse, urllib.request
from dataclasses import dataclass, field

from . import imageinfo, paths
from .limiter import TokenBucket

API = "https://wallhaven.cc/api/v1"
ALLOWED_HOSTS = ("wallhaven.cc", "w.wallhaven.cc", "th.wallhaven.cc")
ID_RE = re.compile(r"^[a-z0-9]{4,10}$")
MAX_JSON = 2 * 1024 * 1024
MAX_THUMB = 2 * 1024 * 1024
MAX_FULL = 80 * 1024 * 1024
UA = "CarpaticOS-wallpapers/1.0 (+https://github.com/carpatic-os)"

SORTINGS = [("toplist", "Top list"), ("date_added", "Latest"), ("random", "Random"), ("relevance", "Relevance"), ("views", "Most viewed"), ("favorites", "Most favourited")]
TOP_RANGES = [("1d", "Day"), ("3d", "3 days"), ("1w", "Week"), ("1M", "Month"), ("3M", "3 months"), ("6M", "6 months"), ("1y", "Year")]
COLORS = ["660000", "990000", "cc0000", "cc3333", "ea4c88", "993399", "663399", "333399", "0066cc", "0099cc", "66cccc", "77cc33",
          "669900", "336600", "666600", "999900", "cccc33", "ffff00", "ffcc33", "ff9900", "ff6600", "cc6633", "996633", "663300",
          "000000", "999999", "cccccc", "ffffff", "424153"]
CATEGORIES = [("general", "General"), ("anime", "Anime"), ("people", "People")]
POPULAR_TAGS = ["nature", "mountains", "landscape", "forest", "minimalism", "space", "city", "night", "sunset", "abstract", "ocean", "sky",
                "lake", "snow", "clouds", "stars", "architecture", "cyberpunk", "fantasy art", "digital art", "dark", "desert", "waterfall",
                "aurorae", "galaxy", "cats", "cars", "flowers", "autumn", "winter", "fog", "illustration", "pixel art", "retro", "synthwave",
                "sci-fi", "japan", "rain", "road", "bridge", "train", "moon", "sea", "island", "beach", "river", "trees", "mist"]


class WallhavenError(Exception):
    """Base class; str() is always a plain-English sentence fit for the user."""

class Offline(WallhavenError):
    def __str__(self): return "You are offline. Wallhaven will load when the connection is back."

class RateLimited(WallhavenError):
    def __str__(self): return "Wallhaven is busy (too many requests). Try again in a minute."

class NotFound(WallhavenError):
    def __str__(self): return "That wallpaper is not on Wallhaven (any more)."

class ApiError(WallhavenError):
    def __init__(self, status=0, msg=""): super().__init__(msg); self.status = status; self.msg = msg
    def __str__(self): return self.msg or f"Wallhaven returned an error ({self.status})."

class BadImage(WallhavenError):
    def __init__(self, msg="This file is not a picture we can safely use."): super().__init__(msg); self.msg = msg
    def __str__(self): return self.msg

class UnsafeURL(WallhavenError):
    def __str__(self): return "Refused: only https addresses on wallhaven.cc are allowed."


def check_url(url):
    p = urllib.parse.urlsplit(url)
    if p.scheme != "https" or (p.hostname or "").lower() not in ALLOWED_HOSTS or p.username or p.password or (p.port not in (None, 443)):
        raise UnsafeURL()
    return url


# ----- data -------------------------------------------------------------------------------------------------------------
@dataclass
class Wallpaper:
    id: str
    url: str
    path: str
    thumb_small: str
    thumb_large: str
    width: int
    height: int
    file_size: int
    file_type: str
    category: str = "general"
    views: int = 0
    favorites: int = 0
    source: str = ""
    short_url: str = ""
    colors: list = field(default_factory=list)
    uploader: str = ""
    tags: list = field(default_factory=list)
    created_at: str = ""
    detail: bool = False  # tags/uploader are only in the single-wallpaper response

    @property
    def resolution(self): return f"{self.width} x {self.height}"
    @property
    def ext(self): return {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}.get(self.file_type, "jpg")
    @property
    def attribution(self):
        return f"Wallpaper by {self.uploader} on Wallhaven" if self.uploader else "Wallpaper from Wallhaven"

    @classmethod
    def parse(cls, d):
        """Validate one API object. Returns None for anything that is not a plain SFW wallpaper on our hosts."""
        try:
            if d.get("purity") != "sfw": return None
            wid = str(d["id"])
            if not ID_RE.match(wid): return None
            thumbs = d.get("thumbs") or {}
            w = cls(id=wid, url=check_url(d["url"]), path=check_url(d["path"]),
                    thumb_small=check_url(thumbs["small"]), thumb_large=check_url(thumbs.get("large") or thumbs["small"]),
                    width=int(d["dimension_x"]), height=int(d["dimension_y"]), file_size=int(d.get("file_size") or 0),
                    file_type=str(d.get("file_type") or "image/jpeg"), category=str(d.get("category") or "general"),
                    views=int(d.get("views") or 0), favorites=int(d.get("favorites") or 0), created_at=str(d.get("created_at") or ""))
            src = str(d.get("source") or "")
            w.source = src if src.startswith(("https://", "http://")) else ""
            w.colors = [c for c in (d.get("colors") or []) if re.match(r"^#[0-9a-fA-F]{6}$", str(c))]
            sh = d.get("short_url")
            w.short_url = sh if isinstance(sh, str) and sh.startswith("https://whvn.cc/") else ""
            if "tags" in d or "uploader" in d:
                w.detail = True
                w.tags = [str(t["name"])[:60] for t in (d.get("tags") or []) if isinstance(t, dict) and t.get("name") and t.get("purity", "sfw") == "sfw"]
                up = d.get("uploader") or {}
                w.uploader = re.sub(r"[^\w .@-]", "", str(up.get("username") or ""))[:40]
            if w.width <= 0 or w.height <= 0 or w.file_type not in ("image/jpeg", "image/png", "image/webp"): return None
            return w
        except (KeyError, ValueError, TypeError, UnsafeURL, AttributeError):
            return None


@dataclass
class Query:
    text: str = ""
    categories: str = "100"  # general anime people, 1 = on. Default: general only
    sorting: str = "toplist"
    top_range: str = "1M"
    atleast: str = ""        # "1920x1080" or ""
    ratios: str = ""         # "16x9,16x10" or ""
    colors: str = ""         # one hex, no '#'
    page: int = 1
    seed: str = ""

    def params(self):
        """The query string pairs. purity is a constant on purpose: this client cannot ask for anything but SFW."""
        cats = self.categories if re.match(r"^[01]{3}$", self.categories) and self.categories != "000" else "100"
        p = [("categories", cats), ("purity", "100"), ("sorting", self.sorting if self.sorting in dict(SORTINGS) else "toplist"), ("order", "desc")]
        text = re.sub(r"[\x00-\x1f\x7f]", " ", self.text).strip()[:200]
        if text: p.append(("q", text))
        if self.sorting == "toplist": p.append(("topRange", self.top_range if self.top_range in dict(TOP_RANGES) else "1M"))
        if re.match(r"^\d{3,5}x\d{3,5}$", self.atleast): p.append(("atleast", self.atleast))
        if re.match(r"^(\d{1,2}x\d{1,2}|landscape|portrait)(,(\d{1,2}x\d{1,2}|landscape|portrait))*$", self.ratios): p.append(("ratios", self.ratios))
        if self.colors.lstrip("#").lower() in COLORS: p.append(("colors", self.colors.lstrip("#").lower()))
        if self.sorting == "random" and re.match(r"^[A-Za-z0-9]{1,12}$", self.seed): p.append(("seed", self.seed))
        p.append(("page", str(max(1, min(int(self.page), 10000)))))
        return p

    def url(self):
        return API + "/search?" + urllib.parse.urlencode(self.params())

    def key(self):
        return hashlib.sha1(self.url().encode()).hexdigest()


@dataclass
class SearchResult:
    items: list
    page: int = 1
    last_page: int = 1
    total: int = 0
    seed: str = ""
    stale: bool = False  # served from the cache while offline

    @property
    def has_more(self): return self.page < self.last_page


def parse_search(body):
    try:
        d = json.loads(body)
        meta = d.get("meta") or {}
        items = [w for w in (Wallpaper.parse(x) for x in d["data"]) if w]
        return SearchResult(items, int(meta.get("current_page") or 1), int(meta.get("last_page") or 1), int(meta.get("total") or 0), str(meta.get("seed") or ""))
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ApiError(0, "Wallhaven sent something unexpected.")


def parse_detail(body):
    try:
        w = Wallpaper.parse(json.loads(body)["data"])
    except (ValueError, KeyError, TypeError):
        w = None
    if not w: raise ApiError(0, "Wallhaven sent something unexpected (or the picture is not marked safe for work).")
    return w


def suggest_tags(prefix, seen=(), limit=8):
    """Tag suggestions: Wallhaven has no autocomplete endpoint, so these come from a curated list plus tags seen on pictures you opened."""
    pre = prefix.strip().lower().lstrip("+-")
    if not pre: return []
    pool = list(dict.fromkeys(list(seen) + POPULAR_TAGS))
    starts = [t for t in pool if t.lower().startswith(pre)]
    inside = [t for t in pool if pre in t.lower() and t not in starts]
    return (starts + inside)[:limit]


# ----- transport --------------------------------------------------------------------------------------------------------
class Response:
    def __init__(self, status, headers, body=b""):
        self.status, self.headers, self.body = status, {k.lower(): v for k, v in headers.items()}, body


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(urllib.parse.urljoin(req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class UrllibTransport:
    """Real network. Timeouts on every call; bodies are read in chunks and cut at max_bytes."""
    def __init__(self, timeout=15):
        self.timeout = timeout
        self.opener = urllib.request.build_opener(_SafeRedirect)

    def open(self, url, headers, max_bytes, sink=None, progress=None):
        check_url(url)
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", **headers})
        try:
            r = self.opener.open(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            return Response(e.code, dict(e.headers), b"")
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, ssl.SSLError, OSError) as e:
            raise Offline() from e
        with r:
            check_url(r.geturl())
            h = dict(r.headers)
            cl = r.headers.get("Content-Length")
            if cl and cl.isdigit() and int(cl) > max_bytes: raise BadImage("This file is larger than the safety limit, so it was not downloaded.")
            got, chunks = 0, []
            try:
                while True:
                    c = r.read(65536)
                    if not c: break
                    got += len(c)
                    if got > max_bytes: raise BadImage("This file is larger than the safety limit, so it was not downloaded.")
                    if sink: sink(c)
                    else: chunks.append(c)
                    if progress: progress(got, int(cl) if cl and cl.isdigit() else 0)
            except (socket.timeout, TimeoutError, ConnectionError, ssl.SSLError, OSError) as e:
                raise Offline() from e
            return Response(r.status, h, b"".join(chunks))


# ----- client -----------------------------------------------------------------------------------------------------------
class Client:
    def __init__(self, transport=None, limiter=None, cache=None, api_key=None, ttl=300, clock=time.time):
        self.transport = transport or UrllibTransport()
        self.limiter = limiter or TokenBucket(40, 8)
        self.cache = cache or paths.api_cache_dir()
        self.api_key = api_key if api_key is not None else load_api_key()
        self.ttl, self.clock = ttl, clock
        self.stats = {"requests": 0, "cache_hits": 0, "not_modified": 0, "stale_served": 0, "thumb_cache_hits": 0, "thumb_requests": 0}

    # -- API
    def _headers(self):
        return {"X-API-Key": self.api_key} if self.api_key else {}

    def _cache_path(self, url):
        return os.path.join(self.cache, hashlib.sha256(url.encode()).hexdigest()[:40] + ".json")

    def _get_json_text(self, url, ttl=None):
        """-> (body, stale). Fresh cache wins; otherwise revalidate with If-None-Match / If-Modified-Since."""
        cp = self._cache_path(url)
        ent = None
        try:
            with open(cp) as f: ent = json.load(f)
        except (OSError, ValueError):
            pass
        ttl = self.ttl if ttl is None else ttl
        if ent and self.clock() - ent.get("t", 0) < ttl:
            self.stats["cache_hits"] += 1
            return ent["body"], False
        hdr = self._headers()
        if ent and ent.get("etag"): hdr["If-None-Match"] = ent["etag"]
        if ent and ent.get("lm"): hdr["If-Modified-Since"] = ent["lm"]
        if not self.limiter.acquire(max_wait=20): raise RateLimited()
        self.stats["requests"] += 1
        try:
            r = self.transport.open(url, hdr, MAX_JSON)
        except Offline:
            if ent:
                self.stats["stale_served"] += 1
                return ent["body"], True
            raise
        if r.status == 304 and ent:
            self.stats["not_modified"] += 1
            self._store(cp, ent["body"], ent.get("etag"), ent.get("lm"))
            return ent["body"], False
        if r.status == 429: raise RateLimited()
        if r.status == 404: raise NotFound()
        if r.status in (401, 403): raise ApiError(r.status, "Wallhaven refused the API key. Check it in the Wallhaven filters, or remove it.")
        if r.status != 200: raise ApiError(r.status)
        body = r.body.decode("utf-8", "replace")
        self._store(cp, body, r.headers.get("etag"), r.headers.get("last-modified"))
        return body, False

    def _store(self, cp, body, etag, lm):
        try:
            paths.ensure(os.path.dirname(cp), 0o700)
            tmp = cp + f".{os.getpid()}.tmp"
            with open(tmp, "w") as f: json.dump({"t": self.clock(), "etag": etag, "lm": lm, "body": body}, f)
            os.replace(tmp, cp)
        except OSError:
            pass

    def search(self, q):
        body, stale = self._get_json_text(q.url(), ttl=0 if q.sorting == "random" and not q.seed else None)
        res = parse_search(body)
        res.stale = stale
        return res

    def info(self, wid):
        if not ID_RE.match(wid): raise NotFound()
        body, _ = self._get_json_text(f"{API}/w/{wid}", ttl=3600)
        return parse_detail(body)

    # -- images
    def thumb(self, w, size="small", cache_root=None):
        """Path of a cached thumbnail file (downloaded on first use). Thumbnails are small: max 2 MB, jpeg/png/webp only."""
        root = cache_root or os.path.join(paths.cache_dir(), "wallhaven")
        dest = os.path.join(root, f"{w.id}-{size}.img")
        if os.path.exists(dest):
            self.stats["thumb_cache_hits"] += 1
            return dest
        url = w.thumb_small if size == "small" else w.thumb_large
        paths.ensure(root, 0o700)
        self.stats["thumb_requests"] += 1
        r = self.transport.open(url, {}, MAX_THUMB)  # thumbnails come from the CDN, not the API: no key, not counted against 45/min
        if r.status != 200: raise ApiError(r.status)
        if imageinfo.sniff(r.body[:32]) not in ("jpeg", "png", "webp"): raise BadImage()
        tmp = dest + f".{os.getpid()}.tmp"
        with open(tmp, "wb") as f: f.write(r.body)
        os.replace(tmp, dest)
        return dest

    def download(self, w, dest_dir=None, progress=None):
        """Download the full image (call only after a click). Returns the saved path; writes <name>.json next to it."""
        dest_dir = paths.ensure(dest_dir or paths.wallhaven_dir())
        if not ID_RE.match(w.id): raise BadImage()
        name = f"wallhaven-{w.id}.{w.ext}"
        dest = os.path.join(dest_dir, name)
        if os.path.exists(dest):
            return dest
        limit = min(MAX_FULL, max(w.file_size * 2, 1) + 1024 * 1024) if w.file_size else MAX_FULL
        part = dest + ".part"
        sniffed = []
        try:
            with open(part, "wb") as f:
                def sink(c):
                    if not sniffed:
                        sniffed.append(imageinfo.sniff(c[:32]))
                        if sniffed[0] not in ("jpeg", "png", "webp"): raise BadImage()
                    f.write(c)
                r = self.transport.open(check_url(w.path), {}, limit, sink=sink, progress=progress)
            if r.status != 200: raise ApiError(r.status)
            if not sniffed: raise BadImage()
            dim = imageinfo.dimensions(part)
            if dim and (dim[0] > 20000 or dim[1] > 20000): raise BadImage("This picture is unreasonably large, so it was not saved.")
            os.replace(part, dest)
        finally:
            try: os.unlink(part)
            except OSError: pass
        side = {"source": "wallhaven", "id": w.id, "page": w.url, "file": w.path, "original_source": w.source, "uploader": w.uploader,
                "tags": w.tags, "resolution": f"{w.width}x{w.height}", "attribution": w.attribution,
                "licence": "Uploaded by a Wallhaven user; the licence is set by the creator. Not bundled with Carpathian OS.",
                "downloaded": int(self.clock())}
        with open(dest + ".json", "w") as f: json.dump(side, f, indent=1)
        return dest


# ----- key storage ------------------------------------------------------------------------------------------------------
def key_path():
    return os.path.join(paths.wp_config_dir(), "wallhaven.key")

def load_api_key():
    try:
        v = open(key_path()).read().strip()
        return v if re.match(r"^[A-Za-z0-9]{16,64}$", v) else None
    except OSError:
        return None

def save_api_key(key):
    """Store (or remove with '') the key in the user config, mode 600. Never in the repo, never in settings.conf."""
    key = (key or "").strip()
    if key and not re.match(r"^[A-Za-z0-9]{16,64}$", key):
        raise ValueError("That does not look like a Wallhaven API key (letters and digits, 32 characters).")
    p = key_path()
    if not key:
        try: os.unlink(p)
        except OSError: pass
        return
    paths.ensure(os.path.dirname(p), 0o700)
    fd = os.open(p + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f: f.write(key + "\n")
    os.replace(p + ".tmp", p)
    os.chmod(p, 0o600)
