"""Users & Groups (adduser/deluser/chpasswd through polkit), Language & Region (input methods), Date & Time (timezone, NTP, calendar)."""
import os, re, pwd, grp, datetime, glob, calendar, shutil
from gi.repository import Gtk, GLib, Pango, PangoCairo
from .. import sysutil as su, ui, theme
from ..app import Page
from ..ui import *
from . import legacy

AVATAR_COLORS = ["#ff453a", "#ff9f0a", "#30b0c7", "#34c759", "#5e5ce6", "#af52de", "#0a84ff", "#ff2d55"]

def list_users(passwd_path=None):
    """human accounts: uid 1000..59999 with a real shell. [(name, full name, uid, home, shell)]"""
    if os.environ.get("CSET_FAKE_HW"): return [("anna", "Anna Popescu", 1000, "/home/anna", "/bin/sh"), ("mihai", "Mihai Ionescu", 1001, "/home/mihai", "/bin/sh")]
    res = []
    for p in pwd.getpwall():
        if 1000 <= p.pw_uid < 60000 and not p.pw_shell.endswith(("nologin", "false")):
            res.append((p.pw_name, (p.pw_gecos or "").split(",")[0] or p.pw_name, p.pw_uid, p.pw_dir, p.pw_shell))
    return sorted(res, key=lambda u: u[2])

def is_admin(name):
    try: return name in grp.getgrnam("wheel").gr_mem or name in grp.getgrnam("sudo").gr_mem
    except KeyError:
        try: return name in grp.getgrnam("sudo").gr_mem
        except KeyError: return False

def avatar(name, size=48):
    da = Gtk.DrawingArea(); da.set_size_request(size, size); col = AVATAR_COLORS[sum(map(ord, name)) % len(AVATAR_COLORS)]
    def draw(w, cr):
        r, g, b = [int(col[i:i+2], 16) / 255 for i in (1, 3, 5)]; cr.set_source_rgb(r, g, b); cr.arc(size / 2, size / 2, size / 2, 0, 6.3); cr.fill()
        lay = PangoCairo.create_layout(cr); fd = Pango.FontDescription("Sans 600"); fd.set_absolute_size(size * 0.42 * Pango.SCALE); lay.set_font_description(fd)
        lay.set_text((name[:1] or "?").upper(), -1); tw, th = lay.get_pixel_size(); cr.set_source_rgb(1, 1, 1); cr.move_to((size - tw) / 2, (size - th) / 2); PangoCairo.show_layout(cr, lay); return False
    da.connect("draw", draw); da.set_valign(Gtk.Align.CENTER); return da

