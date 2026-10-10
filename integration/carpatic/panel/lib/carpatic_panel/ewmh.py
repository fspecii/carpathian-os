"""EWMH view of the desktop for the panel: client list with icons/state, active window, desktops (dwm tags), and the actions
(activate, close, minimise, restore, set struts). Window changes are reported through `on_change` (debounced by the caller)."""
import os
from . import xlib
from .tasks import Win

SKIP_TYPES = {"_NET_WM_WINDOW_TYPE_DOCK", "_NET_WM_WINDOW_TYPE_DESKTOP", "_NET_WM_WINDOW_TYPE_SPLASH", "_NET_WM_WINDOW_TYPE_TOOLBAR",
              "_NET_WM_WINDOW_TYPE_MENU", "_NET_WM_WINDOW_TYPE_DROPDOWN_MENU", "_NET_WM_WINDOW_TYPE_POPUP_MENU", "_NET_WM_WINDOW_TYPE_TOOLTIP",
              "_NET_WM_WINDOW_TYPE_NOTIFICATION", "_NET_WM_WINDOW_TYPE_COMBO", "_NET_WM_WINDOW_TYPE_DND"}


class Ewmh:
    def __init__(self, x=None, on_change=None):
        self.x = x or xlib.X(); self.on_change = on_change or (lambda what: None)
        self.watched = set()
        self.x.select(self.x.root, xlib.PropertyChangeMask | xlib.StructureNotifyMask)

    # ------------------------------------------------------------------ reading
    def client_ids(self): return [w for w in self.x.get_ints(self.x.root, "_NET_CLIENT_LIST", xlib.XA_WINDOW)]
    def active_id(self):
        v = self.x.get_ints(self.x.root, "_NET_ACTIVE_WINDOW", xlib.XA_WINDOW); return v[0] if v else 0

    def desktops(self):
        n = self.x.get_ints(self.x.root, "_NET_NUMBER_OF_DESKTOPS"); cur = self.x.get_ints(self.x.root, "_NET_CURRENT_DESKTOP")
        names = self.x.get_strings(self.x.root, "_NET_DESKTOP_NAMES")
        return (n[0] if n else 0), (cur[0] if cur else 0), names

    def window(self, wid, active=0):
        x = self.x
        types = {x.atom_name(a) for a in x.get_ints(wid, "_NET_WM_WINDOW_TYPE", xlib.XA_ATOM)}
        if types & SKIP_TYPES: return None
        state = {x.atom_name(a) for a in x.get_ints(wid, "_NET_WM_STATE", xlib.XA_ATOM)}
        if "_NET_WM_STATE_SKIP_TASKBAR" in state: return None
        cls = x.get_strings(wid, "WM_CLASS"); inst, klass = (cls + ["", ""])[:2] if len(cls) >= 2 else (cls[0] if cls else "", cls[0] if cls else "")
        title = x.get_text(wid, "_NET_WM_NAME") or (x.get(wid, "WM_NAME")[1].decode("latin-1") if x.get(wid, "WM_NAME")[0] == 8 else "")
        hints = x.get_ints(wid, "WM_HINTS"); urgent = bool(hints and hints[0] & 256)
        urgent = urgent or "_NET_WM_STATE_DEMANDS_ATTENTION" in state
        hidden = "_NET_WM_STATE_HIDDEN" in state
        dsk = x.get_ints(wid, "_NET_WM_DESKTOP"); pid = x.get_ints(wid, "_NET_WM_PID")
        return Win(wid, title, klass, inst, wid == active, urgent, hidden, dsk[0] if dsk else 0, 0, "", pid[0] if pid else 0)

    def windows(self):
        act = self.active_id(); out = []
        ids = self.client_ids()
        for wid in ids:
            if wid not in self.watched:
                self.x.select(wid, xlib.PropertyChangeMask | xlib.StructureNotifyMask); self.watched.add(wid)
            w = self.window(wid, act)
            if w is not None: out.append(w)
        self.watched &= set(ids)
        return out

    def icon(self, wid, want=32):
        """_NET_WM_ICON -> (w, h, [argb ints]) closest to `want`, or None."""
        fmt, vals = self.x.get(wid, "_NET_WM_ICON", 0, 1 << 20)
        if fmt != 32: return None
        best = None; i = 0
        while i + 2 <= len(vals):
            w, h = vals[i], vals[i + 1]
            if w <= 0 or h <= 0 or i + 2 + w * h > len(vals): break
            if best is None or abs(w - want) < abs(best[0] - want): best = (w, h, vals[i + 2:i + 2 + w * h])
            i += 2 + w * h
        return best

    def geometry(self, wid): return self.x.geometry(wid)

    # ------------------------------------------------------------------ events
    def handle(self, kind, win, extra):
        """Called for every X event; returns a short reason string when the task list must be rebuilt."""
        if kind == "property":
            if win == self.x.root and extra in ("_NET_CLIENT_LIST", "_NET_ACTIVE_WINDOW", "_NET_CURRENT_DESKTOP", "_NET_NUMBER_OF_DESKTOPS", "_NET_DESKTOP_NAMES"): return extra
            if win != self.x.root and extra in ("_NET_WM_NAME", "WM_NAME", "WM_HINTS", "_NET_WM_STATE", "_NET_WM_ICON", "WM_CLASS", "_NET_WM_DESKTOP"): return extra
        elif kind == "destroy": return "destroy"
        return None

    # ------------------------------------------------------------------ actions
    def activate(self, wid, source=2): self.x.send(wid, "_NET_ACTIVE_WINDOW", (source, 0, 0, 0, 0))
    def close(self, wid): self.x.send(wid, "_NET_CLOSE_WINDOW", (0, 2, 0, 0, 0))
    def minimize(self, wid): self.x.send(wid, "WM_CHANGE_STATE", (3, 0, 0, 0, 0))     # IconicState (ICCCM 4.1.4)
    def set_state(self, wid, add, prop1, prop2=None):
        self.x.send(wid, "_NET_WM_STATE", (1 if add else 0, self.x.atom(prop1), self.x.atom(prop2) if prop2 else 0, 2, 0))
    def maximize(self, wid, on=True): self.set_state(wid, on, "_NET_WM_STATE_MAXIMIZED_VERT", "_NET_WM_STATE_MAXIMIZED_HORZ")
    def above(self, wid, on=True): self.set_state(wid, on, "_NET_WM_STATE_ABOVE")
    def switch_desktop(self, n): self.x.send(self.x.root, "_NET_CURRENT_DESKTOP", (n, 0, 0, 0, 0))

    def set_struts(self, wid, left=0, right=0, top=0, bottom=0, ranges=None):
        """_NET_WM_STRUT_PARTIAL (+ legacy _NET_WM_STRUT) and dock type, so dwm reserves the strip."""
        r = ranges or (0, 0, 0, 0, 0, 0, 0, 0)
        self.x.set_cardinals(wid, "_NET_WM_STRUT_PARTIAL", [left, right, top, bottom, *r])
        self.x.set_cardinals(wid, "_NET_WM_STRUT", [left, right, top, bottom])
        self.x.set_atoms(wid, "_NET_WM_WINDOW_TYPE", ["_NET_WM_WINDOW_TYPE_DOCK"]); self.x.flush()
