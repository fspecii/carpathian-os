"""Cairo + Pango painting of every card. paint(kind, ctx) never touches the network or the disk: the host puts the data in ctx.state first."""
import datetime, math, os
import cairo, gi
gi.require_foreign("cairo")
gi.require_version("Pango", "1.0"); gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo
from . import data, look as L

DOTS = {  # 5x7 dot-matrix glyphs (Nothing look)
    "0": "01110 10001 10001 10001 10001 10001 01110", "1": "00100 01100 00100 00100 00100 00100 01110", "2": "01110 10001 00001 00010 00100 01000 11111",
    "3": "11110 00001 00001 01110 00001 00001 11110", "4": "00010 00110 01010 10010 11111 00010 00010", "5": "11111 10000 11110 00001 00001 10001 01110",
    "6": "00110 01000 10000 11110 10001 10001 01110", "7": "11111 00001 00010 00100 01000 01000 01000", "8": "01110 10001 10001 01110 10001 10001 01110",
    "9": "01110 10001 10001 01111 00001 00010 01100", ":": "00000 00100 00100 00000 00100 00100 00000", "-": "00000 00000 00000 11111 00000 00000 00000",
    "%": "11001 11010 00010 00100 01000 01011 10011", " ": "00000 00000 00000 00000 00000 00000 00000", ".": "00000 00000 00000 00000 00000 01100 01100",
}


class Ctx:
    def __init__(self, cr, w, h, pal, lk, size="M", state=None, opts=None, now=None):
        self.cr, self.W, self.H, self.pal, self.lk, self.size = cr, w, h, pal, lk, size
        self.state, self.opts, self.now = state or {}, opts or {}, now or datetime.datetime.now()
        self.hits = []; self.x, self.y, self.w, self.h = 0, 0, w, h

    # ----- primitives
    def color(self, c, a=1.0):
        r, g, b = L.hex2rgb(c); self.cr.set_source_rgba(r, g, b, a)

    def rrect(self, x, y, w, h, r):
        cr = self.cr; r = max(0, min(r, w / 2, h / 2)); cr.new_sub_path()
        if r == 0: cr.rectangle(x, y, w, h); return
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0); cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi); cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2); cr.close_path()

    def fill_rrect(self, x, y, w, h, r, col, a=1.0):
        self.rrect(x, y, w, h, r); self.color(col, a); self.cr.fill()

    def text(self, s, x, y, px, col, weight=400, anchor="l", maxw=None, font=None, caps=False, a=1.0, mono=False):
        """Draw one line. anchor l/c/r relates x; y is the top. Returns (width, height). Ellipsizes at maxw."""
        lay = PangoCairo.create_layout(self.cr)
        f = Pango.FontDescription(); f.set_family(font or (self.lk["font"] + (",monospace" if mono else ""))); f.set_absolute_size(px * Pango.SCALE)
        f.set_weight(Pango.Weight(weight)); lay.set_font_description(f); lay.set_text(s.upper() if caps else s, -1)
        if maxw: lay.set_width(int(maxw * Pango.SCALE)); lay.set_ellipsize(Pango.EllipsizeMode.END)
        w, h = lay.get_pixel_size()
        ox = x - w / 2 if anchor == "c" else x - w if anchor == "r" else x
        self.cr.move_to(ox, y); self.color(col, a); PangoCairo.show_layout(self.cr, lay); return w, h

    def dots(self, s, x, y, cell, col, anchor="l", off=None):
        """Dot-matrix text: cell = pitch of one dot. Returns width."""
        gw = 6 * cell; total = len(s) * gw - cell
        x0 = x - total / 2 if anchor == "c" else x - total if anchor == "r" else x
        for i, ch in enumerate(s):
            rows = DOTS.get(ch, DOTS[" "]).split()
            for ry, row in enumerate(rows):
                for rx, bit in enumerate(row):
                    self.cr.new_sub_path(); self.cr.arc(x0 + i * gw + rx * cell + cell / 2, y + ry * cell + cell / 2, cell * 0.36, 0, 6.2832)
                    self.color(col if bit == "1" else (off or self.pal["border"]), 1.0 if bit == "1" else 0.55); self.cr.fill()
        return total

    def hit(self, x, y, w, h, *action):
        self.hits.append((x + self.x * 0, y, w, h, action))

    # ----- frame and header
    def frame(self, title=None):
        """Card background + header per look; sets the body rectangle (self.x, self.y, self.w, self.h)."""
        lk, p = self.lk, self.pal; a = self.state.get("_alpha", lk["alpha"])
        self.fill_rrect(0, 0, self.W, self.H, lk["radius"], p["card"], a)
        self.rrect(0.5, 0.5, self.W - 1, self.H - 1, lk["radius"]); self.color(p["border"] if lk["name"] != "tiling" else p["accent"], 1.0)
        self.cr.set_line_width(1); self.cr.stroke()
        if lk.get("elev"):      # elevation cue without a compositor: the lower edge of the card is a little darker, like a soft shadow seen from above
            cr = self.cr; cr.save(); self.rrect(0.5, 0.5, self.W - 1, self.H - 1, lk["radius"]); cr.clip()
            g = cairo.LinearGradient(0, self.H * 0.7, 0, self.H); r, gg, b = L.hex2rgb(p["fg"]); g.add_color_stop_rgba(0, r, gg, b, 0); g.add_color_stop_rgba(1, r, gg, b, lk["elev"] * (1.0 if p["mode"] != "light" else 1.4))
            cr.set_source(g); cr.rectangle(0, 0, self.W, self.H); cr.fill(); cr.restore()
        pad = lk["pad"]; self.x, self.y, self.w, self.h = pad, pad, self.W - 2 * pad, self.H - 2 * pad
        if title:
            hh = self.header(title, pad)
            self.y += hh; self.h -= hh

    def header(self, title, pad):
        lk, p = self.lk, self.pal; h = lk["head"]
        if h == "plain": self.text(title, pad, pad - 2, 12, p["muted"], 600, maxw=self.W - 2 * pad); return 20
        if h == "icon":
            self.fill_rrect(pad, pad + 1, 10, 10, 3, p["accent"]); self.text(title, pad + 18, pad - 2, 12, p["muted"], 600, maxw=self.W - 2 * pad - 18); return 22
        if h == "bar":
            self.text(title, pad, pad - 2, 13, p["fg"], 700, maxw=self.W - 2 * pad); self.fill_rrect(pad, pad + 18, 22, 3, 1.5, p["accent"]); return 28
        if h == "mono": self.text(f"[ {title.lower()} ]", pad, pad - 3, 12, p["accent"], 400, maxw=self.W - 2 * pad, mono=True); return 20
        self.text(title, pad, pad - 2, 12, p["muted"], 400, font=lk["head_font"] + ",Noto Sans Mono", caps=True, maxw=self.W - 2 * pad - 40)
        for i in range(3): self.cr.new_sub_path(); self.cr.arc(self.W - pad - 4 - i * 9, pad + 6, 2.2, 0, 6.2832); self.color(p["accent"] if i == 0 else p["subtle"]); self.cr.fill()
        return 22


