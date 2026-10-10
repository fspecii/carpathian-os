"""A tiny retained-mode UI kit on top of GtkDrawingArea: a View builds a list of Nodes (rectangles with a paint function and handlers),
the Canvas paints them with hover/press/focus state, animates hover fades, scrolls groups, and routes pointer and keyboard input.

Why not GtkButton and friends: every pixel (tile fills, radii, glyph weight, indicator pills, tabular numerals) has to come from the design
tokens, identical in light and dark, with no theme leaking in. Views also render offscreen to PNG for the tests (`render_png`)."""
import math, time
import cairo
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib
from . import gfx, uiscale
from .theme import Theme


class State:
    __slots__ = ("hover", "press", "focus", "on")

    def __init__(self, hover=0.0, press=False, focus=False, on=False):
        self.hover, self.press, self.focus, self.on = hover, press, focus, on


class Node:
    """A rectangle in view coordinates. `paint(cr, node, st)` draws it; handlers are optional. `group` names a scroll group."""
    __slots__ = ("id", "x", "y", "w", "h", "paint", "on_click", "on_press", "on_drag", "on_context", "on_middle", "on_scroll", "on_hover",
                 "tooltip", "group", "focusable", "data", "radius", "on", "ring")

    def __init__(self, id=None, x=0, y=0, w=0, h=0, paint=None, on_click=None, on_press=None, on_drag=None, on_context=None, on_middle=None,
                 on_scroll=None, on_hover=None, tooltip=None, group=None, focusable=None, data=None, radius=8, on=False, ring=True):
        self.id, self.x, self.y, self.w, self.h = id, x, y, w, h
        self.paint, self.on_click, self.on_press, self.on_drag = paint, on_click, on_press, on_drag
        self.on_context, self.on_middle, self.on_scroll, self.on_hover = on_context, on_middle, on_scroll, on_hover
        self.tooltip, self.group, self.data, self.radius, self.on, self.ring = tooltip, group, data, radius, on, ring
        interactive = any((on_click, on_press, on_drag))
        self.focusable = interactive if focusable is None else focusable

    def contains(self, px, py): return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h


class Group:
    """A vertically scrolling clip region."""

    def __init__(self, x, y, w, h, content_h=0):
        self.x, self.y, self.w, self.h, self.content_h = x, y, w, h, content_h
        self.offset = 0.0
        self.target = 0.0

    @property
    def max_offset(self): return max(0.0, self.content_h - self.h)

    def scroll_by(self, d):
        self.target = max(0.0, min(self.max_offset, self.target + d))

    def contains(self, px, py): return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h


class View:
    """Subclass and implement build(). `self.canvas` is set when attached; call self.refresh() after the model changes."""
    radius = 14
    W = 360
    H = 400
    framed = True

    def __init__(self, theme: Theme):
        self.theme = theme
        self.canvas = None
        self.groups = {}

    def build(self): return []

    def size(self): return (self.W, self.H)

    def refresh(self):
        if self.canvas is not None: self.canvas.invalidate()

    def paint_frame(self, cr, w, h, alpha=1.0):
        t = self.theme
        gfx.rrect(cr, 0, 0, w, h, self.radius); cr.set_source_rgba(t.surface[0], t.surface[1], t.surface[2], alpha); cr.fill()
        gfx.stroke_rrect(cr, 0, 0, w, h, self.radius, t.border_strong, 1.0)

    def fx(self): return 0.0, 1.0
    def key(self, ev): return False
    def animating(self): return False
    def tick(self, dt): pass
    def activated(self, node): pass


def scratch_cr():
    return cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 8, 8))


