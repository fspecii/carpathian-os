"""Local calendar events: .ics reading (with simple recurrence), quick-entry parsing and writing, no network and no daemons.

Sources: ~/.local/share/carpatic/calendar/*.ics (written by the quick entry), ~/.local/share/carpatic/widgets/calendar.ics (the widgets
agent's file), and khal/vdirsyncer folders (~/.calendars/**/*.ics) when present."""
import datetime as dt
import glob, os, re, uuid

DATA = os.environ.get("CARPATIC_DATA", os.path.expanduser("~/.local/share/carpatic"))
PALETTE = ("accent", "info", "ember", "danger", "success")


def sources(data=None):
    d = data or DATA
    out = sorted(glob.glob(os.path.join(d, "calendar", "*.ics"))) + [os.path.join(d, "widgets", "calendar.ics")]
    out += sorted(glob.glob(os.path.expanduser("~/.calendars/*/*.ics"))) + sorted(glob.glob(os.path.expanduser("~/.calendars/*/*/*.ics")))
    return [p for p in out if os.path.isfile(p)]


class Event:
    __slots__ = ("title", "day", "start", "end", "all_day", "where", "color", "uid", "path")

    def __init__(self, title, day, start=None, end=None, all_day=False, where="", color=0, uid="", path=""):
        self.title, self.day, self.start, self.end, self.all_day, self.where, self.color, self.uid, self.path = title, day, start, end, all_day, where, color, uid, path

    def time_text(self, fmt24=True):
        if self.all_day or self.start is None: return "All day"
        f = (lambda t: t.strftime("%H:%M")) if fmt24 else (lambda t: t.strftime("%-I:%M %p").lower())
        return f(self.start) + (f" – {f(self.end)}" if self.end else "")

    def __repr__(self): return f"Event({self.title!r}, {self.day}, {self.start})"


def _unfold(text): return re.sub(r"\r?\n[ \t]", "", text).replace("\r", "")


def _unescape(s): return s.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _parse_dt(val, params=""):
    """-> (date, time|None, all_day). UTC 'Z' times are converted to local time; floating times are taken as local."""
    val = val.strip()
    if re.search(r"(?:^|;)VALUE=DATE(?:;|$)", params.upper()) or re.fullmatch(r"\d{8}", val):
        if not re.fullmatch(r"\d{8}", val): return None
        return dt.datetime.strptime(val, "%Y%m%d").date(), None, True
    m = re.fullmatch(r"(\d{8})T(\d{6}|\d{4})(Z?)", val)
    if not m: return None
    s = m.group(2) + ("00" if len(m.group(2)) == 4 else "")
    d = dt.datetime.strptime(m.group(1) + s, "%Y%m%d%H%M%S")
    if m.group(3) == "Z":
        d = d.replace(tzinfo=dt.timezone.utc).astimezone().replace(tzinfo=None)
    return d.date(), d.time(), False


_DAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def _expand(base, rrule, lo, hi, exdates):
    """Occurrence dates of a recurring event within [lo, hi]. Supports FREQ DAILY/WEEKLY/MONTHLY/YEARLY, INTERVAL, COUNT, UNTIL, BYDAY (weekly)."""
    rp = dict(p.split("=", 1) for p in rrule.split(";") if "=" in p)
    freq = rp.get("FREQ", ""); interval = max(1, int(rp.get("INTERVAL", "1") or 1)); count = int(rp["COUNT"]) if rp.get("COUNT", "").isdigit() else None
    until = None
    if rp.get("UNTIL"):
        r = _parse_dt(rp["UNTIL"]); until = r[0] if r else None
    byday = [_DAYS[x[-2:]] for x in rp.get("BYDAY", "").split(",") if x[-2:] in _DAYS]
    out, n, cur = [], 0, base
    for _ in range(4000):
        cands = [cur]
        if freq == "WEEKLY" and byday:
            monday = cur - dt.timedelta(days=cur.weekday())
            cands = [monday + dt.timedelta(days=d) for d in sorted(byday)]
        for c in cands:
            if c < base: continue
            if until and c > until: return out
            n += 1
            if count and n > count: return out
            if c > hi: return out
            if c >= lo and c not in exdates: out.append(c)
        if freq == "DAILY": cur += dt.timedelta(days=interval)
        elif freq == "WEEKLY": cur += dt.timedelta(weeks=interval)
        elif freq == "MONTHLY":
            y, m = divmod(cur.year * 12 + cur.month - 1 + interval, 12)
            try: cur = cur.replace(year=y, month=m + 1)
            except ValueError: cur = cur.replace(year=y, month=m + 1, day=28)
        elif freq == "YEARLY":
            try: cur = cur.replace(year=cur.year + interval)
            except ValueError: cur = cur.replace(year=cur.year + interval, day=28)
        else: return out
        if cur > hi + dt.timedelta(days=370) and not byday: return out
    return out