class UsersPage(Page):
    id = "users"; title = "Users & Groups"; icon = "system-users"; color = "#0a84ff"; group = 4
    aliases = ("accounts", "user")
    keywords = "accounts password login administrator admin add user delete family"
    entries = (("Change password", "passwd secure", "passwd"), ("Add a user", "new account create", "add-user"), ("Other users", "administrator wheel sudo admin rights delete remove account", "others"))
    optional = frozenset({"others", "add-user"})
    def available(self): return True
    def build(self, pb):
        self.pb = pb; me = "anna" if os.environ.get("CSET_FAKE_HW") else (os.environ.get("USER") or pwd.getpwuid(os.getuid()).pw_name)
        self.me = me; users = list_users(); mine = next((u for u in users if u[0] == me), None)
        full = mine[1] if mine else me
        top = Gtk.Box(spacing=16); top.pack_start(avatar(full, 64), False, False, 0)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2); col.set_valign(Gtk.Align.CENTER); col.pack_start(label(full, "h2" if False else "row-title"), False, False, 0)
        col.get_children()[0].get_style_context().add_class("big-num")
        col.pack_start(label(me + (" \u00b7 Administrator" if is_admin(me) else " \u00b7 Standard"), "row-sub"), False, False, 0); top.pack_start(col, True, True, 0)
        g = pb.group(); g.add(CustomRow(top, key="me"))
        g.add(ButtonRow("Change password", "Needs your administrator password", "Change...", self.change_pw, key="passwd"))
        if su.which("usermod"): g.add(EntryRow("Full name", "", full, self.set_full, key="fullname"))
        self.others = pb.group("Other users", key="others")
        self.fill_others()
        g3 = pb.group()
        if su.which("adduser") or su.which("useradd"):
            g3.add(ButtonRow("Add a user", "Creates a new account with its own files", "Add...", self.add_user, key="add-user"))
    def fill_others(self):
        self.others.clear()
        for name, full, uid, home, shell in list_users():
            if name == self.me: continue
            r = Row(full, name + (" \u00b7 Administrator" if is_admin(name) else ""), key="user-" + name)
            av = avatar(full, 32); r.box.pack_start(av, False, False, 0); r.box.reorder_child(av, 0)
            if su.which("addgroup") or su.which("gpasswd"):
                b = Gtk.Button(label="Remove admin" if is_admin(name) else "Make admin"); b.connect("clicked", lambda _b, n=name: self.toggle_admin(n)); r.ctl.pack_start(b, False, False, 0)
            b = Gtk.Button(label="Delete"); ui.cls(b, "destructive-action"); b.connect("clicked", lambda _b, n=name: self.delete(n)); r.ctl.pack_start(b, False, False, 0)
            self.others.add(r); r.show_all()
        self.others.set_visible(bool(self.others.rows)); self.others.set_no_show_all(not self.others.rows)
    def change_pw(self):
        r = ui.ask_text(self.win, "Change your password", "Type the new password twice. You will be asked for your administrator password to confirm.", "New password", True, "Change", fields=2)
        if not r: return
        if r[0] != r[1] or len(r[0]) < 6:
            self.win.idle("The passwords do not match, or are shorter than 6 characters."); return
        self.win.busy("Changing the password...")
        def work(): return su.run_sync(*su.pk("chpasswd"), stdin=f"{self.me}:{r[0]}\n")
        su.bg(work, lambda res: self.win.idle("Password changed." if not isinstance(res, Exception) and res[0] == 0 else "The password was not changed."))
    def set_full(self, name):
        su.spawn(*su.pk("usermod", "-c", name, self.me), done=lambda rc, o: self.win.idle("Saved." if rc == 0 else "Could not save the name."))
    def add_user(self):
        r = ui.ask_text(self.win, "Add a user", "Choose a short account name (letters and numbers) and a password.", "Account name", False, "Add", fields=2)
        if not r: return
        name, pw = r
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,30}", name) or len(pw) < 6:
            self.win.idle("Account names use lowercase letters and numbers; passwords need 6 or more characters."); return
        self.win.busy("Adding the user...")
        script = 'IFS= read -r pw; if command -v adduser >/dev/null 2>&1 && adduser --help 2>&1 | grep -q -- "-D"; then adduser -D -s /bin/sh "$1"; else useradd -m -s /bin/sh "$1"; fi && chmod 700 "$(getent passwd "$1" | cut -d: -f6)" && printf "%s:%s\\n" "$1" "$pw" | chpasswd'
        def work(): return su.run_sync(*su.pk("sh", "-c", script, "adduser", name), stdin=pw + "\n")
        def done(res):
            ok = not isinstance(res, Exception) and res[0] == 0; self.win.idle("User added." if ok else "The user was not added."); self.fill_others()
        su.bg(work, done)
    def toggle_admin(self, n):
        grpn = "wheel" if grp_exists("wheel") else "sudo"
        cmd = (["delgroup", n, grpn] if is_admin(n) else ["addgroup", n, grpn]) if su.which("addgroup") else (["gpasswd", "-d" if is_admin(n) else "-a", n, grpn])
        self.win.apply(*su.pk(*cmd), msg="Changing...", done=lambda *_: self.fill_others())
    def delete(self, n):
        if ui.confirm(self.win, f"Delete {n}?", "The account and its files in the home folder are removed. This cannot be undone.", "Delete", True):
            cmd = ["deluser", "--remove-home", n] if su.which("deluser") else ["userdel", "-r", n]
            self.win.apply(*su.pk(*cmd), msg="Deleting...", done=lambda *_: self.fill_others())

