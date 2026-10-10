"""XEmbed system tray (freedesktop systemtray spec): owns _NET_SYSTEM_TRAY_S0, docks icons into Gtk.Sockets placed over the panel."""
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib
from . import xlib, uiscale

SYSTEM_TRAY_REQUEST_DOCK = 0


class TrayManager:
    def __init__(self, x, on_change, icon_size=18):
        self.x = x; self.on_change = on_change; self.size = icon_size
        self.owner = 0; self.sockets = {}        # icon xid -> Gtk.Socket
        self.overlay = None; self.rect = (0, 0, 0, 0); self.horizontal = True
        self.tries = 0

    def width(self, vertical=False):
        n = len(self.sockets); return n * (self.size + 4) - (4 if n else 0)

    def acquire(self):
        """Take the selection if free. Called repeatedly at start-up because dwm's own tray releases it only after our bar mapped."""
        x = self.x
        cur = x.selection_owner("_NET_SYSTEM_TRAY_S0")
        if cur and cur != self.owner: return False
        if self.owner: return True
        win = x.create_window(); x.select(win, xlib.StructureNotifyMask)
        x.set_cardinals(win, "_NET_SYSTEM_TRAY_ORIENTATION", [0])
        x.own_selection("_NET_SYSTEM_TRAY_S0", win)
        if x.selection_owner("_NET_SYSTEM_TRAY_S0") != win: x.destroy_window(win); return False
        self.owner = win
        x.send(x.root, "MANAGER", (0, x.atom("_NET_SYSTEM_TRAY_S0"), win, 0, 0), target=x.root, mask=xlib.StructureNotifyMask)
        return True

    def release(self):
        if self.owner:
            self.x.own_selection("_NET_SYSTEM_TRAY_S0", 0); self.x.destroy_window(self.owner); self.owner = 0
        for s in list(self.sockets.values()): s.destroy()
        self.sockets.clear()

    def handle(self, kind, win, extra):
        import os
        if os.environ.get('CARPATIC_TRAY_DEBUG') and kind == 'client': print('tray client', hex(win), extra, hex(self.owner), flush=True)
        if kind == "client" and win == self.owner:
            name, data = extra
            if name == "_NET_SYSTEM_TRAY_OPCODE" and data[1] == SYSTEM_TRAY_REQUEST_DOCK: self.dock(data[2])
            return True
        if kind == "selection-clear" and win == self.owner:
            self.owner = 0
            for s in list(self.sockets.values()): s.destroy()
            self.sockets.clear(); self.on_change(); return True
        return False

    def dock(self, icon):
        if icon in self.sockets or self.overlay is None: return
        s = Gtk.Socket(); s.set_size_request(uiscale.dev(self.size), uiscale.dev(self.size)); s.set_halign(Gtk.Align.START); s.set_valign(Gtk.Align.START)
        s.connect("plug-removed", lambda sock: (self.undock(icon), True)[1])
        self.overlay.add_overlay(s); s.show(); s.add_id(icon)
        self.sockets[icon] = s; self.layout(); self.on_change()

    def undock(self, icon):
        s = self.sockets.pop(icon, None)
        if s is not None: s.destroy()
        self.layout(); self.on_change()

    def layout(self):
        x, y, w, h = self.rect; n = 0
        for icon, s in self.sockets.items():
            D = uiscale.devr      # rect and sizes are logical px, the sockets are positioned in device px
            if self.horizontal: s.set_margin_start(D(x + n * (self.size + 4))); s.set_margin_top(D(y + (h - self.size) / 2))
            else: s.set_margin_start(D(x + (w - self.size) / 2)); s.set_margin_top(D(y + n * (self.size + 4)))
            n += 1
