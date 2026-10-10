"""Minimal ctypes binding to libX11: our own X connection for EWMH (window list, activate/close/minimise), property watching, struts,
selection ownership for the tray. PyGObject's Gdk 3 cannot read or write arbitrary properties, hence this. The connection's fd is
integrated into the GLib main loop by `attach()`."""
import ctypes, ctypes.util, os, struct

_lib = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
c_ulong, c_int, c_long, c_char_p, c_void_p, c_uint = ctypes.c_ulong, ctypes.c_int, ctypes.c_long, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_uint

_lib.XOpenDisplay.restype = c_void_p; _lib.XOpenDisplay.argtypes = [c_char_p]
_lib.XCloseDisplay.argtypes = [c_void_p]
_lib.XDefaultRootWindow.restype = c_ulong; _lib.XDefaultRootWindow.argtypes = [c_void_p]
_lib.XInternAtom.restype = c_ulong; _lib.XInternAtom.argtypes = [c_void_p, c_char_p, c_int]
_lib.XGetAtomName.restype = c_void_p; _lib.XGetAtomName.argtypes = [c_void_p, c_ulong]
_lib.XFree.argtypes = [c_void_p]
_lib.XGetWindowProperty.argtypes = [c_void_p, c_ulong, c_ulong, c_long, c_long, c_int, c_ulong, ctypes.POINTER(c_ulong), ctypes.POINTER(c_int),
                                    ctypes.POINTER(c_ulong), ctypes.POINTER(c_ulong), ctypes.POINTER(c_void_p)]
_lib.XChangeProperty.argtypes = [c_void_p, c_ulong, c_ulong, c_ulong, c_int, c_int, c_void_p, c_int]
_lib.XDeleteProperty.argtypes = [c_void_p, c_ulong, c_ulong]
_lib.XSendEvent.argtypes = [c_void_p, c_ulong, c_int, c_long, c_void_p]
_lib.XSelectInput.argtypes = [c_void_p, c_ulong, c_long]
_lib.XFlush.argtypes = [c_void_p]; _lib.XSync.argtypes = [c_void_p, c_int]
_lib.XPending.argtypes = [c_void_p]; _lib.XNextEvent.argtypes = [c_void_p, c_void_p]
_lib.XConnectionNumber.argtypes = [c_void_p]
_lib.XSetSelectionOwner.argtypes = [c_void_p, c_ulong, c_ulong, c_ulong]
_lib.XGetSelectionOwner.restype = c_ulong; _lib.XGetSelectionOwner.argtypes = [c_void_p, c_ulong]
_lib.XCreateSimpleWindow.restype = c_ulong
_lib.XCreateSimpleWindow.argtypes = [c_void_p, c_ulong, c_int, c_int, c_uint, c_uint, c_uint, c_ulong, c_ulong]
_lib.XDestroyWindow.argtypes = [c_void_p, c_ulong]
_lib.XMapWindow.argtypes = [c_void_p, c_ulong]
_lib.XGetGeometry.argtypes = [c_void_p, c_ulong, ctypes.POINTER(c_ulong), ctypes.POINTER(c_int), ctypes.POINTER(c_int), ctypes.POINTER(c_uint),
                              ctypes.POINTER(c_uint), ctypes.POINTER(c_uint), ctypes.POINTER(c_uint)]
_lib.XTranslateCoordinates.argtypes = [c_void_p, c_ulong, c_ulong, c_int, c_int, ctypes.POINTER(c_int), ctypes.POINTER(c_int), ctypes.POINTER(c_ulong)]
_lib.XSetErrorHandler.argtypes = [c_void_p]
_lib.XMoveResizeWindow.argtypes = [c_void_p, c_ulong, c_int, c_int, c_uint, c_uint]
_lib.XReparentWindow.argtypes = [c_void_p, c_ulong, c_ulong, c_int, c_int]

ERR_HANDLER = ctypes.CFUNCTYPE(c_int, c_void_p, c_void_p)
_quiet = ERR_HANDLER(lambda d, e: 0)       # a window vanishing under us must never kill the panel

