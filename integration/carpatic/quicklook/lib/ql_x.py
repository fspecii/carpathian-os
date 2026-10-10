"""Tiny Xlib/XTest helper (ctypes, no extra packages): focus handling and sending keys to the file manager. Every call is wrapped so that a
vanished window can never kill the daemon (X errors are swallowed by our own error handler)."""
import ctypes, ctypes.util

class X:
    def __init__(self):
        self.ok = False
        try:
            self.x = ctypes.CDLL("libX11.so.6")
            self.x.XOpenDisplay.restype = ctypes.c_void_p
            self.x.XOpenDisplay.argtypes = [ctypes.c_char_p]
            self.x.XSetInputFocus.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            self.x.XGetInputFocus.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int)]
            self.x.XFlush.argtypes = [ctypes.c_void_p]
            self.x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
            self.x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            self.x.XStringToKeysym.restype = ctypes.c_ulong
            self.x.XStringToKeysym.argtypes = [ctypes.c_char_p]
            self.x.XGetWindowProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long, ctypes.c_long, ctypes.c_int, ctypes.c_ulong,
                                                  ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_ulong),
                                                  ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_void_p)]
            self.x.XInternAtom.restype = ctypes.c_ulong
            self.x.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
            self.x.XFree.argtypes = [ctypes.c_void_p]
            self.x.XDefaultRootWindow.restype = ctypes.c_ulong
            self.x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            self._handler_t = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
            self._handler = self._handler_t(lambda d, e: 0)       # ignore BadWindow & co
            self.x.XSetErrorHandler.argtypes = [self._handler_t]
            self.x.XSetErrorHandler(self._handler)
            self.d = self.x.XOpenDisplay(None)
            self.tst = ctypes.CDLL("libXtst.so.6")
            self.tst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
            self.ok = bool(self.d)
        except (OSError, AttributeError):
            self.ok = False

    def focus(self):
        """(window id, revert_to) of the window that has the keyboard focus; (0, 0) when unknown or nobody."""
        if not self.ok: return 0, 0
        w, r = ctypes.c_ulong(0), ctypes.c_int(0)
        self.x.XGetInputFocus(self.d, ctypes.byref(w), ctypes.byref(r))
        return (w.value, r.value) if w.value > 1 else (0, 0)

    def set_focus(self, win):
        if not self.ok or not win: return
        self.x.XSetInputFocus(self.d, win, 2, 0)      # RevertToParent, CurrentTime
        self.x.XFlush(self.d)

    def keys(self, win, names):
        """Send real key presses (XTest) to `win`: focus it, press, and let the caller take the focus back."""
        if not self.ok: return False
        self.set_focus(win)
        for n in names:
            kc = self.x.XKeysymToKeycode(self.d, self.x.XStringToKeysym(n.encode()))
            if not kc: continue
            self.tst.XTestFakeKeyEvent(self.d, kc, 1, 0)
            self.tst.XTestFakeKeyEvent(self.d, kc, 0, 0)
        self.x.XFlush(self.d)
        return True

    def keys_to_focus(self, names):
        """Press and release keys for whoever has the keyboard focus (XTest)."""
        if not self.ok: return False
        for n in names:
            kc = self.x.XKeysymToKeycode(self.d, self.x.XStringToKeysym(n.encode()))
            if not kc: continue
            self.tst.XTestFakeKeyEvent(self.d, kc, 1, 0); self.tst.XTestFakeKeyEvent(self.d, kc, 0, 0)
        self.x.XFlush(self.d); self.x.XSync(self.d, 0)
        return True

    def window_class_name(self, win):
        """WM_CLASS of a window (best effort) to recognise the file manager."""
        if not self.ok or not win: return ""
        try:
            atom = self.x.XInternAtom(self.d, b"WM_CLASS", 0)
            t, f, n, after, data = ctypes.c_ulong(), ctypes.c_int(), ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_void_p()
            if self.x.XGetWindowProperty(self.d, win, atom, 0, 64, 0, 31, ctypes.byref(t), ctypes.byref(f), ctypes.byref(n), ctypes.byref(after), ctypes.byref(data)) != 0 or not data.value:
                return ""
            s = ctypes.string_at(data.value, n.value).replace(b"\0", b" ").decode("latin-1")
            self.x.XFree(data)
            return s.strip()
        except Exception:
            return ""


