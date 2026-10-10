"""Calendar + notification centre flyout.

Layouts (`look`): win (notifications over calendar, Windows 11), mac (calendar card over notifications, rounded 20), ubuntu (two columns, GNOME),
kylin (Windows-like, 12 px radius, 4 px chips). Month grid with real day-name row, locale first weekday, optional week numbers, today in the accent,
selected day, dimmed neighbours, event dots, agenda under the grid, quick entry ('Lunch tomorrow 13:00'), notifications grouped by app with swipe,
clear and do-not-disturb."""
import datetime as dt
import json, os, shutil, subprocess, threading
from gi.repository import GLib
from . import gfx, calmath, events as ev, notes as nt
from .kit import View, Node, Group, p_button

SPECS = {
    "win":    dict(w=384, pad=16, sr=14, cr=10, order="notes-first", cols=1, cell=40),
    "mac":    dict(w=372, pad=14, sr=20, cr=14, order="head-notes-cal", cols=1, cell=38),
    "ubuntu": dict(w=744, pad=16, sr=18, cr=12, order="two", cols=2, cell=40),
    "kylin":  dict(w=388, pad=16, sr=12, cr=8, order="notes-first", cols=1, cell=40),
}


class CalModel:
    """State of the calendar card; no drawing. `today` is injectable for tests."""

    def __init__(self, today=None, first=None, week_numbers=False, clock24=True, data=None):
        self.today = today or dt.date.today()
        self.first = calmath.system_first_weekday("auto") if first is None else first
        self.year, self.month = self.today.year, self.today.month
        self.selected = self.today
        self.week_numbers = week_numbers; self.clock24 = clock24; self.data = data
        self._cache = {}

    def grid(self): return calmath.month_grid(self.year, self.month, self.first)

    def shift(self, n):
        self.year, self.month = calmath.add_months(self.year, self.month, n)
        # keep the selected day's number when the month changes, so Prev/Next feels continuous
        d = calmath.clamp_day(self.year, self.month, self.selected.day)
        self.selected = dt.date(self.year, self.month, d)

    def go_today(self):
        self.year, self.month, self.selected = self.today.year, self.today.month, self.today

    def select(self, d):
        self.selected = d
        if (d.year, d.month) != (self.year, self.month): self.year, self.month = d.year, d.month

    def events_in_grid(self):
        g = self.grid(); lo, hi = g[0][0], g[-1][-1]
        key = (lo, hi)
        if key not in self._cache: self._cache = {key: ev.load_events(lo, hi, self.data)}
        by = {}
        for e in self._cache[key]: by.setdefault(e.day, []).append(e)
        return by

    def invalidate(self): self._cache = {}

    def agenda(self): return self.events_in_grid().get(self.selected, [])

    def title(self): return calmath.month_title(self.year, self.month)


def long_date(d):
    return d.strftime("%A, %-d %B")


