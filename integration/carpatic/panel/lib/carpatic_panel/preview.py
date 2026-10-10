"""Hover tooltips and window previews for the panel. Previews grab each window from the screen (no compositor needed: windows that are
visible and unobscured give a real picture, the others show their icon on a card)."""
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0"); gi.require_version("GdkX11", "3.0")
from gi.repository import Gtk, Gdk, GdkX11, GLib, GdkPixbuf
import cairo
from . import gfx, uiscale
from .kit import Canvas, View, Node, p_button
from .popup import rounded_region


class TipView(View):
    radius = 8

    def __init__(self, theme, text):
        super().__init__(theme); self.text = text
        w = gfx.text_size(gfx._scratch(), text, 12.5, 500, theme.font)[0]
        self.W, self.H = int(w + 22), 28

    def build(self):
        t = self.theme
        return [Node(x=0, y=0, w=self.W, h=self.H, paint=lambda cr, n, s: gfx.text(cr, self.text, n.x + 11, n.y + n.h / 2, 12.5, t.fg, 500, family=t.font))]

    def paint_frame(self, cr, w, h, alpha=1.0):
        t = self.theme
        gfx.rrect(cr, 0, 0, w, h, self.radius); cr.set_source_rgba(*t.surface2); cr.fill(); gfx.stroke_rrect(cr, 0, 0, w, h, self.radius, t.border_strong, 1)


def grab_thumbnail(xid, max_w, max_h):
    """Pixbuf of a window from the screen, scaled to fit, or None if it is not viewable."""
    try:
        d = Gdk.Display.get_default()
        gw = GdkX11.X11Window.foreign_new_for_display(d, xid)
        if gw is None or not gw.is_viewable(): return None
        w, h = gw.get_width(), gw.get_height()
        if w < 8 or h < 8: return None
        pb = Gdk.pixbuf_get_from_window(gw, 0, 0, w, h)
        if pb is None: return None
        sc = min(max_w / w, max_h / h, 1.0)
        return pb.scale_simple(max(1, int(w * sc)), max(1, int(h * sc)), GdkPixbuf.InterpType.BILINEAR) if sc < 1.0 else pb
    except Exception:
        return None


def pb_surface(pb):
    return Gdk.cairo_surface_create_from_pixbuf(pb, 1, None) if pb is not None else None