class Canvas(Gtk.DrawingArea):
    def __init__(self, view: View, scale=1):
        super().__init__()
        self.view = view; view.canvas = self
        self.nodes = []; self.dirty = True
        self.hover_id = None; self.press_id = None; self.focus_id = None; self.drag_node = None
        self.hv = {}              # id -> hover fade 0..1
        self.timer = None; self.last = time.monotonic()
        self.show_focus = False   # focus ring only after keyboard use
        self.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                        Gdk.EventMask.LEAVE_NOTIFY_MASK | Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK |
                        Gdk.EventMask.KEY_PRESS_MASK)
        self.set_can_focus(True)
        self.connect("draw", self.on_draw)
        self.connect("motion-notify-event", self.on_motion); self.connect("leave-notify-event", self.on_leave)
        self.connect("button-press-event", self.on_press); self.connect("button-release-event", self.on_release)
        self.connect("scroll-event", self.on_scroll)
        w, h = view.size(); self.set_size_request(uiscale.dev(w), uiscale.dev(h))

    # ------------------------------------------------------------------ model
    def invalidate(self):
        self.dirty = True; self.queue_draw()

    def rebuild(self):
        self.nodes = self.view.build() or []
        self.dirty = False
        ids = {n.id for n in self.nodes if n.id is not None}
        if self.focus_id not in ids: self.focus_id = None
        if self.hover_id not in ids: self.hover_id = None
        w, h = self.view.size()
        if (uiscale.dev(w), uiscale.dev(h)) != (self.get_size_request()): self.set_size_request(uiscale.dev(w), uiscale.dev(h))

    def node_at(self, x, y):
        for n in reversed(self.nodes):
            if n.id is None and n.on_scroll is None: continue
            px, py = x, y
            if n.group:
                g = self.view.groups.get(n.group)
                if g is None or not g.contains(x, y): continue
                py = y + g.offset
            if n.contains(px, py): return n
        return None

    def node_by_id(self, id_):
        if id_ is None: return None
        for n in self.nodes:
            if n.id == id_: return n
        return None

    # ------------------------------------------------------------------ animation
    def kick(self):
        if self.timer is None:
            self.last = time.monotonic(); self.timer = GLib.timeout_add(16, self.tick)

    def tick(self):
        now = time.monotonic(); dt = now - self.last; self.last = now
        busy = False
        for k in list(self.hv):
            tgt = 1.0 if (k == self.hover_id or k == self.press_id) else 0.0
            v = self.hv[k]
            step = dt / 0.10
            v = min(tgt, v + step) if v < tgt else max(tgt, v - step)
            if v == 0.0 and tgt == 0.0: del self.hv[k]
            else: self.hv[k] = v
            if v != tgt: busy = True
        for g in self.view.groups.values():
            if abs(g.target - g.offset) > 0.4:
                g.offset += (g.target - g.offset) * min(1.0, dt * 18); busy = True
            else: g.offset = g.target
        if self.view.animating(): self.view.tick(dt); busy = True
        self.queue_draw()
        if not busy: self.timer = None
        return busy

    # ------------------------------------------------------------------ draw
    def on_draw(self, widget, cr):
        if self.dirty: self.rebuild()
        f = uiscale.factor()
        w, h = self.get_allocated_width() / f, self.get_allocated_height() / f      # logical px: the views know nothing about the scale
        if getattr(self, "clear_first", False):
            cr.set_operator(cairo.OPERATOR_SOURCE); cr.set_source_rgba(0, 0, 0, 0); cr.paint(); cr.set_operator(cairo.OPERATOR_OVER)
        elif self.view.framed:
            cr.set_source_rgba(*self.view.theme.surface); cr.paint()      # no compositor: nothing may stay uninitialised outside the arc
        if f != 1.0: cr.scale(f, f)
        if self.view.framed:
            self.view.paint_frame(cr, w, h, getattr(self, "frame_alpha", 1.0))
        paint_nodes(cr, self.nodes, self.view, self.hv, self.press_id, self.focus_id if self.show_focus else None, self.hover_id)
        return False

    # ------------------------------------------------------------------ pointer
    def on_motion(self, w, ev):
        self._unscale(ev)
        n = self.node_at(ev.x, ev.y)
        nid = n.id if n is not None and (n.on_click or n.on_press or n.on_drag or n.on_hover) else None
        if self.drag_node is not None and self.drag_node.on_drag:
            self.drag_node.on_drag(self.drag_node, ev.x - self.drag_node.x, ev.y - self.drag_node.y, "move"); self.queue_draw(); return True
        if nid != self.hover_id:
            self.hover_id = nid
            if nid is not None: self.hv.setdefault(nid, 0.0)
            self.kick()
            win = self.get_window()
            if win is not None:
                win.set_cursor(Gdk.Cursor.new_from_name(self.get_display(), "pointer") if (n is not None and nid is not None and (n.on_click or n.on_press)) else None)
            if n is not None and n.on_hover: n.on_hover(n)
            self.on_hover_change(n)
        return False

    def _unscale(self, ev):
        """Pointer events arrive in device px; views are laid out in logical px."""
        f = uiscale.factor()
        if f != 1.0 and not getattr(ev, "_unscaled", False):
            try: ev.x, ev.y = ev.x / f, ev.y / f
            except Exception: pass

    def on_hover_change(self, node): pass

    def on_leave(self, w, ev):
        if self.drag_node is None:
            self.hover_id = None; self.kick()
        return False

    def on_press(self, w, ev):
        self._unscale(ev)
        self.grab_focus(); self.show_focus = False
        n = self.node_at(ev.x, ev.y)
        if n is None: return False
        if ev.button == 3 and n.on_context: n.on_context(n, ev); return True
        if ev.button == 2 and n.on_middle: n.on_middle(n, ev); return True
        if ev.button != 1: return False
        if n.id is not None:
            self.press_id = n.id; self.hv.setdefault(n.id, 0.0); self.kick()
            if n.focusable: self.focus_id = n.id
        if n.on_press: n.on_press(n, ev.x - n.x, ev.y - n.y)
        if n.on_drag:
            self.drag_node = n; n.on_drag(n, ev.x - n.x, ev.y - n.y, "start")
        self.queue_draw(); return True

    def on_release(self, w, ev):
        self._unscale(ev)
        n_press = self.node_by_id(self.press_id) if self.press_id is not None else None
        d = self.drag_node
        self.press_id = None; self.drag_node = None
        if d is not None and d.on_drag: d.on_drag(d, ev.x - d.x, ev.y - d.y, "end")
        n = self.node_at(ev.x, ev.y)
        if ev.button == 1 and n is not None and n_press is n and n.on_click:
            n.on_click(n); self.view.activated(n)
        self.kick(); self.queue_draw(); return True

    def on_scroll(self, w, ev):
        self._unscale(ev)
        n = self.node_at(ev.x, ev.y)
        dy = ev.delta_y if ev.direction == Gdk.ScrollDirection.SMOOTH else (1 if ev.direction == Gdk.ScrollDirection.DOWN else -1 if ev.direction == Gdk.ScrollDirection.UP else 0)
        dx = ev.delta_x if ev.direction == Gdk.ScrollDirection.SMOOTH else 0
        if n is not None and n.on_scroll:
            if n.on_scroll(n, dx, dy): self.queue_draw(); return True
        for g in self.view.groups.values():
            if g.contains(ev.x, ev.y) and g.max_offset > 0:
                g.scroll_by(dy * 48); self.kick(); return True
        return False

    # ------------------------------------------------------------------ keyboard
    def focusables(self): return [n for n in self.nodes if n.focusable and n.id is not None]

    def move_focus(self, dx, dy):
        items = self.focusables()
        if not items: return
        cur = self.node_by_id(self.focus_id)
        if cur is None:
            self.focus_id = items[0].id; self.ensure_visible(items[0]); return
        cx, cy = cur.x + cur.w / 2, cur.y + cur.h / 2
        best, bd = None, 1e9
        for n in items:
            if n is cur: continue
            nx, ny = n.x + n.w / 2, n.y + n.h / 2
            ddx, ddy = nx - cx, ny - cy
            if dx and (ddx * dx <= 0 or abs(ddy) > abs(ddx) * 1.2 + 4): continue
            if dy and (ddy * dy <= 0 or abs(ddx) > abs(ddy) * 1.2 + 4): continue
            d = abs(ddx) + abs(ddy) * (1 if dx else 1)
            if d < bd: best, bd = n, d
        if best is None and dy:   # wrap vertically through list order
            idx = items.index(cur); best = items[(idx + (1 if dy > 0 else -1)) % len(items)]
        if best is not None:
            self.focus_id = best.id; self.ensure_visible(best)

    def ensure_visible(self, n):
        if n.group:
            g = self.view.groups.get(n.group)
            if g:
                if n.y < g.offset: g.target = n.y
                elif n.y + n.h > g.offset + g.h: g.target = n.y + n.h - g.h
                self.kick()

    def handle_key(self, ev):
        if self.view.key(ev): self.invalidate(); return True
        k = ev.keyval
        moves = {Gdk.KEY_Left: (-1, 0), Gdk.KEY_Right: (1, 0), Gdk.KEY_Up: (0, -1), Gdk.KEY_Down: (0, 1)}
        if k in moves:
            self.show_focus = True; self.move_focus(*moves[k]); self.queue_draw(); return True
        if k in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
            items = self.focusables()
            if items:
                ids = [n.id for n in items]; i = ids.index(self.focus_id) if self.focus_id in ids else -1
                step = -1 if (k == Gdk.KEY_ISO_Left_Tab or ev.state & Gdk.ModifierType.SHIFT_MASK) else 1
                self.focus_id = ids[(i + step) % len(ids)]; self.show_focus = True; self.ensure_visible(items[(i + step) % len(ids)]); self.queue_draw()
            return True
        if k in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            n = self.node_by_id(self.focus_id)
            if n is not None and n.on_click: n.on_click(n); self.view.activated(n); return True
        return False


