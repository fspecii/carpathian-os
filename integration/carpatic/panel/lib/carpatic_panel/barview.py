"""BarView: lays out and paints one panel surface (bar or dock) for any design, horizontal or vertical.

The view never talks to X: it reads a `ctx` (task list, clock text, indicator state, tags ...) and calls back into `ctx` for actions. That keeps it
renderable offscreen for the design sheets and testable with fakes."""
import datetime as dt
import math
from . import gfx, designs
from .kit import View, Node, p_button
from .theme import with_alpha, mix


def network_glyph(ctx, wlv):
    """(glyph, level) for the tray: a cable on a machine without Wi-Fi or when the cable is the connection, bars otherwise."""
    if not ctx.has_wifi or (ctx.wired and wlv == 0): return ("ethernet", 0)
    return ("wifi" if ctx.wifi_on else "wifi_off", wlv)


class Ctx:
    """Data + actions a BarView needs. The panel app and the test harness each provide one."""
    tasks = []; tray_w = 0; notif_count = 0; dnd = False
    wifi_level = 3; wifi_on = True; wired = False; has_wifi = True; vol = 40; muted = False; battery = None; charging = False
    tags = (0, 0, []); occupied = frozenset(); focus_app = ""; focus_title = ""; flyout_open = None
    def now(self): return dt.datetime.now()
    def icon(self, task, size): return None
    def activate(self, task): pass
    def task_menu(self, task, node, ev): pass
    def task_middle(self, task): pass
    def hover_task(self, task, node): pass
    def leave_task(self): pass
    def flyout(self, name, node): pass
    def show_desktop(self): pass
    def switch_tag(self, n): pass
    def panel_menu(self, ev, node): pass
    def reorder(self, task, new_index): pass
    def overflow(self, tasks, node): pass
    def toggle_tray_item(self, *a): pass


def draw_logo(cr, cx, cy, s, c1, c2):
    """The Carpatic mark: two ridges and a sun."""
    cr.save(); cr.translate(cx - s / 2, cy - s / 2); cr.scale(s / 24, s / 24)
    cr.set_source_rgba(*c2); cr.arc(17.2, 7.2, 2.6, 0, gfx.TAU); cr.fill()
    cr.set_source_rgba(*c1)
    cr.move_to(1.5, 20.5); cr.line_to(9.2, 6.2); cr.line_to(13.2, 13.4); cr.line_to(15.4, 9.8); cr.line_to(22.5, 20.5); cr.close_path(); cr.fill()
    cr.restore()