def grp_exists(n):
    try: grp.getgrnam(n); return True
    except KeyError: return False

# ---------------------------------------------------------------- Language & Region
LANGS = {"en": "English", "ro": "Romanian", "de": "German", "fr": "French", "es": "Spanish", "it": "Italian", "pt": "Portuguese", "ru": "Russian", "pl": "Polish", "hu": "Hungarian", "cs": "Czech",
         "nl": "Dutch", "sv": "Swedish", "tr": "Turkish", "uk": "Ukrainian", "ja": "Japanese", "ko": "Korean", "zh": "Chinese", "ar": "Arabic", "el": "Greek", "bg": "Bulgarian", "da": "Danish", "fi": "Finnish", "nb": "Norwegian", "vi": "Vietnamese"}
REGIONS = {"US": "United States", "GB": "United Kingdom", "RO": "Romania", "DE": "Germany", "FR": "France", "ES": "Spain", "IT": "Italy", "PT": "Portugal", "BR": "Brazil", "RU": "Russia", "PL": "Poland",
           "HU": "Hungary", "CZ": "Czechia", "NL": "Netherlands", "SE": "Sweden", "TR": "Turkey", "UA": "Ukraine", "JP": "Japan", "KR": "South Korea", "CN": "China", "TW": "Taiwan", "AT": "Austria", "CH": "Switzerland", "CA": "Canada", "AU": "Australia", "IN": "India", "MX": "Mexico", "MD": "Moldova"}

def language_name(loc):
    """en_US.UTF-8 -> English (United States); C / POSIX -> English"""
    base = (loc or "C").split(".")[0].split("@")[0]
    if base in ("C", "POSIX", ""): return "English"
    lang, _, reg = base.partition("_")
    name = LANGS.get(lang, lang)
    return f"{name} ({REGIONS.get(reg, reg)})" if reg else name

class LanguagePage(Page):
    id = "language"; title = "Language & Region"; icon = "preferences-desktop-locale"; color = "#0a84ff"; group = 4
    aliases = ("region", "locale", "input-method")
    keywords = "typing chinese japanese korean vietnamese input method fcitx ibus locale language region"
    sub = "Typing in other languages. Chinese, Japanese, Korean, Vietnamese and some others need an input method."
    entries = (("Input method", "fcitx5 ibus typing cjk", "im"), ("Add a language", "install keyboard engine fonts chinese japanese korean", "add-lang"), ("System language", "locale lang", "locale"))
    optional = frozenset({"im", "add-lang"})
    def available(self): return True
    def build(self, pb):
        loc = os.environ.get("LANG") or su.read_file("/etc/locale.conf").replace("LANG=", "") or "C"
        g = pb.group("This computer")
        g.add(InfoRow("System language", language_name(loc), key="locale"))
        if su.which("carpatic-keyboard"): pb.group().add(NavRow("Keyboard layouts", "Layouts for typing in Latin and other scripts", "input-keyboard", "#8e8e93", "", lambda: self.win.open_page("keyboard"), key="kbd-link"))
        if not su.which("carpatic-input-method"): return
        cur = (su.out("carpatic-input-method", "status").split("\n")[0].replace("input method:", "").strip() or "off")
        g2 = pb.group("Input method", "Fcitx5 works in all apps, including Chrome and apps from the compatibility box. Takes effect after you log out and in.")
        g2.add(PopupRow("Input method", "", [("off", "Off"), ("fcitx5", "Fcitx5 (recommended)"), ("ibus", "IBus")], cur if cur in ("off", "fcitx5", "ibus") else "off", lambda v: self.win.apply("carpatic-input-method", "set", v, msg="Saving..."), key="im"))
        self.lang = PopupRow("Add a language", "Installs the keyboard engine and fonts (about 100 MB for Chinese, Japanese and Korean). Needs your password.",
                             [("chinese", "Chinese"), ("japanese", "Japanese"), ("korean", "Korean"), ("vietnamese", "Vietnamese"), ("other", "Other (engine only)")], "chinese", None, key="add-lang")
        b = Gtk.Button(label="Install"); b.set_valign(Gtk.Align.CENTER)
        def go(*_):
            b.set_sensitive(False)
            name = dict(self.lang.pb.options).get(self.lang.get_value(), "the language")
            ui.ProgressSheet(self.win, f"Adding {name}", [("Installing", f"Installing the keyboard engine and fonts for {name}...", [shutil.which("carpatic-input-method") or "carpatic-input-method", "install", self.lang.get_value()], False, {})],
                             lambda ok: (b.set_sensitive(True), self.win.idle("Done. Log out and in again, then press Ctrl+Space to switch." if ok else "")))
        b.connect("clicked", go); self.lang.ctl.pack_start(b, False, False, 0); self.lang.ctl.show_all(); g2.add(self.lang)