class PreviewView(View):
    radius = 12
    TW, TH = 200, 124

    def __init__(self, theme, task, icon_fn, thumbs, on_activate, on_close, on_hover=None):
        super().__init__(theme)
        self.task, self.icon_fn, self.thumbs = task, icon_fn, thumbs
        self.on_activate, self.on_close = on_activate, on_close
        n = max(1, len(task.windows)); self.n = n
        self.cols = min(n, 4); rows = (n + self.cols - 1) // self.cols
        self.W = 12 + self.cols * (self.TW + 8) - 8 + 12
        self.H = 12 + rows * (self.TH + 34 + 8) - 8 + 12 if task.windows else 56

    def build(self):
        t = self.theme; nodes = []
        if not self.task.windows:
            return [Node(x=0, y=0, w=self.W, h=self.H, paint=lambda cr, n, s: gfx.text(cr, self.task.name, n.x + 14, n.y + n.h / 2, 13, t.fg, 600, family=t.font))]
        for i, w in enumerate(self.task.windows):
            r, c = divmod(i, self.cols); x = 12 + c * (self.TW + 8); y = 12 + r * (self.TH + 34 + 8)
            def paint(cr, n, s, w=w, i=i):
                gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, 8, t.press if s.press else (t.hover if s.hover else t.tile_off))
                if w.active: gfx.stroke_rrect(cr, n.x, n.y, n.w, n.h, 8, t.accent, 2)
                ic = self.icon_fn(16)
                if ic is not None: cr.save(); cr.translate(n.x + 8, n.y + 9); cr.scale(16 / gfx.logical_w(ic), 16 / gfx.logical_w(ic)); cr.set_source_surface(ic, 0, 0); cr.paint(); cr.restore()
                gfx.text(cr, w.title or self.task.name, n.x + 30, n.y + 17, 12, t.fg, 500, maxw=n.w - 30 - 30, family=t.font)
                # thumbnail
                tx, ty, tw, th = n.x + 8, n.y + 34, n.w - 16, n.h - 34 - 8
                cr.save(); gfx.rrect(cr, tx, ty, tw, th, 5); cr.clip(); cr.set_source_rgba(*t.deep); cr.paint()
                sf = self.thumbs.get(w.id)
                if sf is not None:
                    sw, sh = sf.get_width(), sf.get_height(); k = min(tw / sw, th / sh)
                    cr.translate(tx + (tw - sw * k) / 2, ty + (th - sh * k) / 2); cr.scale(k, k); cr.set_source_surface(sf, 0, 0); cr.paint()
                else:
                    big = self.icon_fn(48)
                    if big is not None: cr.translate(tx + tw / 2 - 24, ty + th / 2 - 24); cr.scale(48 / gfx.logical_w(big), 48 / gfx.logical_w(big)); cr.set_source_surface(big, 0, 0); cr.paint()
                cr.restore()
            node = Node(id=f"pv:{w.id}", x=x, y=y, w=self.TW, h=self.TH + 34, paint=paint, radius=8, on_click=(lambda n, ww=w: self.on_activate(ww)),
                        on_middle=(lambda n, ev, ww=w: self.on_close(ww)))
            nodes.append(node)
            def xp(cr, n, s):
                if s.hover or s.press: gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, 6, (t.danger[0], t.danger[1], t.danger[2], 0.9 if s.press else 0.75))
                gfx.glyph(cr, "close", n.x + n.w / 2, n.y + n.h / 2, 11, (1, 1, 1, 1) if (s.hover or s.press) else t.fg_muted, lw=2)
            nodes.append(Node(id=f"px:{w.id}", x=x + self.TW - 28, y=y + 4, w=24, h=24, paint=xp, radius=6, on_click=(lambda n, ww=w: self.on_close(ww))))
        return nodes

    def paint_frame(self, cr, w, h, alpha=1.0):
        t = self.theme
        gfx.rrect(cr, 0, 0, w, h, self.radius); cr.set_source_rgba(*t.surface); cr.fill(); gfx.stroke_rrect(cr, 0, 0, w, h, self.radius, t.border_strong, 1)


class Float(Gtk.Window):
    """Borderless, non-grabbing popup for tips and previews."""

    def __init__(self, view, theme, pos, on_enter=None, on_leave=None):
        super().__init__(type=Gtk.WindowType.POPUP)
        self.canvas = Canvas(view); self.add(self.canvas)
        w, h = uiscale.dev(view.size()[0]), uiscale.dev(view.size()[1]); self.set_default_size(w, h); self.resize(w, h); self.move(*pos)
        self.view = view
        self.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        if on_enter: self.connect("enter-notify-event", lambda *a: on_enter())
        if on_leave: self.connect("leave-notify-event", lambda *a: on_leave())
        self.connect("realize", lambda *_: self.get_window().shape_combine_region(rounded_region(w, h, uiscale.devr(view.radius)), 0, 0))
        self.show_all()


def place_near(rect, size, edge, screen, gap=8):
    x, y, w, h = rect; pw, ph = size; sx, sy, sw, sh = screen
    if edge in ("bottom", "top"):
        px = x + w / 2 - pw / 2; py = y - ph - gap if edge == "bottom" else y + h + gap
    else:
        py = y + h / 2 - ph / 2; px = x + w + gap if edge == "left" else x - pw - gap
    return int(max(sx + 6, min(px, sx + sw - pw - 6))), int(max(sy + 6, min(py, sy + sh - ph - 6)))
