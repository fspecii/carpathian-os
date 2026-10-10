"""Carpathian Quick Look daemon: one warm GTK process that shows and hides the preview window when asked over a Unix socket."""
import os, sys, json, time, socket, subprocess, shutil, math, threading, hashlib, signal, gc, stat, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0"); gi.require_version("GdkPixbuf", "2.0"); gi.require_version("Pango", "1.0")
from gi.repository import Gtk, Gdk, GLib, Gio, GdkPixbuf, Pango
try:
    gi.require_version("GtkSource", "4"); from gi.repository import GtkSource; HAVE_SRC = True
except (ValueError, ImportError):
    GtkSource, HAVE_SRC = None, False
try:
    gi.require_version("GdkX11", "3.0"); from gi.repository import GdkX11
except (ValueError, ImportError):
    GdkX11 = None
import ql_detect as D, ql_logic as L, ql_theme as T, ql_x
from ql_widgets import CloseButton, Canvas, SeekBar, Mpv, rgb, rounded

RT = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
RTDIR = os.path.join(RT, "carpatic-quicklook-%d" % os.getuid() if RT == "/tmp" else "carpatic-quicklook")
SOCK = os.path.join(RT, "carpatic-quicklook.sock" if RT != "/tmp" else "carpatic-quicklook-%d.sock" % os.getuid())
WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ql_worker.py")
DEBUG = os.environ.get("QL_DEBUG") == "1"

def log(*a):
    if DEBUG: print("[ql %.3f]" % time.time(), *a, file=sys.stderr, flush=True)

HINTS = "Space close   ·   ← → browse   ·   Enter open"

# Places holding credentials. The decoder sees the file system read-only (it has to read whatever you preview), but these are masked
# (empty directory / empty file) so a decoder bug cannot even read keys. No network, no writes outside the runtime dir either way.
SECRET_PATHS = (".ssh", ".gnupg", ".aws", ".kube", ".docker", ".password-store", ".local/share/keyrings", ".config/carpatic/wallpapers/wallhaven.key",
                ".mozilla", ".config/chromium", ".config/google-chrome", ".config/BraveSoftware", ".netrc", ".npmrc", ".git-credentials", ".config/gh", ".config/rclone")

def secret_masks(home=None):
    out = []
    home = home or os.path.expanduser("~")
    for rel in SECRET_PATHS:
        p = os.path.join(home, rel)
        if os.path.islink(p): continue
        if os.path.isdir(p): out += ["--tmpfs", p]
        elif os.path.isfile(p): out += ["--ro-bind", "/dev/null", p]
    return out

def sandbox_argv(rtdir=None, home=None):
    """bubblewrap prefix for the decoder: read-only view of the system, private /tmp, no network (unshare-all), no capabilities, credentials masked,
    the only writable place is the runtime dir where previews are written."""
    rtdir = rtdir or RTDIR
    return ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "--bind", rtdir, rtdir, "--unshare-all", "--die-with-parent",
            "--new-session", "--cap-drop", "ALL"] + secret_masks(home)

# ------------------------------------------------------------------------------------------ out-of-process decoder
class Worker:
    """Decoder process with a wall-clock limit. Crash, hang or memory blow-up = one friendly 'cannot preview' card; the daemon lives on."""
    def __init__(self):
        self.p = None; self.q = []; self.cur = None; self.nid = 0; self.buf = b""; self.watch = None; self.timer = None
        self.sandbox = self._pick_sandbox()
        os.makedirs(RTDIR, mode=0o700, exist_ok=True)
    def _pick_sandbox(self):
        if os.environ.get("QL_NO_SANDBOX") == "1" or not shutil.which("bwrap"): return None
        try:
            r = subprocess.run(["bwrap", "--ro-bind", "/", "/", "--unshare-all", "--die-with-parent", "true"], capture_output=True, timeout=5)
            return "bwrap" if r.returncode == 0 else None
        except Exception:
            return None
    def start(self):
        cmd = [sys.executable, WORKER]
        if self.sandbox:
            cmd = sandbox_argv() + cmd
        env = dict(os.environ, QL_OUT=RTDIR, PYTHONDONTWRITEBYTECODE="1")
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, start_new_session=True)
        os.set_blocking(self.p.stdout.fileno(), False)
        self.watch = GLib.io_add_watch(self.p.stdout.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self._readable)
        self.buf = b""
    def request(self, op, cb, timeout=10, **kw):
        self.nid += 1
        self.q.append({"id": self.nid, "op": op, "cb": cb, "timeout": timeout, "kw": kw})
        self._pump()
        return self.nid
    def drop_pending(self):
        self.q = []
        if self.cur and self.cur.get("kw", {}).get("op") is None:
            self.cur["stale"] = True
    def _pump(self):
        if self.cur or not self.q: return
        if not self.p or self.p.poll() is not None: self.start()
        self.cur = self.q.pop(0)
        msg = dict(self.cur["kw"], id=self.cur["id"], op=self.cur["op"])
        try:
            self.p.stdin.write((json.dumps(msg) + "\n").encode()); self.p.stdin.flush()
        except (OSError, ValueError):
            self._fail("Quick Look could not read this file.")
            return
        self.timer = GLib.timeout_add(int(self.cur["timeout"] * 1000), self._timeout, self.cur["id"])
    def _timeout(self, rid):
        if self.cur and self.cur["id"] == rid:
            log("worker timeout, restarting")
            self._kill()
            self._fail("This file takes too long to preview. Press Enter to open it instead.")
        return False
    def _kill(self):
        if self.watch: GLib.source_remove(self.watch); self.watch = None
        if self.p and self.p.poll() is None:
            try: os.killpg(self.p.pid, signal.SIGKILL)
            except OSError: pass
            try: self.p.wait(1)
            except Exception: pass
        self.p = None
    def _fail(self, msg):
        c, self.cur = self.cur, None
        if self.timer: GLib.source_remove(self.timer); self.timer = None
        if c and not c.get("stale"): c["cb"]({"ok": False, "error": msg})
        self._pump()
    def _readable(self, fd, cond):
        try: data = os.read(fd, 1 << 20)
        except BlockingIOError: return True
        except OSError: data = b""
        if not data:
            self.watch = None; self.p = None
            if self.cur: self._fail("Quick Look could not read this file.")
            return False
        self.buf += data
        while b"\n" in self.buf:
            line, self.buf = self.buf.split(b"\n", 1)
            try: r = json.loads(line)
            except ValueError: continue
            if self.cur and r.get("id") == self.cur["id"]:
                c, self.cur = self.cur, None
                if self.timer: GLib.source_remove(self.timer); self.timer = None
                if not c.get("stale"): c["cb"](r)
                self._pump()
        return True
    def ensure(self):
        if not self.p or self.p.poll() is not None: self.start()
    def quit(self):
        self._kill()
        self.cur = None