# ---------------------------------------------------------------- Date & Time
def current_tz():
    try:
        p = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in p: return p.split("zoneinfo/", 1)[1]
    except OSError: pass
    return su.read_file("/etc/timezone") or os.environ.get("TZ", "") or "UTC"

def all_zones():
    zs = []
    for l in su.read_file("/usr/share/zoneinfo/zone1970.tab").splitlines() if os.path.exists("/usr/share/zoneinfo/zone1970.tab") else []:
        if l and not l.startswith("#"):
            f = l.split("\t")
            if len(f) >= 3: zs.append(f[2])
    return sorted(set(zs + ["UTC"]))

def ntp_service():
    for s in ("chronyd", "ntpd", "openntpd", "systemd-timesyncd"):
        if os.path.exists(f"/etc/init.d/{s}"): return s
    return None

class MonthGrid(Gtk.DrawingArea):
    """Month grid drawn with the same date maths as the desktop widgets (widgets/lib/cwidgets/data.py)."""
    def __init__(self, win):
        super().__init__(); self.win = win; self.set_size_request(260, 200); self.connect("draw", self.on_draw); self.set_halign(Gtk.Align.CENTER)
        GLib.timeout_add_seconds(30, lambda: (self.queue_draw(), True)[1])
    def on_draw(self, w, cr):
        try:
            import cwidgets.data as D; grid = D.month_grid; names = D.weekday_names
        except Exception:
            grid = lambda y, m, fw: [[d or 0 for d in wk] for wk in calendar.Calendar(fw).monthdayscalendar(y, m)]; names = lambda fw: [calendar.day_abbr[(fw + i) % 7][:2] for i in range(7)]
        p = self.win.pal; W = w.get_allocated_width(); now = datetime.date.today(); fw = 0
        def rgbc(h): return tuple(int(h[i:i+2], 16) / 255 for i in (1, 3, 5))
        import cairo; fo = cairo.FontOptions(); fo.set_antialias(cairo.ANTIALIAS_GRAY); cr.set_font_options(fo)
        def text(s, x, y, size, col, bold=False):
            lay = PangoCairo.create_layout(cr); fd = Pango.FontDescription("Sans"); fd.set_absolute_size(size * Pango.SCALE); fd.set_weight(Pango.Weight.BOLD if bold else Pango.Weight.NORMAL); lay.set_font_description(fd); lay.set_text(s, -1)
            tw, th = lay.get_pixel_size(); cr.set_source_rgb(*rgbc(col)); cr.move_to(x - tw / 2, y - th / 2); PangoCairo.show_layout(cr, lay)
        cw = W / 7
        text(now.strftime("%B %Y"), W / 2, 12, 14, p["fg"], True)
        for i, nm in enumerate(names(fw)): text(nm, i * cw + cw / 2, 40, 11, p["muted"], True)
        for r, row in enumerate(grid(now.year, now.month, fw)):
            for i, d in enumerate(row):
                if not d: continue
                cx, cy = i * cw + cw / 2, 64 + r * 28
                if d == now.day:
                    cr.set_source_rgb(*rgbc(p["accent"])); cr.arc(cx, cy, 12, 0, 6.3); cr.fill(); text(str(d), cx, cy, 13, p["accent_fg"], True)
                else: text(str(d), cx, cy, 13, p["fg"] if i < 5 else p["muted"])
        return False

