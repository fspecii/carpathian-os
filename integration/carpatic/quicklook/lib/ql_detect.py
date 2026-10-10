"""Carpatic Quick Look: decide what a file is and how to preview it. Pure Python, no GTK, safe to unit-test on any host.

kind(path) -> dict(kind=..., mime=..., label=..., lang=...)
Kinds: folder text code markdown json csv image pdf audio video archive font office ebook binary special missing
The decision uses the file name AND the first bytes: a ".txt" that is really a PNG is shown as an image, a ".png" full of
NUL bytes is not treated as text. Nothing here ever executes or opens the file beyond reading one small head block.
"""
import os, stat

HEAD = 8192

EXT = {}
def _reg(kind, mime_by_ext):
    for e, m in mime_by_ext.items():
        EXT[e] = (kind, m)

_reg("markdown", {"md": "text/markdown", "markdown": "text/markdown", "mdown": "text/markdown", "mkd": "text/markdown"})
_reg("json", {"json": "application/json", "jsonc": "application/json", "geojson": "application/geo+json", "webmanifest": "application/manifest+json",
              "ndjson": "application/x-ndjson", "jsonl": "application/x-ndjson"})
_reg("csv", {"csv": "text/csv", "tsv": "text/tab-separated-values"})
_reg("text", {"txt": "text/plain", "log": "text/x-log", "text": "text/plain", "nfo": "text/plain", "rtf": "text/rtf", "srt": "application/x-subrip",
              "vtt": "text/vtt", "lrc": "text/plain", "ini": "text/x-ini", "conf": "text/plain", "cfg": "text/plain", "env": "text/plain",
              "rst": "text/x-rst", "tex": "text/x-tex", "bib": "text/x-bibtex", "diff": "text/x-diff", "patch": "text/x-diff", "ics": "text/calendar",
              "vcf": "text/vcard", "eml": "message/rfc822", "gitignore": "text/plain", "desktop": "application/x-desktop"})
_reg("code", {e: "text/x-" + e for e in (
    "py c h cpp cc cxx hpp hh rs go java kt kts swift rb php pl pm lua js mjs cjs ts tsx jsx sh bash zsh fish ps1 bat cmd awk sed "
    "css scss sass less html htm xml xsl xslt yaml yml toml sql r jl hs ml mli ex exs erl clj cs fs vb dart scala groovy gradle "
    "nix tf hcl proto graphql gql vue svelte astro zig nim v cmake mk make dockerfile vim el lisp scm asm s ino cu cl glsl wgsl "
    "service socket timer mount rules tpl j2 ini patch").split()})
_reg("image", {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "jpe": "image/jpeg", "gif": "image/gif", "webp": "image/webp",
               "bmp": "image/bmp", "ico": "image/vnd.microsoft.icon", "cur": "image/x-win-bitmap", "tif": "image/tiff", "tiff": "image/tiff",
               "svg": "image/svg+xml", "svgz": "image/svg+xml-compressed", "avif": "image/avif", "heic": "image/heic", "heif": "image/heif",
               "jxl": "image/jxl", "tga": "image/x-tga", "pbm": "image/x-portable-bitmap", "pgm": "image/x-portable-graymap",
               "ppm": "image/x-portable-pixmap", "xpm": "image/x-xpixmap", "qoi": "image/qoi", "dds": "image/vnd-ms.dds", "exr": "image/x-exr",
               "psd": "image/vnd.adobe.photoshop", "xcf": "image/x-xcf"})
_reg("pdf", {"pdf": "application/pdf"})
_reg("audio", {e: "audio/" + m for e, m in {"mp3": "mpeg", "flac": "flac", "ogg": "ogg", "oga": "ogg", "opus": "opus", "wav": "x-wav", "m4a": "mp4",
               "aac": "aac", "wma": "x-ms-wma", "aif": "x-aiff", "aiff": "x-aiff", "mka": "x-matroska", "mid": "midi", "midi": "midi",
               "ape": "x-ape", "wv": "x-wavpack", "amr": "amr", "ac3": "ac3", "m4b": "mp4", "mpc": "x-musepack", "caf": "x-caf"}.items()})
