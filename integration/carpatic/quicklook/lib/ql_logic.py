"""Carpathian Quick Look: the parts that need no GTK. Markdown parser, CSV/JSON readers, archive listing, EXIF, Office text,
hex dump, folder summary, Unix permission strings. Every function reads a bounded amount of data and never executes anything."""
import os, re, io, csv, json, time, stat, zipfile, tarfile, struct, hashlib, pwd, grp, xml.etree.ElementTree as ET
from datetime import datetime

MAX_TEXT = 512 * 1024          # bytes read for text/code (the rest is cut, with a note)
MAX_ROWS = 400
MAX_ARCHIVE_ENTRIES = 1500

def read_text(path, limit=MAX_TEXT):
    """Return (text, truncated, encoding). Partial read for huge files; binary garbage is replaced, never raises."""
    with open(path, "rb") as f:
        raw = f.read(limit + 1)
    cut = len(raw) > limit
    raw = raw[:limit]
    enc = "utf-8"
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        enc = "utf-16"
    elif raw[:3] == b"\xef\xbb\xbf":
        enc = "utf-8-sig"
    try:
        txt = raw.decode(enc)
    except UnicodeDecodeError as e:
        if cut and e.start >= len(raw) - 3:
            txt = raw[:e.start].decode(enc, "replace")
        else:
            txt, enc = raw.decode("utf-8", "replace"), "utf-8 (some characters could not be read)"
    return txt.replace("\r\n", "\n").replace("\r", "\n"), cut, enc

# ---------------------------------------------------------------- Markdown
_inline_re = re.compile(r"(\*\*\*(.+?)\*\*\*|\*\*(.+?)\*\*|__(.+?)__|\*(?!\s)(.+?)(?<!\s)\*|(?<![\w])_(?!\s)(.+?)(?<!\s)_(?![\w])|`([^`]+)`|~~(.+?)~~|!\[([^\]]*)\]\([^)]*\)|\[([^\]]+)\]\(([^)\s]+)[^)]*\)|<(https?://[^>]+)>)")

def inline(text):
    """Markdown inline text -> list of (string, frozenset(flags)); flags: b i c s a. Links keep their target in flag 'a:<url>'."""
    out = []
    def emit(s, fl=()):
        if s: out.append((s, frozenset(fl)))
    def walk(s, fl):
        pos = 0
        for m in _inline_re.finditer(s):
            emit(s[pos:m.start()], fl)
            pos = m.end()
            g = m.groups()
            if g[1]: walk(g[1], fl | {"b", "i"})
            elif g[2] or g[3]: walk(g[2] or g[3], fl | {"b"})
            elif g[4] or g[5]: walk(g[4] or g[5], fl | {"i"})
            elif g[6]: emit(g[6], fl | {"c"})
            elif g[7]: walk(g[7], fl | {"s"})
            elif g[8] is not None: emit("[image: %s]" % g[8] if g[8] else "[image]", fl | {"i"})
            elif g[9]: walk(g[9], fl | {"a", "a:" + g[10]})
            elif g[11]: emit(g[11], fl | {"a", "a:" + g[11]})
        emit(s[pos:], fl)
    walk(text.replace("\\*", "\u0001").replace("\\_", "\u0002").replace("\\`", "\u0003"), frozenset())
    fix = lambda s: s.replace("\u0001", "*").replace("\u0002", "_").replace("\u0003", "`")
    return [(fix(s), f) for s, f in out]