# ---------------------------------------------------------------- icons
def icon_weather(c, kind, cx, cy, r, col, sun="#f2c25a"):
    cr = c.cr; cr.set_line_width(max(1.5, r / 9)); cr.set_line_cap(1)
    def cloud(dx=0, dy=0, k=1.0):
        c.color(col); cr.new_sub_path()
        cr.arc(cx + dx - r * .35 * k, cy + dy + r * .1 * k, r * .38 * k, 0, 6.3); cr.fill(); cr.new_sub_path()
        cr.arc(cx + dx + r * .05 * k, cy + dy - r * .12 * k, r * .48 * k, 0, 6.3); cr.fill(); cr.new_sub_path()
        cr.arc(cx + dx + r * .5 * k, cy + dy + r * .12 * k, r * .34 * k, 0, 6.3); cr.fill()
        cr.rectangle(cx + dx - r * .35 * k, cy + dy + r * .1 * k, r * .85 * k, r * .38 * k); cr.fill()
    if kind == "sun":
        c.color(sun); cr.new_sub_path(); cr.arc(cx, cy, r * .42, 0, 6.3); cr.fill()
        for i in range(8):
            a = i * math.pi / 4; cr.move_to(cx + math.cos(a) * r * .62, cy + math.sin(a) * r * .62); cr.line_to(cx + math.cos(a) * r * .86, cy + math.sin(a) * r * .86); cr.stroke()
    elif kind == "cloud": cloud()
    elif kind == "fog":
        for i in range(3): c.color(col); cr.move_to(cx - r * .7, cy - r * .3 + i * r * .38); cr.line_to(cx + r * .7, cy - r * .3 + i * r * .38); cr.stroke()
    else:
        cloud(0, -r * .22, .9); c.color(c.pal["info"] if kind != "snow" else col)
        for i in range(3):
            x = cx - r * .4 + i * r * .4
            if kind == "snow": cr.new_sub_path(); cr.arc(x, cy + r * .6, r * .06, 0, 6.3); cr.fill()
            elif kind == "storm":
                c.color(sun); cr.move_to(cx + r * .05, cy + r * .2); cr.line_to(cx - r * .15, cy + r * .6); cr.line_to(cx + r * .05, cy + r * .6); cr.line_to(cx - r * .1, cy + r * .95); cr.stroke(); break
            else: cr.move_to(x, cy + r * .5); cr.line_to(x - r * .12, cy + r * .85); cr.stroke()