class KeyGrabber:
    """While the preview is open, take the few keys it uses (Space, Esc, Enter, arrows...) away from whatever window has the focus, so the file
    manager keeps the keyboard focus (dwm hands focus back to the tiled window whenever anything else takes it). Passive XGrabKey on the root
    window, ungrabbed the moment the preview closes; the X server drops the grab by itself if the daemon dies."""
    LOCKS = (0, 2, 16, 2 | 16)                  # none, CapsLock, NumLock, both: a grab only matches the exact modifier state
    SHIFT, CTRL = 1, 4
    KEYS = [("space", (0,)), ("Escape", (0,)), ("Return", (0,)), ("KP_Enter", (0,)), ("Left", (0, 1)), ("Right", (0, 1)), ("Up", (0,)), ("Down", (0,)),
            ("Prior", (0,)), ("Next", (0,)), ("Home", (0,)), ("End", (0,)), ("k", (0,)), ("j", (0,)), ("l", (0,)), ("n", (0,)), ("p", (0,)),
            ("plus", (0, 1)), ("equal", (0,)), ("minus", (0,)), ("KP_Add", (0,)), ("KP_Subtract", (0,)), ("0", (0,)), ("1", (0,)), ("KP_0", (0,)), ("KP_1", (0,)),
            ("c", (4,))]

    def __init__(self, x):
        self.x = x; self.active = False; self.fd = None
        if not x.ok: return
        lib = x.x
        lib.XGrabKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        lib.XUngrabKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_ulong]
        lib.XPending.argtypes = [ctypes.c_void_p]; lib.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.XConnectionNumber.argtypes = [ctypes.c_void_p]
        lib.XKeycodeToKeysym.restype = ctypes.c_ulong; lib.XKeycodeToKeysym.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int]
        lib.XKeysymToString.restype = ctypes.c_char_p; lib.XKeysymToString.argtypes = [ctypes.c_ulong]
        self.root = lib.XDefaultRootWindow(x.d); self.fd = lib.XConnectionNumber(x.d)

    def grab(self):
        if not self.x.ok or self.active: return
        lib, d = self.x.x, self.x.d
        for name, mods in self.KEYS:
            kc = lib.XKeysymToKeycode(d, lib.XStringToKeysym(name.encode()))
            if not kc: continue
            for m in mods:
                for lk in self.LOCKS: lib.XGrabKey(d, kc, m | lk, self.root, 0, 1, 1)
        lib.XFlush(d); self.active = True

    def ungrab(self):
        if not self.x.ok or not self.active: return
        self.x.x.XUngrabKey(self.x.d, 0, 1 << 15, self.root); self.x.x.XFlush(self.x.d); self.active = False

    def events(self):
        """Pending key presses as (key name, ctrl, shift)."""
        out, lib, d = [], self.x.x, self.x.d
        buf = (ctypes.c_ubyte * 192)()
        while lib.XPending(d):
            lib.XNextEvent(d, buf)
            raw = bytes(buf)
            if raw[0] != 2: continue                           # KeyPress only
            state = int.from_bytes(raw[80:84], "little"); kc = int.from_bytes(raw[84:88], "little")
            name = lib.XKeysymToString(lib.XKeycodeToKeysym(d, kc, 1 if state & 1 else 0))
            if name is None: name = lib.XKeysymToString(lib.XKeycodeToKeysym(d, kc, 0))
            if name: out.append((name.decode(), bool(state & self.CTRL), bool(state & self.SHIFT)))
        return out