def markdown(text):
    """Tiny, forgiving Markdown reader -> list of blocks. Enough for READMEs, notes and docs; not a full CommonMark."""
    blocks, lines, i = [], text.split("\n"), 0
    para = []
    def flush():
        nonlocal para
        if para:
            blocks.append(("p", inline(" ".join(s.strip() for s in para))))
            para = []
    if lines and lines[0].strip() == "---":                      # YAML front matter
        for j in range(1, min(len(lines), 60)):
            if lines[j].strip() in ("---", "..."):
                blocks.append(("front", "\n".join(lines[1:j])))
                i = j + 1
                break
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        m = re.match(r"^(```+|~~~+)\s*([\w+-]*)", s)
        if m:
            flush()
            fence, lang, buf = m.group(1), m.group(2), []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(fence[:3]):
                buf.append(lines[i]); i += 1
            blocks.append(("code", lang, "\n".join(buf)))
        elif re.match(r"^#{1,6}\s", s):
            flush()
            lvl = len(s) - len(s.lstrip("#"))
            blocks.append(("h", lvl, inline(s[lvl:].strip().rstrip("#").strip())))
        elif i + 1 < len(lines) and s and re.match(r"^(=+|-+)\s*$", lines[i + 1].strip()) and not para and not s.startswith(("-", "*", ">", "|")):
            flush()
            blocks.append(("h", 1 if lines[i + 1].strip()[0] == "=" else 2, inline(s)))
            i += 1
        elif re.match(r"^([-*_])(\s*\1){2,}$", s):
            flush(); blocks.append(("hr",))
        elif s.startswith(">"):
            flush()
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip()[1:].strip()); i += 1
            i -= 1
            blocks.append(("quote", inline(" ".join(buf))))
        elif "|" in s and i + 1 < len(lines) and re.match(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$", lines[i + 1].strip()):
            flush()
            rows = []
            while i < len(lines) and "|" in lines[i]:
                if not re.match(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$", lines[i].strip()):
                    rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            i -= 1
            blocks.append(("table", rows))
        else:
            lm = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(\[[ xX]\]\s+)?(.*)$", ln)
            if lm:
                flush()
                depth = len(lm.group(1).replace("\t", "    ")) // 2
                mark = "•" if lm.group(2) in "-*+" else lm.group(2)
                if lm.group(3):
                    mark = "☑" if lm.group(3).strip()[1] in "xX" else "☐"
                blocks.append(("li", depth, mark, inline(lm.group(4))))
            elif not s:
                flush()
            else:
                para.append(s)
        i += 1
    flush()
    return blocks

# ---------------------------------------------------------------- JSON and CSV
def pretty_json(text, limit=1_000_000):
    """Returns (pretty_text, note). Falls back to the original text when it is not valid JSON (e.g. JSON with comments, NDJSON)."""
    if len(text) > limit:
        return text, "Large file: showing it as it is, without reformatting."
    try:
        return json.dumps(json.loads(text), indent=2, ensure_ascii=False), ""
    except ValueError as e:
        lines = [l for l in text.split("\n") if l.strip()]
        if len(lines) > 1:
            try:
                return "\n".join(json.dumps(json.loads(l), ensure_ascii=False) for l in lines), "One JSON value per line."
            except ValueError:
                pass
        return text, "This is not strictly valid JSON (%s). Showing it as written." % str(e).split(":")[0].lower()

def read_csv(text, delimiter=None):
    sample = text[:8192]
    if not delimiter:
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = "\t" if sample.count("\t") > sample.count(",") else ","
    rows = []
    csv.field_size_limit(1 << 20)
    try:
        for r in csv.reader(io.StringIO(text), delimiter=delimiter):
            rows.append(r)
            if len(rows) > MAX_ROWS: break
    except csv.Error:
        pass
    return rows, delimiter

# ---------------------------------------------------------------- Archives
def archive_listing(path, mime="", limit=MAX_ARCHIVE_ENTRIES):
    """Return dict(entries=[(name, size, is_dir)], total, count, note). Listing only, nothing is extracted. Falls back to bsdtar/7z when installed."""
    entries, total, note, count = [], 0, "", 0
    def add(name, size, isdir):
        nonlocal total, count
        count += 1; total += size or 0
        if len(entries) < limit: entries.append((name, size or 0, isdir))
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                infos = z.infolist()
                for zi in infos[:200000]:
                    add(zi.filename, zi.file_size, zi.is_dir())
                if len(infos) > 200000: note = "Very large archive: listing is partial."
                if any(zi.flag_bits & 1 for zi in infos[:50]): note = "This archive is password protected."
        elif tarfile.is_tarfile(path):
            with tarfile.open(path) as t:
                for n, ti in enumerate(t):
                    if n >= 100000: note = "Very large archive: listing is partial."; break
                    add(ti.name, ti.size, ti.isdir())
        else:
            raise ValueError("other")
    except Exception:
        out = _external_list(path)
        if out is None:
            return {"entries": [], "total": 0, "count": 0, "note": "Quick Look cannot list this kind of archive here. Open it with an archive manager to see inside."}
        for name, size, isdir in out: add(name, size, isdir)
    return {"entries": entries, "total": total, "count": count, "note": note}

def _external_list(path):
    import shutil, subprocess
    for tool, args in (("bsdtar", ["-tvf"]), ("7z", ["l", "-ba"])):
        exe = shutil.which(tool)
        if not exe: continue
        try:
            r = subprocess.run([exe] + args + [path], capture_output=True, text=True, timeout=8, stdin=subprocess.DEVNULL)
        except Exception:
            continue
        if r.returncode != 0 or not r.stdout.strip(): continue
        out = []
        for l in r.stdout.split("\n")[:5000]:
            if not l.strip(): continue
            if tool == "bsdtar":
                p = l.split(None, 8)
                if len(p) >= 9: out.append((p[8], int(p[4]) if p[4].isdigit() else 0, l.startswith("d")))
            else:
                p = l.split(None, 5)
                if len(p) >= 6: out.append((p[5], int(p[3]) if p[3].isdigit() else 0, p[2].startswith("D")))
        if out: return out
    return None

# ---------------------------------------------------------------- Office / ebook documents
_NS_STRIP = re.compile(r"\{[^}]*\}")

def _xml_text(data, limit=1800, paragraph_tags=("p", "h", "list-item")):
    out, cur = [], []
    try:
        for ev, el in ET.iterparse(io.BytesIO(data[:6_000_000]), events=("end",)):
            tag = _NS_STRIP.sub("", el.tag)
            if tag in ("t", "text") and el.text: cur.append(el.text)
            elif tag == "p" or tag == "h":
                if el.text and tag in ("p", "h") and not cur: cur.append(el.text)
                s = "".join(cur).strip()
                if s: out.append(s)
                cur = []
                el.clear()
            if sum(len(x) for x in out) > limit: break
    except ET.ParseError:
        pass
    return "\n".join(out)[:limit]

def office_info(path):
    """Title, author, a text excerpt and an embedded thumbnail (bytes) from docx/xlsx/pptx/odt/ods/odp/epub. Never launches an office suite."""
    info = {"title": "", "author": "", "excerpt": "", "thumb": None, "pages": None, "sheets": [], "slides": None, "created": "", "modified": ""}
    try:
        z = zipfile.ZipFile(path)
    except Exception:
        return info
    with z:
        names = z.namelist()
        def rd(n, cap=6_000_000):
            try:
                zi = z.getinfo(n)
                if zi.file_size > cap * 3: return b""
                return z.read(n)[:cap]
            except Exception:
                return b""
        core = rd("docProps/core.xml")
        if core:
            try:
                for el in ET.fromstring(core):
                    t = _NS_STRIP.sub("", el.tag)
                    if t == "title": info["title"] = el.text or ""
                    elif t == "creator": info["author"] = el.text or ""
                    elif t == "created": info["created"] = el.text or ""
                    elif t == "modified": info["modified"] = el.text or ""
            except ET.ParseError: pass
        meta = rd("meta.xml")
        if meta:
            try:
                for el in ET.fromstring(meta).iter():
                    t = _NS_STRIP.sub("", el.tag)
                    if t == "title" and el.text: info["title"] = el.text
                    elif t == "initial-creator" and el.text: info["author"] = el.text
                    elif t == "creation-date" and el.text: info["created"] = el.text
            except ET.ParseError: pass
        for tn in ("Thumbnails/thumbnail.png", "docProps/thumbnail.jpeg", "docProps/thumbnail.png", "docProps/thumbnail.jpg"):
            if tn in names:
                info["thumb"] = rd(tn, 2_000_000); break
        if "word/document.xml" in names:
            info["excerpt"] = _xml_text(rd("word/document.xml"))
        elif "content.xml" in names:
            info["excerpt"] = _xml_text(rd("content.xml"))
        slides = sorted(n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n))
        if slides:
            info["slides"] = len(slides)
            info["excerpt"] = _xml_text(rd(slides[0]))
        if "xl/workbook.xml" in names:
            try:
                info["sheets"] = [e.get("name") for e in ET.fromstring(rd("xl/workbook.xml")).iter() if _NS_STRIP.sub("", e.tag) == "sheet"][:20]
            except ET.ParseError: pass
            shared = rd("xl/sharedStrings.xml")
            if shared: info["excerpt"] = "\n".join(re.findall(r"<t[^>]*>([^<]{1,80})</t>", shared.decode("utf-8", "replace"))[:25])
        if "META-INF/container.xml" in names or any(n.endswith(".opf") for n in names):
            for n in names:
                if n.endswith(".opf"):
                    try:
                        for el in ET.fromstring(rd(n)).iter():
                            t = _NS_STRIP.sub("", el.tag)
                            if t == "title" and el.text and not info["title"]: info["title"] = el.text
                            elif t == "creator" and el.text and not info["author"]: info["author"] = el.text
                    except ET.ParseError: pass
                    break
            if not info["excerpt"]:
                for n in names:
                    if n.lower().endswith((".xhtml", ".html", ".htm")):
                        raw = rd(n, 400_000).decode("utf-8", "replace")
                        txt = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
                        txt = re.sub(r"<[^>]+>", " ", txt)
                        txt = re.sub(r"\s+", " ", txt).strip()
                        if len(txt) > 200:
                            info["excerpt"] = txt[:1500]; break
            if not info["thumb"]:
                for n in names:
                    if re.search(r"cover[^/]*\.(jpe?g|png)$", n, re.I):
                        info["thumb"] = rd(n, 3_000_000); break
        if path.lower().endswith(".cbz") and not info["thumb"]:
            imgs = sorted(n for n in names if n.lower().endswith((".jpg", ".jpeg", ".png", ".webp")))
            if imgs: info["thumb"] = rd(imgs[0], 6_000_000)
    return info

# ---------------------------------------------------------------- EXIF (JPEG)
_EXIF_TAGS = {0x010F: "Camera maker", 0x0110: "Camera", 0x0131: "Software", 0x0132: "Taken", 0x829A: "Exposure", 0x829D: "Aperture", 0x8827: "ISO",
              0x9003: "Taken", 0x920A: "Focal length", 0xA434: "Lens", 0x0112: "Orientation"}

def exif(path):
    """Small, bounds-checked EXIF reader for JPEG (and HEIC-less) files. Returns dict label -> text; {} when absent."""
    try:
        with open(path, "rb") as f:
            d = f.read(262144)
    except OSError:
        return {}
    if d[:2] != b"\xff\xd8": return {}
    i, out = 2, {}
    while i + 4 < len(d):
        if d[i] != 0xFF: break
        marker, ln = d[i + 1], struct.unpack(">H", d[i + 2:i + 4])[0]
        if marker == 0xE1 and d[i + 4:i + 10] == b"Exif\x00\x00":
            t = d[i + 10:i + 2 + ln]
            try: _parse_tiff(t, out)
            except Exception: pass
            break
        if marker == 0xDA: break
        i += 2 + ln
    return out

def _parse_tiff(t, out):
    e = "<" if t[:2] == b"II" else ">"
    u16 = lambda o: struct.unpack(e + "H", t[o:o + 2])[0]
    u32 = lambda o: struct.unpack(e + "I", t[o:o + 4])[0]
    sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}
    def ifd(off, depth=0):
        if off + 2 > len(t) or depth > 2: return
        n = u16(off)
        for k in range(min(n, 200)):
            eo = off + 2 + k * 12
            if eo + 12 > len(t): return
            tag, typ, cnt = u16(eo), u16(eo + 2), u32(eo + 4)
            sz = sizes.get(typ, 1) * cnt
            vo = eo + 8 if sz <= 4 else u32(eo + 8)
            if tag in (0x8769,) and typ == 4: ifd(u32(eo + 8), depth + 1); continue
            name = _EXIF_TAGS.get(tag)
            if not name or vo + sz > len(t): continue
            if typ == 2: v = t[vo:vo + cnt].split(b"\x00")[0].decode("latin-1").strip()
            elif typ == 3: v = str(u16(vo))
            elif typ == 5:
                num, den = u32(vo), u32(vo + 4)
                if not den: continue
                if tag == 0x829A: v = "1/%d s" % round(den / num) if num and num < den else "%g s" % (num / den)
                elif tag == 0x829D: v = "f/%g" % round(num / den, 1)
                elif tag == 0x920A: v = "%g mm" % round(num / den, 1)
                else: v = "%g" % (num / den)
            else: continue
            if v and (name not in out or name != "Taken"): out[name] = v
    ifd(u32(4))
    if "Camera maker" in out and "Camera" in out and out["Camera"].lower().startswith(out["Camera maker"].lower().split()[0]):
        out.pop("Camera maker")
    out.pop("Orientation", None)

