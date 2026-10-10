"""Start menu flyout. Looks: win (Windows 11: search, pinned grid, recommended, All apps, user + power row), twopane (Zen / Kylin: app list on the
left, favourites grid on the right, side buttons), launchpad (macOS: full-screen grid)."""
import glob, json, os, re, shutil, subprocess, time
from . import uiscale
from . import gfx, tasks as tk
from .kit import View, Node, Group, p_button

STATE = os.environ.get("CARPATIC_STATE", os.path.expanduser("~/.local/state/carpatic"))
DEFAULT_PINNED = ["org.xfce.Thunar", "firefox", "carpatic-terminal", "carpatic-settings", "carpatic-store", "org.gnome.gedit", "vlc", "org.gnome.Calculator", "libreoffice-writer",
                  "thunar", "st", "chromium", "code", "gimp", "org.gnome.Nautilus", "org.gnome.Terminal"]


def read_list(name):
    try: return [l.strip() for l in open(os.path.join(STATE, name)) if l.strip()]
    except OSError: return []


def write_list(name, items):
    os.makedirs(STATE, exist_ok=True)
    tmp = os.path.join(STATE, name + ".tmp")
    with open(tmp, "w") as f: f.write("\n".join(items) + "\n")
    os.replace(tmp, os.path.join(STATE, name))


def record_launch(app_id):
    r = [x for x in read_list("start-recent") if x != app_id]; write_list("start-recent", ([app_id] + r)[:12])


def recent_files(limit=6, path=None):
    """GTK recently-used.xbel -> [(title, path, mtime)] newest first, only files that still exist."""
    p = path or os.path.expanduser("~/.local/share/recently-used.xbel")
    try: txt = open(p, encoding="utf-8", errors="replace").read()
    except OSError: return []
    out = []
    for m in re.finditer(r'<bookmark href="file://([^"]+)"[^>]*modified="([^"]+)"', txt):
        from urllib.parse import unquote
        f = unquote(m.group(1))
        if os.path.exists(f): out.append((os.path.basename(f), f, m.group(2)))
    out.sort(key=lambda t: t[2], reverse=True); return out[:limit]


def search_apps(apps, q):
    q = q.strip().lower()
    if not q: return []
    scored = []
    for a in apps:
        n = a.name.lower()
        if n.startswith(q): s = 0
        elif any(w.startswith(q) for w in re.split(r"[\s\-_.]+", n)): s = 1
        elif q in n: s = 2
        elif q in a.id.lower() or q in (a.exec or "").lower().split()[0:1].__str__(): s = 3
        else: continue
        scored.append((s, n, a))
    scored.sort(key=lambda t: (t[0], t[1])); return [a for _, _, a in scored]


def sorted_apps(cat):
    return sorted([a for a in cat.values() if not a.hidden], key=lambda a: a.name.lower())


def letter_groups(apps):
    out = []; cur = None
    for a in apps:
        L = a.name[:1].upper(); L = L if L.isalpha() else "#"
        if L != cur: out.append((L, [])); cur = L
        out[-1][1].append(a)
    return out


def display_name():
    """The name typed in the installer (/etc/carpatic/user_full_name.txt), else the passwd comment, else the login name."""
    try: full = open("/etc/carpatic/user_full_name.txt").read().strip()
    except OSError: full = ""
    login = os.environ.get("USER", "")
    if not full:
        try:
            import pwd
            full = pwd.getpwnam(login).pw_gecos.split(",")[0].strip() if login else ""
        except Exception: full = ""
    return full or login


SUGGESTED_NAMES = ["Text Editor", "Calculator", "Image Viewer", "Document Viewer", "Archive Manager", "Video Player", "Disks", "Task Manager"]


