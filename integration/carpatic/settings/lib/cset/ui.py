"""Reusable GTK3 components of Carpathian OS Settings: icon tiles, Clamp, GroupCard and the Row family (SwitchRow, PopupRow, SliderRow, SpinRow,
EntryRow, ButtonRow, NavRow, InfoRow, ColorRow, ProgressRow, CustomRow), PageBuilder, PopupButton, Segmented, Gallery.
Every row is a Gtk.ListBoxRow inside a GroupCard (rounded list); look comes from theme.CSS (class names here are part of that contract)."""
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib, GObject, Pango

# ---------------------------------------------------------------- helpers
_tile_provider = None
_tile_known = set()

def _tile_css(color):
    global _tile_provider
    if _tile_provider is None:
        _tile_provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), _tile_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 2)
    cls = "tc-" + color.lstrip("#").lower()
    if cls not in _tile_known:
        _tile_known.add(cls)
        _tile_css.rules = getattr(_tile_css, "rules", "") + f".tile.{cls} {{ background-color: {color}; background-image: linear-gradient(to bottom, rgba(255,255,255,0.16), rgba(255,255,255,0)); box-shadow: inset 0 0 0 1px rgba(0,0,0,0.10); }}\n"
        _tile_provider.load_from_data(_tile_css.rules.encode())
    return cls

def cls(widget, *names):
    ctx = widget.get_style_context()
    for n in names: ctx.add_class(n)
    return widget

def label(text="", css=None, xalign=0.0, wrap=False, selectable=False, ellipsize=False, lines=0):
    l = Gtk.Label(label=text, xalign=xalign)
    l.set_line_wrap(wrap)
    if wrap: l.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    l.set_selectable(selectable)
    if ellipsize: l.set_ellipsize(Pango.EllipsizeMode.END)
    if css: cls(l, *css.split())
    return l

def icon_tile(icon, color="#8e8e93", size="md"):
    """Coloured rounded square with a white symbolic glyph (sizes: sm 24, md 28, lg 40)."""
    box = Gtk.Box(); box.set_halign(Gtk.Align.CENTER); box.set_valign(Gtk.Align.CENTER)
    cls(box, "tile", _tile_css(color))
    px = {"sm": 14, "md": 16, "lg": 24}[size]
    if size == "sm": cls(box, "tile-sm")
    if size == "lg": cls(box, "tile-lg")
    img = Gtk.Image.new_from_icon_name(icon if icon.endswith("-symbolic") else icon + "-symbolic", Gtk.IconSize.BUTTON)
    img.set_pixel_size(px); img.set_halign(Gtk.Align.CENTER); img.set_valign(Gtk.Align.CENTER)
    box.set_center_widget(img)
    box.set_size_request({"sm": 24, "md": 28, "lg": 40}[size], {"sm": 24, "md": 28, "lg": 40}[size])
    return box

def set_a11y(widget, name, desc=None):
    try:
        a = widget.get_accessible()
        if a is not None:
            a.set_name(name)
            if desc: a.set_description(desc)
    except Exception:
        pass

def chevron(name="go-next-symbolic"):
    i = Gtk.Image.new_from_icon_name(name, Gtk.IconSize.BUTTON); i.set_pixel_size(16); cls(i, "row-chevron"); return i

# ---------------------------------------------------------------- Clamp (max content width, centered)
try: from carpatic_scale import px as _px            # design px -> device px at the display scale
except ImportError:
    def _px(n): return n


class Clamp(Gtk.Bin):
    __gtype_name__ = "CsetClamp"
    def __init__(self, max_width=680):
        super().__init__(); self.max_width = _px(max_width); self.set_has_window(False)
    def do_get_preferred_width(self):
        c = self.get_child()
        if c is None or not c.get_visible(): return 0, 0
        mn, nat = c.get_preferred_width(); return min(mn, self.max_width), min(nat, self.max_width)
    def do_get_preferred_height_for_width(self, w):
        c = self.get_child()
        if c is None or not c.get_visible(): return 0, 0
        return c.get_preferred_height_for_width(min(w, self.max_width))
    def do_get_preferred_height(self):
        c = self.get_child()
        if c is None or not c.get_visible(): return 0, 0
        return c.get_preferred_height()
    def do_size_allocate(self, a):
        self.set_allocation(a)
        c = self.get_child()
        if c is None or not c.get_visible(): return
        w = min(a.width, self.max_width); r = Gdk.Rectangle()
        r.x = a.x + (a.width - w) // 2; r.y = a.y; r.width = w; r.height = a.height
        c.size_allocate(r)