# ---------------------------------------------------------------- generic file facts
def perm_string(mode):
    return stat.filemode(mode)

def owner_of(st):
    try: u = pwd.getpwuid(st.st_uid).pw_name
    except KeyError: u = str(st.st_uid)
    try: g = grp.getgrgid(st.st_gid).gr_name
    except KeyError: g = str(st.st_gid)
    return u, g

def when(ts):
    if not ts: return ""
    d = datetime.fromtimestamp(ts)
    now = datetime.now()
    if d.date() == now.date(): return "Today, " + d.strftime("%H:%M")
    if (now.date() - d.date()).days == 1: return "Yesterday, " + d.strftime("%H:%M")
    return d.strftime("%-d %b %Y, %H:%M")

def hexdump(path, n=160):
    try:
        with open(path, "rb") as f: b = f.read(n)
    except OSError: return ""
    lines = []
    for o in range(0, len(b), 16):
        c = b[o:o + 16]
        lines.append("%08x  %-47s  %s" % (o, " ".join("%02x" % x for x in c), "".join(chr(x) if 32 <= x < 127 else "." for x in c)))
    return "\n".join(lines)

def sha256_file(path, progress=None, cancel=lambda: False, chunk=1 << 20):
    h, done = hashlib.sha256(), 0
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b: break
            h.update(b); done += len(b)
            if progress: progress(done / max(size, 1))
            if cancel(): return None
    return h.hexdigest()