def spark(c, vals, x, y, w, h, col, mx=None):
    vals = list(vals); mx = mx or max(max(vals), 1e-9); n = len(vals); cr = c.cr
    if n < 2: return
    cr.move_to(x, y + h)
    for i, v in enumerate(vals): cr.line_to(x + w * i / (n - 1), y + h - h * min(1, v / mx))
    cr.line_to(x + w, y + h); cr.close_path(); c.color(col, 0.18); cr.fill_preserve(); cr.new_path()
    for i, v in enumerate(vals):
        (cr.move_to if i == 0 else cr.line_to)(x + w * i / (n - 1), y + h - h * min(1, v / mx))
    c.color(col); cr.set_line_width(1.6); cr.set_line_join(1); cr.stroke()


def bar(c, x, y, w, h, frac, col):
    c.fill_rrect(x, y, w, h, h / 2 if c.lk["radius"] else 0, c.pal["card2"]); fw = max(0, min(1, frac)) * w
    if fw > 0: c.fill_rrect(x, y, max(fw, h if c.lk["radius"] else 1), h, h / 2 if c.lk["radius"] else 0, col)


def ring(c, cx, cy, r, frac, col, lw=6):
    cr = c.cr; cr.set_line_width(lw); cr.set_line_cap(1); c.color(c.pal["card2"]); cr.new_sub_path(); cr.arc(cx, cy, r, 0, 6.2832); cr.stroke()
    if frac > 0: c.color(col); cr.new_sub_path(); cr.arc(cx, cy, r, -math.pi / 2, -math.pi / 2 + 6.2832 * min(1, frac)); cr.stroke()


# ---------------------------------------------------------------- painters
def clock(c):
    p, lk = c.pal, c.lk; n = c.now; mode = c.opts.get("clock") or ("dots" if lk["name"] == "nothing" else "analog" if lk["name"] == "macos" and c.size != "M" else "digital")
    c.frame(); W, H = c.W, c.H; fmt = "%H:%M" if c.opts.get("h24", True) else "%I:%M"
    date = n.strftime("%A, %-d %B") if c.size != "S" else n.strftime("%a %-d %b")
    if mode == "analog":
        r = min(W, H) / 2 - lk["pad"] - 4; cx, cy = (W / 2, H / 2) if c.size != "M" else (H / 2, H / 2)
        c.cr.new_sub_path(); c.cr.arc(cx, cy, r, 0, 6.3); c.color(p["card2"]); c.cr.fill()
        c.cr.set_line_width(2)
        for i in range(12):
            a = i * math.pi / 6; k = .86 if i % 3 else .8; c.color(p["fg"] if i % 3 == 0 else p["subtle"])
            c.cr.move_to(cx + math.sin(a) * r * k, cy - math.cos(a) * r * k); c.cr.line_to(cx + math.sin(a) * r * .94, cy - math.cos(a) * r * .94); c.cr.stroke()
        hrs = (n.hour % 12 + n.minute / 60) / 12 * 2 * math.pi; mins = (n.minute + n.second / 60) / 60 * 2 * math.pi; secs = n.second / 60 * 2 * math.pi
        for ang, ln, wd, col in ((hrs, .5, 4, p["fg"]), (mins, .75, 3, p["fg"]), (secs, .85, 1.5, p["accent"])):
            c.cr.set_line_width(wd); c.cr.set_line_cap(1); c.color(col); c.cr.move_to(cx, cy); c.cr.line_to(cx + math.sin(ang) * r * ln, cy - math.cos(ang) * r * ln); c.cr.stroke()
        c.cr.new_sub_path(); c.cr.arc(cx, cy, 3.5, 0, 6.3); c.color(p["accent"]); c.cr.fill()
        if c.size == "M": c.text(n.strftime("%A"), H + 4, H / 2 - 22, 14, p["muted"], 500, maxw=W - H - 12); c.text(n.strftime("%-d %B"), H + 4, H / 2 - 2, 22, p["fg"], 600, maxw=W - H - 12)
        return
    if mode == "dots":
        cell = max(3, min((W - 2 * lk["pad"]) / (5 * 6 - 1) , (H - 2 * lk["pad"] - 22) / 7)) if True else 4
        cell = min(cell, 9); tw = 5 * 6 * cell - cell
        c.dots(n.strftime(fmt), W / 2, (H - 7 * cell) / 2 - (8 if c.size != "S" else 12), cell, p["fg"] if True else p["accent"], "c")
        c.text(date, W / 2, H - lk["pad"] - 16, 12, p["muted"], 400, "c", maxw=W - 2 * lk["pad"], caps=True); return
    big = {"S": 44, "M": 64, "L": 96}[c.size]
    wt, _ = c.text(n.strftime(fmt), W / 2, H / 2 - big * .72, big, p["fg"], 600 if lk["name"] != "tiling" else 400, "c", mono=lk["name"] == "tiling")
    c.text(date, W / 2, H / 2 + big * .46, 13 if c.size == "S" else 15, p["muted"], 400, "c", maxw=W - 2 * lk["pad"])


