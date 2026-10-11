"""Runs one flyout: builds model + view for the chosen mode, positions it next to the panel, runs the GTK loop."""
import os, sys, threading
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib
from .theme import Theme, read_env
from . import placement, popup as pp, uiscale

PROFILE_LOOK = {"windows": "win", "beginner": "win", "macos": "mac", "ubuntu": "ubuntu", "tiling": "win", "zen": "win", "kylin": "kylin"}


def threaded(fn, cb=None):
    """Run fn off the UI thread; cb(result) on it."""
    def work():
        try: r = fn()
        except Exception as e: r = None
        if cb: GLib.idle_add(lambda: (cb(r), False)[1])
    threading.Thread(target=work, daemon=True).start()


def sync_run(fn, cb=None):
    r = fn()
    if cb: cb(r)


def pick_look(args):
    if args.look: return args.look
    env = read_env(os.path.expanduser("~/.config/carpatic/profile.env"))
    return PROFILE_LOOK.get(env.get("STYLEPACK") or env.get("PROFILE", "windows"), "win")


def screen_rect():
    d = Gdk.Display.get_default()
    m = d.get_primary_monitor() or d.get_monitor(0)
    g = m.get_geometry(); return (g.x, g.y, g.width, g.height)


def main(args):
    theme = Theme.load(args.mode_theme)
    look = pick_look(args)
    pidfile = os.path.join(__import__("carpatic_panel.config", fromlist=["x"]).runtime_dir(), f"carpatic-flyout.{os.getuid()}")
    if pp.toggle_instance(args.mode, pidfile): return 0
    try:
        run = sync_run if args.fake else threaded
        if args.mode == "quick":
            from .system import System, FakeSystem
            from .media import Media, FakeMedia
            from .quickmodel import QuickModel
            from .flyout_quick import QuickView
            model = QuickModel(FakeSystem() if args.fake else System(), FakeMedia() if args.fake else Media())
            view = QuickView(theme, model, look if look in ("win", "mac", "ubuntu", "kylin") else "win", on_close=lambda: Gtk.main_quit(), async_run=run)
            if args.pane: view.open_pane(args.pane); view.pane_t = 1.0
        elif args.mode == "calendar":
            from .flyout_cal import CalView, CalModel
            from .notes import Dunst, FakeNotes
            from .system import System, FakeSystem
            s = FakeSystem() if args.fake else System()
            cal = CalModel(first=None)
            sc = screen_rect()
            view = CalView(theme, cal, FakeNotes() if args.fake else Dunst(), look if look in ("win", "mac", "ubuntu", "kylin") else "win", max_h=min(760, uiscale.logical(sc[3]) - 80),
                           dnd_get=lambda: bool(s.dnd()), dnd_set=s.dnd_set, on_close=lambda: Gtk.main_quit())
        else:
            from .flyout_start import make_start
            view = make_start(theme, look, args)
        w, h = uiscale.dev(view.size()[0]), uiscale.dev(view.size()[1])      # device px: placement works on the screen
        sc = screen_rect()
        if args.anchor:
            anchor = tuple(int(v) for v in args.anchor.split(",")); edge = args.edge or "bottom"
        else:
            st = placement.read_state(); a = placement.anchor_for(args.mode, st)
            if a: edge, anchor = a
            else:
                env = read_env(os.path.expanduser("~/.config/carpatic/profile.env"))
                bb = int(env.get("BAR_BOTTOM", 0) or 0); bt = int(env.get("BAR_TOP", 0) or 0)
                edge = args.edge or ("top" if bt and not bb else "bottom")
                anchor = (sc[0] + sc[2] - 100, sc[1] + sc[3] - bb, 100, bb) if edge == "bottom" else (sc[0] + sc[2] - 100, sc[1], 100, bt)
        x, y = placement.place(w, h, sc, edge, anchor, args.mode, getattr(args, 'align', None) or 'auto')
        if args.mode == "start" and look == "launchpad": x, y = sc[0], sc[1]
        win = pp.Popup(view, theme, (x, y), edge, slide=not args.no_slide and not args.shot and look != "launchpad")
        if args.mode == "start": win.canvas.view.menu_cb = None
        if args.shot:
            GLib.timeout_add(700, lambda: (shot(args.shot), Gtk.main_quit(), False)[2])
        Gtk.main()
    finally:
        if 'view' in locals():
            dispose = getattr(view, 'dispose', None)
            if dispose: dispose()
        try: os.unlink(pidfile)
        except OSError: pass
    return 0


def shot(path):
    root = Gdk.get_default_root_window(); w, h = root.get_width(), root.get_height()
    pb = Gdk.pixbuf_get_from_window(root, 0, 0, w, h); pb.savev(path, "png", [], [])