# ------------------------------------------------------------------------------------------ the window
class QuickLook:
    def __init__(self):
        self.look = T.look()
        self.files, self.idx, self.visible = [], 0, False
        self.token = 0; self.mpv = None; self.tick = None; self.media_len = 0.0
        self.fm_win = 0; self.nav_until = 0.0; self.tmpfiles = []
        self.x = ql_x.X()
        self.grab = ql_x.KeyGrabber(self.x)
        if self.grab.fd is not None: GLib.io_add_watch(self.grab.fd, GLib.PRIORITY_DEFAULT, GLib.IO_IN, self.on_grab_io)
        self.worker = Worker()
        self.info = None; self.canvas = None; self.pdf = None
        self.settings_mtime = 0
        self.mode = os.environ.get("QL_WINDOW", "popup")        # popup (no title bar, no window-manager) | managed
        self.build()

    # ---- window skeleton
    def build(self):
        L_ = self.look
        self.win = Gtk.Window(type=Gtk.WindowType.POPUP if self.mode == "popup" else Gtk.WindowType.TOPLEVEL)
        self.win.set_title("Carpathian Quick Look"); self.win.set_role("carpatic-quicklook"); self.win.set_wmclass("carpatic-quicklook", "CarpaticQuickLook")
        self.win.set_decorated(False); self.win.set_skip_taskbar_hint(True); self.win.set_keep_above(True); self.win.set_accept_focus(True)
        self.win.get_style_context().add_class("ql")
        self.win.connect("key-press-event", self.on_key)
        self.win.connect("map-event", lambda *a: log("mapped +%.0f ms" % ((time.monotonic() - self.t_req) * 1000)))
        self.root_drawn = False
        self.win.connect("size-allocate", lambda *a: self.apply_shape())
        self.root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); self.win.add(self.root)
        # header
        self.head = Gtk.Box(); self.head.get_style_context().add_class("ql-head"); self.head.set_size_request(-1, 44)
        self.icon = Gtk.Image(); self.icon.set_pixel_size(24)
        self.title = Gtk.Label(xalign=0); self.title.get_style_context().add_class("ql-title"); self.title.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.sub = Gtk.Label(xalign=0); self.sub.get_style_context().add_class("ql-sub"); self.sub.set_ellipsize(Pango.EllipsizeMode.END)
        tb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); tb.set_valign(Gtk.Align.CENTER); tb.pack_start(self.title, False, False, 0); tb.pack_start(self.sub, False, False, 0)
        self.drag = Gtk.EventBox(); db = Gtk.Box(spacing=10); db.pack_start(self.icon, False, False, 0); db.pack_start(tb, True, True, 0); self.drag.add(db)
        self.drag.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, [Gtk.TargetEntry.new("text/uri-list", 0, 0)], Gdk.DragAction.COPY)
        self.drag.connect("drag-data-get", self.on_drag_get)
        self.count = Gtk.Label(); self.count.get_style_context().add_class("ql-sub")
        self.open_btn = Gtk.Button(label="Open"); self.open_btn.get_style_context().add_class("ql-open"); self.open_btn.set_can_focus(False)
        self.open_btn.connect("clicked", lambda *_: self.open_default()); self.open_btn.set_valign(Gtk.Align.CENTER)
        self.close = CloseButton(L_["buttons"], L_, self.hide)
        left = T.button_side(L_["buttons"]) == "left"
        pad = Gtk.Box(); pad.set_size_request(12, 1)
        if left: self.head.pack_start(self.close, False, False, 8)
        else: self.head.pack_start(pad, False, False, 6)
        self.head.pack_start(self.drag, True, True, 6)
        self.head.pack_start(self.count, False, False, 8); self.head.pack_start(self.open_btn, False, False, 6)
        if not left: self.head.pack_start(self.close, False, False, 0)
        else: self.head.pack_start(Gtk.Box(), False, False, 6)
        self.root.pack_start(self.head, False, False, 0)
        # body + footer
        self.body = Gtk.Box(); self.body.set_hexpand(True); self.body.set_vexpand(True); self.body.get_style_context().add_class("ql-body")
        self.root.pack_start(self.body, True, True, 0)
        self.foot = Gtk.Box(); self.foot.get_style_context().add_class("ql-foot"); self.foot.set_size_request(-1, 30)
        self.status = Gtk.Label(xalign=0); self.status.set_ellipsize(Pango.EllipsizeMode.END)
        self.hints = Gtk.Label(label=HINTS, xalign=1); self.hints.get_style_context().add_class("ql-hint")
        self.foot.pack_start(self.status, True, True, 14); self.foot.pack_end(self.hints, False, False, 14)
        self.root.pack_end(self.foot, False, False, 0)
        self.apply_css()
        self.root.show_all()
        self.t_req = time.monotonic()
        self.body.connect("draw", lambda *a: (log("first body paint +%.0f ms" % ((time.monotonic() - self.t_req) * 1000)) if not getattr(self, "_p", 0) else None, setattr(self, "_p", 1), False)[2])

    def apply_css(self):
        L_ = self.look; r = L_["radius"]
        mono = '"JetBrains Mono", "DejaVu Sans Mono", monospace'
        css = f"""
        window.ql {{ background-color: {L_['surface']}; color: {L_['fg']}; border: 1px solid alpha({L_['fg']}, 0.18); border-radius: {r}px; }}
        .ql-head {{ background-color: {L_['surface']}; border-bottom: 1px solid alpha({L_['fg']}, 0.10); border-radius: {r}px {r}px 0 0; }}
        .ql-title {{ font-weight: 600; font-size: 13px; color: {L_['fg']}; }}
        .ql-sub, .ql-hint {{ font-size: 11px; color: {L_['muted']}; }}
        .ql-foot {{ background-color: {L_['surface']}; border-top: 1px solid alpha({L_['fg']}, 0.10); font-size: 11px; color: {L_['muted']}; border-radius: 0 0 {r}px {r}px; }}
        .ql-body {{ background-color: {L_['bg']}; }}
        .ql-open {{ background-image: none; background-color: {L_['accent']}; color: {L_['accent_fg']}; border: none; border-radius: 999px; padding: 3px 14px;
                   font-size: 12px; font-weight: 600; box-shadow: none; min-height: 0; }}
        .ql-open:hover {{ background-color: alpha({L_['accent']}, 0.85); }}
        .ql-open label {{ color: {L_['accent_fg']}; }}
        .ql-pill {{ background-image: none; background-color: alpha({L_['fg']}, 0.10); color: {L_['fg']}; border: none; border-radius: 999px; padding: 4px 14px; box-shadow: none; min-height: 0; }}
        .ql-pill:hover {{ background-color: alpha({L_['fg']}, 0.18); }}
        .ql-play {{ background-image: none; background-color: {L_['accent']}; color: {L_['accent_fg']}; border: none; border-radius: 999px; min-width: 44px; min-height: 44px; padding: 0; box-shadow: none; }}
        .ql-play:hover {{ background-color: alpha({L_['accent']}, 0.85); }}
        .ql-play image {{ color: {L_['accent_fg']}; }}
        .ql-big {{ font-size: 22px; font-weight: 600; color: {L_['fg']}; }}
        .ql-muted {{ color: {L_['muted']}; font-size: 12px; }}
        .ql-key {{ color: {L_['muted']}; font-size: 12px; }}
        .ql-val {{ color: {L_['fg']}; font-size: 12px; }}
        .ql-mono {{ font-family: {mono}; font-size: 11px; color: {L_['muted']}; }}
        .ql-paper {{ background-color: {L_['bg']}; }}
        textview, textview text, .ql-text {{ background-color: {L_['bg']}; color: {L_['fg']}; font-family: {mono}; font-size: 12px; }}
        textview.ql-prose, textview.ql-prose text {{ font-family: Inter, Cantarell, sans-serif; font-size: 14px; }}
        textview text selection, textview selection {{ background-color: {L_['selection']}; color: {L_['fg']}; }}
        treeview.view {{ background-color: {L_['bg']}; color: {L_['fg']}; font-size: 12px; }}
        treeview.view:selected, treeview.view:selected:focus {{ background-color: {L_['selection']}; color: {L_['fg']}; }}
        treeview header button {{ background-image: none; background-color: {L_['surface']}; color: {L_['muted']}; border: none; border-bottom: 1px solid alpha({L_['fg']}, 0.1); font-weight: 600; font-size: 11px; }}
        scrollbar slider {{ background-color: alpha({L_['fg']}, 0.28); border-radius: 999px; min-width: 6px; min-height: 6px; border: 2px solid transparent; }}
        scrollbar slider:hover {{ background-color: alpha({L_['fg']}, 0.45); }}
        scrollbar trough {{ background: transparent; border: none; }}
        scrolledwindow {{ border: none; }}
        tooltip {{ background-color: {L_['surface2']}; color: {L_['fg']}; border-radius: 6px; }}
        """
        if not hasattr(self, "css"):
            self.css = Gtk.CssProvider()
            Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), self.css, Gtk.STYLE_PROVIDER_PRIORITY_USER + 5)
        self.css.load_from_data(css.encode())

    def apply_shape(self):
        """Round the corners of the (un-composited) window with an X shape mask, the same way dwm rounds its windows."""
        r = self.look["radius"]; gw = self.win.get_window()
        if not gw: return
        if r <= 0:
            gw.shape_combine_region(None, 0, 0); return
        import cairo
        W, H = self.win.get_allocated_width(), self.win.get_allocated_height()
        reg = cairo.Region(cairo.RectangleInt(0, 0, W, H))
        for y in range(r):
            dx = r - int(math.sqrt(max(0.0, r * r - (r - y - 0.5) ** 2)) + 0.5)
            if dx <= 0: continue
            for yy in (y, H - 1 - y):
                reg.subtract(cairo.RectangleInt(0, yy, dx, 1)); reg.subtract(cairo.RectangleInt(W - dx, yy, dx, 1))
        gw.shape_combine_region(reg, 0, 0)

    # ---- show / hide
    def reload_look(self):
        try: m = os.stat(os.path.join(T.CFG, "settings.conf")).st_mtime
        except OSError: m = 0
        if m == self.settings_mtime and hasattr(self, "css"): return
        self.settings_mtime = m
        new = T.look()
        if new != self.look:
            self.look = new
            self.apply_css()
            # button style and side can change: rebuild the header's close button
            self.head.remove(self.close); self.close.destroy()
            self.close = CloseButton(new["buttons"], new, self.hide)
            left = T.button_side(new["buttons"]) == "left"
            if left: self.head.pack_start(self.close, False, False, 8); self.head.reorder_child(self.close, 0)
            else: self.head.pack_end(self.close, False, False, 0)
            self.close.show_all()
            self.scheme = None

    def show(self, files, toggle=False):
        t0 = self.t_req = time.monotonic()
        files = [f for f in files if f]
        if self.visible and toggle and (not files or (files == self.files and time.monotonic() > self.nav_until)):
            self.hide(); return
        if not files:
            return
        self.reload_look()
        if not self.look["enabled"]:
            return
        self.idle_gen = getattr(self, "idle_gen", 0) + 1           # cancels a pending idle clean-up
        self.worker.ensure()
        if not self.visible:
            fw, _ = self.x.focus()
            self.fm_win = fw
            self.position()
            self.visible = True
            self.win.show()
            self.win.show()
            if self.mode == "popup": self.grab.grab()
        self.files, self.idx = files, 0
        self._p = 0
        self.show_index(0)
        log("show -> %.0f ms" % ((time.monotonic() - t0) * 1000))

    def position(self, w=None, h=None):
        disp = Gdk.Display.get_default()
        seat = disp.get_default_seat(); _, px, py = seat.get_pointer().get_position()
        mon = disp.get_monitor_at_point(px, py) or disp.get_primary_monitor()
        g = mon.get_workarea()
        w = w or max(560, min(int(g.width * 0.62), 1040)); h = h or max(420, min(int(g.height * 0.72), 760))
        w, h = min(w, g.width - 40), min(h, g.height - 40)
        self.win.set_default_size(w, h); self.win.resize(w, h)
        self.win.move(g.x + (g.width - w) // 2, g.y + (g.height - h) // 2)
        self.workarea = g

    def hide(self):
        if not self.visible: return
        self.visible = False
        self.token += 1
        self.worker.drop_pending()
        self.stop_media()
        self.grab.ungrab()
        self.win.hide()
        self.canvas = None; self.pdf = None; self.textview = None
        self.clear_body()
        for f in self.tmpfiles:
            try: os.unlink(f)
            except OSError: pass
        self.tmpfiles = []
        gc.collect()
        self.idle_gen = getattr(self, "idle_gen", 0) + 1
        GLib.timeout_add_seconds(30, self.idle_cleanup, self.idle_gen)

    @staticmethod
    def rss_mb():
        try:
            for l in open("/proc/self/status"):
                if l.startswith("VmRSS:"): return int(l.split()[1]) / 1024
        except OSError: pass
        return 0

    def idle_cleanup(self, gen):
        """Nobody looked at a preview for 30 s: stop the decoder process and, if the daemon grew, restart it (about 1 s, invisible)."""
        if self.visible or gen != self.idle_gen: return False
        self.worker.quit()
        if self.rss_mb() > float(os.environ.get("QL_RECYCLE_MB", "62")):
            log("recycling daemon at %.0f MB" % self.rss_mb())
            try: os.unlink(SOCK)
            except OSError: pass
            os.execv(sys.executable, [sys.executable] + sys.argv)
        return False

    def clear_body(self):
        for c in self.body.get_children():
            self.body.remove(c); c.destroy()

    def set_body(self, w):
        self.clear_body(); self.body.pack_start(w, True, True, 0); w.show_all()

    def status_text(self, s): self.status.set_text(s)

    # ---- navigation and keys
    def show_index(self, i):
        self.idx = i % len(self.files)
        self.token += 1
        self.worker.drop_pending()
        self.stop_media()
        self.canvas = None; self.pdf = None; self.textview = None
        path = self.files[self.idx]
        self.info = D.kind(path)
        info = self.info
        self.title.set_text(info["name"])
        sub = D.LABEL.get(info["kind"], "File")
        if info["kind"] in ("folder", "missing", "special"): pass
        elif "stat" in info: sub += " · " + D.human_size(info["stat"].st_size)
        self.sub.set_text(sub)
        self.count.set_text("%d of %d" % (self.idx + 1, len(self.files)) if len(self.files) > 1 else "")
        self.set_icon(path, info)
        self.set_open_label(info)
        self.status_text(""); self.hints.set_text(HINTS)
        try: getattr(self, "k_" + info["kind"])(path, info, self.token)
        except Exception as e:                                         # a renderer bug must never take the daemon down
            log("render error", repr(e))
            self.show_message("Quick Look could not show this file.", "Press Enter to open it with its usual app.")

    def set_icon(self, path, info):
        try:
            gi_ = Gio.File.new_for_path(path).query_info("standard::icon", Gio.FileQueryInfoFlags.NONE, None).get_icon()
            self.icon.set_from_gicon(gi_, Gtk.IconSize.DND)
        except GLib.Error:
            self.icon.set_from_icon_name("text-x-generic", Gtk.IconSize.DND)

    def set_open_label(self, info):
        name = ""
        try:
            if info["kind"] == "folder": name = "Files"
            else:
                ai = Gio.AppInfo.get_default_for_type(info.get("mime", ""), False)
                name = ai.get_display_name() if ai else ""
        except Exception: pass
        short = name.split(" Media")[0].split(" Viewer")[0]
        self.open_btn.set_label(("Open with " + (short[:16] + "\u2026" if len(short) > 17 else short)) if short else "Open")
        self.open_btn.set_sensitive(info["kind"] != "missing")

    def nav(self, d):
        if len(self.files) > 1:
            self.show_index(self.idx + d)
        else:
            # one item shown: move the selection in the file manager and ask again (macOS behaviour)
            self.nav_until = time.monotonic() + 1.2
            # The grab stays on until the very moment the keys are sent (so a second arrow typed in between is caught and queued as another
            # forward, not delivered to the file manager behind our back); it is released only for the XTest call, which is synchronous
            # (XSync), and taken again at once. The old code released it for 150 ms, long enough for a quick second key to be lost.
            def forward():                                      # a moment later: the physical key must be up, or X ignores our fake press
                popup = self.visible and self.mode == "popup"
                if popup: self.grab.ungrab()                    # our own grab would swallow the keys we are about to send
                try: self.x.keys_to_focus(["Left" if d < 0 else "Right", "space"])
                finally:
                    if popup and self.visible: self.grab.grab()
                return False
            GLib.timeout_add(70, forward)

    def on_key(self, w, ev):                                   # managed-window mode: keys arrive through GTK
        k = Gdk.keyval_name(ev.keyval) or ""; st = ev.state & Gtk.accelerator_get_default_mod_mask()
        return self.dispatch(k, bool(st & Gdk.ModifierType.CONTROL_MASK), bool(st & Gdk.ModifierType.SHIFT_MASK))

    def on_grab_io(self, fd, cond):                            # popup mode: keys arrive through the X grab
        for k, ctrl, shift in self.grab.events():
            if self.visible: self.dispatch(k, ctrl, shift)
        return True

    def scroll(self, k):
        sw = self.find_scroller(self.body)
        if not sw: return
        a = sw.get_vadjustment(); page = a.get_page_size()
        step = {"Up": -60, "Down": 60, "Prior": -page * 0.9, "Next": page * 0.9, "Home": -1e9, "End": 1e9}[k]
        a.set_value(max(a.get_lower(), min(a.get_upper() - page, a.get_value() + step)))

    def find_scroller(self, w):
        if isinstance(w, Gtk.ScrolledWindow): return w
        if isinstance(w, Gtk.Container):
            for c in w.get_children():
                r = self.find_scroller(c)
                if r: return r
        return None

    def dispatch(self, k, ctrl=False, shift=False):
        if k in ("space", "Escape") and not ctrl: self.hide(); return True
        if k in ("Return", "KP_Enter"): self.open_default(); return True
        if k in ("Left", "Right") and not (ctrl or shift): self.nav(-1 if k == "Left" else 1); return True
        if k == "c" and ctrl:
            if self.has_selection(): tv = self.textview; tv.get_buffer().copy_clipboard(Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)); self.toast("Copied"); return True
            self.copy_path(); return True
        if k in ("k", "K") and self.mpv: self.toggle_play(); return True
        if self.mpv and ((shift and k in ("Left", "Right")) or k in ("j", "l")):
            self.mpv.seek_rel(-5 if k in ("Left", "j") else 5); return True
        if self.canvas and k in ("plus", "equal", "KP_Add"): self.canvas.zoom_by(1.25); return True
        if self.canvas and k in ("minus", "KP_Subtract"): self.canvas.zoom_by(0.8); return True
        if self.canvas and k in ("0", "KP_0"): self.canvas.set_zoom(0, fit=True); return True
        if self.canvas and k in ("1", "KP_1"): self.canvas.set_zoom(1.0); return True
        if self.pdf:
            if k in ("Next", "Page_Down", "n"): self.pdf_goto(self.pdf["page"] + 1); return True
            if k in ("Prior", "Page_Up", "p"): self.pdf_goto(self.pdf["page"] - 1); return True
            if k == "Home": self.pdf_goto(0); return True
            if k == "End": self.pdf_goto(self.pdf["pages"] - 1); return True
        if k in ("Up", "Down", "Prior", "Next", "Home", "End"): self.scroll(k); return True
        return False

    def has_selection(self):
        tv = getattr(self, "textview", None)
        return bool(tv and self.body.get_children() and tv.get_buffer().get_has_selection())

    def copy_path(self):
        p = self.files[self.idx]
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(p, -1)
        self.toast("Path copied")

    def toast(self, msg, ms=1600):
        old = self.status.get_text(); self.status.set_text(msg)
        GLib.timeout_add(ms, lambda: (self.status.set_text(old) if self.status.get_text() == msg else None, False)[1])

    def on_drag_get(self, w, ctx, data, info, time_):
        data.set_uris([Gio.File.new_for_path(self.files[self.idx]).get_uri()])

    def open_default(self):
        if not self.files: return
        path = self.files[self.idx]
        try:
            Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(path).get_uri(), None)
        except GLib.Error:
            subprocess.Popen(["xdg-open", path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.hide()

    # ---- small building blocks
    def label(self, text, cls=None, wrap=False, sel=False, xalign=0):
        l = Gtk.Label(label=text, xalign=xalign)
        if cls: l.get_style_context().add_class(cls)
        l.set_line_wrap(wrap); l.set_selectable(sel)
        return l

    def show_message(self, title, detail="", icon="dialog-information-symbolic"):
        b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); b.set_valign(Gtk.Align.CENTER); b.set_halign(Gtk.Align.CENTER)
        im = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.DIALOG); im.set_pixel_size(56); im.set_opacity(0.6)
        b.pack_start(im, False, False, 0)
        t = self.label(title, "ql-big", wrap=True, xalign=0.5); t.set_justify(Gtk.Justification.CENTER); b.pack_start(t, False, False, 0)
        if detail:
            d = self.label(detail, "ql-muted", wrap=True, xalign=0.5); d.set_justify(Gtk.Justification.CENTER); b.pack_start(d, False, False, 0)
        b.set_margin_start(40); b.set_margin_end(40)
        self.set_body(b)

    def loading(self):
        self.set_body(self.label("Loading…", "ql-muted", xalign=0.5))

    def scrolled(self, child, h=Gtk.PolicyType.AUTOMATIC):
        sw = Gtk.ScrolledWindow(); sw.set_policy(h, Gtk.PolicyType.AUTOMATIC); sw.add(child); return sw

    def facts_grid(self, rows):
        g = Gtk.Grid(column_spacing=14, row_spacing=6)
        for i, (k, v) in enumerate(rows):
            if not v: continue
            g.attach(self.label(k, "ql-key", xalign=1), 0, i, 1, 1)
            vl = self.label(v, "ql-val", wrap=True, sel=True); vl.set_max_width_chars(60); g.attach(vl, 1, i, 1, 1)
        return g

    def file_facts(self, info):
        st = info.get("stat") or info.get("lstat"); rows = []
        if not st: return rows
        u, g = L.owner_of(st)
        rows += [("Kind", D.LABEL.get(info["kind"], "File") + (" (%s)" % info["mime"] if info["mime"] not in ("application/octet-stream", "inode/directory") else "")),
                 ("Size", D.human_size(st.st_size) + (" (%s bytes)" % format(st.st_size, ",") if st.st_size >= 1000 else "")),
                 ("Modified", L.when(st.st_mtime)), ("Opened", L.when(st.st_atime)), ("Changed", L.when(st.st_ctime)),
                 ("Permissions", "%s  (%s:%s)" % (L.perm_string(info["lstat"].st_mode), u, g)),
                 ("Location", os.path.dirname(info["path"]) or "/")]
        if info.get("link"): rows.append(("Link to", info["link"]))
        return rows

    # ---- renderers: one k_<kind> per kind
    def k_missing(self, path, info, tok):
        self.show_message("This file is no longer there.", info.get("error", "It may have been moved or deleted."), "dialog-warning-symbolic")

    def k_special(self, path, info, tok):
        self.show_message("This is a special file.", "Devices, sockets and pipes cannot be previewed.\n" + L.perm_string(info["lstat"].st_mode))

    def k_binary(self, path, info, tok):
        if info.get("error"): return self.show_message("You cannot open this file.", info["error"], "dialog-warning-symbolic")
        self.card(path, info, extra_hex=True)

    def card(self, path, info, extra_hex=False, thumb=None, title=None, lines=None, excerpt=""):
        box = Gtk.Box(spacing=28); box.set_margin_start(36); box.set_margin_end(36); box.set_margin_top(28); box.set_margin_bottom(24)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); left.set_valign(Gtk.Align.START)
        if thumb:
            im = Gtk.Image.new_from_pixbuf(thumb)
        else:
            im = Gtk.Image(); im.set_pixel_size(96)
            try: im.set_from_gicon(Gio.File.new_for_path(path).query_info("standard::icon", 0, None).get_icon(), Gtk.IconSize.DIALOG)
            except GLib.Error: im.set_from_icon_name("text-x-generic", Gtk.IconSize.DIALOG)
            im.set_pixel_size(96)
        left.pack_start(im, False, False, 0)
        box.pack_start(left, False, False, 0)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        t = self.label(title or info["name"], "ql-big", wrap=True, sel=True); t.set_max_width_chars(48); right.pack_start(t, False, False, 0)
        for ln in lines or []:
            right.pack_start(self.label(ln, "ql-muted", wrap=True), False, False, 0)
        if excerpt:
            ex = self.label(excerpt, "ql-val", wrap=True); ex.set_max_width_chars(70); ex.set_lines(12); ex.set_ellipsize(Pango.EllipsizeMode.END)
            right.pack_start(ex, False, False, 4)
        right.pack_start(self.facts_grid(self.file_facts(info)), False, False, 6)
        if info["kind"] in ("binary", "office", "ebook", "archive") or extra_hex:
            self.checksum_row(right, path)
        if extra_hex and info.get("stat") and info["stat"].st_size:
            hx = self.label(L.hexdump(path), "ql-mono"); hx.set_selectable(True); right.pack_start(hx, False, False, 6)
        box.pack_start(right, True, True, 0)
        self.set_body(self.scrolled(box, Gtk.PolicyType.NEVER))

    def checksum_row(self, box, path):
        row = Gtk.Box(spacing=10)
        btn = Gtk.Button(label="Calculate checksum"); btn.get_style_context().add_class("ql-pill"); btn.set_can_focus(False)
        out = self.label("", "ql-mono", sel=True); out.set_line_wrap(True); out.set_line_wrap_mode(Pango.WrapMode.CHAR); out.set_max_width_chars(64)
        def done(h):
            out.set_text(("SHA-256  " + h) if h else "Could not read the file."); btn.set_label("Copy checksum"); btn.set_sensitive(bool(h)); btn.handler_unblock(hid2)
            btn.connect("clicked", lambda *_: (Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(h, -1), self.toast("Checksum copied")))
        def run(*_):
            btn.set_sensitive(False); btn.set_label("Calculating…"); btn.handler_block(hid2)
            tok = self.token
            def work():
                try: h = L.sha256_file(path, cancel=lambda: tok != self.token)
                except OSError: h = ""
                if h is not None: GLib.idle_add(lambda: (done(h) if tok == self.token else None, False)[1])
            threading.Thread(target=work, daemon=True).start()
        hid2 = btn.connect("clicked", run)
        row.pack_start(btn, False, False, 0)
        box.pack_start(row, False, False, 2); box.pack_start(out, False, False, 0)

    # -- text, code, json
    def scheme_for_look(self):
        if getattr(self, "scheme", None) is not None: return self.scheme
        if not HAVE_SRC: return None
        L_ = self.look
        key = hashlib.md5(json.dumps(L_, sort_keys=True).encode()).hexdigest()[:8]
        sid = "carpatic-ql-" + key
        d = os.path.join(GLib.get_user_cache_dir(), "carpatic", "quicklook", "styles"); os.makedirs(d, exist_ok=True)
        c = lambda n, v: f'<color name="{n}" value="{v}"/>'
        xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<style-scheme id="{sid}" name="Carpathian Quick Look" version="1.0">
 {c('bg', L_['bg'])}{c('fg', L_['fg'])}{c('sel', L_['selection'])}{c('muted', L_['subtle'])}{c('acc', L_['accent'])}{c('red', L_['red'])}{c('grn', L_['green'])}
 {c('yel', L_['yellow'])}{c('blu', L_['blue'])}{c('mag', L_['magenta'])}{c('cyn', L_['cyan'])}{c('org', L_['orange'])}{c('surf', L_['surface'])}
 <style name="text" foreground="fg" background="bg"/>
 <style name="selection" foreground="fg" background="sel"/>
 <style name="current-line" background="surf"/>
 <style name="line-numbers" foreground="muted" background="bg"/>
 <style name="search-match" background="sel"/>
 <style name="def:comment" foreground="muted" italic="true"/>
 <style name="def:shebang" foreground="muted" bold="true"/>
 <style name="def:doc-comment-element" foreground="muted" italic="true"/>
 <style name="def:string" foreground="grn"/>
 <style name="def:special-char" foreground="cyn"/>
 <style name="def:special-constant" foreground="org"/>
 <style name="def:constant" foreground="org"/>
 <style name="def:number" foreground="org"/>
 <style name="def:decimal" foreground="org"/><style name="def:base-n-integer" foreground="org"/><style name="def:floating-point" foreground="org"/>
 <style name="def:boolean" foreground="org"/>
 <style name="def:keyword" foreground="mag"/>
 <style name="def:statement" foreground="mag"/>
 <style name="def:type" foreground="yel"/>
 <style name="def:function" foreground="blu"/>
 <style name="def:builtin" foreground="blu"/>
 <style name="def:preprocessor" foreground="red"/>
 <style name="def:identifier" foreground="fg"/>
 <style name="def:operator" foreground="cyn"/>
 <style name="def:error" foreground="red" underline="true"/>
 <style name="def:warning" foreground="org"/>
 <style name="def:note" foreground="acc" bold="true"/>
 <style name="def:underlined" foreground="blu" underline="true"/>
 <style name="def:heading" foreground="acc" bold="true"/>
 <style name="def:emphasis" italic="true"/><style name="def:strong-emphasis" bold="true"/>
 <style name="def:inline-code" foreground="grn"/>
 <style name="def:link-text" foreground="blu" underline="true"/>
 <style name="def:link-destination" foreground="blu" underline="true"/>
 <style name="def:deletion" foreground="red"/><style name="def:addition" foreground="grn"/>