# ---------------------------------------------------------------- Rows
class Row(Gtk.ListBoxRow):
    """label + secondary text on the left, a control on the right. key = anchor for search / deep links."""
    def __init__(self, title="", sub="", icon=None, color="#8e8e93", key=None, activatable=False, setting=None):
        super().__init__()
        self.key = key or title; self.title_text = title; self.setting = setting   # setting = the configuration key this row edits (one page owns each key: see docs/SETTINGS-IA.md)
        self.set_activatable(activatable); self.set_selectable(False)
        self.guard = False
        box = Gtk.Box(spacing=12); box.set_margin_top(8); box.set_margin_bottom(8); box.set_margin_start(16); box.set_margin_end(16)
        if icon:
            self.tile = icon_tile(icon, color); box.pack_start(self.tile, False, False, 0)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2); col.set_valign(Gtk.Align.CENTER)
        self.title = label(title, "row-title", wrap=True); col.pack_start(self.title, False, False, 0)
        self.sub = label(sub, "row-sub", wrap=True); self.sub.set_no_show_all(True); col.pack_start(self.sub, False, False, 0)
        if sub: self.sub.set_no_show_all(False)
        self.text = col
        box.pack_start(col, True, True, 0)
        self.ctl = Gtk.Box(spacing=8); self.ctl.set_valign(Gtk.Align.CENTER); box.pack_end(self.ctl, False, False, 0)
        self.spinner = Gtk.Spinner(); self.spinner.set_no_show_all(True)
        self.ctl.pack_start(self.spinner, False, False, 0)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sep = Gtk.Separator(); cls(sep, "row-sep"); sep.set_margin_start(56 if icon else 16)   # inset like macOS: lines start at the text, not at the card edge
        outer.pack_start(sep, False, False, 0); outer.pack_start(box, True, True, 0)
        self.add(outer); self.box = box; self.outer = outer
    def set_title(self, t): self.title_text = t; self.title.set_text(t)
    def set_sub(self, t):
        self.sub.set_text(t or ""); self.sub.set_no_show_all(not t); self.sub.set_visible(bool(t))
    def add_control(self, w, name=None, pack_start=False):
        (self.ctl.pack_start if not pack_start else self.ctl.pack_end)(w, False, False, 0)
        set_a11y(w, name or self.title_text, self.sub.get_text() or None); w.show_all(); return w
    def focus_control(self):
        """Reveal a setting with focus on its first usable control, or on the row."""
        window = self.get_toplevel()
        if isinstance(window, Gtk.Window): window.set_focus(None)
        if not self.ctl.child_focus(Gtk.DirectionType.TAB_FORWARD):
            self.grab_focus()
    def set_busy(self, on):
        self.spinner.set_no_show_all(False); self.spinner.set_visible(on)
        if on: self.spinner.start()
        else: self.spinner.stop(); self.spinner.hide()
    def set_value_quiet(self, v): pass

class SwitchRow(Row):
    def __init__(self, title, sub="", active=False, on_change=None, **kw):
        super().__init__(title, sub, activatable=True, **kw)
        self.sw = Gtk.Switch(); self.sw.set_active(active); self.sw.set_valign(Gtk.Align.CENTER); self.on_change = on_change
        self.sw.connect("notify::active", self._changed); self.add_control(self.sw)
        self.connect("activate", lambda *_: self.sw.set_active(not self.sw.get_active()))
    def _changed(self, sw, _p):
        if not self.guard and self.on_change: self.on_change(sw.get_active())
    def set_value_quiet(self, v):
        self.guard = True; self.sw.set_active(bool(v)); self.guard = False
    def get_value(self): return self.sw.get_active()

class PopupButton(Gtk.MenuButton):
    """macOS-style pop-up button: current value + chevron, list in a popover (keyboard: Enter, arrows, Esc)."""
    def __init__(self, options, value=None, on_change=None, min_width=0):
        super().__init__(); self.options = list(options); self.value = value; self.on_change = on_change; self.guard = False
        cls(self, "popup-btn")
        box = Gtk.Box(spacing=8); self.lab = label("", ellipsize=True); box.pack_start(self.lab, True, True, 0)
        box.pack_start(Gtk.Image.new_from_icon_name("pan-down-symbolic", Gtk.IconSize.BUTTON), False, False, 0)
        self.add(box); self.set_halign(Gtk.Align.END)
        if min_width: self.set_size_request(min_width, -1)
        self.pop = Gtk.Popover(); self.set_popover(self.pop)
        self.rebuild()
    def rebuild(self):
        old = self.pop.get_child()
        if old: self.pop.remove(old)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2); v.set_margin_top(4); v.set_margin_bottom(4); v.set_margin_start(4); v.set_margin_end(4)
        for oid, text in self.options:
            b = Gtk.Button(); cls(b, "pop-item"); b.set_relief(Gtk.ReliefStyle.NONE)
            h = Gtk.Box(spacing=8)
            chk = Gtk.Image.new_from_icon_name("object-select-symbolic", Gtk.IconSize.MENU); chk.set_opacity(1.0 if oid == self.value else 0.0)
            h.pack_start(chk, False, False, 0); l = label(text); h.pack_start(l, True, True, 0)
            b.add(h); b.connect("clicked", self._pick, oid); v.pack_start(b, False, False, 0)
        if len(self.options) > 9:
            sw = Gtk.ScrolledWindow(); sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); sw.set_min_content_height(288); sw.set_propagate_natural_height(True); sw.set_max_content_height(288); sw.add(v); sw.show_all(); self.pop.add(sw)
        else:
            v.show_all(); self.pop.add(v)
        self.lab.set_text(dict(self.options).get(self.value, self.options[0][1] if self.options and self.value is None else (self.value or "")))
    def _pick(self, _b, oid):
        self.pop.popdown()
        if oid == self.value: return
        self.value = oid; self.rebuild()
        if self.on_change and not self.guard: self.on_change(oid)
    def set_options(self, options, value=None):
        self.options = list(options)
        if value is not None: self.value = value
        self.rebuild()
    def set_value(self, v):
        self.guard = True; self.value = v; self.rebuild(); self.guard = False