class CalView(View):
    def __init__(self, theme, cal: CalModel, notes_src, look="win", max_h=720, dnd_get=None, dnd_set=None, on_close=None, now_fn=None, weather=None):
        super().__init__(theme)
        self.cal = cal; self.notes_src = notes_src; self.look = look; self.sp = SPECS[look]
        self.radius = self.sp["sr"]; self.W = self.sp["w"]; self.max_h = max_h
        self.dnd_get = dnd_get or (lambda: False); self.dnd_set = dnd_set or (lambda v: None)
        self.on_close = on_close or (lambda: None)
        self.notes = notes_src.history() if notes_src else []
        self.live_entry = False
        self.expanded = set(); self.swipe = {}; self.entry_rect = None; self.entry_text = ""
        self.weather = weather
        self.groups = {}
        self.H = self._height()
        self.reminders_day = None
        self.reminders_count = None
        self.reminders_status = 'Loading reminders…'
        self._reminders_busy = False
        self._reminders_timer = GLib.timeout_add(150, self._load_reminders)

    def refresh(self):
        # Defer new I/O until after first paint / date-selection rendering.
        if (hasattr(self, 'reminders_day') and self.reminders_day != self.cal.selected
                and not self._reminders_timer and not self._reminders_busy):
            self._reminders_timer = GLib.timeout_add(150, self._load_reminders)
        super().refresh()

    def _load_reminders(self):
        self._reminders_timer = 0
        if self._reminders_busy: return False
        day = self.cal.selected
        self._reminders_busy = True
        def worker():
            count = None; status = 'Reminders unavailable'
            try:
                executable = shutil.which('carpatic-reminders')
                if executable:
                    result = subprocess.run([executable, 'list', '--pending', '--date', day.isoformat()],
                                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=2, check=True)
                    if len(result.stdout) > 1024 * 1024: raise ValueError('oversize reminders result')
                    items = json.loads(result.stdout)
                    if not isinstance(items, list) or len(items) > 1000: raise ValueError('invalid reminders result')
                    count = len(items); status = ''
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
            GLib.idle_add(deliver, count, status)
        def deliver(count, status):
            self._reminders_busy = False
            self.reminders_day = day
            self.reminders_count = count
            self.reminders_status = status
            self.refresh()
            return False
        threading.Thread(target=worker, name='calendar-reminders', daemon=True).start()
        return False

    def _open_reminders(self, new=False):
        day = self.cal.selected.isoformat()
        def worker():
            try:
                executable = shutil.which('carpatic-reminders')
                if not executable: raise FileNotFoundError()
                subprocess.Popen([executable, '--date', day] + (['--new'] if new else []),
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
            except OSError:
                GLib.idle_add(failed)
            else:
                GLib.idle_add(self.on_close)
        def failed():
            self.reminders_status = 'Reminders app is not installed'
            super(CalView, self).refresh()
            return False
        threading.Thread(target=worker, name='calendar-open-reminders', daemon=True).start()

    def on_entry_change(self, text): self.entry_text = text; self.refresh()

    def on_entry_activate(self, text, entry):
        if self.submit_entry(text): entry.set_text("")

    # ------------------------------------------------------------------ geometry
    def _cal_h(self):
        sp = self.sp
        return 44 + 26 + 6 * sp["cell"] + 4

    def _agenda_rows(self, avail):
        return max(1, min(3, len(self.cal.agenda()), (avail - 28 - 52) // 44)) if self.cal.agenda() else 0

    def _height(self):
        if self.sp["cols"] == 2: return 580
        sp = self.sp
        cal_h = self._cal_h() + 8
        agenda_h = 28 + 36 + (3 * 44 if self.cal.agenda() else 56) + 8
        entry_h = 44
        fixed = sp["pad"] * 2 + 44 + cal_h + agenda_h + entry_h + 12
        notes_h = 220 if self.notes else 110
        want = fixed + notes_h + (52 if sp["order"] == "head-notes-cal" else 0)
        return int(min(self.max_h, max(want, 600)))

    def size(self): return (self.W, self.H)

    # ------------------------------------------------------------------ build
    def build(self):
        self.entry_rect = None
        sp = self.sp; nodes = []
        if sp["cols"] == 2:
            colw = (self.W - 2 * sp["pad"] - 16) / 2
            nodes += self._notif_block(sp["pad"], sp["pad"], colw, self.H - 2 * sp["pad"], title=True)
            lx = sp["pad"] + colw + 16
            nodes.append(Node(x=lx - 8, y=sp["pad"], w=1, h=self.H - 2 * sp["pad"], paint=lambda cr, n, st: (cr.set_source_rgba(*self.theme.border), cr.rectangle(n.x, n.y, 1, n.h), cr.fill())))
            y = sp["pad"]
            nodes += self._date_header(lx, y, colw); y += 52
            nodes += self._calendar_block(lx, y, colw); y += self._cal_h() + 8
            nodes += self._agenda_block(lx, y, colw, self.H - sp["pad"] - y - 48)
            return nodes
        x0, cw = sp["pad"], self.W - 2 * sp["pad"]
        y = sp["pad"]
        cal_h = self._cal_h(); agenda_min = 28 + 36 + (44 * min(3, max(1, len(self.cal.agenda()))) if self.cal.agenda() else 56) + 8 + 44
        if sp["order"] == "notes-first":
            notes_h = self.H - 2 * sp["pad"] - (cal_h + 8 + agenda_min + 8)
            nodes += self._notif_block(x0, y, cw, notes_h, title=True); y += notes_h + 8
            nodes += self._calendar_block(x0, y, cw, card=True); y += cal_h + 8
            nodes += self._agenda_block(x0, y, cw, self.H - sp["pad"] - y)
        else:
            nodes += self._date_header(x0, y, cw); y += 52
            notes_h = self.H - sp["pad"] - y - (cal_h + 4 + agenda_min + 8)
            nodes += self._notif_block(x0, y, cw, notes_h, title=True); y += notes_h + 8
            nodes += self._calendar_block(x0, y, cw, card=False); y += cal_h + 4
            nodes += self._agenda_block(x0, y, cw, self.H - sp["pad"] - y)
        return nodes

    # ------------------------------------------------------------------ date header
    def _date_header(self, x, y, w):
        t = self.theme; today = self.cal.today
        def paint(cr, n, st):
            gfx.text(cr, long_date(today), n.x, n.y + 18, 20, t.fg, 600, maxw=n.w)
            gfx.text(cr, f"Week {calmath.week_number(today)}", n.x, n.y + 40, 12, t.fg_muted, 400)
        return [Node(x=x, y=y, w=w, h=48, paint=paint)]

    # ------------------------------------------------------------------ month grid
    def _calendar_block(self, x, y, w, card=True):
        t, sp, c = self.theme, self.sp, self.cal; nodes = []
        cell = sp["cell"]; h = self._cal_h()
        if card:
            nodes.append(Node(x=x, y=y, w=w, h=h, paint=lambda cr, n, st: gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, sp["cr"] + 2, t.tile_off)))
        px = 8 if card else 0
        gx, gw = x + px, w - 2 * px
        wk = 28 if c.week_numbers else 0
        colw = (gw - wk) / 7
        # header
        def title_paint(cr, n, st):
            gfx.text(cr, c.title(), n.x + 4, n.y + n.h / 2, 15, t.fg, 600, maxw=n.w - 8)
        is_cur = (c.year, c.month) == (c.today.year, c.today.month)
        nodes.append(Node(id="cal:title", x=gx + 4, y=y + 4, w=gw - 140, h=36, paint=title_paint,
                          on_click=lambda n: (c.go_today(), self.refresh()) if not is_cur else None, radius=8, focusable=False))
        def btn(id_, g, bx, tip, fn):
            return Node(id=id_, x=bx, y=y + 8, w=32, h=32, paint=self._btn_paint(g), on_click=fn, radius=8, tooltip=tip)
        right = gx + gw
        nodes.append(btn("cal:next", "chevron_r", right - 36, "Next month", lambda n: (c.shift(1), self.refresh())))
        nodes.append(btn("cal:prev", "chevron_l", right - 70, "Previous month", lambda n: (c.shift(-1), self.refresh())))
        if not is_cur or c.selected != c.today:
            def today_paint(cr, n, st):
                p_button(t, 8)(cr, n, st)
                gfx.text(cr, "Today", n.x + n.w / 2, n.y + n.h / 2, 12.5, t.accent, 600, "c")
            nodes.append(Node(id="cal:today", x=right - 70 - 58, y=y + 8, w=54, h=32, paint=today_paint, on_click=lambda n: (c.go_today(), self.refresh()), radius=8, tooltip="Go to today"))
        # day names
        names = calmath.weekday_names(c.first, "short")
        def dn_paint(cr, n, st):
            for i, nm in enumerate(names):
                gfx.text(cr, nm.upper() if False else nm, n.x + wk + colw * i + colw / 2, n.y + n.h / 2, 11, t.fg_muted, 600, "c")
            if wk: gfx.text(cr, "#", n.x + wk / 2, n.y + n.h / 2, 11, t.fg_subtle, 600, "c")
        nodes.append(Node(x=gx, y=y + 44, w=gw, h=26, paint=dn_paint))
        grid = c.grid(); ev_by = c.events_in_grid()
        gy = y + 70
        for r, row in enumerate(grid):
            if wk:
                nodes.append(Node(x=gx, y=gy + r * cell, w=wk, h=cell, paint=(lambda cr, n, st, d=row[0]: gfx.text(cr, str(calmath.week_number(d + dt.timedelta(days=3 if False else 0))), n.x + n.w / 2, n.y + n.h / 2, 11, t.fg_subtle, 500, "c", tnum=True))))
            for col, d in enumerate(row):
                nodes.append(self._day_node(d, gx + wk + colw * col, gy + r * cell, colw, cell, ev_by.get(d, [])))
        return nodes

    def _btn_paint(self, g):
        t = self.theme
        def paint(cr, n, st):
            p_button(t, 8)(cr, n, st); gfx.glyph(cr, g, n.x + n.w / 2, n.y + n.h / 2, 18, t.fg)
        return paint

    def _day_node(self, d, x, y, w, h, evs):
        t, c = self.theme, self.cal
        in_month = d.month == c.month; is_today = d == c.today; is_sel = d == c.selected
        def paint(cr, n, st):
            cx, cy = n.x + n.w / 2, n.y + n.h / 2 - 2
            r = n.h / 2 - 6
            if is_today: gfx.circle(cr, cx, cy, r, t.accent)
            elif is_sel: gfx.circle(cr, cx, cy, r, t.accent_soft); cr.new_sub_path(); cr.arc(cx, cy, r - 0.75, 0, gfx.TAU); cr.set_source_rgba(*t.accent); cr.set_line_width(1.5); cr.stroke()
            elif st.hover or st.press: gfx.circle(cr, cx, cy, r, (t.press if st.press else (t.hover[0], t.hover[1], t.hover[2], t.hover[3] * max(st.hover, .01))))
            col = t.accent_fg if is_today else (t.fg if in_month else t.fg_subtle)
            gfx.text(cr, str(d.day), cx, cy, 13, col, 700 if is_today else (500 if in_month else 400), "c", tnum=True)
            if evs:
                cols = [t.accent, t.info, t.ember, t.danger, t.success]
                k = min(3, len(evs)); x0 = cx - (k - 1) * 3.5
                for i in range(k):
                    dc = cols[evs[i].color % 5]
                    gfx.circle(cr, x0 + i * 7, cy + r + 4, 1.9, (dc[0], dc[1], dc[2], 0.95 if in_month else 0.45))
        return Node(id="day:" + d.isoformat(), x=x, y=y, w=w, h=h, paint=paint, on_click=lambda n, dd=d: (c.select(dd), self.refresh()), radius=h / 2 - 3, ring=True,
                    tooltip=d.strftime("%A %-d %B"))

    # ------------------------------------------------------------------ agenda + quick entry
    def _agenda_block(self, x, y, w, h):
        t, c = self.theme, self.cal; nodes = []
        sel = c.selected; evs = c.agenda()
        title = "Today" if sel == c.today else ("Tomorrow" if sel == c.today + dt.timedelta(days=1) else sel.strftime("%A %-d %B"))
        def head(cr, n, st):
            gfx.text(cr, title, n.x + 2, n.y + 14, 13, t.fg, 600)
            gfx.text(cr, (f"{len(evs)} event" + ("s" if len(evs) != 1 else "")) if evs else "", n.x + n.w - 2, n.y + 14, 12, t.fg_muted, 400, "r")
        nodes.append(Node(x=x, y=y, w=w, h=28, paint=head))
        yy = y + 28
        def reminders_paint(cr, n, st):
            p_button(t, 8)(cr, n, st)
            same_day = self.reminders_day == sel
            label = (f'Reminders · {self.reminders_count} pending' if same_day and self.reminders_count is not None
                     else (self.reminders_status if same_day else 'Loading reminders…'))
            gfx.text(cr, label, n.x + 8, n.y + n.h / 2, 12, t.accent, 500, maxw=n.w - 16)
        nodes.append(Node(id='cal:reminders', x=x, y=yy, w=max(80, w - 86), h=30, paint=reminders_paint,
                          on_click=lambda n: self._open_reminders(), tooltip='Open reminders for ' + sel.isoformat(), radius=8))
        def add_paint(cr, n, st):
            p_button(t, 8)(cr, n, st)
            gfx.text(cr, '+ Add', n.x + n.w / 2, n.y + n.h / 2, 12, t.accent, 600, 'c')
        nodes.append(Node(id='cal:new-reminder', x=x + w - 80, y=yy, w=80, h=30, paint=add_paint,
                          on_click=lambda n: self._open_reminders(True), tooltip='New reminder for ' + sel.isoformat(), radius=8))
        yy += 36
        entry_h = 44
        ey = y + h - entry_h + 4
        rows = max(0, min(len(evs), 3, int((h - 28 - 36 - entry_h - 20) // 44)))
        if not evs and ey - yy >= 32:
            nodes.append(Node(x=x, y=yy, w=w, h=min(48, ey - yy - 16), paint=lambda cr, n, st: gfx.text(cr, "No calendar events for this day.", n.x + 2, n.y + 16, 12.5, t.fg_muted, 400)))
        for i, e in enumerate(evs[:rows]):
            nodes.append(self._event_row(e, x, yy, w)); yy += 44
        if len(evs) > rows and rows and ey - yy >= 28:
            more = len(evs) - rows
            nodes.append(Node(x=x, y=yy - 6, w=w, h=20, paint=lambda cr, n, st: gfx.text(cr, f"+ {more} more", n.x + 2, n.y + 10, 11.5, t.fg_muted, 500)))
            yy += 14
        # quick entry
        self.entry_rect = (x, ey, w, 36)
        parsed = self.preview()
        nodes.append(Node(x=x, y=ey - 18, w=w, h=16, paint=lambda cr, n, st: gfx.text(cr, parsed, n.x + 4, n.y + 8, 11, t.accent, 500, maxw=n.w - 8) if parsed else None))
        def field(cr, n, st):
            gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, 10, t.tile_off)
            gfx.stroke_rrect(cr, n.x, n.y, n.w, n.h, 10, t.accent if self.entry_text and self.live_entry else t.border, 1)
            gfx.glyph(cr, "plus", n.x + 20, n.y + n.h / 2, 16, t.fg_muted)
            if not self.live_entry:
                if self.entry_text: gfx.text(cr, self.entry_text, n.x + 38, n.y + n.h / 2, 13, t.fg, 400, maxw=n.w - 50)
                else: gfx.text(cr, "Add event, e.g. Lunch tomorrow 13:00", n.x + 38, n.y + n.h / 2, 13, t.fg_subtle, 400, maxw=n.w - 50)
        nodes.insert(len(nodes) - 1, Node(x=x, y=ey, w=w, h=36, paint=field))
        return nodes

    def preview(self):
        txt = self.entry_text.strip()
        if not txt: return ""
        title, day, st, en = ev.parse_quick(txt, self.cal.today)
        if not title: return ""
        when = day.strftime("%a %-d %b") + (f" · {st:%H:%M}" + (f"–{en:%H:%M}" if en else "") if st else " · all day")
        return f"↵  {title}  ·  {when}"

    def submit_entry(self, text):
        title, day, st, en = ev.parse_quick(text, self.cal.today)
        if not title: return False
        ev.write_event(title, day, st, en, self.cal.data)
        self.cal.invalidate(); self.cal.select(day); self.entry_text = ""; self.refresh(); return True

    def _event_row(self, e, x, y, w):
        t = self.theme
        cols = [t.accent, t.info, t.ember, t.danger, t.success]
        col = cols[e.color % 5]
        def paint(cr, n, st):
            p_button(t, 8)(cr, n, st)
            gfx.fill_rrect(cr, n.x + 6, n.y + 6, 3, n.h - 12, 1.5, col)
            gfx.text(cr, e.time_text(self.cal.clock24).split(" – ")[0] if not e.all_day else "All day", n.x + 18, n.y + n.h / 2 - (8 if e.where else 0) if False else n.y + n.h / 2, 12, t.fg_muted, 500, tnum=True)
            tx = n.x + 78
            if e.where:
                gfx.text(cr, e.title, tx, n.y + n.h / 2 - 8, 13, t.fg, 600, maxw=n.w - 90); gfx.text(cr, e.where, tx, n.y + n.h / 2 + 9, 11.5, t.fg_muted, 400, maxw=n.w - 90)
            else:
                gfx.text(cr, e.title, tx, n.y + n.h / 2, 13, t.fg, 600, maxw=n.w - 90)
        return Node(id="ev:%s:%s" % (e.uid or e.title, e.day), x=x, y=y, w=w, h=40, paint=paint, radius=8, on_click=lambda n: None, focusable=False)

    # ------------------------------------------------------------------ notifications
    def _notif_block(self, x, y, w, h, title=True):
        t, sp = self.theme, self.sp; nodes = []
        dnd = self.dnd_get()
        def head(cr, n, st): gfx.text(cr, "Notifications", n.x + 2, n.y + n.h / 2, 15, t.fg, 600)
        nodes.append(Node(x=x, y=y, w=w - 170, h=36, paint=head))
        def dnd_paint(cr, n, st):
            if dnd: gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, 8, t.accent_soft)
            else: p_button(t, 8)(cr, n, st)
            gfx.glyph(cr, "bell_off" if dnd else "bell", n.x + 17, n.y + n.h / 2, 16, t.accent if dnd else t.fg_muted)
            gfx.text(cr, "Silent" if dnd else "Do not disturb" if False else "Focus", n.x + 32, n.y + n.h / 2, 12, t.accent if dnd else t.fg_muted, 600)
        nodes.append(Node(id="dnd", x=x + w - 164, y=y, w=84 if False else 78, h=32, paint=dnd_paint, on_click=lambda n: (self.dnd_set(not dnd), self.refresh()), radius=8, tooltip="Do not disturb"))
        if self.notes:
            def clear_paint(cr, n, st):
                p_button(t, 8)(cr, n, st); gfx.text(cr, "Clear all", n.x + n.w / 2, n.y + n.h / 2, 12, t.fg_muted, 600, "c")
            nodes.append(Node(id="clear", x=x + w - 82, y=y, w=82, h=32, paint=clear_paint, on_click=lambda n: (self.notes_src.clear(), self._reload()), radius=8))
        top = y + 40
        g = self.groups.get("notes")
        if g is None: g = self.groups["notes"] = Group(x, top, w, h - 40)
        g.x, g.y, g.w, g.h = x, top, w, h - 40
        cy = top
        if not self.notes:
            def empty(cr, n, st):
                gfx.glyph(cr, "bell", n.x + n.w / 2, n.y + n.h / 2 - 14, 30, t.fg_subtle)
                gfx.text(cr, "No new notifications", n.x + n.w / 2, n.y + n.h / 2 + 18, 13, t.fg_muted, 500, "c")
            nodes.append(Node(x=x, y=top, w=w, h=max(80, h - 40), paint=empty))
            g.content_h = 0; return nodes
        for app, items in nt.group_by_app(self.notes):
            exp = app in self.expanded; shown = items if exp or len(items) <= 2 else items[:2]
            def gh(cr, n, st, app=app, items=items):
                gfx.text(cr, app, n.x + 4, n.y + n.h / 2, 11.5, t.fg_muted, 600)
                gfx.text(cr, str(len(items)) if len(items) > 1 else "", n.x + 6 + gfx.text_size(gfx._scratch(), app, 11.5, 600)[0] + 8, n.y + n.h / 2, 11, t.fg_subtle, 500, tnum=True)
            nodes.append(Node(x=x, y=cy, w=w - 36, h=26, paint=gh, group="notes"))
            if len(items) > 1:
                nodes.append(Node(id="gclr:" + app, x=x + w - 30, y=cy, w=26, h=26, paint=self._x_paint(), on_click=(lambda n, its=items: ([self.notes_src.remove(i.id) for i in its], self._reload())), radius=13, group="notes", tooltip="Clear " + app))
            cy += 28
            for nn in shown:
                nodes.append(self._note_card(nn, x, cy, w - 8)); cy += (72 if nn.body else 46) + 6
            if len(items) > 2:
                lab = "Show less" if exp else f"Show {len(items) - 2} more"
                def lp(cr, n, st, lab=lab):
                    p_button(t, 8)(cr, n, st); gfx.text(cr, lab, n.x + 10, n.y + n.h / 2, 12, t.accent, 600)
                nodes.append(Node(id="exp:" + app, x=x, y=cy - 2, w=110, h=26, paint=lp, on_click=(lambda n, a=app: (self.expanded.symmetric_difference_update({a}), self.refresh())), radius=8, group="notes"))
                cy += 30
            cy += 6
        g.content_h = cy - top
        return nodes

    def _x_paint(self):
        t = self.theme
        def paint(cr, n, st):
            if st.hover or st.press: gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, n.h / 2, t.press if st.press else t.hover)
            gfx.glyph(cr, "close", n.x + n.w / 2, n.y + n.h / 2, 12, t.fg_muted, lw=2)
        return paint

    def _reload(self):
        self.notes = self.notes_src.history(); self.refresh()

    def _note_card(self, nn, x, y, w):
        t = self.theme; sp = self.sp; h = 72 if nn.body else 46
        key = "nc:%s" % nn.id
        def paint(cr, n, st):
            off = self.swipe.get(nn.id, 0.0)
            cr.save(); cr.translate(off, 0)
            alpha = max(0.15, 1 - abs(off) / 220)
            gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, sp["cr"], (t.card[0], t.card[1], t.card[2], alpha) if False else t.tile_off)
            if st.hover or st.press: gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, sp["cr"], t.hover)
            ic = nn.icon
            surf = gfx.load_icon(ic, 28) if ic else None
            if surf is not None: cr.set_source_surface(surf, n.x + 12, n.y + 12); cr.paint()
            else:
                gfx.fill_rrect(cr, n.x + 12, n.y + 12, 28, 28, 8, t.accent_soft); gfx.text(cr, (nn.app or "?")[:1].upper(), n.x + 26, n.y + 26, 13, t.accent, 700, "c")
            tx = n.x + 52; mw = n.w - 52 - 70
            gfx.text(cr, nn.summary, tx, n.y + 20, 13, t.fg, 600, maxw=mw)
            gfx.text(cr, nt.age_text(nn.age), n.x + n.w - 12 - (22 if st.hover else 0), n.y + 20, 11, t.fg_subtle, 400, "r")
            if nn.body:
                for i, ln in enumerate(gfx.wrap_text(cr, nn.body, 12, n.w - 52 - 14, 400, max_lines=2)):
                    gfx.text(cr, ln, tx, n.y + 40 + i * 16, 12, t.fg_muted, 400)
            if st.hover:
                gfx.circle(cr, n.x + n.w - 18, n.y + 20, 10, t.press); gfx.glyph(cr, "close", n.x + n.w - 18, n.y + 20, 11, t.fg, lw=2)
            cr.restore()
        def drag(n, lx, ly, phase):
            if phase == "start": self._sx = lx; self.swipe[nn.id] = 0.0
            elif phase == "move": self.swipe[nn.id] = lx - self._sx
            else:
                off = self.swipe.get(nn.id, 0.0)
                if abs(off) > 90 or (abs(off) < 4 and lx > n.w - 32):
                    self.notes_src.remove(nn.id); self.swipe.pop(nn.id, None); self._reload()
                else: self.swipe[nn.id] = 0.0
        return Node(id=key, x=x, y=y, w=w, h=h, paint=paint, on_drag=drag, radius=sp["cr"], group="notes", focusable=True, tooltip=None)