class BarView(View):
    framed = True

    def __init__(self, theme, surface, opts, ctx, length, monitor_h=900):
        super().__init__(theme)
        self.s = surface; self.o = opts; self.ctx = ctx
        self.length = length          # size along the main axis (px)
        self.cr_ = gfx._scratch()
        self.horiz = surface.horizontal
        self.T = surface.thickness; self.margin = surface.margin
        self.rects = {}
        self.drag = None              # (task key, current main-axis offset)
        self.I = opts["icon_size"]
        self.style = surface.style
        self.radius = surface.radius
        self.hover_key = None
        self.W, self.H = (length, self.T + self.margin) if self.horiz else (self.T + self.margin, length)
        self.group_len = {}

    def size(self): return (self.W, self.H)

    def natural_length(self):
        """Main-axis length a centred dock needs for its buttons (docks shrink-wrap their content)."""
        gap = {"mac-dock": 8, "floating": 6, "ubuntu-dock": 4}.get(self.style, 4)
        n = len(self.ctx.tasks)
        return int(sum(self.task_len(t) for t in self.ctx.tasks) + gap * max(0, n - 1) + 2 * 14 + 2 * self.margin)

    def set_length(self, length):
        self.length = length
        self.W, self.H = (length, self.T + self.margin) if self.horiz else (self.T + self.margin, length)

    # ------------------------------------------------------------------ container (the visible bar, inside the window)
    def container(self):
        """Rectangle of the visible bar inside the window (floating designs keep an invisible margin that is shaped away)."""
        m = self.margin; e = self.s.edge; T = self.T
        if self.horiz:
            return (m, (m if e == "top" else 0), self.W - 2 * m, T)
        return ((m if e == "left" else 0), m, T, self.H - 2 * m)

    def container_radius(self): return self.radius if (self.margin or self.s.style in ("mac-dock", "floating")) else 0

    def shape_rects(self):
        x, y, w, h = self.container(); return (x, y, w, h, self.container_radius())

    def paint_container(self, cr, alpha=1.0):
        t = self.theme; x, y, w, h = self.container(); r = self.container_radius(); st = self.style
        fill = t.surface
        if st in ("mac-dock", "floating"): fill = mix(t.surface, t.fg, 0.04 if t.dark else 0.0)
        if st == "mac-menubar": fill = t.surface
        cr.save(); gfx.rrect(cr, x, y, w, h, r); cr.set_source_rgba(fill[0], fill[1], fill[2], alpha); cr.fill(); cr.restore()
        if r or st in ("mac-dock", "floating", "zorin") and self.margin:
            gfx.stroke_rrect(cr, x, y, w, h, r, t.border_strong, 1)
        else:
            e = self.s.edge; cr.set_source_rgba(*t.border_strong)
            if e == "bottom": cr.rectangle(x, y, w, 1)
            elif e == "top": cr.rectangle(x, y + h - 1, w, 1)
            elif e == "left": cr.rectangle(x + w - 1, y, 1, h)
            else: cr.rectangle(x, y, 1, h)
            cr.fill()

    def paint_frame(self, cr, w, h, alpha=1.0): self.paint_container(cr, alpha)

    # ------------------------------------------------------------------ measuring
    def text_w(self, s, px, weight=400, tnum=False): return gfx.text_size(self.cr_, s, px, weight, self.theme.font, tnum)[0]

    def clock_lines(self):
        n = self.ctx.now(); fmt = self.o.get("clock_format") or "%H:%M"
        if str(self.o.get("clock_24h", "1")).lower() in ("0", "false", "no", "off") and fmt == "%H:%M": fmt = "%-I:%M %p"
        l1 = n.strftime(fmt)
        two = self.o.get("date_in_clock") == "on" and self.horiz
        l2 = n.strftime("%x") if two else ""
        return l1, l2

    def item_len(self, name):
        T, I = self.T, self.I; st = self.style
        if name in ("start", "search", "taskview", "widgets"): return T - (8 if st != "kylin" else 0) if st != "classic" else T
        if name == "logo": return 36
        if name == "sep": return 9
        if name == "tray": return self.ctx.tray_w + (8 if self.ctx.tray_w else 0)
        if name == "quick": return 18 * 3 + 8 * 2 + 20 if st != "ubuntu-top" else 18 * 4 + 8 * 3 + 20
        if name == "bell": return 36
        if name == "showdesktop": return {"kylin": 17, "zorin": 8, "win11": 10}.get(st, 8) + 2
        if name == "clock":
            l1, l2 = self.clock_lines()
            return max(self.text_w(l1, 13 if not l2 else 12.5, 500, True), self.text_w(l2, 11.5, 400, True)) + 20
        if name == "appname": return self.text_w(self.ctx.focus_app or "Desktop", 13.5, 700) + 20
        if name == "activities": return self.text_w("Activities", 13, 600) + 28
        if name == "tags": return (4 + 26 * max(1, self.ctx.tags[0]) + 4) if self.style == "minimal" else (8 + 16 * max(1, self.ctx.tags[0]) + 10)
        if name == "apps": return T
        if name == "title": return 0
        return 0

    def task_len(self, task):
        st = self.style; T, I = self.T, self.I
        if st == "classic" or self.o.get("labels") == "on" and st in ("win11", "zorin", "kylin"):
            return 160 if st != "minimal" else 150
        if st == "minimal": return min(220, 28 + self.text_w(task.name, 12.5, 500))
        if st == "mac-dock": return I + 10
        if st == "ubuntu-dock": return I + 12
        if st == "floating": return I + 10
        if st == "kylin": return T
        if st == "zorin": return I + 20
        return I + 20     # win11

    # ------------------------------------------------------------------ layout
    def rect(self, pos, ln, off=0, thick=None):
        """Main-axis interval -> window rectangle, within the container."""
        cx, cy, cw, ch = self.container()
        thick = thick if thick is not None else (ch if self.horiz else cw)
        if self.horiz: return (cx + pos, cy + off, ln, thick - 2 * off)
        return (cx + off, cy + pos, thick - 2 * off, ln)

    def build(self):
        s, ctx = self.s, self.ctx; self.rects = {}
        nodes = []
        cx, cy, cw, ch = self.container()
        main = cw if self.horiz else ch
        pad = 6 if self.style != "mac-dock" else 10
        edge_pad = 8 if self.style in ("win11", "classic", "kylin", "zorin", "minimal") else pad
        lens = {g: [] for g in ("left", "center", "right")}
        tasks_len = 0
        tasks = ctx.tasks
        gap = {"win11": 4, "classic": 2, "kylin": 4, "zorin": 4, "mac-dock": 8, "ubuntu-dock": 4, "floating": 6, "minimal": 2}.get(self.style, 4)
        group_of = {}
        for gname in ("left", "center", "right"):
            for it in getattr(s, gname): group_of[it] = gname
        # right group
        def group_len(items):
            L = 0
            for i, it in enumerate(items):
                ln = tasks_total if it == "tasks" else self.item_len(it)
                L += ln + (gap if i else 0) if ln else 0
            return L
        tasks_total = 0
        right_len = 0
        for i, it in enumerate(s.right):
            ln = self.item_len(it)
            if ln: right_len += ln + (2 if right_len else 0)
        left_fixed = sum(self.item_len(it) + 2 for it in s.left if it != "tasks" and it != "title") + 0
        # tasks budget
        free = main - 2 * edge_pad - right_len - left_fixed - (self.item_len("start") if "start" in s.center else 0)
        center_fixed = sum(self.item_len(it) + gap for it in s.center if it != "tasks")
        n = len(tasks)
        per = [self.task_len(t) for t in tasks]
        total = sum(per) + gap * max(0, n - 1)
        avail = (main - 2 * (edge_pad + max(right_len, 0) + 12) - center_fixed) if s.center else (main - 2 * edge_pad - left_fixed - right_len - 12)
        self.vis_tasks, self.hidden_tasks = list(tasks), []
        self.center_left = False
        if s.center and total > avail and n:          # too wide to stay centred: use the whole free width, left aligned
            avail = main - 2 * edge_pad - right_len - 12 - center_fixed; self.center_left = True
        if total > avail and n:
            minw = 30 if per[0] < 80 else 64
            scale = max(0.2, (avail - gap * max(0, n - 1)) / max(1, sum(per))); per = [max(int(p * scale), minw) for p in per]
            total = sum(per) + gap * max(0, n - 1)
            if total > avail:                                  # still too many: keep what fits and add a "+N" menu button
                ovf = 34
                k = max(1, int((avail - ovf + gap) // (minw + gap)))
                vis = list(tasks[:k]); rest = list(tasks[k:])
                act = next((t for t in rest if t.active or t.urgent), None)
                if act is not None: rest.remove(act); rest.insert(0, vis.pop()); vis.append(act)
                self.vis_tasks, self.hidden_tasks = vis, rest
                per = [minw] * len(vis) + [ovf]; total = sum(per) + gap * len(vis)
        tasks_total = total
        # positions
        place = {}
        pos = edge_pad
        for it in s.left:
            if it == "tasks":
                place["tasks"] = pos; pos += tasks_total + gap
            elif it == "title":
                place["title"] = pos
            else:
                ln = self.item_len(it)
                if ln: place[it] = pos; pos += ln + 2
        if s.center:
            clen = 0
            for it in s.center:
                ln = tasks_total if it == "tasks" else self.item_len(it)
                if ln: clen += ln + gap
            clen -= gap if clen else 0
            start = (main - clen) / 2
            start = max(start, pos) if s.left else start
            if self.center_left: start = edge_pad
            pos2 = start
            for it in s.center:
                ln = tasks_total if it == "tasks" else self.item_len(it)
                if ln: place[it] = pos2; pos2 += ln + gap
            self.center_span = (start, clen)
        pos = main - edge_pad
        for it in reversed(s.right):
            ln = self.item_len(it)
            if ln: pos -= ln; place[it] = pos; pos -= 2
        if "title" in s.left and "title" in place:
            end = min([v for k, v in place.items() if k in s.right] or [main - edge_pad]) - 8
            self.title_span = (place["title"], max(0, end - place["title"]))
        # build nodes per item
        for it, p in place.items():
            if it == "tasks": nodes += self._tasks_nodes(p, per, gap)
            else: nodes += self._item_nodes(it, p)
        # container context menu (right click on empty space)
        bg = Node(id=None, x=0, y=0, w=self.W, h=self.H, paint=None, on_context=lambda n, ev: ctx.panel_menu(ev, n))
        bg.id = "bg"; bg.focusable = False
        self.groups = {}
        return [bg] + nodes

    # ------------------------------------------------------------------ simple items
    def _node(self, id_, pos, ln, off=0, thick=None, **kw):
        x, y, w, h = self.rect(pos, ln, off, thick)
        n = Node(id=id_, x=x, y=y, w=w, h=h, **kw)
        self.rects[id_] = (x, y, w, h)
        return n

    def _btn_paint(self, glyph_name, size=20, active_fn=None, radius=6, color=None, extra=None):
        t = self.theme
        def paint(cr, n, st):
            act = active_fn() if active_fn else False
            if act: gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, radius, t.hover if False else (t.fg[0], t.fg[1], t.fg[2], 0.10))
            p_button(t, radius)(cr, n, st)
            sc = 0.9 if st.press else 1.0
            gfx.glyph(cr, glyph_name, n.x + n.w / 2, n.y + n.h / 2, size * sc, color or t.fg)
            if extra: extra(cr, n, st)
        return paint

    def _item_nodes(self, it, pos):
        t, ctx, st = self.theme, self.ctx, self.style
        T = self.T; out = []
        vpad = 4 if st in ("win11", "zorin", "kylin", "classic") else 3
        if it == "start":
            ln = self.item_len("start")
            def start_paint(cr, n, s):
                p_button(t, 6 if st != "classic" else 0)(cr, n, s)
                sz = 22 if st != "ubuntu-top" else 18
                draw_logo(cr, n.x + n.w / 2, n.y + n.h / 2, sz * (0.92 if s.press else 1), t.accent, t.ember)
            out.append(self._node("start", pos, ln, vpad, on_click=lambda n: ctx.flyout("start", n), paint=start_paint, radius=6, tooltip="Start"))
        elif it in ("search", "taskview", "widgets"):
            g = {"search": "search", "taskview": "taskview", "widgets": "widgets"}[it]
            ln = self.item_len(it)
            out.append(self._node(it, pos, ln, vpad, on_click=lambda n, i=it: ctx.flyout(i, n), paint=self._btn_paint(g, 20, color=t.fg), radius=6, tooltip={"search": "Search", "taskview": "Task view", "widgets": "Widgets"}[it]))
        elif it == "sep":
            out.append(self._node(None, pos, 9, 0, paint=lambda cr, n, s: (cr.set_source_rgba(*t.border_strong), cr.rectangle(n.x + n.w / 2, n.y + n.h * 0.25, 1, n.h * 0.5) if self.horiz else cr.rectangle(n.x + n.w * .25, n.y + n.h / 2, n.w * .5, 1), cr.fill())))
        elif it == "tray":
            self.rects["tray"] = self.rect(pos, self.item_len("tray"), 0)
        elif it == "quick":
            out.append(self._quick_node(pos))
        elif it == "bell":
            ln = self.item_len("bell")
            def extra(cr, n, s):
                c = ctx.notif_count
                if c > 0 and not ctx.dnd:
                    gfx.circle(cr, n.x + n.w / 2 + 8, n.y + n.h / 2 - 8, 7, t.danger)
                    gfx.text(cr, str(min(c, 9)) + ("+" if c > 9 else ""), n.x + n.w / 2 + 8, n.y + n.h / 2 - 8, 9, (1, 1, 1, 1), 700, "c", tnum=True)
            out.append(self._node("bell", pos, ln, vpad, on_click=lambda n: ctx.flyout("calendar", n), paint=self._btn_paint("bell_off" if ctx.dnd else "bell", 18, active_fn=lambda: ctx.flyout_open == "calendar", extra=extra), radius=6, tooltip="Notifications"))
        elif it == "clock":
            out.append(self._clock_node(pos))
        elif it == "showdesktop":
            ln = self.item_len("showdesktop")
            def sd(cr, n, s):
                if s.hover or s.press: gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, 0, t.press if s.press else t.hover)
                cr.set_source_rgba(*t.border_strong); cr.rectangle(n.x, n.y + (6 if st == "win11" else 0), 1, n.h - (12 if st == "win11" else 0)); cr.fill()
            out.append(self._node("showdesktop", pos, ln, 0, on_click=lambda n: ctx.show_desktop(), paint=sd, radius=0, tooltip="Show desktop"))
        elif it == "logo":
            out.append(self._node("logo", pos, 36, 2, on_click=lambda n: ctx.flyout("start", n), paint=lambda cr, n, s: (p_button(t, 5)(cr, n, s), draw_logo(cr, n.x + n.w / 2, n.y + n.h / 2, 15, t.fg, t.fg)), radius=5, tooltip="Carpatic"))
        elif it == "appname":
            ln = self.item_len("appname")
            out.append(self._node("appname", pos, ln, 2, paint=lambda cr, n, s: gfx.text(cr, ctx.focus_app or "Desktop", n.x + 10, n.y + n.h / 2, 13.5, t.fg, 700, maxw=n.w - 12), radius=5))
            title = ctx.focus_title
        elif it == "activities":
            ln = self.item_len("activities")
            def act(cr, n, s):
                gfx.fill_rrect(cr, n.x, n.y + 2, n.w, n.h - 4, (n.h - 4) / 2, t.press if s.press else (t.hover if s.hover else (t.fg[0], t.fg[1], t.fg[2], 0.0)))
                gfx.text(cr, "Activities", n.x + n.w / 2, n.y + n.h / 2, 13, t.fg, 600, "c")
            out.append(self._node("activities", pos, ln, 0, on_click=lambda n: ctx.flyout("start", n), paint=act, radius=12, tooltip="Activities"))
        elif it == "tags":
            n_, cur, names = ctx.tags
            mini = st == "minimal"
            def tp(cr, n, s):
                occ = ctx.occupied
                for i in range(max(1, n_)):
                    if mini:
                        x = n.x + 4 + i * 26
                        if i == cur: gfx.fill_rrect(cr, x + 1, n.y + 4, 24, n.h - 8, 5, t.accent); col = t.accent_fg
                        else: col = t.fg_muted
                        gfx.text(cr, names[i] if i < len(names) and names[i] else str(i + 1), x + 13, n.y + n.h / 2, 12, col, 700 if i == cur else 500, "c", tnum=True)
                    else:   # pager dots: the current workspace is a wide pill, workspaces with windows are filled, empty ones are rings
                        x = n.x + 8 + i * 16; cy = n.y + n.h / 2
                        if i == cur: gfx.fill_rrect(cr, x - 3, cy - 3.5, 14, 7, 3.5, t.accent)
                        elif i in occ: gfx.fill_rrect(cr, x, cy - 3, 6, 6, 3, (t.fg[0], t.fg[1], t.fg[2], 1.0))
                        else: gfx.fill_rrect(cr, x, cy - 3, 6, 6, 3, (t.fg_muted[0], t.fg_muted[1], t.fg_muted[2], 0.45))
            step = 26 if mini else 16; off = 4 if mini else 8
            nd = self._node("tags", pos, self.item_len("tags"), 0, paint=tp, on_click=lambda n: None, radius=5, tooltip="Workspaces")
            nd.on_press = lambda n, lx, ly: ctx.switch_tag(max(0, min(max(1, ctx.tags[0]) - 1, int((lx - off + (0 if mini else 3)) // step))))
            out.append(nd)
        elif it == "title":
            sp = getattr(self, "title_span", (pos, 200))
            out.append(self._node(None, sp[0], sp[1], 0, paint=lambda cr, n, s: gfx.text(cr, ctx.focus_title, n.x + 8, n.y + n.h / 2, 12.5, t.fg_muted, 500, maxw=n.w - 8) if self.horiz else None))
        elif it == "apps":
            out.append(self._node("apps", pos, self.item_len("apps"), 6, on_click=lambda n: ctx.flyout("start", n), paint=self._btn_paint("apps", 22), radius=8, tooltip="Show applications"))
        return out

    def _quick_node(self, pos):
        t, ctx, st = self.theme, self.ctx, self.style
        ln = self.item_len("quick"); vpad = 4 if st not in ("mac-menubar", "ubuntu-top") else 2
        wlv = ctx.wifi_level if ctx.wifi_on else 0
        def paint(cr, n, s):
            open_ = ctx.flyout_open == "quick"
            rad = 6 if st not in ("ubuntu-top",) else n.h / 2
            if open_ or st == "ubuntu-top": gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, rad, (t.fg[0], t.fg[1], t.fg[2], 0.14 if open_ else 0.07))
            p_button(t, rad)(cr, n, s)
            gs = 16 if st not in ("mac-menubar",) else 15
            items = [network_glyph(ctx, wlv)]
            items.append(("volume_mute" if (ctx.muted or ctx.vol == 0) else "volume", 2 if ctx.vol > 33 else 1))
            if ctx.battery is not None: items.append(("battery", ctx.battery))
            if st == "ubuntu-top": items.append(("power", 0))
            if self.horiz:
                cx = n.x + (n.w - (len(items) * gs + (len(items) - 1) * 8)) / 2 + gs / 2
                for g, lv in items:
                    gfx.glyph(cr, g, cx, n.y + n.h / 2, gs, t.fg, level=lv, charging=ctx.charging); cx += gs + 8
            else:
                cy = n.y + 10
                for g, lv in items: gfx.glyph(cr, g, n.x + n.w / 2, cy, gs, t.fg, level=lv); cy += gs + 8
        return self._node("quick", pos, ln, vpad, on_click=lambda n: ctx.flyout("quick", n), paint=paint, radius=6, tooltip="Quick settings")

    def _clock_node(self, pos):
        t, ctx, st = self.theme, self.ctx, self.style
        l1, l2 = self.clock_lines(); ln = self.item_len("clock")
        two = bool(l2)
        def paint(cr, n, s):
            if ctx.flyout_open == "calendar": gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, 6 if st != "ubuntu-top" else n.h / 2, (t.fg[0], t.fg[1], t.fg[2], 0.10))
            p_button(t, 6 if st != "ubuntu-top" else n.h / 2)(cr, n, s)
            l1_, l2_ = self.clock_lines()
            al = "c" if st in ("ubuntu-top",) else "r"
            x = n.x + n.w / 2 if al == "c" else n.x + n.w - 10
            if l2_:
                gfx.text(cr, l1_, x, n.y + n.h / 2 - 8, 13, t.fg, 500, al, tnum=True); gfx.text(cr, l2_, x, n.y + n.h / 2 + 8, 11.5, t.fg_muted, 400, al, tnum=True)
            else:
                gfx.text(cr, l1_, n.x + n.w / 2, n.y + n.h / 2, 13 if st != "mac-menubar" else 13, t.fg, 500 if st != "mac-menubar" else 500, "c", tnum=True)
        vpad = 3 if st in ("win11", "zorin", "kylin", "classic") else 2
        return self._node("clock", pos, ln, vpad, on_click=lambda n: ctx.flyout("calendar", n), paint=paint, radius=6, tooltip=ctx.now().strftime("%A, %-d %B %Y"))

    # ------------------------------------------------------------------ tasks
    def _tasks_nodes(self, pos, per, gap):
        ctx = self.ctx; out = []; p = pos
        T, I, st = self.T, self.I, self.style
        for i, task in enumerate(self.vis_tasks):
            ln = per[i]
            off = {"win11": 4, "classic": 0, "kylin": 0, "zorin": 3, "mac-dock": 8, "ubuntu-dock": 2, "floating": 6, "minimal": 3}.get(st, 4)
            if st == "ubuntu-dock" or (st in ("mac-dock", "floating") and not self.horiz):
                x, y, w, h = self.rect(p, ln, 6)
            elif st in ("mac-dock", "floating") and self.horiz:
                x, y, w, h = self.rect(p, ln, 0)
                # icon sits in the upper part, indicator in the bottom 8 px
                cx, cy, cw, ch = self.container()
                y, h = cy + (ch - (I + 12)) / 2 - 2, I + 12
            else:
                x, y, w, h = self.rect(p, ln, off)
            node = Node(id="task:" + task.key, x=x, y=y, w=w, h=h, paint=self._task_paint(task), radius=8 if st not in ("classic", "minimal") else 3)
            node.on_click = lambda n, tk=task: ctx.activate(tk)
            node.on_context = lambda n, ev, tk=task: ctx.task_menu(tk, n, ev)
            node.on_middle = lambda n, ev, tk=task: ctx.task_middle(tk)
            node.on_hover = lambda n, tk=task: ctx.hover_task(tk, n)
            node.on_drag = (lambda n, lx, ly, ph, tk=task, idx=i: self._drag(tk, idx, n, lx, ly, ph)) if task.pinned or True else None
            node.on_click = node.on_click
            node.tooltip = task.name
            node.data = task
            self.rects[node.id] = (x, y, w, h)
            out.append(node)
            p += ln + gap
        if self.hidden_tasks:
            x, y, w, h = self.rect(p, per[len(self.vis_tasks)], 6)
            hid = list(self.hidden_tasks); t_ = self.theme
            def ov(cr, n, s_):
                p_button(t_, 6)(cr, n, s_); gfx.text(cr, f"+{len(hid)}", n.x + n.w / 2, n.y + n.h / 2, 12.5, t_.fg_muted, 600, "c", tnum=True)
            on = Node(id="overflow", x=x, y=y, w=w, h=h, paint=ov, radius=6, tooltip="More windows", on_click=lambda n, h_=hid: ctx.overflow(h_, n))
            self.rects["overflow"] = (x, y, w, h); out.append(on)
        return out

    def _drag(self, task, idx, node, lx, ly, ph):
        main = lx if self.horiz else ly
        if ph == "start": self._dstart = main; self.drag = None; return
        d = main - self._dstart
        if ph == "move":
            if abs(d) > 6 or self.drag: self.drag = (task.key, d)
        else:
            if self.drag and task.pinned:
                step = (node.w if self.horiz else node.h) + 4
                new = max(0, min(len([t for t in self.ctx.tasks if t.pinned]) - 1, idx + int(round(d / step))))
                if new != idx: self.ctx.reorder(task, new)
            self.drag = None
            return "drop"

    def _icon(self, cr, task, cx, cy, size):
        surf = self.ctx.icon(task, size)
        t = self.theme
        if surf is not None:
            w = gfx.logical_w(surf); sc = size / max(1, w)      # logical width (icon surfaces carry the UI scale as device scale)
            cr.save(); cr.translate(cx - size / 2, cy - size / 2); cr.scale(sc, sc); cr.set_source_surface(surf, 0, 0)
            cr.paint_with_alpha(0.5 if task.all_minimized else 1.0); cr.restore()
        else:
            gfx.app_letter_icon(cr, cx - size / 2, cy - size / 2, size, task.name, t.surface2, t.fg)

    def _task_paint(self, task):
        t, ctx, st = self.theme, self.ctx, self.style
        I = self.I
        def paint(cr, n, s):
            off = 0
            if self.drag and self.drag[0] == task.key:
                off = self.drag[1]
                if self.horiz: cr.translate(off, -3)
                else: cr.translate(-3, off)
            act = task.active; run = task.running
            urgent = task.urgent
            if st == "win11":
                if act: gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, 6, (t.fg[0], t.fg[1], t.fg[2], 0.10))
                if s.hover or s.press: gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, 6, t.press if s.press else t.hover)
                if urgent: gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, 6, (t.ember[0], t.ember[1], t.ember[2], 0.30))
                self._icon(cr, task, n.x + n.w / 2, n.y + n.h / 2 - (1 if run else 0), I * (0.88 if s.press else 1))
                if run:
                    w = 16 if act else 6
                    gfx.fill_rrect(cr, n.x + n.w / 2 - w / 2, n.y + n.h - 3.5, w, 3, 1.5, t.accent if act else t.fg_subtle)
                self._badge(cr, task, n)
            elif st == "classic":
                lab = self.o.get("labels") == "on" or n.w > 80
                if act: gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, 0, (t.fg[0], t.fg[1], t.fg[2], 0.14))
                if s.hover or s.press: gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, 0, t.press if s.press else t.hover)
                if urgent: gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, 0, (t.ember[0], t.ember[1], t.ember[2], 0.35))
                self._icon(cr, task, n.x + 8 + I / 2 if lab else n.x + n.w / 2, n.y + n.h / 2 - 1, I)
                if lab and n.w > 60: gfx.text(cr, task.windows[0].title if task.windows else task.name, n.x + 8 + I + 8, n.y + n.h / 2, 12.5, t.fg, 400, maxw=n.w - I - 24)
                if run: gfx.fill_rrect(cr, n.x + 2, n.y + n.h - 3, n.w - 4, 2, 0, t.accent if act else t.fg_subtle)
            elif st == "kylin":
                if act or s.hover or s.press:
                    a = 0.20 if s.press else 0.15 if (s.hover or act) else 0
                    gfx.fill_rrect(cr, n.x + 4, n.y + 4, n.w - 8, n.h - 8, 6, (t.fg[0], t.fg[1], t.fg[2], a if s.hover or s.press else 0.10))
                if urgent: gfx.fill_rrect(cr, n.x + 4, n.y + 4, n.w - 8, n.h - 8, 6, (1.0, 0.57, 0.0, 0.45))
                self._icon(cr, task, n.x + n.w / 2, n.y + n.h / 2 - 2, I * (0.9 if s.press else 1))
                if run:
                    w = min(task.count * 8, 16)
                    gfx.fill_rrect(cr, n.x + n.w / 2 - w / 2, n.y + n.h - 5, w, 4, 2, t.accent if act else (t.fg[0], t.fg[1], t.fg[2], 0.35))
                self._badge(cr, task, n)
            elif st == "zorin":
                if s.hover or s.press: gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, 8, t.press if s.press else t.hover)
                if act: gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, 8, (t.accent[0], t.accent[1], t.accent[2], 0.14))
                if urgent: gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, 8, (t.ember[0], t.ember[1], t.ember[2], 0.30))
                self._icon(cr, task, n.x + n.w / 2, n.y + n.h / 2 - 1, I * (0.9 if s.press else 1))
                if run:
                    if act: gfx.fill_rrect(cr, n.x + n.w / 2 - 10, n.y + n.h - 3.5, 20, 3, 1.5, t.accent)     # focused: elongated
                    else:
                        k = min(task.count, 4); x0 = n.x + n.w / 2 - (k - 1) * 5
                        for i in range(k): gfx.circle(cr, x0 + i * 10, n.y + n.h - 2.5, 2, t.fg_muted)
            elif st in ("mac-dock", "floating"):
                if s.hover and not s.press: pass
                sc = 1.0 + (0.0 if not self.o.get("magnify") == "on" else 0.0)
                cy_ = n.y + n.h / 2 - 5 - (3 if s.hover else 0)
                self._icon(cr, task, n.x + n.w / 2, cy_, I * (0.92 if s.press else 1))
                if run: gfx.circle(cr, n.x + n.w / 2, n.y + n.h - 3, 2.2, t.fg_muted if not act else t.fg)
                if urgent: gfx.circle(cr, n.x + n.w / 2, n.y + n.h - 3, 2.6, t.ember)
                self._badge(cr, task, n)
            elif st == "ubuntu-dock":
                if act: gfx.fill_rrect(cr, n.x + 4, n.y, n.w - 8, n.h, 8, (t.fg[0], t.fg[1], t.fg[2], 0.14))
                if s.hover or s.press: gfx.fill_rrect(cr, n.x + 4, n.y, n.w - 8, n.h, 8, t.press if s.press else t.hover)
                self._icon(cr, task, n.x + n.w / 2, n.y + n.h / 2, I * (0.9 if s.press else 1))
                if run:
                    k = min(task.count, 4)
                    y0 = n.y + n.h / 2 - (k - 1) * 4.5
                    for i in range(k): gfx.circle(cr, n.x + 5, y0 + i * 9, 2.2, t.accent if act else t.fg_muted)
                self._badge(cr, task, n)
            elif st == "minimal":
                if act: gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, 3, (t.accent[0], t.accent[1], t.accent[2], 0.20))
                if s.hover or s.press: gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, 3, t.press if s.press else t.hover)
                self._icon(cr, task, n.x + 6 + 8, n.y + n.h / 2, 16)
                gfx.text(cr, task.name, n.x + 30, n.y + n.h / 2, 12, t.fg if act else t.fg_muted, 600 if act else 500, maxw=n.w - 34)
                if act: gfx.fill_rrect(cr, n.x, n.y + n.h - 2, n.w, 2, 1, t.accent)
        return paint

    def _badge(self, cr, task, n):
        c = task.count
        if c > 1 and self.style in ("kylin",) and False: pass