class PopupRow(Row):
    def __init__(self, title, sub="", options=(), value=None, on_change=None, **kw):
        super().__init__(title, sub, **kw)
        self.pb = PopupButton(options, value, on_change); self.add_control(self.pb)
    def set_value_quiet(self, v): self.pb.set_value(v)
    def set_options(self, o, v=None): self.pb.set_options(o, v)
    def get_value(self): return self.pb.value

class SliderRow(Row):
    def __init__(self, title, sub="", lo=0, hi=100, step=1, value=0, on_change=None, fmt=lambda v: f"{v:.0f}", marks=None, **kw):
        super().__init__(title, sub, **kw)
        self.fmt = fmt; self.on_change = on_change; self._deb = 0
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step); self.scale.set_draw_value(False)
        self.scale.set_size_request(200, 28); self.scale.set_value(value); self.scale.set_valign(Gtk.Align.CENTER)
        self.val = label(fmt(value), "row-value", xalign=1.0); self.val.set_size_request(48, -1)
        self.scale.connect("value-changed", self._changed)
        for m, t in (marks or {}).items(): self.scale.add_mark(m, Gtk.PositionType.BOTTOM, None)
        self.ctl.pack_start(self.scale, False, False, 0); self.ctl.pack_start(self.val, False, False, 0)
        set_a11y(self.scale, title, sub or None); self.ctl.show_all()
    def _changed(self, sc):
        self.val.set_text(self.fmt(sc.get_value()))
        if self.guard or not self.on_change: return
        if self._deb: GLib.source_remove(self._deb)
        self._deb = GLib.timeout_add(180, self._fire)
    def _fire(self):
        self._deb = 0; self.on_change(self.scale.get_value()); return False
    def set_value_quiet(self, v):
        self.guard = True; self.scale.set_value(v); self.guard = False; self.val.set_text(self.fmt(v))

class Stepper(Gtk.Box):
    """Compact value with - and + buttons (macOS stepper). API like Gtk.SpinButton: get_value, set_value, 'value-changed'."""
    __gsignals__ = {"value-changed": (GObject.SignalFlags.RUN_FIRST, None, ())}
    def __init__(self, lo, hi, step, value):
        super().__init__(spacing=0); cls(self, "stepper")
        self.lo, self.hi, self.step, self.value = lo, hi, step, value
        self.val = label("", "stepper-val", xalign=0.5); self.val.set_size_request(40, -1); self.pack_start(self.val, False, False, 0)
        self.minus = Gtk.Button(); self.plus = Gtk.Button()
        for b, ic in ((self.minus, "list-remove-symbolic"), (self.plus, "list-add-symbolic")):
            cls(b, "step-btn"); b.add(Gtk.Image.new_from_icon_name(ic, Gtk.IconSize.BUTTON)); b.set_relief(Gtk.ReliefStyle.NONE); self.pack_start(b, False, False, 0)
        set_a11y(self.minus, "Decrease"); set_a11y(self.plus, "Increase")
        self.minus.connect("clicked", lambda *_: self.bump(-1)); self.plus.connect("clicked", lambda *_: self.bump(1)); self.set_value(value, quiet=True)
        self.connect("scroll-event", lambda w, ev: (self.bump(-1 if ev.direction == Gdk.ScrollDirection.UP else 1), True)[1] if False else False)
    def bump(self, d):
        self.set_value(self.value + d * self.step)
    def get_value(self): return self.value
    def set_value(self, v, quiet=False):
        v = max(self.lo, min(self.hi, v)); ch = v != self.value; self.value = v
        self.val.set_text(f"{v:g}"); self.minus.set_sensitive(v > self.lo); self.plus.set_sensitive(v < self.hi)
        if ch and not quiet: self.emit("value-changed")