def folder_summary(path, budget=0.35, max_entries=6000):
    """Quick look at a folder: direct children (sorted folders first) plus recursive counts, bounded in time and entries."""
    t0 = time.monotonic()
    try:
        with os.scandir(path) as it:
            kids = []
            for n, de in enumerate(it):
                if n > 20000: break
                try:
                    isd = de.is_dir(follow_symlinks=False)
                    sz = 0 if isd else de.stat(follow_symlinks=False).st_size
                except OSError:
                    isd, sz = False, 0
                kids.append((de.name, isd, sz))
    except PermissionError:
        return {"error": "You do not have permission to look inside this folder."}
    except OSError as e:
        return {"error": e.strerror or "This folder cannot be read."}
    kids.sort(key=lambda k: (not k[1], k[0].lower()))
    files, dirs, total, seen, partial = 0, 0, 0, 0, False
    stack = [path]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for de in it:
                    seen += 1
                    if seen > max_entries or time.monotonic() - t0 > budget:
                        partial = True; stack = []; break
                    try:
                        if de.is_dir(follow_symlinks=False):
                            dirs += 1; stack.append(de.path)
                        else:
                            files += 1; total += de.stat(follow_symlinks=False).st_size
                    except OSError: pass
        except OSError: pass
    return {"children": kids, "files": files, "dirs": dirs, "size": total, "partial": partial}