def _parse_event(blk, lo, hi, color, path):
    out = []
    props = {}
    for line in blk.strip().split("\n"):
        if ":" not in line: continue
        k, v = line.split(":", 1)
        name, _, params = k.partition(";")
        props.setdefault(name.upper(), []).append((params, v))
    if "DTSTART" not in props: raise ValueError("missing start date")
    s = _parse_dt(props["DTSTART"][0][1], props["DTSTART"][0][0])
    if not s: raise ValueError("invalid start date")
    day, st, all_day = s
    en = _parse_dt(props["DTEND"][0][1], props["DTEND"][0][0]) if "DTEND" in props else None
    if "DTEND" in props and not en: raise ValueError("invalid end date")
    title = _unescape(props.get("SUMMARY", [("", "(no title)")])[0][1]).strip() or "(no title)"
    where = _unescape(props.get("LOCATION", [("", "")])[0][1]).strip()
    uid = props.get("UID", [("", "")])[0][1]
    span = 0
    if en and en[0] > day: span = (en[0] - day).days - (1 if all_day else 0)
    en_t = en[1] if en and en[0] == day else None
    ex = set()
    for p, v in props.get("EXDATE", []):
        for x in v.split(","):
            r = _parse_dt(x, p)
            if not r: raise ValueError("invalid exclusion date")
            ex.add(r[0])
    dates = _expand(day, props["RRULE"][0][1], lo - dt.timedelta(days=span), hi, ex) if "RRULE" in props else [day]
    for d0 in dates:
        for k in range(max(0, (lo - d0).days), min(span, (hi - d0).days) + 1):
            d = d0 + dt.timedelta(days=k)
            if lo <= d <= hi: out.append(Event(title, d, st if k == 0 else None, en_t if k == span else None, all_day or k > 0, where, color, uid, path))
    return out


def parse_ics(text, lo, hi, color=0, path="", issues=None):
    """Read each record independently so damaged imports preserve valid neighbors."""
    out = []
    for blk in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", _unfold(text), re.S):
        try:
            out.extend(_parse_event(blk, lo, hi, color, path))
        except (ValueError, OverflowError):
            if issues is not None: issues.append("A calendar event could not be read")
    return out

def load_events(lo, hi, data=None, issues=None):
    out = []
    for i, p in enumerate(sources(data)):
        try:
            with open(p, "rb") as f: raw = f.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                if issues is not None: issues.append("A calendar file is too large to read")
                continue
            out += parse_ics(raw.decode("utf-8", "replace"), lo, hi, i % len(PALETTE), p, issues)
        except OSError:
            if issues is not None: issues.append("A calendar file could not be opened")
            continue
    out.sort(key=lambda e: (e.day, not e.all_day, e.start or dt.time(0)))
    return out


# ----------------------------------------------------------------------------- quick entry
_WD = {"mon": 0, "monday": 0, "tue": 1, "tues": 1, "tuesday": 1, "wed": 2, "wednesday": 2, "thu": 3, "thur": 3, "thurs": 3, "thursday": 3,
       "fri": 4, "friday": 4, "sat": 5, "saturday": 5, "sun": 6, "sunday": 6}