_reg("video", {e: "video/" + m for e, m in {"mp4": "mp4", "m4v": "x-m4v", "mkv": "x-matroska", "webm": "webm", "mov": "quicktime", "avi": "x-msvideo",
               "wmv": "x-ms-wmv", "flv": "x-flv", "mpg": "mpeg", "mpeg": "mpeg", "ogv": "ogg", "3gp": "3gpp", "ts": "mp2t", "m2ts": "mp2t",
               "vob": "mpeg", "mts": "mp2t"}.items()})
_reg("archive", {"zip": "application/zip", "tar": "application/x-tar", "gz": "application/gzip", "tgz": "application/gzip", "bz2": "application/x-bzip2",
                 "tbz2": "application/x-bzip2", "xz": "application/x-xz", "txz": "application/x-xz", "zst": "application/zstd", "tzst": "application/zstd",
                 "7z": "application/x-7z-compressed", "rar": "application/vnd.rar", "iso": "application/x-iso9660-image", "deb": "application/vnd.debian.binary-package",
                 "rpm": "application/x-rpm", "apk": "application/vnd.android.package-archive", "jar": "application/java-archive", "war": "application/java-archive",
                 "cpio": "application/x-cpio", "lz": "application/x-lzip", "lzma": "application/x-lzma", "cab": "application/vnd.ms-cab-compressed",
                 "whl": "application/zip", "egg": "application/zip", "crx": "application/x-chrome-extension", "xpi": "application/zip", "zipx": "application/zip"})
_reg("font", {"ttf": "font/ttf", "otf": "font/otf", "woff": "font/woff", "woff2": "font/woff2", "ttc": "font/collection", "pfb": "application/x-font-type1",
              "pcf": "application/x-font-pcf"})
_reg("office", {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation", "odt": "application/vnd.oasis.opendocument.text",
                "ods": "application/vnd.oasis.opendocument.spreadsheet", "odp": "application/vnd.oasis.opendocument.presentation",
                "odg": "application/vnd.oasis.opendocument.graphics", "doc": "application/msword", "xls": "application/vnd.ms-excel",
                "ppt": "application/vnd.ms-powerpoint", "pages": "application/x-iwork-pages", "key": "application/x-iwork-keynote", "numbers": "application/x-iwork-numbers",
                "dotx": "application/vnd.openxmlformats-officedocument.wordprocessingml.template", "odf": "application/vnd.oasis.opendocument.formula"})
_reg("ebook", {"epub": "application/epub+zip", "mobi": "application/x-mobipocket-ebook", "azw3": "application/vnd.amazon.ebook", "fb2": "application/x-fictionbook+xml",
               "cbz": "application/vnd.comicbook+zip", "cbr": "application/vnd.comicbook-rar", "djvu": "image/vnd.djvu"})

NAMES = {"makefile": "code", "dockerfile": "code", "containerfile": "code", "cmakelists.txt": "code", "gemfile": "code", "rakefile": "code",
         "readme": "text", "license": "text", "copying": "text", "authors": "text", "changelog": "text", "todo": "text", "notice": "text",
         "pkgbuild": "code", "apkbuild": "code", ".bashrc": "code", ".zshrc": "code", ".profile": "code", ".xinitrc": "code",
         ".gitignore": "text", ".gitattributes": "text", ".editorconfig": "text", "requirements.txt": "text", "meson.build": "code"}

