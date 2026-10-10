"""Socket front end of the Quick Look daemon. One JSON object per line: {"cmd": "show"|"toggle"|"hide"|"status"|"quit", "files": [...]}."""
import os, sys, json, socket, time, resource
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def carpatic_session():
    """Quick Look only ever runs inside a Carpathian desktop: CARPATIC_SESSION=1 (set by carpatic-session) or the configurator install marker,
    on an X11 display and never under Wayland. This keeps it from attaching to someone else's desktop (a dev host, a test run)."""
    if os.environ.get("WAYLAND_DISPLAY") or not os.environ.get("DISPLAY"): return False
    if os.environ.get("CARPATIC_SESSION") == "1": return True
    return any(os.path.isdir(p) for p in ("/usr/local/share/carpatic/configurator", "/usr/share/carpatic"))

def main():
    import ql_app
    from ql_app import GLib, SOCK, log
    # already running? then there is nothing to do
    try:
        s = socket.socket(socket.AF_UNIX); s.settimeout(0.5); s.connect(SOCK); s.sendall(b'{"cmd":"status"}\n'); s.close()
        print("carpatic-quicklookd is already running"); return 0
    except OSError:
        try: os.unlink(SOCK)
        except OSError: pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old = os.umask(0o177); srv.bind(SOCK); os.umask(old); srv.listen(8); srv.setblocking(False)
    ql = ql_app.QuickLook()

    def handle(conn):
        t0 = time.monotonic()
        try:
            conn.settimeout(0.5); data = b""
            while b"\n" not in data and len(data) < 1 << 20:
                c = conn.recv(65536)
                if not c: break
                data += c
            req = json.loads(data.split(b"\n")[0] or b"{}")
        except (OSError, ValueError):
            conn.close(); return
        cmd = req.get("cmd"); out = {"ok": True}
        files = [f for f in req.get("files", []) if isinstance(f, str) and f.startswith("/")][:500]
        try:
            if cmd == "show": ql.show(files)
            elif cmd == "toggle": ql.show(files, toggle=True)
            elif cmd == "hide": ql.hide()
            elif cmd == "status":
                rss = 0
                try:
                    for l in open("/proc/self/status"):
                        if l.startswith("VmRSS:"): rss = int(l.split()[1])
                except OSError: pass
                out.update(visible=ql.visible, file=ql.files[ql.idx] if ql.visible and ql.files else "", rss_kb=rss, pid=os.getpid(), sandbox=ql.worker.sandbox or "none",
                           window=ql.mode, enabled=ql.look["enabled"])
            elif cmd == "reload": ql.settings_mtime = 0; ql.reload_look()
            elif cmd == "quit": GLib.idle_add(lambda: (ql.worker.quit(), os.path.exists(SOCK) and os.unlink(SOCK), os._exit(0)))
            else: out = {"ok": False, "error": "unknown command"}
        except Exception as e:                                # the daemon must survive anything a file or a caller throws at it
            log("handler error", repr(e)); out = {"ok": False, "error": "failed"}
        try: conn.sendall((json.dumps(out) + "\n").encode())
        except OSError: pass
        conn.close()
        log("%s handled in %.1f ms" % (cmd, (time.monotonic() - t0) * 1000))

    def accept(fd, cond):
        try:
            while True:
                conn, _ = srv.accept(); handle(conn)
        except BlockingIOError:
            pass
        return True
    GLib.io_add_watch(srv.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN, accept)
    # warm everything a first preview needs, while nobody is waiting
    def warm():
        try:
            if ql_app.HAVE_SRC:
                lm = ql_app.GtkSource.LanguageManager.get_default()
                for n in ("a.py", "a.sh", "a.json", "a.c"): lm.guess_language(n, None)
                ql.scheme_for_look()
            ql.worker.request("ping", lambda r: (log("worker", r), ql.worker.quit()), 20)     # proves the decoder works, then frees it until needed
        except Exception as e:
            log("warm failed", repr(e))
        return False
    GLib.timeout_add(300, warm)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, 15, lambda: (ql.worker.quit(), os.path.exists(SOCK) and os.unlink(SOCK), os._exit(0)))
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, 2, lambda: (ql.worker.quit(), os.path.exists(SOCK) and os.unlink(SOCK), os._exit(0)))
    ql_app.Gtk.main()
    return 0