class DateTimePage(Page):
    id = "datetime"; title = "Date & Time"; icon = "preferences-system-time"; color = "#0a84ff"; group = 4
    aliases = ("date", "time", "clock", "timezone")
    keywords = "clock timezone zone ntp chrony automatic set time 24-hour calendar sync"
    entries = (("Set time automatically", "ntp chrony internet sync", "ntp"), ("Time zone", "region city utc", "tz"), ("Set date and time", "manual", "manual"), ("Calendar", "month today", "calendar"))
    optional = frozenset({"ntp"})
    def available(self): return True
    def build(self, pb):
        self.pb = pb; svc = ntp_service()
        g0 = pb.group(); g0.add(CustomRow(MonthGrid(self.win), key="calendar"))
        g = pb.group(None, "Your clock stays correct by asking time servers on the internet." if svc else "")
        self.now_row = InfoRow("Now", datetime.datetime.now().strftime("%A %-d %B %Y, %H:%M"), key="now"); g.add(self.now_row)
        GLib.timeout_add_seconds(20, lambda: (self.now_row.set_value(datetime.datetime.now().strftime("%A %-d %B %Y, %H:%M")), True)[1])
        self.ntp = None
        if svc:
            on = False
            if su.which("rc-service"): on = "started" in su.out("rc-service", svc, "status")
            self.ntp = SwitchRow("Set time automatically", "", on, lambda v: self.win.apply(*su.pk("sh", "-c", f"rc-update {'add' if v else 'del'} {svc} default; rc-service {svc} {'start' if v else 'stop'}"), msg="Saving...", done=lambda *_: self.sync_state()), key="ntp")
            g.add(self.ntp)
            self.sync_row = InfoRow("Last sync", "", key="sync"); g.add(self.sync_row); self.sync_row.hide(); self.sync_row.set_no_show_all(True)
        zs = all_zones(); tz = current_tz()
        if zs:
            if tz not in zs: zs = [tz] + zs
            g.add(PopupRow("Time zone", "", [(z, z.replace("_", " ")) for z in zs], tz, self.set_tz, key="tz"))
        self.manual = ButtonRow("Set date and time", "Only when automatic time is off" if svc else "", "Set...", self.set_manual, key="manual"); g.add(self.manual)
        self.sync_state()
    def sync_state(self):
        if self.ntp is None: return
        def work():
            return su.out("chronyc", "tracking", timeout=5) if su.which("chronyc") else ""
        def done(t):
            on = self.ntp.get_value(); self.manual.set_sensitive(not on)
            m = re.search(r"Last offset\s*:\s*([+-]?[\d.]+) seconds", t or "")
            if m and on: self.sync_row.set_value(f"{abs(float(m.group(1))) * 1000:.1f} ms off from the time servers"); self.sync_row.set_no_show_all(False); self.sync_row.show()
        su.bg(work, done)
    def set_tz(self, z):
        self.win.apply(*su.pk("sh", "-c", f"ln -sf /usr/share/zoneinfo/{z} /etc/localtime && echo {z} > /etc/timezone"), msg="Setting the time zone...", done=lambda rc, o: self.win.idle("Time zone changed." if rc == 0 else "The time zone was not changed."))
    def set_manual(self):
        r = ui.ask_text(self.win, "Set date and time", "Type the date and time as YYYY-MM-DD HH:MM, for example 2026-03-01 14:30.", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), False, "Set")
        if not r: return
        if not re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d", r[0].strip()): self.win.idle("That is not a date and time I understand."); return
        self.win.apply(*su.pk("date", "-s", r[0].strip() + ":00"), msg="Setting the clock...", done=lambda rc, o: self.win.idle("Done." if rc == 0 else "The clock was not changed."))

PAGES = [UsersPage, LanguagePage, DateTimePage]
