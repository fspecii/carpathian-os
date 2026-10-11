"""Strict editing of calendars created by this panel; imported calendars stay read-only."""
import contextlib
import datetime as dt
import fcntl
import hashlib
import os
import re
import stat
import uuid

from . import events

LIMIT = 64 * 1024


class CalendarError(Exception):
    """The selected local event cannot safely be changed."""


class CalendarCommitUncertain(CalendarError):
    """The mutation happened, but directory durability could not be confirmed."""
    def __init__(self, operation, snapshot=None):
        super().__init__("Persistence after a restart could not be confirmed")
        self.operation = operation
        self.snapshot = snapshot


def _regular(fd):
    s = os.fstat(fd)
    if not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid() or s.st_nlink != 1 or s.st_mode & 0o022:
        raise CalendarError("Calendar file is not a private regular file")
    return s


@contextlib.contextmanager
def _directory(path, uid, data):
    directory = os.path.abspath(os.path.join(data or events.DATA, "calendar"))
    if not isinstance(path, str) or not os.path.isabs(path) or path != os.path.join(directory, os.path.basename(path)):
        raise CalendarError("Event is outside the local calendar")
    name = os.path.basename(path)
    if not re.fullmatch(r"[0-9a-f]{32}\.ics", name) or uid != name[:-4] + "@carpatic":
        raise CalendarError("Event identity does not match its file")
    dfd = lock = None
    try:
        dfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        s = os.fstat(dfd)
        if s.st_uid != os.getuid() or s.st_mode & 0o022:
            raise CalendarError("Calendar directory is not private")
        lock = os.open(".local-events.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=dfd)
        ls = _regular(lock)
        if stat.S_IMODE(ls.st_mode) != 0o600:
            raise CalendarError("Calendar lock is not private")
        fcntl.flock(lock, fcntl.LOCK_EX)
        # An unlinked/replaced lock must never coordinate mutations.
        fresh = os.stat(".local-events.lock", dir_fd=dfd, follow_symlinks=False)
        if (fresh.st_dev, fresh.st_ino) != (ls.st_dev, ls.st_ino):
            raise CalendarError("Calendar lock changed")
        yield dfd, name
    except (OSError, ValueError, UnicodeError, OverflowError) as exc:
        raise CalendarError("Local calendar could not be accessed") from exc
    finally:
        if lock is not None: os.close(lock)
        if dfd is not None: os.close(dfd)


def _read(dfd, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=dfd)
    try:
        s = _regular(fd)
        if s.st_size > LIMIT: raise CalendarError("Calendar file is too large")
        raw = b""
        while len(raw) <= LIMIT:
            part = os.read(fd, LIMIT + 1 - len(raw))
            if not part: break
            raw += part
        if len(raw) > LIMIT: raise CalendarError("Calendar file is too large")
        after = os.fstat(fd)
        if (s.st_size, s.st_mtime_ns, s.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise CalendarError("Event changed while reading")
        return raw, (s.st_dev, s.st_ino)
    finally: os.close(fd)


def _text(value):
    out = []; i = 0
    while i < len(value):
        c = value[i]
        if c == "\\":
            i += 1
            if i >= len(value) or value[i] not in "nN\\,;": raise CalendarError("Invalid calendar text")
            c = "\n" if value[i] in "nN" else value[i]
        elif c in ",;": raise CalendarError("Unescaped calendar text")
        out.append(c); i += 1
    return "".join(out)


def validate_event(title, day, start=None, end=None):
    if not isinstance(title, str) or not title.strip() or len(title) > 2000 or any(ord(c) < 32 and c not in "\r\n\t" for c in title):
        raise CalendarError("Enter a title of at most 2000 characters")
    if type(day) is not dt.date: raise CalendarError("Invalid event date")
    if start is None:
        if end is not None or day == dt.date.max: raise CalendarError("Invalid all-day event")
    else:
        for t in (start, end):
            if t is not None and (type(t) is not dt.time or t.tzinfo is not None or t.microsecond or t.fold):
                raise CalendarError("Use a local time with whole seconds")
        if end is not None and end <= start: raise CalendarError("End must be after start on the same day")


def _parse(raw, path, uid):
    text = raw.decode("utf-8")
    if "\x00" in text: raise CalendarError("Invalid calendar text")
    text = text.replace("\r\n", "\n")
    if "\r" in text: raise CalendarError("Invalid line endings")
    lines = re.sub(r"\n[ \t]", "", text).removesuffix("\n").split("\n")
    if lines[:3] not in (["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Carpathian OS//panel//EN"], ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Carpatic OS//panel//EN"]) or lines[3:4] != ["BEGIN:VEVENT"] or lines[-2:] != ["END:VEVENT", "END:VCALENDAR"]:
        raise CalendarError("Only original local events can be edited")
    p = {}
    for line in lines[4:-2]:
        key, sep, value = line.partition(":")
        if not sep or key in p or key not in {"UID", "DTSTAMP", "DTSTART", "DTEND", "DTSTART;VALUE=DATE", "DTEND;VALUE=DATE", "SUMMARY"}:
            raise CalendarError("Event contains unsupported properties")
        p[key] = value
    if p.get("UID") != uid or not {"UID", "DTSTAMP", "SUMMARY"} <= p.keys(): raise CalendarError("Event identity is invalid")
    if not re.fullmatch(r"\d{8}T\d{6}Z", p["DTSTAMP"]): raise CalendarError("Invalid timestamp")
    dt.datetime.strptime(p["DTSTAMP"], "%Y%m%dT%H%M%SZ")
    def parse(value, allday):
        if not re.fullmatch(r"\d{8}" if allday else r"\d{8}T\d{6}", value): raise CalendarError("Invalid event date")
        return dt.datetime.strptime(value, "%Y%m%d" if allday else "%Y%m%dT%H%M%S")
    allday = "DTSTART;VALUE=DATE" in p
    expected = {"UID", "DTSTAMP", "SUMMARY", "DTSTART;VALUE=DATE", "DTEND;VALUE=DATE"} if allday else {"UID", "DTSTAMP", "SUMMARY", "DTSTART"}
    if set(p) != expected and not (not allday and set(p) == expected | {"DTEND"}): raise CalendarError("Event date properties are unsupported")
    a = parse(p["DTSTART;VALUE=DATE" if allday else "DTSTART"], allday)
    b = parse(p["DTEND;VALUE=DATE" if allday else "DTEND"], allday) if (allday or "DTEND" in p) else None
    if b and ((allday and b.date() != a.date() + dt.timedelta(days=1)) or (not allday and b.date() != a.date())): raise CalendarError("Multi-day events cannot be edited")
    title = _text(p["SUMMARY"]); start = None if allday else a.time(); end = None if allday or b is None else b.time()
    validate_event(title, a.date(), start, end)
    return dict(path=path, uid=uid, revision=hashlib.sha256(raw).hexdigest(), title=title, day=a.date(), start=start, end=end, all_day=allday)


def inspect_local(path, uid, data=None):
    with _directory(path, uid, data) as (dfd, name):
        raw, _ = _read(dfd, name)
        return _parse(raw, path, uid)


def _fresh(dfd, name, raw, identity, revision):
    current, ident = _read(dfd, name)
    if ident != identity or current != raw or hashlib.sha256(current).hexdigest() != revision:
        raise CalendarError("Event changed; reopen it before saving")


def update_local(path, uid, revision, title, day, start=None, end=None, data=None):
    validate_event(title, day, start, end)
    with _directory(path, uid, data) as (dfd, name):
        raw, identity = _read(dfd, name); _parse(raw, path, uid)
        esc = title.replace("\r\n", "\n").replace("\r", "\n").replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")
        date = lambda d: f"{d.year:04d}{d.month:02d}{d.day:02d}"
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Carpathian OS//panel//EN", "BEGIN:VEVENT", "UID:" + uid, "DTSTAMP:" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")]
        if start is None:
            lines += ["DTSTART;VALUE=DATE:" + date(day), "DTEND;VALUE=DATE:" + date(day + dt.timedelta(days=1))]
        else:
            lines += ["DTSTART:" + date(day) + "T" + start.strftime("%H%M%S")]
            if end is not None: lines += ["DTEND:" + date(day) + "T" + end.strftime("%H%M%S")]
        lines += ["SUMMARY:" + esc, "END:VEVENT", "END:VCALENDAR"]
        output = ("\r\n".join(lines) + "\r\n").encode("utf-8")
        temp = ".edit-" + uuid.uuid4().hex
        fd = None
        try:
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=dfd)
            with os.fdopen(fd, "wb") as f:
                fd = None; f.write(output); f.flush(); os.fsync(f.fileno())
            _fresh(dfd, name, raw, identity, revision)
            os.replace(temp, name, src_dir_fd=dfd, dst_dir_fd=dfd)
            try: os.fsync(dfd)
            except OSError as exc:
                raise CalendarCommitUncertain("save", _parse(output, path, uid)) from exc
        finally:
            if fd is not None: os.close(fd)
            try: os.unlink(temp, dir_fd=dfd)
            except FileNotFoundError: pass
        return _parse(output, path, uid)


def delete_local(path, uid, revision, data=None):
    with _directory(path, uid, data) as (dfd, name):
        raw, identity = _read(dfd, name); _parse(raw, path, uid)
        _fresh(dfd, name, raw, identity, revision)
        os.unlink(name, dir_fd=dfd)
        try: os.fsync(dfd)
        except OSError as exc:
            raise CalendarCommitUncertain("delete") from exc
        return True