class SpinRow(Row):
    def __init__(self, title, sub="", lo=0, hi=100, step=1, value=0, on_change=None, unit="", **kw):
        super().__init__(title, sub, **kw)
        self.on_change = on_change; self._deb = 0
        self.spin = Stepper(lo, hi, step, value); self.spin.set_valign(Gtk.Align.CENTER)
        self.spin.connect("value-changed", self._changed); self.ctl.pack_start(self.spin, False, False, 0); self.spin.show_all()
        ui_name = title; set_a11y(self.spin, ui_name)
        if unit: self.ctl.pack_start(label(unit, "row-value"), False, False, 0); self.ctl.show_all()
    def _changed(self, sp):
        if self.guard or not self.on_change: return
        if self._deb: GLib.source_remove(self._deb)
        self._deb = GLib.timeout_add(450, self._fire)
    def _fire(self):
        self._deb = 0; self.on_change(self.spin.get_value()); return False
    def set_value_quiet(self, v): self.guard = True; self.spin.set_value(v, quiet=True); self.guard = False

class EntryRow(Row):
    def __init__(self, title, sub="", text="", on_commit=None, placeholder="", password=False, width=240, **kw):
        super().__init__(title, sub, **kw)
        self.entry = Gtk.Entry(); self.entry.set_text(text); self.entry.set_width_chars(max(8, width // 9)); self.entry.set_placeholder_text(placeholder or None)
        self.entry.set_valign(Gtk.Align.CENTER)
        if password: self.entry.set_visibility(False)
        self.on_commit = on_commit; self.entry.connect("activate", self._commit); self.entry.connect("focus-out-event", lambda *_: (self._commit(), False)[1])
        self._last = text; self.add_control(self.entry)
    def _commit(self, *_):
        t = self.entry.get_text()
        if t != self._last and self.on_commit: self._last = t; self.on_commit(t)
    def set_value_quiet(self, t): self._last = t; self.entry.set_text(t)

class ButtonRow(Row):
    """A row whose control is one or more buttons. style: default | suggested | destructive"""
    def __init__(self, title, sub="", button="OK", on_click=None, style="default", **kw):
        super().__init__(title, sub, **kw)
        self.buttons = []; self.add_button(button, on_click, style)
    def add_button(self, text, on_click, style="default"):
        b = Gtk.Button(label=text); b.set_valign(Gtk.Align.CENTER)
        if style == "suggested": cls(b, "suggested-action")
        if style == "destructive": cls(b, "destructive-action")
        if on_click: b.connect("clicked", lambda *_: on_click())
        self.buttons.append(b); self.add_control(b, f"{text}, {self.title_text}"); return b
    def set_button_text(self, t, i=0): self.buttons[i].set_label(t)

class NavRow(Row):
    """Opens a sub-page. value = secondary text shown before the chevron."""
    def __init__(self, title, sub="", icon=None, color="#8e8e93", value="", on_activate=None, **kw):
        super().__init__(title, sub, icon, color, activatable=True, **kw)
        self.on_activate = on_activate; self.value = label(value, "row-value", ellipsize=True); self.value.set_max_width_chars(28)
        self.ctl.pack_start(self.value, False, False, 0); self.ctl.pack_start(chevron(), False, False, 0); self.ctl.show_all()
        self.connect("activate", lambda *_: on_activate and on_activate())
        set_a11y(self, title + (", " + sub if sub else ""))
    def set_value(self, v): self.value.set_text(v)

class InfoRow(Row):
    def __init__(self, title, value="", sub="", selectable=True, **kw):
        super().__init__(title, sub, **kw)
        self.val = label(value, "row-value", xalign=1.0, wrap=True, selectable=selectable); self.val.set_max_width_chars(44); self.val.set_justify(Gtk.Justification.RIGHT)
        self.ctl.pack_start(self.val, False, False, 0); self.ctl.show_all()
    def set_value_quiet(self, v): self.val.set_text(v)
    set_value = set_value_quiet

class StatusRow(InfoRow):
    """InfoRow with a coloured dot: state = ok | warn | bad | off"""
    def __init__(self, title, value="", state="off", sub="", **kw):
        super().__init__(title, value, sub, **kw)
        self.dot = Gtk.Box(); self.dot.set_valign(Gtk.Align.CENTER); cls(self.dot, "status-dot"); self.dot.set_size_request(10, 10)
        self.ctl.pack_start(self.dot, False, False, 0); self.ctl.reorder_child(self.dot, 0); self.set_state(state); self.ctl.show_all()
    def set_state(self, s):
        ctx = self.dot.get_style_context()
        for n in ("status-ok", "status-warn", "status-bad", "status-off"): ctx.remove_class(n)
        ctx.add_class("status-" + s)

class ColorRow(Row):
    """Row of round colour swatches. colors: [(id, '#hex', 'name')]"""
    def __init__(self, title, sub="", colors=(), value=None, on_change=None, **kw):
        super().__init__(title, sub, **kw)
        self.colors = list(colors); self.value = value; self.on_change = on_change; self.btns = {}
        self.sw = Gtk.Box(spacing=8)
        for cid, hx, name in self.colors:
            b = Gtk.Button(); b.set_relief(Gtk.ReliefStyle.NONE); cls(b, "swatch"); b.set_tooltip_text(name); set_a11y(b, f"{name}")
            p = Gtk.CssProvider(); p.load_from_data(f"button.swatch {{ background-color: {hx}; background-image: none; }}".encode()); b.get_style_context().add_provider(p, Gtk.STYLE_PROVIDER_PRIORITY_USER + 3)
            b.connect("clicked", self._pick, cid); self.btns[cid] = b; self.sw.pack_start(b, False, False, 0)
        self.ctl.pack_start(self.sw, False, False, 0); self.ctl.show_all(); self._mark()
    def _mark(self):
        for cid, b in self.btns.items():
            c = b.get_style_context()
            (c.add_class if cid == self.value else c.remove_class)("selected")
    def _pick(self, _b, cid):
        if cid == self.value: return
        self.value = cid; self._mark()
        if self.on_change and not self.guard: self.on_change(cid)
    def set_value_quiet(self, v): self.value = v; self._mark()

class ProgressRow(Row):
    def __init__(self, title, sub="", fraction=0.0, text="", **kw):
        super().__init__(title, sub, **kw)
        self.bar = Gtk.ProgressBar(); self.bar.set_size_request(160, -1); self.bar.set_valign(Gtk.Align.CENTER)
        self.txt = label(text, "row-value", xalign=1.0); self.txt.set_size_request(84, -1)
        self.ctl.pack_start(self.bar, False, False, 0); self.ctl.pack_start(self.txt, False, False, 0); self.ctl.show_all(); self.set_fraction(fraction, text)
    def set_fraction(self, f, text=None):
        self.bar.set_fraction(max(0.0, min(1.0, f)))
        c = self.bar.get_style_context(); c.remove_class("warn"); c.remove_class("bad")
        if f > 0.95: c.add_class("bad")
        elif f > 0.85: c.add_class("warn")
        if text is not None: self.txt.set_text(text)

class CustomRow(Gtk.ListBoxRow):
    """Full-width row holding any widget (previews, galleries, lists)."""
    def __init__(self, widget, key=None, pad=16, setting=None):
        super().__init__(); self.key = key; self.title_text = key or ""; self.setting = setting; self.set_activatable(False); self.set_selectable(False)
        widget.set_margin_top(pad); widget.set_margin_bottom(pad); widget.set_margin_start(pad); widget.set_margin_end(pad)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); sep = Gtk.Separator(); cls(sep, "row-sep")
        outer.pack_start(sep, False, False, 0); outer.pack_start(widget, True, True, 0); self.add(outer); self.child_widget = widget

# ---------------------------------------------------------------- GroupCard / PageBuilder
class GroupCard(Gtk.Box):
    def __init__(self, title=None, footer=None, page=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.page = page; self.rows = []; self.plain = False
        if title:
            self.head = label(title, "group-title"); self.head.set_margin_start(4); self.pack_start(self.head, False, False, 0)
            self.head.set_margin_top(0); self.title_text = title
        self.list = Gtk.ListBox(); self.list.set_selection_mode(Gtk.SelectionMode.NONE); cls(self.list, "card")
        self.list.set_activate_on_single_click(True); self.list.set_no_show_all(True)   # shown with the first row: an empty card would draw a stray line
        self.pack_start(self.list, False, False, 0)
        self.foot = None
        if footer: self.set_footer(footer)
    def set_footer(self, text):
        if self.foot is None:
            self.foot = label("", "group-footer", wrap=True); self.foot.set_margin_start(4); self.foot.set_margin_end(4); self.pack_start(self.foot, False, False, 0)
        self.foot.set_text(text); self.foot.show()
    def add(self, *rows):
        for r in rows:
            self.list.add(r); self.rows.append(r); r.connect("notify::visible", lambda *_: self.sync())
            if self.page is not None and getattr(r, "key", None): self.page.keyed[r.key] = r
            if self.page is not None and getattr(r, "setting", None): self.page.register_setting(r.setting, r)
            r.show_all() if isinstance(r, Gtk.Widget) else None
        self.sync()
        return rows[0] if rows else None
    def sync(self):
        """the card is shown only while at least one of its rows is visible (an empty card would draw a stray line)"""
        if not self.plain: self.list.set_visible(any(x.get_visible() for x in self.rows))
    def add_plain(self, widget, key=None, setting=None):
        """Put a widget (a Gallery) directly on the page under the title, without the card frame."""
        self.plain = True; self.list.hide(); self.list.set_no_show_all(True)
        self.pack_start(widget, False, False, 0); widget.show_all()
        if self.page is not None and key: self.page.keyed[key] = widget
        if self.page is not None and setting: self.page.register_setting(setting, widget)
        return widget
    def clear(self):
        for r in self.rows:
            if self.page is not None: self.page.keyed.pop(getattr(r, "key", None), None)
            self.list.remove(r)
        self.rows = []; self.list.hide()

class PageBuilder(Gtk.Box):
    """The content of one settings page: large title, optional subtitle, banners, then GroupCards."""
    def __init__(self, title="", sub="", big_title=True):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.keyed = {}; self.settings = {}; self.title_text = title
        self.set_margin_start(32); self.set_margin_end(32); self.set_margin_top(8); self.set_margin_bottom(32)
        self.header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.title_label = label(title, "page-title"); self.header.pack_start(self.title_label, False, False, 0)
        self.sub_label = label(sub, "page-sub", wrap=True); self.header.pack_start(self.sub_label, False, False, 0)
        self.sub_label.set_no_show_all(not sub)
        if big_title and title: self.pack_start(self.header, False, False, 0)
    def group(self, title=None, footer=None, key=None):
        g = GroupCard(title, footer, page=self); self.pack_start(g, False, False, 0)
        if key: self.keyed[key] = g
        return g
    def add(self, widget, expand=False):
        self.pack_start(widget, expand, expand, 0); return widget
    def banner(self, text, kind="info", title=None):
        b = Gtk.Box(spacing=12); cls(b, "banner"); 
        if kind == "warn": cls(b, "warn")
        if kind == "bad": cls(b, "bad")
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        if title: col.pack_start(label(title, "row-title", wrap=True), False, False, 0)
        l = label(text, "row-sub", wrap=True); l.set_name("banner-text"); col.pack_start(l, False, False, 0)
        b.pack_start(col, True, True, 0); b.text = l; b.show_all(); self.pack_start(b, False, False, 0); return b
    def find(self, key): return self.keyed.get(key)
    def register_setting(self, name, widget): self.settings.setdefault(name, []).append(widget)

class PageView(Gtk.ScrolledWindow):
    """Scrollable page: Clamp (680 px) centered in the window. Emits 'scrolled' with the offset (drives the sticky header)."""
    __gsignals__ = {"offset": (GObject.SignalFlags.RUN_FIRST, None, (float,))}
    def __init__(self, content, max_width=680):
        super().__init__(); self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.content = content; self.set_overlay_scrolling(True)
        clamp = Clamp(max_width); clamp.add(content); self.add(clamp)
        self.get_vadjustment().connect("value-changed", lambda a: self.emit("offset", a.get_value()))
    def scroll_to(self, widget):
        # smooth enough: put the widget near the top third of the viewport
        def go():
            try:
                _, y = widget.translate_coordinates(self.content, 0, 0)
                adj = self.get_vadjustment(); adj.set_value(max(0, y - 120))
            except Exception:
                pass
            return False
        GLib.idle_add(go)
    def flash(self, row):
        row = getattr(row, "list", row); c = row.get_style_context(); c.add_class("flash")
        GLib.timeout_add(1600, lambda: (c.remove_class("flash"), False)[1])

# ---------------------------------------------------------------- Segmented / Gallery
class Segmented(Gtk.Box):
    """Linked pill group of toggle buttons: options [(id, label)]"""
    def __init__(self, options, value=None, on_change=None):
        super().__init__(spacing=2); cls(self, "seg"); self.on_change = on_change; self.btns = {}; self.guard = False; self.value = value
        group = None
        for oid, text in options:
            b = Gtk.RadioButton.new_with_label_from_widget(group, text) if group else Gtk.RadioButton.new_with_label(None, text)
            group = group or b; b.set_mode(False); cls(b, "seg-btn"); b.set_active(oid == value)
            b.connect("toggled", self._t, oid); self.btns[oid] = b; self.pack_start(b, True, True, 0)
    def _t(self, b, oid):
        if self.guard or not b.get_active(): return
        self.value = oid
        if self.on_change: self.on_change(oid)
    def set_value(self, v):
        self.guard = True; self.value = v
        if v in self.btns: self.btns[v].set_active(True)
        self.guard = False

class Gallery(Gtk.FlowBox):
    """Grid of selectable cards. add_item(id, title, sub, content_widget) -> the card button."""
    def __init__(self, cols=3, on_pick=None):
        super().__init__(); self.set_selection_mode(Gtk.SelectionMode.NONE); self.set_homogeneous(True)
        self.set_min_children_per_line(2); self.set_max_children_per_line(cols); self.set_row_spacing(12); self.set_column_spacing(12)
        self.set_valign(Gtk.Align.START); self.on_pick = on_pick; self.items = {}; self.guard = False; self.value = None
    def add_item(self, iid, title, sub="", content=None, badge=False):
        b = Gtk.Button(); cls(b, "gallery"); b.set_relief(Gtk.ReliefStyle.NONE)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        if content is not None: v.pack_start(content, False, False, 4)
        t = label(title, "gallery-title", xalign=0.5, wrap=True); t.set_justify(Gtk.Justification.CENTER); v.pack_start(t, False, False, 0)
        if sub:
            s = label(sub, "gallery-sub", xalign=0.5, wrap=True); s.set_justify(Gtk.Justification.CENTER); s.set_max_width_chars(22); v.pack_start(s, False, False, 0)
        b.add(v); b.connect("clicked", self._click, iid); set_a11y(b, title, sub or None)
        b.title_text = title
        self.items[iid] = b; self.add(b); b.show_all(); return b
    def _click(self, _b, iid):
        if self.on_pick and not self.guard: self.on_pick(iid)
    def select(self, iid):
        self.value = iid
        for k, b in self.items.items():
            c = b.get_style_context(); (c.add_class if k == iid else c.remove_class)("selected")
    def clear(self):
        for c in self.get_children(): self.remove(c)
        self.items = {}

def confirm(parent, title, text, ok="OK", destructive=False):
    d = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.NONE, text=title, secondary_text=text, title="Settings")
    cls(d, "cset")
    d.add_button("Cancel", Gtk.ResponseType.CANCEL); b = d.add_button(ok, Gtk.ResponseType.OK)
    cls(b, "destructive-action" if destructive else "suggested-action")
    r = d.run(); d.destroy(); return r == Gtk.ResponseType.OK

def ask_text(parent, title, text, placeholder="", password=False, ok="OK", fields=1):
    """Small modal with 1-2 entries; returns list of strings or None."""
    d = Gtk.Dialog(transient_for=parent, modal=True, title="Settings")
    cls(d, "cset")
    area = d.get_content_area(); area.set_spacing(8); area.set_margin_start(24); area.set_margin_end(24); area.set_margin_top(24); area.set_margin_bottom(8)
    area.pack_start(label(title, "row-title", wrap=True), False, False, 0)
    if text: area.pack_start(label(text, "row-sub", wrap=True), False, False, 0)
    entries = []
    for i in range(fields):
        e = Gtk.Entry(); e.set_activates_default(True)
        if i == 0 and placeholder: e.set_placeholder_text(placeholder)
        if password: e.set_visibility(False)
        area.pack_start(e, False, False, 4); entries.append(e)
    d.add_button("Cancel", Gtk.ResponseType.CANCEL); b = d.add_button(ok, Gtk.ResponseType.OK); cls(b, "suggested-action"); d.set_default_response(Gtk.ResponseType.OK)
    d.show_all(); r = d.run(); res = [e.get_text() for e in entries]; d.destroy()
    return res if r == Gtk.ResponseType.OK else None

def hidpi_image(path, size, fallback_icon="image-missing"):
    """Image from a file (svg/png) rendered at size x size logical px, sharp on HiDPI screens."""
    try:
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
        import cairo
        scale = Gdk.Screen.get_default().get_monitor_scale_factor(0) if Gdk.Screen.get_default().get_n_monitors() else 1
        pb = GdkPixbuf.Pixbuf.new_from_file_at_size(path, size * scale, size * scale)
        surf = Gdk.cairo_surface_create_from_pixbuf(pb, scale, None)
        return Gtk.Image.new_from_surface(surf)
    except Exception:
        i = Gtk.Image.new_from_icon_name(fallback_icon, Gtk.IconSize.DIALOG); i.set_pixel_size(size); return i

def copy_text(text):
    Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)