def calendar(c):
    p, lk = c.pal, c.lk; n = c.now; today = n.date(); small = c.size == "S"
    if small:
        c.frame(); c.text(today.strftime("%b").upper() if lk["name"] != "macos" else today.strftime("%B"), c.W / 2, 14, 13, p["accent"], 700, "c")
        c.text(str(today.day), c.W / 2, c.H / 2 - 28, 56, p["fg"], 600, "c"); c.text(today.strftime("%A"), c.W / 2, c.H - 30, 13, p["muted"], 400, "c"); return
    c.frame(today.strftime("%B %Y")); fw = c.state.get("firstweekday", 0)
    aw = c.w * (0.58 if c.size == "L" else 1.0); cellw = aw / 7
    for i, nm in enumerate(data.weekday_names(fw)): c.text(nm, c.x + i * cellw + cellw / 2, c.y, 11, p["muted"], 600, "c")
    grid = data.month_grid(today.year, today.month, fw); rh = min(42, (c.h - 22) / len(grid)); dfs = 14 if rh >= 34 else 13
    for r, row in enumerate(grid):
        for i, d in enumerate(row):
            if not d: continue
            cx, cy = c.x + i * cellw + cellw / 2, c.y + 20 + r * rh
            if d == today.day:
                c.cr.new_sub_path(); c.cr.arc(cx, cy + rh / 2 - 3, min(cellw, rh) / 2 - 1, 0, 6.3); c.color(p["accent"]); c.cr.fill()
                c.text(str(d), cx, cy + rh / 2 - 11, dfs, p["accent_fg"], 700, "c")
            else: c.text(str(d), cx, cy + rh / 2 - 11, dfs, p["fg"] if i < 5 else p["muted"], 400, "c")
    if c.size == "L":
        ax = c.x + aw + 16; c.text("Coming up", ax, c.y, 12, p["muted"], 600)
        ev = c.state.get("events") or []
        if not ev: c.text("No events. Put a calendar.ics file in the widgets folder to see them here.", ax, c.y + 22, 12, p["muted"], 400, maxw=c.w - aw - 16)
        for i, (d, t, s) in enumerate(ev[:6]):
            y = c.y + 22 + i * 34; c.fill_rrect(ax, y + 2, 3, 26, 1.5, p["accent"])
            c.text(s, ax + 10, y, 13, p["fg"], 500, maxw=c.w - aw - 30); c.text(d.strftime("%a %-d %b") + (f"  {t[:2]}:{t[2:]}" if t else ""), ax + 10, y + 16, 11, p["muted"], 400)