PropertyChangeMask, StructureNotifyMask, SubstructureNotifyMask, SubstructureRedirectMask = 1 << 22, 1 << 17, 1 << 19, 1 << 20
PropertyNotify, DestroyNotify, ClientMessage, SelectionClear, UnmapNotify, MapNotify = 28, 17, 33, 29, 18, 19
XA_ATOM, XA_CARDINAL, XA_WINDOW, XA_STRING = 4, 6, 33, 31


class XClientMessage(ctypes.Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", c_int), ("display", c_void_p), ("window", c_ulong), ("message_type", c_ulong),
                ("format", c_int), ("data", c_long * 5)]


class XAnyEvent(ctypes.Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", c_int), ("display", c_void_p), ("window", c_ulong)]


class XPropertyEvent(ctypes.Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", c_int), ("display", c_void_p), ("window", c_ulong), ("atom", c_ulong), ("time", c_ulong), ("state", c_int)]


class XDestroyEvent(ctypes.Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", c_int), ("display", c_void_p), ("event", c_ulong), ("window", c_ulong)]


class XEvent(ctypes.Union):
    _fields_ = [("type", c_int), ("any", XAnyEvent), ("property", XPropertyEvent), ("client", XClientMessage), ("destroy", XDestroyEvent), ("pad", c_long * 24)]


class X:
    """One X connection. Atoms are cached. All reads return plain Python values and never raise on missing properties."""

    def __init__(self, display=None):
        self.dpy = _lib.XOpenDisplay(display.encode() if display else None)
        if not self.dpy: raise RuntimeError("cannot open the X display")
        _lib.XSetErrorHandler(_quiet)
        self.root = _lib.XDefaultRootWindow(self.dpy)
        self._atoms = {}; self.handlers = []; self._watch = None

    def close(self):
        if self.dpy: _lib.XCloseDisplay(self.dpy); self.dpy = None

    def atom(self, name):
        a = self._atoms.get(name)
        if a is None: a = self._atoms[name] = _lib.XInternAtom(self.dpy, name.encode(), 0)
        return a

    def atom_name(self, a):
        p = _lib.XGetAtomName(self.dpy, a)
        if not p: return ""
        s = ctypes.string_at(p).decode(errors="replace"); _lib.XFree(p); return s

    # ------------------------------------------------------------------ properties
    def get(self, win, name, typ=0, length=4096):
        """-> (format, [values]) ; values are ints (format 32/16) or bytes (format 8). Empty list when absent."""
        at, fmt, n, after, data = c_ulong(), c_int(), c_ulong(), c_ulong(), c_void_p()
        r = _lib.XGetWindowProperty(self.dpy, win, self.atom(name), 0, length, 0, typ, ctypes.byref(at), ctypes.byref(fmt), ctypes.byref(n), ctypes.byref(after), ctypes.byref(data))
        if r != 0 or not data.value or fmt.value == 0: return 0, []
        try:
            if fmt.value == 32: vals = list(ctypes.cast(data, ctypes.POINTER(c_ulong))[:n.value])
            elif fmt.value == 16: vals = list(ctypes.cast(data, ctypes.POINTER(ctypes.c_ushort))[:n.value])
            else: vals = ctypes.string_at(data.value, n.value)
        finally: _lib.XFree(data)
        return fmt.value, vals

    def get_ints(self, win, name, typ=0):
        fmt, v = self.get(win, name, typ)
        return v if fmt in (16, 32) else []

    def get_text(self, win, name):
        fmt, v = self.get(win, name)
        if fmt != 8 or not v: return ""
        return v.decode("utf-8", "replace")

    def get_strings(self, win, name):
        fmt, v = self.get(win, name)
        if fmt != 8 or not v: return []
        return [p.decode("utf-8", "replace") for p in v.split(b"\0") if p]

    def set_cardinals(self, win, name, vals, typ=XA_CARDINAL):
        arr = (c_long * len(vals))(*vals)
        _lib.XChangeProperty(self.dpy, win, self.atom(name), typ, 32, 0, ctypes.cast(arr, c_void_p), len(vals))

    def set_atoms(self, win, name, names):
        self.set_cardinals(win, name, [self.atom(n) for n in names], XA_ATOM)

    def set_windows(self, win, name, ids): self.set_cardinals(win, name, ids, XA_WINDOW)

    def set_utf8(self, win, name, s):
        b = s.encode(); _lib.XChangeProperty(self.dpy, win, self.atom(name), self.atom("UTF8_STRING"), 8, 0, c_char_p(b), len(b))

    def set_string(self, win, name, s):
        b = s.encode(); _lib.XChangeProperty(self.dpy, win, self.atom(name), XA_STRING, 8, 0, c_char_p(b), len(b))

    def delete(self, win, name): _lib.XDeleteProperty(self.dpy, win, self.atom(name))

    # ------------------------------------------------------------------ messages
    def send(self, win, msg, data=(0, 0, 0, 0, 0), target=None, fmt=32, mask=SubstructureNotifyMask | SubstructureRedirectMask):
        ev = XEvent(); ev.client.type = ClientMessage; ev.client.window = win; ev.client.message_type = self.atom(msg); ev.client.format = fmt
        d = list(data) + [0] * (5 - len(data))
        for i in range(5): ev.client.data[i] = d[i]
        _lib.XSendEvent(self.dpy, target or self.root, 0, mask, ctypes.byref(ev)); _lib.XFlush(self.dpy)

    def select(self, win, mask): _lib.XSelectInput(self.dpy, win, mask)
    def set_focus(self, win):
        _lib.XSetInputFocus.argtypes = [c_void_p, c_ulong, c_int, c_ulong]; _lib.XSetInputFocus(self.dpy, win, 2, 0); _lib.XFlush(self.dpy)
    def flush(self): _lib.XFlush(self.dpy)
    def sync(self): _lib.XSync(self.dpy, 0)

    def geometry(self, win):
        """(x, y, w, h) in root coordinates, or None."""
        r, x, y, w, h, bw, d = c_ulong(), c_int(), c_int(), c_uint(), c_uint(), c_uint(), c_uint()
        if not _lib.XGetGeometry(self.dpy, win, ctypes.byref(r), ctypes.byref(x), ctypes.byref(y), ctypes.byref(w), ctypes.byref(h), ctypes.byref(bw), ctypes.byref(d)): return None
        rx, ry, ch = c_int(), c_int(), c_ulong()
        _lib.XTranslateCoordinates(self.dpy, win, self.root, 0, 0, ctypes.byref(rx), ctypes.byref(ry), ctypes.byref(ch))
        return rx.value, ry.value, w.value, h.value

    # ------------------------------------------------------------------ selections (tray manager)
    def own_selection(self, name, win): _lib.XSetSelectionOwner(self.dpy, self.atom(name), win, 0); _lib.XFlush(self.dpy)
    def selection_owner(self, name): return _lib.XGetSelectionOwner(self.dpy, self.atom(name))
    def create_window(self, w=1, h=1): return _lib.XCreateSimpleWindow(self.dpy, self.root, -10, -10, w, h, 0, 0, 0)
    def destroy_window(self, win): _lib.XDestroyWindow(self.dpy, win)

    # ------------------------------------------------------------------ events
    def attach(self, glib, callback):
        """Pump X events into callback(kind, window, atom_name_or_data) from the GLib main loop."""
        self.callback = callback
        self._watch = glib.io_add_watch(_lib.XConnectionNumber(self.dpy), glib.PRIORITY_DEFAULT, glib.IOCondition.IN, self._on_io)

    def _on_io(self, *a):
        self.drain(); return True

    def drain(self):
        ev = XEvent()
        while self.dpy and _lib.XPending(self.dpy):
            _lib.XNextEvent(self.dpy, ctypes.byref(ev))
            t = ev.type
            if t == PropertyNotify: self.callback("property", ev.property.window, self.atom_name(ev.property.atom))
            elif t == DestroyNotify: self.callback("destroy", ev.destroy.window, None)
            elif t == ClientMessage: self.callback("client", ev.client.window, (self.atom_name(ev.client.message_type), list(ev.client.data)))
            elif t == SelectionClear: self.callback("selection-clear", ev.any.window, None)
            else: self.callback("other", ev.any.window, t)
