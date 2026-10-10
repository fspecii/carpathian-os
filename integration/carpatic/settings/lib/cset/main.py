import os, sys, time
T_PROC = time.time()

def parse(argv):
    o = {"page": None, "anchor": None, "shot": None, "theme": None, "size": None, "sub": None, "wait": 1.2, "query": None}
    it = iter(argv); rest = []
    for a in it:
        if a == "--page": o["page"] = next(it, None)
        elif a == "--anchor": o["anchor"] = next(it, None)
        elif a == "--shot": o["shot"] = next(it, None)
        elif a == "--theme": o["theme"] = next(it, None)
        elif a == "--sub": o["sub"] = next(it, None)
        elif a == "--query": o["query"] = next(it, None)
        elif a == "--wait": o["wait"] = float(next(it, "1.2"))
        elif a == "--size":
            w, _, h = (next(it, "") or "").partition("x"); o["size"] = (int(w), int(h))
        elif not a.startswith("-"): rest.append(a)
    if rest and not o["page"]: o["page"] = rest[0]
    return o

def in_carpatic_session():
    return bool(os.environ.get("CARPATIC_FORCE") or os.environ.get("CARPATIC_SESSION")
                or os.path.isdir("/usr/local/share/carpatic") or os.path.isdir("/usr/share/carpatic"))

def main(argv):
    o = parse(argv)
    if not in_carpatic_session():
        print("carpatic-settings: this is not a Carpathian OS session, so Settings will not open here.", file=sys.stderr); return 2
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, Gdk, GLib
    GLib.set_prgname("carpatic-settings"); GLib.set_application_name("Settings")
    from . import app, theme
    from .pages import ALL
    t0 = time.time()
    pal = theme.palette(o["theme"]) if o["theme"] else None
    w = app.SettingsWindow(ALL, pal, o["size"])
    w.connect("destroy", Gtk.main_quit)
    if o["shot"]: w.set_decorated(False)
    first = o["page"] or "appearance"
    w.show_all()
    w.open_page(first, sub=o["sub"], anchor=o["anchor"])
    if not w.current and w.pages: w.open_page(w.pages[0].id)
    if o["query"]: w.search.set_text(o["query"])
    w.sb_rows[w.current.id].grab_focus() if w.current else None; w.back_btn.set_visible(len(w.trail) > 1)
    if os.environ.get("CSET_TIMING"):
        done = []
        def first_draw(*_):
            if not done:
                done.append(1); print("first frame %.3fs after start of main(); process total %.3fs" % (time.time() - t0, time.time() - T_PROC), file=sys.stderr)
        w.connect_after("draw", first_draw)
    if o["shot"]:
        def shoot():
            import cairo
            al = w.get_allocation()
            sf = cairo.ImageSurface(cairo.FORMAT_ARGB32, al.width, al.height); cr = cairo.Context(sf)
            w.draw(cr); sf.write_to_png(o["shot"])
            Gtk.main_quit(); return False
        GLib.timeout_add(int(o["wait"] * 1000), shoot)
    Gtk.main()
    return 0