def weather(c):
    p, lk = c.pal, c.lk; st = c.state; w = st.get("weather"); cfg = st.get("weather_cfg", {})
    c.frame("Weather" if c.size != "S" else None)
    if not w:
        msg = "Choose where you are" if st.get("weather_error") == "nolocation" else "No forecast yet. Connect to the internet."
        sub = "Open Settings > Widgets and type your city." if st.get("weather_error") == "nolocation" else "It will appear here and stay available offline."
        c.text(msg, c.x, c.y + 4, 15, p["fg"], 600, maxw=c.w); c.text(sub, c.x, c.y + 26, 12, p["muted"], 400, maxw=c.w)
        if st.get("weather_error") == "nolocation" and c.size != "S": c.text("or: carpatic widgets weather city <name>", c.x, c.y + 44, 12, p["muted"], 400, maxw=c.w, mono=True)
        return
    u = "°F" if cfg.get("units") == "f" else "°C"; kind = data.wmo_kind(w["code"])
    if c.size == "S":
        icon_weather(c, kind, c.W / 2, 36, 22, p["fg"], p["warn"]); c.text(f"{w['temp']}°", c.W / 2, 62, 34, p["fg"], 600, "c")
        c.text(cfg.get("name", ""), c.W / 2, c.H - 26, 12, p["muted"], 400, "c", maxw=c.W - 16); return
    icon_weather(c, kind, c.x + 30, c.y + 38, 28, p["fg"], p["warn"])
    c.text(f"{w['temp']}{u}", c.x + 72, c.y + 4, 40, p["fg"], 600); c.text(data.WMO.get(w["code"], ""), c.x + 72, c.y + 52, 14, p["muted"], 400, maxw=c.w - 72)
    c.text(cfg.get("name", ""), c.x + c.w, c.y + 4, 13, p["fg"], 500, "r", maxw=c.w * .4)
    c.text(f"Wind {w['wind']} {'mph' if cfg.get('units') == 'f' else 'km/h'}", c.x + c.w, c.y + 22, 12, p["muted"], 400, "r")
    age = st.get("weather_age", ""); 
    if st.get("weather_error") == "offline": c.text(f"Offline, from {age}", c.x + c.w, c.y + 38, 11, p["warn"], 500, "r", maxw=c.w * .5)
    if c.size == "L":
        for i, d in enumerate(w["days"][1:4]):
            y = c.y + 92 + i * 38; wd = datetime.date.fromisoformat(d["date"]).strftime("%A")
            c.text(wd, c.x, y + 6, 14, p["fg"], 500); icon_weather(c, data.wmo_kind(d["code"]), c.x + c.w * .55, y + 14, 13, p["fg"], p["warn"])
            c.text(f"{d['hi']}°", c.x + c.w - 36, y + 6, 14, p["fg"], 600, "r"); c.text(f"{d['lo']}°", c.x + c.w, y + 6, 14, p["muted"], 400, "r")


def sysmon(c):
    p, lk = c.pal, c.lk; m = c.state.get("sysmon")
    c.frame("System" if c.size != "S" else None)
    if not m: return
    cpu = m.cpu; used, tot = m.mem(); du, dt = m.disk(); mem = used / tot if tot else 0; dfrac = du / dt if dt else 0
    def col(f): return p["bad"] if f > .9 else p["warn"] if f > .75 else p["accent"]
    if c.size == "S":
        ring(c, c.W / 2, c.H / 2 - 4, 30, cpu / 100, col(cpu / 100), 7); c.text(f"{cpu:.0f}%", c.W / 2, c.H / 2 - 18, 22, p["fg"], 600, "c"); c.text("CPU", c.W / 2, c.H - 24, 11, p["muted"], 600, "c"); return
    rows = [("CPU", cpu / 100, f"{cpu:.0f}%"), ("Memory", mem, f"{human(used)} / {human(tot)}"), ("Disk", dfrac, f"{human(du)} / {human(dt)}")]
    cols = c.size == "M"; bw = c.w * (.58 if cols else 1)
    for i, (nm, f, txt) in enumerate(rows):
        y = c.y + i * (24 if cols else 36)
        c.text(nm, c.x, y, 12, p["muted"], 500); c.text(txt, c.x + bw, y, 12, p["fg"], 500, "r")
        bar(c, c.x, y + 17 if not cols else y + 17, bw, 5, f, col(f))
    if cols:
        sx = c.x + bw + 14; sw = c.w - bw - 14
        spark(c, m.hist_cpu, sx, c.y + 2, sw, 26, p["accent"], 100)
        c.text("↓ " + data.human_rate(m.rx), sx, c.y + 36, 11, p["fg"], 500, maxw=sw)
    else:
        y = c.y + 3 * 36 + 4; spark(c, m.hist_cpu, c.x, y, c.w, 40, p["accent"], 100); c.text("Processor, last minute", c.x, y + 44, 11, p["muted"], 400)
        y += 70; c.text("Network", c.x, y, 12, p["muted"], 500); c.text("↓ " + data.human_rate(m.rx) + "   ↑ " + data.human_rate(m.tx), c.x + c.w, y, 12, p["fg"], 500, "r")
        spark(c, m.hist_net, c.x, y + 20, c.w, 30, p["info"])
        t = m.temp(); c.text("Temperature", c.x, y + 62, 12, p["muted"], 500); c.text(f"{t:.0f}°C" if t is not None else "No sensor here", c.x + c.w, y + 62, 12, p["fg"], 500, "r")