</style-scheme>'''
        with open(os.path.join(d, sid + ".xml"), "w") as f: f.write(xml)
        mgr = GtkSource.StyleSchemeManager.get_default(); mgr.prepend_search_path(d); mgr.force_rescan()
        self.scheme = mgr.get_scheme(sid)
        return self.scheme

    def k_text(self, path, info, tok): self.text_view(path, info, wrap=True, numbers=False, prose=True)
    def k_code(self, path, info, tok): self.text_view(path, info, wrap=False, numbers=True)
    def k_json(self, path, info, tok): self.text_view(path, info, wrap=False, numbers=True)

    def text_view(self, path, info, wrap, numbers, prose=False):
        if info.get("empty"): return self.show_message("This file is empty.", "", "text-x-generic-symbolic")
        text, cut, enc = L.read_text(path)
        note = ""
        if info["kind"] == "json": text, note = L.pretty_json(text) if not cut else (text, "")
        if HAVE_SRC:
            buf = GtkSource.Buffer(); buf.begin_not_undoable_action(); buf.set_text(text); buf.end_not_undoable_action(); buf.set_max_undo_levels(0)
            sc = self.scheme_for_look()
            if sc: buf.set_style_scheme(sc)
            if not prose:
                lm = GtkSource.LanguageManager.get_default()
                head = text[:2048].encode("utf-8", "ignore")
                ct = Gio.content_type_guess(info["name"], head)[0]
                lang = lm.guess_language(info["name"], ct) or lm.get_language(D.LANG.get(info.get("ext", ""), "")) or (lm.get_language("sh") if text.startswith("#!") else None)
                if lang: buf.set_language(lang)
            view = GtkSource.View(buffer=buf)
            view.set_show_line_numbers(numbers); view.set_highlight_current_line(False)
        else:
            buf = Gtk.TextBuffer(); buf.set_text(text); view = Gtk.TextView(buffer=buf)
        view.set_editable(False); view.set_cursor_visible(False); view.set_monospace(not prose)
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR if wrap else Gtk.WrapMode.NONE)
        view.set_left_margin(18 if not numbers else 8); view.set_right_margin(18); view.set_top_margin(14); view.set_bottom_margin(14)
        view.set_can_focus(True)
        if prose: view.get_style_context().add_class("ql-prose")
        self.textview = view
        self.set_body(self.scrolled(view))
        lines = text.count("\n") + 1
        extra = " · first %s shown" % D.human_size(L.MAX_TEXT) if cut else ""
        self.status_text("%s lines%s%s" % (format(lines, ","), extra, (" · " + note) if note else ""))
        GLib.idle_add(lambda: (view.grab_focus(), False)[1])

    # -- markdown
    def k_markdown(self, path, info, tok):
        if info.get("empty"): return self.show_message("This file is empty.", "", "text-x-generic-symbolic")
        text, cut, enc = L.read_text(path)
        view = Gtk.TextView(); buf = view.get_buffer()
        view.set_editable(False); view.set_cursor_visible(False); view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        view.set_left_margin(36); view.set_right_margin(36); view.set_top_margin(24); view.set_bottom_margin(30); view.get_style_context().add_class("ql-prose")
        L_ = self.look
        mono = "JetBrains Mono, DejaVu Sans Mono, monospace"
        tag = lambda n, **k: buf.create_tag(n, **k)
        for i, sz in enumerate((1.9, 1.5, 1.25, 1.1, 1.0, 0.95), 1):
            tag("h%d" % i, scale=sz, weight=Pango.Weight.BOLD, pixels_above_lines=14 if i < 3 else 10, pixels_below_lines=6, foreground=L_["accent"] if i == 1 else L_["fg"])
        tag("b", weight=Pango.Weight.BOLD); tag("i", style=Pango.Style.ITALIC); tag("s", strikethrough=True)
        tag("c", family=mono, background=L_["surface2"], foreground=L_["green"], scale=0.92)
        tag("a", foreground=L_["blue"], underline=Pango.Underline.SINGLE)
        tag("p", pixels_below_lines=8, pixels_inside_wrap=3)
        tag("code", family=mono, scale=0.9, paragraph_background=L_["surface"], left_margin=44, right_margin=36, pixels_above_lines=1, wrap_mode=Gtk.WrapMode.NONE)
        tag("quote", left_margin=52, foreground=L_["muted"], style=Pango.Style.ITALIC, pixels_below_lines=8)
        tag("li", pixels_below_lines=3, pixels_inside_wrap=2)
        tag("hr", foreground=L_["subtle"], pixels_above_lines=6, pixels_below_lines=6)
        tag("tbl", family=mono, scale=0.9, left_margin=44, wrap_mode=Gtk.WrapMode.NONE, pixels_below_lines=1)
        tag("front", family=mono, scale=0.85, foreground=L_["subtle"], left_margin=44, pixels_below_lines=10)
        end = lambda: buf.get_end_iter()
        def put(runs, *tags):
            for s, fl in runs:
                names = [t for t in ("b", "i", "c", "s", "a") if t in fl] + list(tags)
                buf.insert_with_tags_by_name(end(), s, *names)
        for b in L.markdown(text)[:4000]:
            k = b[0]
            if k == "h": put(b[2], "h%d" % min(b[1], 6)); buf.insert(end(), "\n")
            elif k == "p": put(b[1], "p"); buf.insert(end(), "\n")
            elif k == "li": buf.insert_with_tags_by_name(end(), "    " * b[1] + "  %s  " % b[2], "li"); put(b[3], "li"); buf.insert(end(), "\n")
            elif k == "quote": buf.insert_with_tags_by_name(end(), "▎ ", "quote"); put(b[1], "quote"); buf.insert(end(), "\n")
            elif k == "code": buf.insert_with_tags_by_name(end(), b[2].rstrip("\n") + "\n", "code"); buf.insert(end(), "\n")
            elif k == "hr": buf.insert_with_tags_by_name(end(), "─" * 40 + "\n", "hr")
            elif k == "front": buf.insert_with_tags_by_name(end(), b[1] + "\n", "front")
            elif k == "table":
                rows = b[1]; ncol = max(len(r) for r in rows); wd = [0] * ncol
                strip = lambda s: s.replace("`", "").replace("**", "")
                for r in rows:
                    for j, c in enumerate(r): wd[j] = min(40, max(wd[j], len(strip(c))))
                for ri, r in enumerate(rows):
                    line = "  ".join(strip(r[j] if j < len(r) else "")[:40].ljust(wd[j]) for j in range(ncol))
                    buf.insert_with_tags_by_name(end(), line.rstrip() + "\n", "tbl", *(["b"] if ri == 0 else []))
                    if ri == 0: buf.insert_with_tags_by_name(end(), "─" * min(100, sum(wd) + 2 * ncol) + "\n", "tbl", "hr")
                buf.insert(end(), "\n")
        self.textview = view
        self.set_body(self.scrolled(view))
        self.status_text("Markdown" + (" · first %s shown" % D.human_size(L.MAX_TEXT) if cut else ""))

    # -- csv
    def k_csv(self, path, info, tok):
        if info.get("empty"): return self.show_message("This file is empty.", "", "text-x-generic-symbolic")
        text, cut, enc = L.read_text(path, 2_000_000)
        rows, delim = L.read_csv(text)
        if not rows: return self.k_text(path, info, tok)
        ncol = min(40, max(len(r) for r in rows))
        store = Gtk.ListStore(*([str] * ncol))
        for r in rows[1:]: store.append([(r[j] if j < len(r) else "")[:200] for j in range(ncol)])
        tv = Gtk.TreeView(model=store); tv.set_grid_lines(Gtk.TreeViewGridLines.BOTH); tv.set_headers_visible(True); tv.set_enable_search(False)
        for j in range(ncol):
            cell = Gtk.CellRendererText(); cell.set_property("xpad", 10); cell.set_property("ypad", 4)
            col = Gtk.TreeViewColumn(rows[0][j][:60] if j < len(rows[0]) else "", cell, text=j); col.set_resizable(True); col.set_min_width(80); tv.append_column(col)
        self.set_body(self.scrolled(tv))
        shown = len(rows) - 1
        self.status_text("%s%s rows · %d columns%s" % (format(shown, ","), "+" if shown >= L.MAX_ROWS or cut else "", ncol, " · showing the first %d" % L.MAX_ROWS if shown >= L.MAX_ROWS else ""))

    # -- images
    def k_image(self, path, info, tok):
        self.loading()
        self.worker.request("image", lambda r: self.image_done(r, tok, info), 14, path=path, max=3000 if info.get("ext") not in ("svg", "svgz") else 1800)

    def image_done(self, r, tok, info):
        if tok != self.token: return
        if not r.get("ok"): return self.card_or_msg(r, info)
        pb = GdkPixbuf.Pixbuf.new_from_file(r["file"]); self.tmpfiles.append(r["file"])
        self.canvas = Canvas(self.look, on_zoom=self.zoom_status)
        self.set_body(self.canvas)
        self.canvas.set_pixbuf(pb, native=(r["w"], r["h"]))
        self.size_for_image(r["w"], r["h"])
        ex = r.get("exif") or {}
        bits = ["%s × %s px" % (r["w"], r["h"])] + ([r["format"].upper()] if r.get("format") else [])
        det = [ex[k] for k in ("Camera", "Lens", "Aperture", "Exposure", "ISO", "Focal length", "Taken") if k in ex]
        if ex.get("ISO"): det = [("ISO " + x) if x == ex["ISO"] else x for x in det]
        self.sub.set_text(self.sub.get_text() + " · " + " · ".join(bits))
        self.exif_line = " · ".join(det)
        self.zoom_status(self.canvas.zoom, True)

    def size_for_image(self, w, h):
        g = self.workarea; aw, ah = int(g.width * 0.78), int(g.height * 0.78)
        s = min(aw / max(w, 1), ah / max(h, 1), 1.0)
        ww, hh = max(520, int(w * s)), max(380, int(h * s) + 76)
        self.position(ww, hh)

    def zoom_status(self, z, fit):
        extra = getattr(self, "exif_line", "") if self.info and self.info["kind"] == "image" else ""
        if self.info and self.info["kind"] == "image":
            self.status_text("%s%d %%%s   (+ - zoom, 0 fit, 1 actual size)" % (("Fit · " if fit else ""), round(z * 100), ("   ·   " + extra) if extra else ""))
        elif self.pdf:
            self.pdf_status()

    def card_or_msg(self, r, info):
        self.show_message(r.get("error", "Quick Look could not show this file."), "Press Enter to open it with its usual app.", "dialog-warning-symbolic")

    # -- pdf
    def k_pdf(self, path, info, tok):
        self.loading()
        self.worker.request("pdf_info", lambda r: self.pdf_opened(r, tok, path, info), 12, path=path)

    def pdf_opened(self, r, tok, path, info):
        if tok != self.token: return
        if not r.get("ok"): return self.show_message(r.get("error", "This PDF cannot be shown."), "Press Enter to open it with a PDF viewer.", "dialog-warning-symbolic")
        self.pdf = {"path": path, "pages": r["pages"], "page": 0, "w": r["page_w"], "h": r["page_h"], "tok": tok, "busy": False, "want": None}
        self.canvas = Canvas(self.look, on_zoom=lambda z, f: self.pdf_status(), on_resize_render=self.pdf_render)
        self.set_body(self.canvas)
        t = r.get("title") or ""
        self.sub.set_text(self.sub.get_text() + " · %d page%s" % (r["pages"], "" if r["pages"] == 1 else "s"))
        g = self.workarea; ph = int(g.height * 0.86); pw = int(ph * r["page_w"] / max(r["page_h"], 1))
        if r["page_w"] > r["page_h"]: pw = int(g.width * 0.7); ph = int(pw * r["page_h"] / r["page_w"])
        self.position(max(560, min(pw + 40, g.width - 60)), max(420, min(ph + 80, g.height - 60)))
        self.pdf_render()

    def pdf_goto(self, n):
        if not self.pdf: return
        n = max(0, min(self.pdf["pages"] - 1, n))
        if n != self.pdf["page"]:
            self.pdf["page"] = n; self.pdf_render(reset=True)

    def pdf_status(self):
        if not self.pdf: return
        z = self.canvas.zoom * 100 if self.canvas and self.canvas.pb else 100
        self.status_text("Page %d of %d   (Page Up / Page Down, + - zoom, 0 fit)" % (self.pdf["page"] + 1, self.pdf["pages"]))

    def pdf_render(self, reset=False):
        p = self.pdf
        if not p: return
        if p["busy"]:
            p["want"] = True; return
        p["busy"] = True
        if self.canvas.fit or reset or self.canvas.pb is None:
            aw, ah = (self.canvas.get_allocated_width() or 900), (self.canvas.get_allocated_height() or 700)
            width = int(max(500, min(aw, ah * p["w"] / max(p["h"], 1))))      # the whole page fits the window
        else:
            width = int(self.canvas.native[0] * self.canvas.zoom)             # zoomed: render exactly the size on screen
        width = min(3000, width)
        page, tok = p["page"], p["tok"]
        self.worker.request("pdf_page", lambda r: self.pdf_page_done(r, tok, page), 20, path=p["path"], page=page, width=width, paper=self.look["paper"])
        self.pdf_status()

    def pdf_page_done(self, r, tok, page):
        p = self.pdf
        if not p or tok != p["tok"] or tok != self.token: return
        p["busy"] = False
        if not r.get("ok"):
            return self.status_text(r.get("error", "This page cannot be shown."))
        pb = GdkPixbuf.Pixbuf.new_from_file(r["file"]); self.tmpfiles.append(r["file"])
        try: os.unlink(r["file"])
        except OSError: pass
        keep = not self.canvas.fit and self.canvas.pb is not None
        if keep:                       # zoomed view: the new bitmap is drawn at the zoom the user chose
            z = self.canvas.zoom
            self.canvas.set_pixbuf(pb, native=(int(r["w"] / z), int(r["h"] / z)), keep_zoom=True)
        else:
            self.canvas.set_pixbuf(pb, native=(r["w"], r["h"]))
        if p["want"]: p["want"] = None; self.pdf_render()
        self.canvas.get_vadjustment().set_value(0)

    # -- media
    def k_audio(self, path, info, tok): self.media_view(path, info, tok, video=False)
    def k_video(self, path, info, tok): self.media_view(path, info, tok, video=True)

    def media_view(self, path, info, tok, video):
        if not shutil.which("mpv"):
            return self.card(path, info)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); box.get_style_context().add_class("ql-body")
        self.media = {"video": video, "tok": tok, "dur": 0.0, "playing": True}
        L_ = self.look
        if video:
            self.vid = Gtk.DrawingArea()
            self.vid.set_size_request(320, 200); self.vid.connect("draw", lambda w, cr: (cr.set_source_rgb(0, 0, 0), cr.paint(), True)[2])
            box.pack_start(self.vid, True, True, 0)
            self.poster = None
        else:
            top = Gtk.Box(spacing=26); top.set_margin_start(36); top.set_margin_end(36); top.set_margin_top(26)
            self.cover = Gtk.Image(); self.cover.set_size_request(200, 200)
            self.cover.set_from_icon_name("audio-x-generic-symbolic", Gtk.IconSize.DIALOG); self.cover.set_pixel_size(96); self.cover.set_opacity(0.5)
            top.pack_start(self.cover, False, False, 0)
            meta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6); meta.set_valign(Gtk.Align.CENTER)
            self.m_title = self.label(os.path.splitext(info["name"])[0], "ql-big", wrap=True); self.m_artist = self.label("", "ql-muted", wrap=True); self.m_extra = self.label("", "ql-muted", wrap=True)
            for w in (self.m_title, self.m_artist, self.m_extra): meta.pack_start(w, False, False, 0)
            top.pack_start(meta, True, True, 0)
            box.pack_start(top, True, True, 0)
        bar = Gtk.Box(spacing=14); bar.set_margin_start(26); bar.set_margin_end(26); bar.set_margin_top(10); bar.set_margin_bottom(16)
        self.play = Gtk.Button(); self.play.get_style_context().add_class("ql-play"); self.play.set_can_focus(False)
        self.play_img = Gtk.Image.new_from_icon_name("media-playback-pause-symbolic", Gtk.IconSize.LARGE_TOOLBAR); self.play.add(self.play_img)
        self.play.connect("clicked", lambda *_: self.toggle_play()); self.play.set_valign(Gtk.Align.CENTER)
        self.seek = SeekBar(L_, self.seek_frac, height=64 if not video else 28)
        self.time_l = self.label("0:00 / 0:00", "ql-muted"); self.time_l.set_width_chars(12)
        bar.pack_start(self.play, False, False, 0); bar.pack_start(self.seek, True, True, 0); bar.pack_start(self.time_l, False, False, 0)
        box.pack_end(bar, False, False, 0)
        self.set_body(box)
        self.hints.set_text("Space close   ·   K play / pause   ·   Shift+← → skip 5 s   ·   ← → browse")
        if video:
            self.position(max(640, int(self.workarea.width * 0.62)), max(480, int(self.workarea.height * 0.7)))
        # metadata and waveform from the worker; playback starts at once (after the box is realised, for video)
        self.worker.request("media", lambda r: self.media_info(r, tok), 25, path=path, palette={"accent": L_["accent"]}, video=video)
        GLib.timeout_add(120, self.start_mpv, path, tok, video)
        self.tick = GLib.timeout_add(250, self.media_tick, tok)

    def start_mpv(self, path, tok, video):
        if tok != self.token or not self.visible: return False
        wid = None
        if video:
            gw = self.vid.get_window()
            if gw is not None and GdkX11 is not None and isinstance(gw, GdkX11.X11Window): wid = gw.get_xid()
        self.mpv = Mpv(path, RTDIR, wid=wid, vo=os.environ.get("QL_VO"))
        return False

    def media_info(self, r, tok):
        if tok != self.token or not hasattr(self, "media"): return
        if r.get("duration"): self.media["dur"] = r["duration"]
        if r.get("peaks"): self.seek.peaks = r["peaks"]; self.seek.queue_draw()
        if not self.media["video"]:
            if r.get("title"): self.m_title.set_text(r["title"])
            self.m_artist.set_text(" — ".join(x for x in (r.get("artist"), r.get("album")) if x))
            bits = [r.get("codec", "").upper(), ("%d kbit/s" % (r["bitrate"] // 1000)) if r.get("bitrate") else "", ("%s Hz" % r["rate"]) if r.get("rate") else ""]
            self.m_extra.set_text("  ·  ".join(b for b in bits if b))
            if r.get("cover"):
                try:
                    pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(r["cover"], 220, 220, True); self.cover.set_from_pixbuf(pb); self.cover.set_opacity(1); self.cover.set_size_request(-1, -1)
                    self.tmpfiles.append(r["cover"])
                except GLib.Error: pass
        else:
            if r.get("w"): self.sub.set_text(self.sub.get_text() + " · %d × %d" % (r["w"], r["h"]))
        if r.get("duration"): self.sub.set_text(self.sub.get_text() + " · " + self.fmt_t(r["duration"]))

    @staticmethod
    def fmt_t(s):
        s = int(max(0, s)); return "%d:%02d:%02d" % (s // 3600, s // 60 % 60, s % 60) if s >= 3600 else "%d:%02d" % (s // 60, s % 60)

    def media_tick(self, tok):
        if tok != self.token or not self.visible or not self.mpv: return tok == self.token and self.visible
        if not self.mpv.alive():
            if self.media["video"] and time.monotonic() - self.mpv.t0 < 2.0 and not os.environ.get("QL_VO"):
                self.status_text("This video needs a different player mode; retrying…")
                self.mpv = Mpv(self.files[self.idx], RTDIR, wid=self.vid.get_window().get_xid(), vo="x11")
            else:
                self.status_text("Quick Look could not play this file. Press Enter to open it with another app.")
            return True
        pos, dur = self.mpv.get("time-pos"), self.mpv.get("duration")
        if dur: self.media["dur"] = dur
        d = self.media["dur"]
        if pos is not None and d:
            self.seek.set_frac(pos / d); self.time_l.set_text("%s / %s" % (self.fmt_t(pos), self.fmt_t(d)))
        paused = self.mpv.get("pause")
        if paused is not None: self.play_img.set_from_icon_name("media-playback-start-symbolic" if paused else "media-playback-pause-symbolic", Gtk.IconSize.LARGE_TOOLBAR)
        return True

    def toggle_play(self):
        if self.mpv: self.mpv.toggle()

    def seek_frac(self, f):
        if self.mpv and self.media["dur"]: self.mpv.seek_abs(f * self.media["dur"])

    def stop_media(self):
        self.tick = None                       # the tick callback stops itself when the token changes
        if self.mpv:
            self.mpv.stop(); self.mpv = None
        self.media = {}

    # -- archives, folders
    def k_archive(self, path, info, tok):
        self.loading()
        self.worker.request("archive", lambda r: self.archive_done(r, tok, info), 20, path=path, mime=info["mime"])

    def list_view(self, rows, cols):
        store = Gtk.ListStore(str, str, str)
        for icon, name, size in rows: store.append([icon, name, size])
        tv = Gtk.TreeView(model=store); tv.set_headers_visible(True); tv.set_enable_search(False)
        c0 = Gtk.TreeViewColumn(cols[0]); ci = Gtk.CellRendererPixbuf(); ci.set_property("xpad", 8); c0.pack_start(ci, False); c0.add_attribute(ci, "icon-name", 0)
        ct = Gtk.CellRendererText(); ct.set_property("ypad", 3); c0.pack_start(ct, True); c0.add_attribute(ct, "text", 1); c0.set_expand(True); tv.append_column(c0)
        cs = Gtk.CellRendererText(); cs.set_property("xalign", 1.0); cs.set_property("xpad", 12); cs.set_property("foreground", self.look["muted"])
        c1 = Gtk.TreeViewColumn(cols[1], cs, text=2); tv.append_column(c1)
        return tv

    def archive_done(self, r, tok, info):
        if tok != self.token: return
        if not r.get("ok"): return self.card_or_msg(r, info)
        if not r["entries"]:
            return self.show_message(r.get("note") or "This archive is empty.", "", "package-x-generic-symbolic")
        rows = [("folder-symbolic" if d else "text-x-generic-symbolic", n, "" if d else D.human_size(s)) for n, s, d in r["entries"]]
        self.set_body(self.scrolled(self.list_view(rows, ("Name", "Size"))))
        self.sub.set_text(self.sub.get_text() + " · %s items" % format(r["count"], ","))
        self.status_text(("%s items · %s once unpacked" % (format(r["count"], ","), D.human_size(r["total"]))) + (" · showing the first %d" % len(r["entries"]) if r["count"] > len(r["entries"]) else "") + ((" · " + r["note"]) if r.get("note") else ""))

    def k_folder(self, path, info, tok):
        s = L.folder_summary(path)
        if s.get("error"): return self.show_message(s["error"], "", "dialog-warning-symbolic")
        kids = s["children"]
        if not kids: return self.show_message("This folder is empty.", "", "folder-symbolic")
        rows = [("folder-symbolic" if d else "text-x-generic-symbolic", n, "" if d else D.human_size(sz)) for n, d, sz in kids[:600]]
        self.set_body(self.scrolled(self.list_view(rows, ("Name", "Size"))))
        self.sub.set_text("Folder · %s item%s" % (format(len(kids), ","), "" if len(kids) == 1 else "s"))
        pl = lambda n, w: "%s %s%s" % (format(n, ","), w, "" if n == 1 else "s")
        self.status_text("%s and %s inside%s \u00b7 %s%s" % (pl(s["files"], "file"), pl(s["dirs"], "folder"), "+" if s["partial"] else "", D.human_size(s["size"]), "+" if s["partial"] else ""))

    # -- fonts, office
    def k_font(self, path, info, tok):
        self.loading()
        L_ = self.look
        self.worker.request("font", lambda r: self.font_done(r, tok, info), 12, path=path, palette={"bg": L_["bg"], "fg": L_["fg"], "accent": L_["accent"], "muted": L_["muted"]})

    def font_done(self, r, tok, info):
        if tok != self.token: return
        if not r.get("ok"): return self.card(self.files[self.idx], info)
        pb = GdkPixbuf.Pixbuf.new_from_file(r["file"]); self.tmpfiles.append(r["file"])
        self.canvas = Canvas(self.look); self.set_body(self.canvas); self.canvas.set_pixbuf(pb, native=(r["w"], r["h"]))
        self.sub.set_text("Font · %s %s" % (r["family"], r["style"]))
        self.status_text(r.get("full", ""))

    def k_office(self, path, info, tok):
        self.loading()
        self.worker.request("office", lambda r: self.office_done(r, tok, info), 12, path=path)

    k_ebook = k_office

    def office_done(self, r, tok, info):
        if tok != self.token: return
        if not r.get("ok"): return self.card(self.files[self.idx], info)
        th = None
        if r.get("thumb_file"):
            try:
                th = GdkPixbuf.Pixbuf.new_from_file_at_scale(r["thumb_file"], 220, 280, True); self.tmpfiles.append(r["thumb_file"])
            except GLib.Error: th = None
        lines = []
        if r.get("author"): lines.append("By " + r["author"])
        if r.get("slides"): lines.append("%d slides" % r["slides"])
        if r.get("sheets"): lines.append("Sheets: " + ", ".join(r["sheets"][:8]))
        self.card(self.files[self.idx], info, thumb=th, title=r.get("title") or info["name"], lines=lines, excerpt=r.get("excerpt", ""))