# ---------------------------------------------------------------- ProgressSheet: long actions inside the app (never a terminal)
class ProgressSheet(Gtk.Dialog):
    """Dialog with a title, a status line and a progress bar for one or more commands run in order.
    steps: [(title, status_text, cmd_list, needs_root, env)]. done(ok) is called when the sheet is closed (ok = every step finished)."""
    def __init__(self, parent, heading, steps, done=None, detail_note=""):
        super().__init__(transient_for=parent, modal=True, title="Settings"); cls(self, "cset")
        from . import runner
        self.runner = runner; self.steps = steps; self.done_cb = done; self.job = None; self.ok = False; self.finished = False; self.password = None
        self.set_default_size(420, -1); self.set_resizable(False)
        area = self.get_content_area(); area.set_spacing(12)
        for m in ("start", "end"): getattr(area, f"set_margin_{m}")(24)
        area.set_margin_top(24); area.set_margin_bottom(8)
        self.heading = label(heading, "row-title", wrap=True); area.pack_start(self.heading, False, False, 0)
        self.status = label("Getting ready...", "row-sub", wrap=True); area.pack_start(self.status, False, False, 0)
        self.bar = Gtk.ProgressBar(); area.pack_start(self.bar, False, False, 4)
        self.steplab = label("", "row-sub"); area.pack_start(self.steplab, False, False, 0)
        self.ex = Gtk.Expander(label="Show details"); self.tv = Gtk.TextView(); self.tv.set_editable(False); self.tv.set_monospace(True); sw = Gtk.ScrolledWindow(); sw.set_min_content_height(120); sw.add(self.tv); self.ex.add(sw)
        self.ex.set_no_show_all(True); area.pack_start(self.ex, False, False, 0)
        self.btn_cancel = self.add_button("Cancel", Gtk.ResponseType.CANCEL); self.btn_retry = self.add_button("Try again", Gtk.ResponseType.APPLY); cls(self.btn_retry, "suggested-action")
        self.btn_close = self.add_button("Close", Gtk.ResponseType.CLOSE)
        for b in (self.btn_retry, self.btn_close): b.set_no_show_all(True); b.hide()
        self.connect("response", self.on_response); self.connect("delete-event", lambda *a: not self.finished)
        self.pulse_id = GLib.timeout_add(120, self.pulse); self.step_i = 0
        self.show_all(); self.ex.hide()
        GLib.idle_add(self.start)
    def pulse(self):
        if self.finished: return False
        if self.frac is None: self.bar.pulse()
        return True
    frac = None
    def log(self, text):
        b = self.tv.get_buffer(); b.insert(b.get_end_iter(), text + "\n")
    def start(self):
        self.finished = False; self.ok = False; self.step_i = 0; self.tv.get_buffer().set_text("")
        for b in (self.btn_retry, self.btn_close): b.hide()
        self.btn_cancel.show(); self.btn_cancel.set_sensitive(True); self.ex.hide(); self.run_step(); return False
    def run_step(self):
        if self.step_i >= len(self.steps): return self.finish(True)
        title, status, cmd, needs_root, env = self.steps[self.step_i]
        self.status.set_text(status or title); self.frac = None
        self.steplab.set_text(f"Step {self.step_i + 1} of {len(self.steps)}" if len(self.steps) > 1 else "")
        self.bar.set_fraction(0.0); self.pulsing = True
        full = list(cmd); password = None
        if needs_root:
            kind, prefix = self.runner.elevation()
            if kind is None: return self.finish(False, "This needs your administrator password, and this computer has no way to ask for it. Open a terminal and run: doas " + " ".join(cmd))
            if kind in ("doas", "sudo"):
                if self.password is None:
                    r = ask_text(self, "Password needed", "Type your password to continue. It is only used for this action.", "Password", True, "Continue")
                    if r is None: return self.finish(False, "The password was not entered, so nothing was changed.")
                    self.password = r[0]
                password = self.password; full = prefix + full
            else: full = prefix + full
        job = self.runner.Job(full, env, password); self.job = job
        def work():
            def on_line(l):
                f, t = self.runner.parse_progress(l)
                GLib.idle_add(self.on_line, l, f, t)
            return job.run(on_line)
        from . import sysutil as su
        su.bg(work, lambda rc: self.step_done(rc))
    def on_line(self, raw, frac, text):
        self.log(raw)
        if frac is not None:
            self.frac = frac; self.bar.set_fraction(max(0.0, min(1.0, (self.step_i + frac) / len(self.steps))))
        if text: self.status.set_text(text)
        return False
    def step_done(self, rc):
        if isinstance(rc, Exception): rc = 1
        job = self.job
        details = "\n".join(job.tail[-6:]) if job else ""
        if "do not restart" in details.lower():
            return self.finish(False, self.runner.friendly_error(rc, details))
        if job and job.cancelled:
            return self.finish(False, "Cancelled. Some changes may have completed; review the details before trying again.")
        if job and job.auth_failed and rc != 0:
            self.password = None
            return self.finish(False, "That password did not work. Try again.")
        if rc != 0: return self.finish(False, self.runner.friendly_error(rc, details))
        self.step_i += 1; self.frac = 1.0; self.bar.set_fraction(self.step_i / len(self.steps)); self.run_step()
    def finish(self, ok, message=""):
        self.finished = True; self.ok = ok; self.btn_cancel.hide()
        if ok:
            self.bar.set_fraction(1.0); self.status.set_text("Done."); GLib.timeout_add(700, lambda: (self.response(Gtk.ResponseType.CLOSE), False)[1]); return
        self.bar.set_fraction(0.0); self.status.set_text(message); self.heading.set_text("That did not work")
        self.btn_retry.show(); self.btn_close.show(); self.ex.show(); self.ex.set_no_show_all(False)
    def on_response(self, d, rid):
        if rid == Gtk.ResponseType.CANCEL and self.job and not self.finished: self.job.cancel(); self.btn_cancel.set_sensitive(False); return
        if rid == Gtk.ResponseType.APPLY: self.heading.set_text(self.heading.get_text()); GLib.idle_add(self.start); return
        if rid in (Gtk.ResponseType.CLOSE, Gtk.ResponseType.DELETE_EVENT):
            cb, self.done_cb = self.done_cb, None; self.destroy()
            if cb: cb(self.ok)

def run_sheet(parent, heading, steps, done=None):
    """show a ProgressSheet (non-blocking)"""
    return ProgressSheet(parent, heading, steps, done)
