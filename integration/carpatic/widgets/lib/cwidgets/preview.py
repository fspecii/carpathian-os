"""Offscreen rendering of cards (gallery previews in Settings, theming render tests, README pictures). Needs cairo + Pango, no display."""
import datetime
import cairo
from . import conf, data, draw, look as L


class _FakeMon(data.SysMon):
    def __init__(self):
        super().__init__(); self.cpu, self.rx, self.tx = 37.0, 182000.0, 24000.0
        self.hist_cpu.extend([20, 25, 31, 28, 44, 52, 40, 36, 30, 33, 47, 61, 55, 38, 37][-30:]); self.hist_net.extend([5, 8, 30, 90, 120, 60, 40, 180][-30:])
    def mem(self): return 6_100_000_000, 16_000_000_000
    def disk(self): return 210_000_000_000, 512_000_000_000
    def temp(self): return 54.0


def sample_state(now=None):
    now = now or datetime.datetime(2026, 10, 8, 9, 41, 7); today = now.date()
    days = [dict(date=(today + datetime.timedelta(d)).isoformat(), code=c, hi=h, lo=l) for d, (c, h, l) in enumerate(((2, 17, 8), (61, 14, 9), (0, 19, 7), (3, 16, 8)))]
    return dict(weather=dict(temp=16, code=2, wind=11, day=True, days=days), weather_cfg=dict(name="Bucharest", units="c"), weather_age="3 min ago",
                sysmon=_FakeMon(), battery=(76, "Discharging", 192), profile="balanced",
                nowplaying=dict(title="Dust on the Ridge", artist="The Carpathians", album="", art="", playing=True, status="Playing", length=215.0, position=92.0, player="Music"),
                notes="Call the bank\nBuy bread and cheese\nCarpatic widgets: try the Nothing theme", todo=[dict(t="Reply to Ana", done=True), dict(t="Backup photos", done=False), dict(t="Book train to Brasov", done=False)],
                toggles=[dict(id="wifi", label="Wi-Fi", kind="switch", state=True), dict(id="bluetooth", label="Bluetooth", kind="switch", state=False),
                         dict(id="dnd", label="Do not disturb", kind="switch", state=False), dict(id="night", label="Night light", kind="switch", state=None),
                         dict(id="volume", label="Volume", kind="slider", state=55), dict(id="brightness", label="Brightness", kind="slider", state=70)],
                shortcuts=[dict(name=n, cmd=n, icon=None) for n in ("Terminal", "Files", "Web", "Settings", "Store")],
                tip=data.TIPS[0], events=[(today + datetime.timedelta(1), "0930", "Stand-up"), (today + datetime.timedelta(3), "", "Maria's birthday")], firstweekday=0)


def pixel_size(kind, size, scale=1.0):
    c, r = conf.dims(kind, size); return int((c * conf.PITCH - conf.GAP) * scale), int((r * conf.PITCH - conf.GAP) * scale)


def render(kind, size, pal, lk, state=None, scale=1.0, now=None, opts=None, backdrop=True):
    w, h = pixel_size(kind, size, scale)
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h); cr = cairo.Context(s)
    if backdrop: cr.set_source_rgb(*L.hex2rgb(pal["bg"])); cr.paint()
    cr.scale(scale, scale)
    ctx = draw.Ctx(cr, w / scale, h / scale, pal, lk, size, state if state is not None else sample_state(now), opts, now or datetime.datetime(2026, 10, 8, 9, 41, 7))
    ctx.state["_alpha"] = 1.0
    draw.paint(kind, ctx); return s, ctx


def look_by(name, theme):
    lk = dict(L.LOOKS[name]); lk["name"] = name; return L.palette(theme), lk


def sheet(name, theme, path, kinds=None, sizes=("M",)):
    """One PNG with every card of one look in a grid, on the theme background."""
    pal, lk = look_by(name, theme); kinds = kinds or list(conf.CATALOG); cells = []
    for k in kinds:
        for sz in sizes: cells.append(render(k, sz, pal, lk)[0])
    cols = 3; pad = 20; colw = max(c.get_width() for c in cells); rows = [cells[i:i + cols] for i in range(0, len(cells), cols)]
    H = sum(max(c.get_height() for c in r) + pad for r in rows) + pad; W = cols * (colw + pad) + pad
    out = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H); cr = cairo.Context(out); cr.set_source_rgb(*L.hex2rgb(pal["bg"])); cr.paint(); y = pad
    for r in rows:
        for i, c in enumerate(r): cr.set_source_surface(c, pad + i * (colw + pad), y); cr.paint()
        y += max(c.get_height() for c in r) + pad
    out.write_to_png(path); return path