class StartView(View):
    def __init__(self, theme, look, catalogue, launch, close, screen=(1920, 1080), pinned=None, recent=None, files=None, user="", skin="win", spawn=None):
        super().__init__(theme)
        self.look = look; self.skin = skin; self.cat = catalogue; self.launch_fn = launch; self.close = close; self.screen = screen
        self.apps = sorted_apps(catalogue)
        ids = pinned if pinned is not None else (read_list("start-pinned") or DEFAULT_PINNED)
        self.pinned = [catalogue[i] for i in ids if i in catalogue and not catalogue[i].hidden][:18]
        if not self.pinned: self.pinned = self.apps[:12]
        self.recent_apps = [catalogue[i] for i in (recent if recent is not None else read_list("start-recent")) if i in catalogue][:6]
        self.files = files if files is not None else recent_files()
        self.user = user or display_name()
        self.spawn = spawn or (lambda *c: subprocess.Popen(list(c), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True))
        self.query = ""; self.page = "home"          # home | all
        self.entry_rect = None; self.entry_kind = "text"; self.entry_placeholder = "Search apps, settings and files"
        self.live_entry = False
        self.groups = {}
        if look == "win": self.W, self.H = 640, min(720, screen[1] - 100); self.radius = 14
        elif look == "twopane": self.W, self.H = (766, min(688, screen[1] - 100)); self.radius = 12 if skin == "kylin" else 14
        else: self.W, self.H = screen; self.radius = 0; self.framed = True
        self.menu_cb = None

    # ------------------------------------------------------------------ entry hooks
    def on_entry_change(self, text):
        self.query = text; self.groups = {}; self.refresh()

    def on_entry_activate(self, text, entry):
        res = search_apps(self.apps, text)
        if res: self.launch(res[0])
        elif text.strip(): self.spawn("sh", "-c", text.strip()); self.close()

    def key(self, ev):
        return False

    def launch(self, app):
        record_launch(app.id); self.launch_fn(app); self.close()

    def paint_frame(self, cr, w, h, alpha=1.0):
        t = self.theme
        if self.look == "launchpad":
            cr.set_source_rgba(t.deep[0], t.deep[1], t.deep[2], 0.97); cr.paint(); return
        super().paint_frame(cr, w, h, alpha)

    # ------------------------------------------------------------------ shared pieces
    def _search_box(self, x, y, w, h=40):
        t = self.theme; self.entry_rect = (x, y, w, h)
        def paint(cr, n, s):
            gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, n.h / 2 if self.look != "twopane" else 8, t.tile_off)
            gfx.stroke_rrect(cr, n.x, n.y, n.w, n.h, n.h / 2 if self.look != "twopane" else 8, t.accent if self.query else t.border, 1)
            gfx.glyph(cr, "search", n.x + 22, n.y + n.h / 2, 16, t.fg_muted)
            if not self.live_entry:
                gfx.text(cr, self.query or self.entry_placeholder, n.x + 40, n.y + n.h / 2, 13.5, t.fg if self.query else t.fg_subtle, 400, maxw=n.w - 56, family=t.font)
        return Node(x=x, y=y, w=w, h=h, paint=paint)

    def _app_tile(self, app, x, y, w, h, icon=32, label=True, id_prefix="app", twoline=True):
        t = self.theme
        def paint(cr, n, s):
            p_button(t, 8)(cr, n, s)
            surf = gfx.load_icon(app.icon, icon) if app.icon else None
            ix = n.x + n.w / 2 - icon / 2; iy = n.y + 10
            if surf is not None: cr.set_source_surface(surf, ix, iy); cr.paint()
            else: gfx.app_letter_icon(cr, ix, iy, icon, app.name, t.accent_soft, t.accent)
            if label:
                lines = gfx.wrap_text(cr, app.name, 12, n.w - 8, 400, t.font, 2)
                for i, ln in enumerate(lines): gfx.text(cr, ln, n.x + n.w / 2, iy + icon + 14 + i * 15, 12, t.fg, 400, "c", family=t.font)
        nd = Node(id=f"{id_prefix}:{app.id}", x=x, y=y, w=w, h=h, paint=paint, radius=8, on_click=lambda n, a=app: self.launch(a), tooltip=app.name)
        nd.on_context = lambda n, ev, a=app: self.context(a, ev)
        return nd

    def _app_row(self, app, x, y, w, h=40, icon=28, sub=None, group=None):
        t = self.theme
        def paint(cr, n, s):
            p_button(t, 8)(cr, n, s)
            surf = gfx.load_icon(app.icon, icon) if app.icon else None
            iy = n.y + (n.h - icon) / 2
            if surf is not None: cr.set_source_surface(surf, n.x + 10, iy); cr.paint()
            else: gfx.app_letter_icon(cr, n.x + 10, iy, icon, app.name, t.accent_soft, t.accent)
            if sub:
                gfx.text(cr, app.name, n.x + 10 + icon + 12, n.y + n.h / 2 - 8, 13, t.fg, 500, maxw=n.w - 70, family=t.font); gfx.text(cr, sub, n.x + 10 + icon + 12, n.y + n.h / 2 + 9, 11.5, t.fg_muted, 400, maxw=n.w - 70, family=t.font)
            else: gfx.text(cr, app.name, n.x + 10 + icon + 12, n.y + n.h / 2, 13, t.fg, 400, maxw=n.w - 70, family=t.font)
        nd = Node(id=f"row:{app.id}", x=x, y=y, w=w, h=h, paint=paint, radius=8, on_click=lambda n, a=app: self.launch(a), group=group)
        nd.on_context = lambda n, ev, a=app: self.context(a, ev); return nd

    def context(self, app, ev):
        if self.menu_cb: self.menu_cb(app, ev)

    def _header(self, text, x, y, w, right=None):
        t = self.theme; nodes = [Node(x=x, y=y, w=w - 110, h=28, paint=lambda cr, n, s: gfx.text(cr, text, n.x + 4, n.y + n.h / 2, 13.5, t.fg, 600, family=t.font))]
        if right:
            label, fn = right
            def p(cr, n, s):
                p_button(t, 6)(cr, n, s)
                if label == "Back":   # a back button points left, with the label after the arrow
                    gfx.glyph(cr, "chevron_l", n.x + 14, n.y + n.h / 2, 12, t.fg_muted, lw=2); gfx.text(cr, label, n.x + 28, n.y + n.h / 2, 12, t.fg, 500, family=t.font)
                else:
                    gfx.text(cr, label, n.x + 10, n.y + n.h / 2, 12, t.fg, 500, family=t.font); gfx.glyph(cr, "chevron_r", n.x + n.w - 12, n.y + n.h / 2, 12, t.fg_muted, lw=2)
            nodes.append(Node(id="hdr:" + label, x=x + w - 100, y=y, w=100, h=28, paint=p, on_click=lambda n: fn(), radius=6))
        return nodes

    def _footer(self, x, y, w, h=56):
        t = self.theme; nodes = []
        nodes.append(Node(x=x, y=y, w=w, h=h, paint=lambda cr, n, s: (gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, 0, (t.deep[0], t.deep[1], t.deep[2], 0.55 if t.dark else 0.5)), cr.set_source_rgba(*t.border), cr.rectangle(n.x, n.y, n.w, 1), cr.fill())))
        def user(cr, n, s):
            p_button(t, 8)(cr, n, s)
            gfx.circle(cr, n.x + 22, n.y + n.h / 2, 14, t.accent_soft); gfx.glyph(cr, "user", n.x + 22, n.y + n.h / 2, 16, t.accent)
            gfx.text(cr, self.user or "Account", n.x + 44, n.y + n.h / 2, 13, t.fg, 500, family=t.font)
        nodes.append(Node(id="user", x=x + 16, y=y + 8, w=170, h=h - 16, paint=user, radius=8, on_click=lambda n: (self.spawn("carpatic-settings"), self.close()), tooltip="Account settings"))
        def btn(id_, g, bx, tip, cmd):
            def p(cr, n, s): p_button(t, 8)(cr, n, s); gfx.glyph(cr, g, n.x + n.w / 2, n.y + n.h / 2, 18, t.fg)
            return Node(id=id_, x=bx, y=y + 8, w=40, h=h - 16, paint=p, radius=8, on_click=lambda n: (self.spawn(*cmd), self.close()), tooltip=tip)
        nodes.append(btn("settings", "gear", x + w - 16 - 40 * 3 - 4, "Settings", ["carpatic-settings"]))
        nodes.append(btn("lock", "lock", x + w - 16 - 40 * 2 - 2, "Lock", ["carpatic-lock"]))
        nodes.append(btn("power", "power", x + w - 16 - 40, "Power", ["carpatic-powermenu"]))
        return nodes

    # ------------------------------------------------------------------ build
    def build(self):
        self.entry_rect = None
        if self.look == "win": return self._build_win()
        if self.look == "twopane": return self._build_two()
        return self._build_launchpad()

    def _results(self, x, y, w, h, grp="res"):
        t = self.theme; nodes = []; res = search_apps(self.apps, self.query)
        g = self.groups.get(grp) or Group(x, y, w, h); self.groups[grp] = g; g.x, g.y, g.w, g.h = x, y, w, h
        cy = y
        if not res:
            nodes.append(Node(x=x, y=y + 30, w=w, h=60, paint=lambda cr, n, s: (gfx.text(cr, f"No apps match “{self.query}”", n.x + n.w / 2, n.y + 10, 13.5, t.fg_muted, 500, "c", family=t.font),
                                                                          gfx.text(cr, "Press Enter to run it as a command.", n.x + n.w / 2, n.y + 32, 12, t.fg_subtle, 400, "c", family=t.font))))
            g.content_h = 0; return nodes
        nodes.append(Node(x=x, y=cy, w=w, h=26, paint=lambda cr, n, s: gfx.text(cr, "Best match" if True else "", n.x + 6, n.y + 13, 12, t.fg_muted, 600, family=t.font), group=grp)); cy += 28
        for i, a in enumerate(res[:30]):
            nodes.append(self._app_row(a, x, cy, w - 8, 46, 32, sub="App", group=grp)); cy += 48
        g.content_h = cy - y
        return nodes

    def _build_win(self):
        t = self.theme; W, H = self.W, self.H; pad = 28; nodes = []; cw = W - 2 * pad
        nodes.append(self._search_box(pad, 24, cw, 40))
        top = 24 + 40 + 20; foot_h = 56; body_h = H - foot_h - top
        if self.query:
            nodes += self._results(pad - 6, top, cw + 12, body_h); nodes += self._footer(0, H - foot_h, W, foot_h); return nodes
        if self.page == "all":
            nodes += self._header("All apps", pad, top, cw, ("Back", lambda: self._go("home")))
            g = self.groups.get("all") or Group(pad - 6, top + 34, cw + 12, body_h - 34); self.groups["all"] = g; g.x, g.y, g.w, g.h = pad - 6, top + 34, cw + 12, body_h - 34
            cy = top + 34
            for L, items in letter_groups(self.apps):
                nodes.append(Node(x=pad, y=cy, w=cw, h=28, paint=lambda cr, n, s, L=L: gfx.text(cr, L, n.x + 8, n.y + n.h / 2, 13, t.accent, 700, family=t.font), group="all")); cy += 30
                for a in items: nodes.append(self._app_row(a, pad - 2, cy, cw + 4, 42, 28, group="all")); cy += 42
                cy += 6
            g.content_h = cy - (top + 34); nodes += self._footer(0, H - foot_h, W, foot_h); return nodes
        nodes += self._header("Pinned", pad, top, cw, ("All apps", lambda: self._go("all")))
        cols = 6; tw = cw / cols; th = 84; y = top + 34
        for i, a in enumerate(self.pinned[:18]):
            r, c = divmod(i, cols); nodes.append(self._app_tile(a, pad + c * tw, y + r * (th + 4), tw - 4, th, 32))
        rows = (min(len(self.pinned), 18) + cols - 1) // cols; y += rows * (th + 4) + 12
        nodes += self._header("Recommended", pad, y, cw); y += 34
        rec = [(a.name, a, None) for a in self.recent_apps] + [(f[0], None, f[1]) for f in self.files]
        slots = 6; colw = cw / 2
        for i, (title, app, path) in enumerate(rec[:slots]):
            r, c = divmod(i, 2); x = pad + c * colw; yy = y + r * 52
            if app: nodes.append(self._app_row(app, x, yy, colw - 6, 48, 32, sub="Recently used"))
            else: nodes.append(self._file_row(title, path, x, yy, colw - 6))
        # a new account has no history: fill the free slots with everyday apps that are installed but not pinned, so the menu is never a blank page
        if len(rec) < slots:
            have = {a.id for a in self.pinned} | {a.id for a in self.recent_apps}
            sugg = [a for n_ in SUGGESTED_NAMES for a in self.apps if a.name == n_ and a.id not in have]
            for j, app in enumerate(sugg[:slots - len(rec)]):
                i = len(rec[:slots]) + j; r, c = divmod(i, 2)
                nodes.append(self._app_row(app, pad + c * colw, y + r * 52, colw - 6, 48, 32, sub="Suggested"))
        if not rec and not self.apps:
            nodes.append(Node(x=pad, y=y + 12, w=cw, h=60, paint=lambda cr, n, s: gfx.text(cr, "Apps and files you use will show up here.", n.x + 6, n.y + 16, 13, t.fg_muted, 400, family=t.font)))
        nodes += self._footer(0, H - foot_h, W, foot_h)
        return nodes

    def _file_row(self, title, path, x, y, w):
        t = self.theme
        def paint(cr, n, s):
            p_button(t, 8)(cr, n, s)
            gfx.fill_rrect(cr, n.x + 10, n.y + 8, 32, 32, 8, t.accent_soft); gfx.glyph(cr, "folder" if os.path.isdir(path) else "edit", n.x + 26, n.y + 24, 16, t.accent)
            gfx.text(cr, title, n.x + 54, n.y + n.h / 2 - 8, 13, t.fg, 500, maxw=n.w - 64, family=t.font)
            gfx.text(cr, os.path.dirname(path).replace(os.path.expanduser("~"), "~"), n.x + 54, n.y + n.h / 2 + 9, 11.5, t.fg_muted, 400, maxw=n.w - 64, family=t.font)
        return Node(id="file:" + path, x=x, y=y, w=w, h=48, paint=paint, radius=8, on_click=lambda n: (self.spawn("xdg-open", path), self.close()))

    def _go(self, page):
        self.page = page; self.groups = {}; self.refresh()

    # ------------------------------------------------------------------ two-pane (Zen / Kylin)
    def _build_two(self):
        t = self.theme; W, H = self.W, self.H; nodes = []
        left = 312; side = 56; mid = W - left - side - 2
        nodes.append(Node(x=left, y=0, w=1, h=H, paint=lambda cr, n, s: (cr.set_source_rgba(*t.border), cr.rectangle(n.x, n.y, 1, n.h), cr.fill())))
        nodes.append(Node(x=W - side - 1, y=0, w=1, h=H, paint=lambda cr, n, s: (cr.set_source_rgba(*t.border), cr.rectangle(n.x, n.y, 1, n.h), cr.fill())))
        nodes.append(self._search_box(16, 14, left - 32, 40))
        g = self.groups.get("list") or Group(8, 66, left - 16, H - 74); self.groups["list"] = g; g.x, g.y, g.w, g.h = 8, 66, left - 16, H - 74
        cy = 66
        if self.query:
            res = search_apps(self.apps, self.query)
            for a in res[:40]: nodes.append(self._app_row(a, 8, cy, left - 24, 40, 28, group="list")); cy += 40
            if not res:
                nodes.append(Node(x=8, y=90, w=left - 16, h=40, paint=lambda cr, n, s: gfx.text(cr, "No matching apps", n.x + n.w / 2, n.y + 20, 13, t.fg_muted, 500, "c", family=t.font)))
        else:
            for L, items in letter_groups(self.apps):
                nodes.append(Node(x=16, y=cy, w=left - 40, h=30, paint=lambda cr, n, s, L=L: gfx.text(cr, L, n.x + 4, n.y + n.h / 2, 12, t.accent, 700, family=t.font), group="list")); cy += 30
                for a in items: nodes.append(self._app_row(a, 8, cy, left - 24, 40, 28, group="list")); cy += 40
        g.content_h = cy - 66
        # favourites
        x0 = left + 16; cw = mid - 32
        tabs = ["Favourites", "Recent"]
        def tabp(cr, n, s):
            gfx.text(cr, "Favourites", n.x + 4, n.y + n.h / 2, 14, t.fg, 600, family=t.font)
        nodes.append(Node(x=x0, y=16, w=cw, h=32, paint=tabp))
        cols = max(3, int(cw // 92)); tw = cw / cols; th = 100; y = 60
        for i, a in enumerate(self.pinned[:15]):
            r, c = divmod(i, cols); nodes.append(self._app_tile(a, x0 + c * tw, y + r * (th + 4), tw - 4, th, 48))
        rows = (min(15, len(self.pinned)) + cols - 1) // cols; y += rows * (th + 4) + 12
        if self.recent_apps or self.files:
            nodes.append(Node(x=x0, y=y, w=cw, h=28, paint=lambda cr, n, s: gfx.text(cr, "Recent", n.x + 4, n.y + n.h / 2, 14, t.fg, 600, family=t.font))); y += 32
            for a in self.recent_apps[:3]:
                if y + 44 > H - 8: break
                nodes.append(self._app_row(a, x0 - 6, y, cw + 6, 44, 28)); y += 44
        # side buttons
        sx = W - side + 8; items = [("user", "user", "Account", ["carpatic-settings"]), ("files", "folder", "Files", ["thunar"]), ("settings", "gear", "Settings", ["carpatic-settings"]), ("power", "power", "Power", ["carpatic-powermenu"])]
        for k, (id_, g_, tip, cmd) in enumerate(items):
            by = 16 + k * 40 if k < 3 else H - 56
            def p(cr, n, s, g_=g_): p_button(t, 4 if self.skin == "kylin" else 8)(cr, n, s); gfx.glyph(cr, g_, n.x + n.w / 2, n.y + n.h / 2, 18, t.fg)
            nodes.append(Node(id="side:" + id_, x=sx, y=by, w=40, h=36, paint=p, radius=6, tooltip=tip, on_click=lambda n, c=cmd: (self.spawn(*c), self.close())))
        return nodes

    # ------------------------------------------------------------------ launchpad
    def _build_launchpad(self):
        t = self.theme; W, H = self.W, self.H; nodes = []
        sw = min(480, W - 80); nodes.append(self._search_box((W - sw) // 2, 56, sw, 40))
        cols = max(4, min(9, int((W - 160) // 150))); tw = 150; th = 128
        gx = (W - cols * tw) // 2
        g = self.groups.get("pad") or Group(0, 120, W, H - 120); self.groups["pad"] = g; g.x, g.y, g.w, g.h = 0, 120, W, H - 120
        apps = search_apps(self.apps, self.query) if self.query else self.apps
        for i, a in enumerate(apps):
            r, c = divmod(i, cols)
            def paint(cr, n, s, a=a):
                if s.hover or s.press: gfx.fill_rrect(cr, n.x + 12, n.y, n.w - 24, n.h, 14, t.press if s.press else t.hover)
                surf = gfx.load_icon(a.icon, 64) if a.icon else None
                ix, iy = n.x + n.w / 2 - 32, n.y + 12
                if surf is not None: cr.set_source_surface(surf, ix, iy); cr.paint()
                else: gfx.app_letter_icon(cr, ix, iy, 64, a.name, t.accent_soft, t.accent)
                gfx.text(cr, a.name, n.x + n.w / 2, iy + 64 + 18, 13, t.fg, 500, "c", maxw=n.w - 16, family=t.font)
            nodes.append(Node(id=f"app:{a.id}", x=gx + c * tw, y=130 + r * th, w=tw, h=th - 8, paint=paint, radius=14, group="pad", on_click=lambda n, a=a: self.launch(a)))
        rows = (len(apps) + cols - 1) // cols; g.content_h = rows * th + 20
        if not apps:
            nodes.append(Node(x=0, y=200, w=W, h=40, paint=lambda cr, n, s: gfx.text(cr, "No matching apps", n.x + n.w / 2, n.y + 20, 15, t.fg_muted, 500, "c", family=t.font)))
        return nodes


def make_start(theme, look, args):
    import gi
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, Gtk
    d = Gdk.Display.get_default(); m = d.get_primary_monitor() or d.get_monitor(0); g = m.get_geometry()
    if args.fake:
        from .tasks import App
        names = ["Files", "Firefox", "Terminal", "Settings", "Store", "Text Editor", "Music", "Calculator", "Image Viewer", "Videos", "Calendar", "Notes", "Weather", "Camera", "Archive Manager", "Disks", "Clocks", "Maps", "Photos", "Contacts", "Document Viewer", "System Monitor", "Backups", "Fonts"]
        icons = ["system-file-manager", "firefox", "utilities-terminal", "preferences-system", "system-software-install", "accessories-text-editor", "multimedia-audio-player", "accessories-calculator", "image-x-generic", "video-x-generic",
                 "x-office-calendar", "accessories-text-editor", "weather-clear", "camera-photo", "package-x-generic", "drive-harddisk", "appointment-soon", "applications-internet", "image-x-generic", "x-office-address-book", "x-office-document", "utilities-system-monitor", "drive-harddisk", "preferences-desktop-font"]
        cat = {n.lower().replace(" ", "-"): App(n.lower().replace(" ", "-"), n, n.lower(), i) for n, i in zip(names, icons)}
        v = StartView(theme, look, cat, lambda a: None, lambda: Gtk.main_quit(), (int(g.width / uiscale.factor()), int(g.height / uiscale.factor())), pinned=list(cat)[:18], recent=["music", "notes", "weather"],
                      files=[("Trip plan.odt", "/home/user/Documents/Trip plan.odt", ""), ("bucegi.jpg", "/home/user/Pictures/bucegi.jpg", ""), ("budget.ods", "/home/user/Documents/budget.ods", "")], user="Ana", skin="win")
    else:
        cat = tk.catalogue()
        v = StartView(theme, look, cat, lambda a: subprocess.Popen(tk.exec_argv(a.exec), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True),
                      lambda: Gtk.main_quit(), (int(g.width / uiscale.factor()), int(g.height / uiscale.factor())), skin="kylin" if look == "twopane" and "kylin" in (os.environ.get("CARPATIC_STYLE", "")) else "win")
    return v