def human(n): return data.human_bytes(n)


def nowplaying(c):
    p = c.pal; np_ = c.state.get("nowplaying"); c.frame("Now playing" if c.size != "S" else None)
    if not np_:
        c.text("No music playing", c.x, c.y + 4, 15, p["fg"], 600, maxw=c.w); c.text("Start music or a video and it shows up here.", c.x, c.y + 26, 12, p["muted"], 400, maxw=c.w); return
    art = c.state.get("art"); s = c.h if c.size == "M" else min(c.w, c.h - 70) if c.size == "L" else 0
    if s and art:
        c.cr.save(); c.rrect(c.x, c.y, s, s, 8); c.cr.clip(); c.cr.translate(c.x, c.y); c.cr.scale(s / art.get_width(), s / art.get_height()); c.cr.set_source_surface(art, 0, 0); c.cr.paint(); c.cr.restore()
    elif s: c.fill_rrect(c.x, c.y, s, s, 8, p["card2"]); c.text("♪", c.x + s / 2, c.y + s / 2 - 16, 32, p["subtle"], 400, "c")
    tx = c.x + (s + 12 if c.size == "M" else 0); tw = c.w - (s + 12 if c.size == "M" else 0); ty = c.y + (0 if c.size == "M" else s + 8)
    if c.size == "S": ty = c.y + 6
    c.text(np_["title"], tx, ty, 15, p["fg"], 600, maxw=tw); c.text(np_["artist"], tx, ty + 20, 12, p["muted"], 400, maxw=tw)
    if np_["length"] > 0 and c.size != "S": bar(c, tx, ty + 44, tw, 4, np_["position"] / np_["length"], p["accent"])
    by = c.y + c.h - 30 if c.size != "S" else c.y + c.h - 30; bx = tx
    for i, (g, act) in enumerate((("⏮", "prev"), ("⏸" if np_["playing"] else "▶", "playpause"), ("⏭", "next"))):
        x = bx + i * 36; c.fill_rrect(x, by, 30, 26, 13 if c.lk["radius"] else 0, p["accent"] if act == "playpause" else p["card2"])
        c.text(g, x + 15, by + 3, 14, p["accent_fg"] if act == "playpause" else p["fg"], 400, "c", font="Symbols Nerd Font,Noto Sans Symbols 2,DejaVu Sans")
        c.hit(x, by, 30, 26, "mpris", act)


def battery(c):
    p = c.pal; b = c.state.get("battery"); prof = c.state.get("profile", "")
    c.frame("Battery" if c.size != "S" else None)
    if not b:
        c.text("No battery", c.W / 2 if c.size == "S" else c.x, c.H / 2 - 10 if c.size == "S" else c.y + 4, 15, p["fg"], 600, "c" if c.size == "S" else "l"); 
        if c.size != "S": c.text("This computer runs on mains power.", c.x, c.y + 26, 12, p["muted"], 400)
        return
    pct, stt, mins = b; col = p["ok"] if stt in ("Charging", "Full") or pct > 30 else p["warn"] if pct > 15 else p["bad"]
    when = "" if mins is None else (f"{mins // 60} h {mins % 60:02d} min " + ("until full" if stt == "Charging" else "left"))
    if c.size == "S":
        ring(c, c.W / 2, c.H / 2 - 2, 30, pct / 100, col, 7); c.text(f"{pct}%", c.W / 2, c.H / 2 - 16, 20, p["fg"], 600, "c")
        c.text("Charging" if stt == "Charging" else "", c.W / 2, c.H - 26, 11, p["muted"], 500, "c"); return
    ring(c, c.x + 34, c.y + 36, 30, pct / 100, col, 7); c.text(f"{pct}%", c.x + 34, c.y + 25, 17, p["fg"], 600, "c")
    c.text(stt if stt != "Not charging" else "Plugged in", c.x + 84, c.y + 12, 16, p["fg"], 600); c.text(when, c.x + 84, c.y + 36, 12, p["muted"], 400, maxw=c.w - 84)
    if prof:
        for i, (k, nm) in enumerate((("saver", "Saver"), ("balanced", "Balanced"), ("performance", "Max"))):
            bw = (c.w - 84 - 12) / 3; x = c.x + 84 + i * (bw + 6); on = prof.replace("power-", "") == k
            c.fill_rrect(x, c.y + 62, bw, 24, 12 if c.lk["radius"] else 0, p["accent"] if on else p["card2"])
            c.text(nm, x + bw / 2, c.y + 66, 11, p["accent_fg"] if on else p["fg"], 600, "c", maxw=bw - 6); c.hit(x, c.y + 62, bw, 24, "power", k)