# (offset, bytes, kind, mime). Checked before the extension for binary kinds, so a renamed file is still shown for what it is.
MAGIC = [
    (0, b"%PDF-", "pdf", "application/pdf"), (0, b"\x89PNG\r\n\x1a\n", "image", "image/png"), (0, b"\xff\xd8\xff", "image", "image/jpeg"),
    (0, b"GIF87a", "image", "image/gif"), (0, b"GIF89a", "image", "image/gif"), (0, b"BM", "image", "image/bmp"),
    (0, b"II*\x00", "image", "image/tiff"), (0, b"MM\x00*", "image", "image/tiff"), (0, b"\x00\x00\x01\x00", "image", "image/vnd.microsoft.icon"),
    (0, b"8BPS", "image", "image/vnd.adobe.photoshop"),
    (0, b"ID3", "audio", "audio/mpeg"), (0, b"fLaC", "audio", "audio/flac"), (0, b"OggS", "audio", "audio/ogg"), (0, b"MThd", "audio", "audio/midi"),
    (0, b"\x1aE\xdf\xa3", "video", "video/x-matroska"),
    (0, b"PK\x03\x04", "archive", "application/zip"), (0, b"PK\x05\x06", "archive", "application/zip"),
    (0, b"\x1f\x8b", "archive", "application/gzip"), (0, b"BZh", "archive", "application/x-bzip2"), (0, b"\xfd7zXZ\x00", "archive", "application/x-xz"),
    (0, b"7z\xbc\xaf\x27\x1c", "archive", "application/x-7z-compressed"), (0, b"Rar!\x1a\x07", "archive", "application/vnd.rar"),
    (0, b"\x28\xb5\x2f\xfd", "archive", "application/zstd"), (257, b"ustar", "archive", "application/x-tar"), (0, b"!<arch>\n", "archive", "application/x-archive"),
    (0, b"wOFF", "font", "font/woff"), (0, b"wOF2", "font", "font/woff2"), (0, b"OTTO", "font", "font/otf"), (0, b"\x00\x01\x00\x00\x00", "font", "font/ttf"),
    (0, b"ttcf", "font", "font/collection"), (0, b"true", "font", "font/ttf"),
    (0, b"\x7fELF", "binary", "application/x-executable"), (0, b"MZ", "binary", "application/vnd.microsoft.portable-executable"),
    (0, b"SQLite format 3\x00", "binary", "application/vnd.sqlite3"),
]

def _sniff_riff_iso(head):
    """Container formats whose type sits at a fixed offset behind a size field."""
    if head[:4] == b"RIFF":
        t = head[8:12]
        if t == b"WAVE": return "audio", "audio/x-wav"
        if t == b"WEBP": return "image", "image/webp"
        if t == b"AVI ": return "video", "video/x-msvideo"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"heic", b"heix", b"hevc", b"mif1", b"msf1", b"heim", b"heis"): return "image", "image/heic"
        if brand in (b"avif", b"avis"): return "image", "image/avif"
        if brand in (b"M4A ", b"M4B ", b"M4P "): return "audio", "audio/mp4"
        return "video", "video/mp4"
    if head[:4] == b"FORM" and head[8:12] in (b"AIFF", b"AIFC"): return "audio", "audio/x-aiff"
    if head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2", b"\xff\xfa"): return "audio", "audio/mpeg"
    if head[:4] == b"\x00\x00\x01\xba": return "video", "video/mpeg"
    return None

def is_text(head):
    """True if the bytes look like human text: valid UTF-8 (a cut multibyte tail is fine), UTF-16 with BOM, or Latin-1-ish without NULs."""
    if not head: return True
    if head[:2] in (b"\xff\xfe", b"\xfe\xff") or head[:3] == b"\xef\xbb\xbf": return True
    if b"\x00" in head: return False
    bad = sum(1 for b in head if b < 9 or 13 < b < 32 and b != 27)
    if bad > len(head) * 0.02: return False
    try:
        head.decode("utf-8")
        return True
    except UnicodeDecodeError as e:
        if e.start >= len(head) - 3: return True     # truncated in the middle of a character
    return bad == 0 and sum(1 for b in head if b >= 128) < len(head) * 0.3

def read_head(path, n=HEAD):
    try:
        with open(path, "rb") as f:
            return f.read(n)
    except OSError:
        return None

def _text_kind(head, name, ext):
    first = head[:200].lstrip()
    if head[:2] == b"#!": return "code", "text/x-script"
    if first[:5].lower() in (b"<?xml", b"<!doc") or first[:5] == b"<html" or first[:4] == b"<svg": return "code", "text/xml"
    return "text", "text/plain"