def parse_quick(text, today=None):
    """'Lunch with Ana tomorrow 13:00' -> (title, date, start_time|None, end_time|None). Understands today/tomorrow, weekday names, ISO dates,
    'oct 20' / '20 oct', times like 13:00, 9am, 9:30pm, and 'from 9 to 10'. The remaining words are the title."""
    today = today or dt.date.today()
    s = " " + text.strip() + " "
    day = None; st = en = None
    m = re.search(r"\s(\d{4})-(\d{2})-(\d{2})\s", s)
    if m:
        try: day = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))); s = s.replace(m.group(0), " ", 1)
        except ValueError: pass
    if day is None:
        for w, off in (("today", 0), ("tomorrow", 1), ("tmrw", 1), ("day after tomorrow", 2)):
            m = re.search(r"\s" + w + r"\s", s, re.I)
            if m: day = today + dt.timedelta(days=off); s = s.replace(m.group(0), " ", 1); break
    if day is None:
        m = re.search(r"\s(?:next\s+|on\s+)?(" + "|".join(sorted(_WD, key=len, reverse=True)) + r")\s", s, re.I)
        if m:
            delta = (_WD[m.group(1).lower()] - today.weekday()) % 7
            if delta == 0 or "next" in m.group(0).lower(): delta = delta or 7
            day = today + dt.timedelta(days=delta); s = s.replace(m.group(0), " ", 1)
    if day is None:
        mon = "jan feb mar apr may jun jul aug sep oct nov dec".split()
        names = "|".join(mon)
        m = re.search(r"\s(" + names + r")[a-z]*\.?\s+(\d{1,2})\s", s, re.I)
        m2 = re.search(r"\s(\d{1,2})\s+(" + names + r")[a-z]*\.?\s", s, re.I)
        mm = m or m2
        if mm:
            mo = mon.index((m.group(1) if m else m2.group(2)).lower()) + 1; dd = int(m.group(2) if m else m2.group(1))
            try:
                cand = dt.date(today.year, mo, dd)
                if cand < today: cand = dt.date(today.year + 1, mo, dd)
                day = cand; s = s.replace(mm.group(0), " ", 1)
            except ValueError: pass
    def clock(h, mi, ap):
        h = int(h); mi = int(mi or 0)
        if ap:
            ap = ap.lower()
            if ap == "pm" and h < 12: h += 12
            if ap == "am" and h == 12: h = 0
        return dt.time(h, mi) if 0 <= h < 24 and 0 <= mi < 60 else None
    tre = r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?"
    m = re.search(r"\s(?:from\s+)?" + tre + r"\s*(?:-|to|–)\s*" + tre + r"\s", s, re.I)
    if m and (m.group(2) or m.group(3) or m.group(5) or m.group(6) or ":" in m.group(0)):
        a, b = clock(m.group(1), m.group(2), m.group(3) or m.group(6)), clock(m.group(4), m.group(5), m.group(6))
        if a and b: st, en = a, b; s = s.replace(m.group(0), " ", 1)
    if st is None:
        m = re.search(r"\s(?:at\s+)?(\d{1,2}):(\d{2})\s*(am|pm)?\s", s, re.I) or re.search(r"\s(?:at\s+)?(\d{1,2})()\s*(am|pm)\s", s, re.I) or re.search(r"\sat\s+(\d{1,2})()()\s", s, re.I)
        if m:
            t = clock(m.group(1), m.group(2), m.group(3))
            if t: st = t; s = s.replace(m.group(0), " ", 1)
    title = re.sub(r"\s+", " ", s).strip(" -,;")
    title = re.sub(r"\b(on|at|from)$", "", title).strip()
    if st and en is None: en = (dt.datetime.combine(dt.date.today(), st) + dt.timedelta(hours=1)).time() if st.hour < 23 else None
    return title, day or today, st, en


def write_event(title, day, start=None, end=None, data=None):
    """Writes ~/.local/share/carpatic/calendar/<uid>.ics (atomic) and returns the path."""
    d = os.path.join(data or DATA, "calendar"); os.makedirs(d, exist_ok=True)
    uid = uuid.uuid4().hex
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Carpathian OS//panel//EN", "BEGIN:VEVENT", f"UID:{uid}@carpatic",
             "DTSTAMP:" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")]
    esc = title.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;")
    if start is None:
        lines += [f"DTSTART;VALUE=DATE:{day:%Y%m%d}", f"DTEND;VALUE=DATE:{day + dt.timedelta(days=1):%Y%m%d}"]
    else:
        lines.append(f"DTSTART:{day:%Y%m%d}T{start:%H%M%S}")
        if end: lines.append(f"DTEND:{day:%Y%m%d}T{end:%H%M%S}")
    lines += [f"SUMMARY:{esc}", "END:VEVENT", "END:VCALENDAR"]
    p = os.path.join(d, uid + ".ics"); tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f: f.write("\r\n".join(lines) + "\r\n")
    os.replace(tmp, p)
    return p


def delete_event(path, uid, data=None):
    """Remove an event the quick entry wrote (only files inside our own calendar dir are ever deleted)."""
    d = os.path.realpath(os.path.join(data or DATA, "calendar"))
    if os.path.dirname(os.path.realpath(path)) == d:
        try: os.unlink(path); return True
        except OSError: return False
    return False