def notes(c):
    p = c.pal; t = c.state.get("notes", ""); c.frame("Notes" if c.size != "S" else None)
    if not t.strip():
        c.text("Click to write a note", c.x, c.y + 2, 14, p["muted"], 400, maxw=c.w); c.hit(0, 0, c.W, c.H, "edit_notes"); return
    y = c.y; lh = 20; maxl = int(c.h // lh)
    lines = []
    for ln in t.splitlines():
        while len(ln) > max(8, int(c.w / 7.5)): cut = ln.rfind(" ", 0, int(c.w / 7.5)); cut = cut if cut > 0 else int(c.w / 7.5); lines.append(ln[:cut]); ln = ln[cut:].lstrip()
        lines.append(ln)
    for i, ln in enumerate(lines[:maxl]): c.text(ln, c.x, y + i * lh, 14, p["fg"], 400, maxw=c.w)
    if len(lines) > maxl: c.text("…", c.x + c.w, c.y + c.h - 16, 14, p["muted"], 400, "r")
    c.hit(0, 0, c.W, c.H, "edit_notes")


def todo(c):
    p = c.pal; items = c.state.get("todo", []); c.frame("To-do" if c.size != "S" else None)
    if not items:
        c.text("Nothing to do", c.x, c.y + 2, 15, p["fg"], 600); c.text("Add items with: carpatic widgets todo add \"Buy bread\"", c.x, c.y + 24, 12, p["muted"], 400, maxw=c.w)
        c.hit(0, 0, c.W, c.H, "edit_todo"); return
    n = max(1, int(c.h // 28))
    for i, it in enumerate(items[:n]):
        y = c.y + i * 28
        c.fill_rrect(c.x, y + 3, 16, 16, 8 if c.lk["radius"] else 0, p["accent"] if it["done"] else p["card2"])
        if it["done"]: c.text("✓", c.x + 8, y + 3, 12, p["accent_fg"], 700, "c")
        else:
            c.rrect(c.x + .5, y + 3.5, 15, 15, 7.5 if c.lk["radius"] else 0); c.color(p["subtle"]); c.cr.set_line_width(1.2); c.cr.stroke()
        c.text(it["t"], c.x + 26, y + 1, 14, p["muted"] if it["done"] else p["fg"], 400, maxw=c.w - 26)
        c.hit(c.x, y, c.w, 26, "todo", i)
    if len(items) > n: c.text(f"+{len(items) - n} more", c.x + c.w, c.y + c.h - 14, 11, p["muted"], 400, "r")


def toggles(c):
    """Only tiles this computer can really do are shown, and the tiles grow to fill the card."""
    p, lk = c.pal, c.lk; ts = [t for t in c.state.get("toggles", []) if t["state"] is not None]; c.frame("Quick settings" if c.size != "S" else None)
    sw = [t for t in ts if t["kind"] == "switch"]; sl = [t for t in ts if t["kind"] == "slider"]
    if c.size == "S": sw, sl = sw[:4], []
    elif c.size == "M": sw, sl = sw[:3], []
    cols = 2 if c.size == "S" else 3; cols = max(1, min(cols, len(sw)))
    rows = (len(sw) + cols - 1) // cols; avail = c.h - (0 if c.size != "L" else 22 * len(sl) * 2 + 8 * (1 if sl else 0))
    bw = (c.w - (cols - 1) * 8) / cols; bh = max(34, min(78, (avail - (rows - 1) * 8) / max(rows, 1)))
    for i, t in enumerate(sw):
        x, y = c.x + (i % cols) * (bw + 8), c.y + (i // cols) * (bh + 8); on = t["state"]
        c.fill_rrect(x, y, bw, bh, 14 if lk["radius"] else 0, p["accent"] if on else p["card2"])
        fgc = p["accent_fg"] if on else p["fg"]
        if bh >= 52:
            c.text(t["label"], x + 12, y + bh / 2 - 17, 12, fgc, 600, maxw=bw - 20); c.text("On" if on else "Off", x + 12, y + bh / 2 + 2, 12, fgc, 400, maxw=bw - 20)
        else: c.text(t["label"], x + bw / 2, y + (bh - 15) / 2, 11 if c.size == "S" else 12, fgc, 600, "c", maxw=bw - 8)
        c.hit(x, y, bw, bh, "toggle", t["id"])
    if c.size == "L":
        y0 = c.y + rows * (bh + 8) + 4
        for j, t in enumerate(sl):
            y = y0 + j * 44; c.text(t["label"], c.x, y, 12, p["muted"], 500); c.text(f"{t['state']}%", c.x + c.w, y, 12, p["fg"], 500, "r")
            bar(c, c.x, y + 22, c.w, 8, t["state"] / 100, p["accent"]); c.hit(c.x, y + 14, c.w, 24, "slider", t["id"], c.x, c.w)


def photo(c):
    p = c.pal; im = c.state.get("photo"); cr = c.cr
    c.frame()
    if im:
        cr.save(); c.rrect(0, 0, c.W, c.H, c.lk["radius"]); cr.clip(); k = max(c.W / im.get_width(), c.H / im.get_height())
        cr.translate((c.W - im.get_width() * k) / 2, (c.H - im.get_height() * k) / 2); cr.scale(k, k); cr.set_source_surface(im, 0, 0); cr.paint(); cr.restore()
        g = c.state.get("photo_name", "")
        if g and c.size != "S": c.fill_rrect(10, c.H - 32, min(c.W - 20, len(g) * 8 + 20), 22, 11 if c.lk["radius"] else 0, "#000000", .55); c.text(g, 20, c.H - 29, 12, "#ffffff", 500, maxw=c.W - 40)
    else: c.text("No wallpaper picture", c.W / 2, c.H / 2 - 8, 13, p["muted"], 400, "c")


def shortcuts(c):
    p = c.pal; apps = c.state.get("shortcuts", []); c.frame("Apps" if c.size == "L" else None)
    n = len(apps) or 1; cols = 2 if c.size == "S" else 5; cw = c.w / cols
    for i, a in enumerate(apps[:cols * (2 if c.size == "S" else 1)]):
        x, y = c.x + (i % cols) * cw, c.y + (i // cols) * (c.h / 2 if c.size == "S" else 0) + (4 if c.size != "S" else 0)
        sz = 44 if c.size != "S" else 34; im = a.get("icon")
        if im: c.cr.save(); c.cr.translate(x + (cw - sz) / 2, y); c.cr.scale(sz / im.get_width(), sz / im.get_height()); c.cr.set_source_surface(im, 0, 0); c.cr.paint(); c.cr.restore()
        else: c.fill_rrect(x + (cw - sz) / 2, y, sz, sz, sz * .22, p["card2"]); c.text(a["name"][:1].upper(), x + cw / 2, y + sz / 2 - 10, 18, p["fg"], 600, "c")
        if c.size != "S": c.text(a["name"], x + cw / 2, y + sz + 6, 11, p["muted"], 500, "c", maxw=cw - 4)
        c.hit(x, y, cw, sz + (24 if c.size != "S" else 0), "launch", a["cmd"])


def tip(c):
    p = c.pal; c.frame("Tip" if c.size != "S" else None); t = c.state.get("tip", "")
    if c.size == "S": c.text("✦", c.W / 2, 14, 18, p["accent"], 400, "c")
    lay = PangoCairo.create_layout(c.cr); f = Pango.FontDescription(); f.set_family(c.lk["font"]); f.set_absolute_size((13 if c.size != "S" else 12) * Pango.SCALE); lay.set_font_description(f)
    lay.set_text(t, -1); lay.set_width(int(c.w * Pango.SCALE)); lay.set_wrap(Pango.WrapMode.WORD_CHAR); lay.set_height(int((c.h - (30 if c.size == "S" else 0)) * Pango.SCALE)); lay.set_ellipsize(Pango.EllipsizeMode.END)
    c.cr.move_to(c.x, c.y + (30 if c.size == "S" else 0)); c.color(p["fg"]); PangoCairo.show_layout(c.cr, lay); c.hit(0, 0, c.W, c.H, "nexttip")


PAINTERS = dict(clock=clock, calendar=calendar, weather=weather, sysmon=sysmon, nowplaying=nowplaying, battery=battery, notes=notes, todo=todo,
                toggles=toggles, photo=photo, shortcuts=shortcuts, tip=tip)


def paint(kind, ctx):
    PAINTERS[kind](ctx); return ctx.hits