def kind(path):
    """Classify path. Never raises; unreadable things become kind 'binary' with an 'error' note."""
    name = os.path.basename(path.rstrip("/")) or path
    res = {"kind": "binary", "mime": "application/octet-stream", "name": name, "path": path}
    try:
        st = os.lstat(path)
    except OSError as e:
        res.update(kind="missing", error=e.strerror or "not found")
        return res
    res["lstat"] = st
    if stat.S_ISLNK(st.st_mode):
        res["link"] = os.readlink(path)
        try:
            st = os.stat(path)
        except OSError:
            res.update(kind="missing", error="This link points to something that no longer exists.")
            return res
        res["stat"] = st
    else:
        res["stat"] = st
    m = st.st_mode
    if stat.S_ISDIR(m):
        res.update(kind="folder", mime="inode/directory")
        return res
    if not stat.S_ISREG(m):
        res.update(kind="special", mime="inode/special")
        return res
    low = name.lower()
    ext = low.rsplit(".", 1)[-1] if "." in low and not low.startswith(".") or low.count(".") > 1 else ""
    if low.endswith((".tar.gz", ".tar.xz", ".tar.bz2", ".tar.zst")): ext = "tar"
    byext = EXT.get(ext) or ((NAMES[low], "text/plain") if low in NAMES else None)
    if st.st_size == 0:
        res.update(kind=(byext[0] if byext and byext[0] in ("text", "code", "markdown", "json", "csv") else "text"), mime=(byext[1] if byext else "text/plain"), empty=True)
        return res
    head = read_head(path)
    if head is None:
        res.update(kind="binary", error="You do not have permission to read this file.")
        return res
    mg = _magic(head)
    texty = is_text(head)
    if byext and byext[0] in ("text", "code", "markdown", "json", "csv"):
        if texty:
            res.update(kind=byext[0], mime=byext[1])
        elif mg:
            res.update(kind=mg[0], mime=mg[1])
        elif ext in ("rtf",):
            res.update(kind="text", mime=byext[1])
        else:
            res.update(kind="binary", mime="application/octet-stream")
    elif byext and byext[0] == "image" and ext in ("svg", "svgz"):
        res.update(kind="image", mime=byext[1])
    elif byext and byext[0] in ("office", "ebook", "font") and (not mg or mg[0] in ("archive", byext[0], "binary")):
        res.update(kind=byext[0], mime=byext[1])
    elif mg and not (byext and byext[0] == mg[0]):
        # content wins over a wrong or missing extension, except zip-based formats whose extension is more specific
        if mg[0] == "archive" and byext and byext[0] in ("office", "ebook", "archive"):
            res.update(kind=byext[0], mime=byext[1])
        else:
            res.update(kind=mg[0], mime=mg[1])
    elif byext:
        res.update(kind=byext[0], mime=byext[1])
    elif mg:
        res.update(kind=mg[0], mime=mg[1])
    elif texty:
        k, mime = _text_kind(head, name, ext)
        res.update(kind=k, mime=mime)
    res["ext"] = ext
    return res

def _magic(head):
    for off, sig, k, mime in MAGIC:
        if head[off:off + len(sig)] == sig:
            if sig == b"BM" and len(head) > 14 and not (head[6:10] == b"\x00\x00\x00\x00"):
                continue
            if sig == b"MZ" or sig == b"true":
                pass
            return (k, mime)
    return _sniff_riff_iso(head)

# The pretty label users see in the info line
LABEL = {"folder": "Folder", "text": "Text", "code": "Source code", "markdown": "Markdown document", "json": "JSON", "csv": "Table", "image": "Image",
         "pdf": "PDF document", "audio": "Audio", "video": "Video", "archive": "Archive", "font": "Font", "office": "Document", "ebook": "Book",
         "binary": "File", "special": "Special file", "missing": "Missing"}

# GtkSourceView language ids by extension (what the highlight engine calls them); used only when the guess by name fails
LANG = {"py": "python3", "js": "js", "mjs": "js", "cjs": "js", "ts": "typescript", "tsx": "typescript", "jsx": "js", "sh": "sh", "bash": "sh", "zsh": "sh",
        "c": "c", "h": "c", "cpp": "cpp", "cc": "cpp", "hpp": "cpp", "rs": "rust", "go": "go", "java": "java", "rb": "ruby", "php": "php", "lua": "lua",
        "css": "css", "html": "html", "htm": "html", "xml": "xml", "yaml": "yaml", "yml": "yaml", "toml": "toml", "sql": "sql", "json": "json",
        "md": "markdown", "diff": "diff", "patch": "diff", "ini": "ini", "conf": "ini", "desktop": "desktop", "tex": "latex", "cs": "c-sharp", "kt": "kotlin",
        "swift": "swift", "pl": "perl", "hs": "haskell", "dockerfile": "dockerfile", "makefile": "makefile", "mk": "makefile", "make": "makefile", "cmake": "cmake"}

def human_size(n):
    for unit, div in (("GB", 1e9), ("MB", 1e6), ("kB", 1e3)):
        if n >= div:
            v = n / div
            return ("%.1f %s" % (v, unit)).replace(".0 ", " ")
    return "%d bytes" % n