def paint_nodes(cr, nodes, view, hv, press_id=None, focus_id=None, hover_id=None):
    t = view.theme
    dx, alpha = view.fx()
    if dx or alpha < 1.0:
        cr.push_group(); cr.translate(dx, 0)
    for n in nodes:
        if n.paint is None: continue
        st = State(hv.get(n.id, 0.0) if n.id is not None else 0.0, n.id is not None and n.id == press_id, n.id is not None and n.id == focus_id, n.on)
        cr.save()
        if n.group:
            g = view.groups.get(n.group)
            if g is not None:
                cr.rectangle(g.x, g.y, g.w, g.h); cr.clip(); cr.translate(0, -g.offset)
        n.paint(cr, n, st)
        if st.focus and n.ring and n.id is not None:
            gfx.rrect(cr, n.x - 1, n.y - 1, n.w + 2, n.h + 2, n.radius + 1); cr.set_source_rgba(*t.accent); cr.set_line_width(2); cr.stroke()
        cr.restore()
    if dx or alpha < 1.0:
        cr.pop_group_to_source(); cr.paint_with_alpha(alpha)
    for g in view.groups.values():
        if g.max_offset > 0:
            frac = g.h / g.content_h; th = max(24, g.h * frac); ty = g.y + (g.h - th) * (g.offset / g.max_offset)
            cr.save(); gfx.rrect(cr, g.x + g.w - 5, ty, 3, th, 1.5); cr.set_source_rgba(*t.fg[:3], 0.22); cr.fill(); cr.restore()


def render_png(view, path, scale=1, hover=None, focus=None, pad=0):
    """Offscreen render of a view (frame + nodes). `hover` = node id painted in its hover state, `focus` = id with a focus ring."""
    w, h = view.size()
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, int((w + 2 * pad) * scale), int((h + 2 * pad) * scale))
    cr = cairo.Context(surf); cr.scale(scale, scale); cr.translate(pad, pad)
    nodes = view.build() or []
    if view.framed: view.paint_frame(cr, w, h)
    paint_nodes(cr, nodes, view, {hover: 1.0} if hover else {}, None, focus, hover)
    surf.write_to_png(path)
    return nodes


def render_surface(view, bg=None, scale=1, hover=None, focus=None, pad=0):
    w, h = view.size()
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, int((w + 2 * pad) * scale), int((h + 2 * pad) * scale))
    cr = cairo.Context(surf)
    if bg is not None: cr.set_source_rgba(*bg); cr.paint()
    cr.scale(scale, scale); cr.translate(pad, pad)
    nodes = view.build() or []
    if view.framed: view.paint_frame(cr, w, h)
    paint_nodes(cr, nodes, view, {hover: 1.0} if hover else {}, None, focus, hover)
    return surf, nodes


# ----------------------------------------------------------------------------- common widgets (paint functions)
def p_button(theme, radius=6, fill=None, fg_on=False):
    """Flat button painter: rest transparent, hover/press overlay, optional `on` accent fill."""
    def paint(cr, n, st):
        if n.on:
            gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, radius, theme.accent_soft if not fg_on else theme.accent)
        base = fill
        if base: gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, radius, base)
        if st.hover > 0 or st.press:
            c = theme.press if st.press else theme.hover
            gfx.fill_rrect(cr, n.x, n.y, n.w, n.h, radius, (c[0], c[1], c[2], c[3] * (1.0 if st.press else st.hover)))
    return paint


def slider_value(node_w, x, knob=0):
    return max(0.0, min(1.0, (x - knob / 2) / max(1, node_w - knob)))


def fmt_time(dt, fmt):
    return dt.strftime(fmt)
