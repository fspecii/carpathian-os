"""`carpatic wallpaper ...` command line. Exit codes: 0 ok, 1 error (plain-English message on stderr), 2 usage."""
import json, os, re, subprocess, sys, urllib.parse

from . import apply, library, paths, state, wallhaven

USAGE = """usage: carpatic wallpaper <command>
  list [carpatic|mine|all] [--json]     show the pictures (id, size, title)
  set <path|id|title> [--fill MODE] [--monitor NAME] [--theme] [--light|--dark]
  fill fill|fit|stretch|center|tile     change how the picture covers the screen
  add <file|folder|wallhaven-url|wallhaven:ID>   add to My pictures (a Wallhaven id is downloaded)
  remove <file|folder>                  stop listing it (files on disk are never deleted)
  next | random                         next picture of the rotation collection / a random one
  rotate on [--every MIN] [--collection NAME] [--no-shuffle] [--login] | off | status | resume
  collection list | new NAME | add NAME PATH | rm NAME [PATH] | show NAME
  wallhaven search QUERY [--sort S] [--range R] [--page N] [--all-sizes] [--category general|anime|people ...] [--json]
  wallhaven get ID [--set] [--no-download]      show details, download, optionally set
  wallhaven key set|clear                       optional API key (read from stdin), stored mode 600
  accent [path] [--apply]                       suggest an accent colour from the picture
  pair light PATH dark PATH | pair off          a different picture for light and dark
  sync                                          apply the pair / per-theme picture (theme-set hook)
  resolve                                       print the paired / per-theme picture
  paint [PATH] [--fill MODE]                    repaint explicitly or use the current picture and saved fill mode
  thumbs [--stats|--prune]                      thumbnail cache"""

def err(m): print(m, file=sys.stderr)

def find_item(ref):
    if os.path.isfile(os.path.expanduser(ref)): return os.path.abspath(os.path.expanduser(ref))
    items = library.builtin_items() + library.local_items()
    for i in items:
        if i.id == ref: return i.path
    hits = [i for i in items if ref.lower() == i.title.lower() or ref.lower() in (os.path.basename(i.path).lower(), os.path.splitext(os.path.basename(i.path))[0].lower())]
    if not hits: hits = [i for i in items if ref.lower() in i.title.lower()]
    if len(hits) == 1: return hits[0].path
    if len(hits) > 1:
        paths_ = {i.path for i in hits}
        if len({os.path.basename(p) for p in paths_}) == 1: return sorted(paths_)[0]
        mode = apply.theme_mode()
        m = [i for i in hits if i.mode == mode]
        if len(m) == 1: return m[0].path
        raise apply.WallpaperError("More than one picture matches: " + ", ".join(f"{i.id} ({i.title} {i.mode})" for i in hits[:6]))
    raise apply.WallpaperError(f"No picture called '{ref}'. Try: carpatic wallpaper list")

def opt(args, name, default=None, flag=False):
    if name in args:
        i = args.index(name)
        if flag: args.pop(i); return True
        v = args[i + 1] if i + 1 < len(args) else None
        del args[i:i + 2]; return v
    return default

def add_target(ref, client=None):
    m = re.match(r"^(?:wallhaven:|https://wallhaven\.cc/w/|https://whvn\.cc/)([a-z0-9]{4,10})/?$", ref)
    if m:
        c = client or wallhaven.Client()
        w = c.info(m.group(1))
        return c.download(w)
    if re.match(r"^[a-z]+://", ref):
        if ref.startswith("file://"): ref = urllib.parse.unquote(urllib.parse.urlsplit(ref).path)
        else: raise apply.WallpaperError("Only wallhaven.cc links can be added from the web. Save the picture first, then add the file.")
    p = os.path.abspath(os.path.expanduser(ref))
    if os.path.isdir(p): library.add_folder(p); return p
    return library.add_file(p)

def main(argv=None, client=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if not a or a[0] in ("-h", "--help", "help"): print(USAGE); return 0 if a else 2
    cmd, a = a[0], a[1:]
    try:
        return run(cmd, a, client)
    except (apply.WallpaperError, library_error(), wallhaven.WallhavenError, KeyError, ValueError) as e:
        err(str(e).strip("'") if isinstance(e, KeyError) else str(e)); return 1
    except Exception as e:  # never a raw traceback for a user
        err(f"Something went wrong ({type(e).__name__}). Run with CARPATIC_DEBUG=1 for details.")
        if os.environ.get("CARPATIC_DEBUG"): raise
        return 1

def library_error(): return OSError

def run(cmd, a, client):
    if cmd == "list":
        js = opt(a, "--json", flag=True)
        which = a[0] if a else "all"
        items = []
        if which in ("all", "carpatic"): items += library.builtin_items()
        if which in ("all", "mine", "local"): items += library.local_items(with_hashes=True)
        if js: print(json.dumps([i.to_dict() for i in items], indent=1))
        else:
            for i in items:
                print(f"{i.id}  {i.width}x{i.height:<5} {i.mode or '-':5} {i.title}" + ("  (duplicate)" if i.dup_of else "") + f"  {i.path}")
        return 0
    if cmd == "set":
        if not a: raise apply.WallpaperError("Which picture? carpatic wallpaper set <path|id|title>")
        fill, mon = opt(a, "--fill"), opt(a, "--monitor")
        th = opt(a, "--theme", flag=True); li = opt(a, "--light", flag=True); da = opt(a, "--dark", flag=True)
        p = apply.set_wallpaper(find_item(a[0]), fill=fill, monitor=mon, for_theme=th, pair="light" if li else "dark" if da else None)
        print(p); return 0
    if cmd == "fill":
        if not a or a[0] not in apply.FEH_FLAGS: raise apply.WallpaperError("fill, fit, stretch, center or tile?")
        cur = apply.current_wallpaper()
        state.update(lambda d: d.update(fill=a[0]))
        apply.set_setting("WALLPAPER_MODE", a[0])
        if cur: apply.paint(cur, a[0])
        return 0
    if cmd == "add":
        if not a: raise apply.WallpaperError("Add what? a file, a folder or a Wallhaven link")
        print(add_target(a[0], client)); return 0
    if cmd == "remove":
        if not a: raise apply.WallpaperError("Remove what?")
        p = os.path.abspath(os.path.expanduser(a[0]))
        (library.remove_folder if p in library.folders() else library.remove_file)(p); return 0
    if cmd in ("next", "random"):
        if cmd == "next": print(apply.advance())
        else:
            import random
            pool = state.collection_paths("all", apply.theme_mode())
            cur = apply.current_wallpaper()
            pool = [p for p in pool if p != cur] or pool
            if not pool: raise apply.WallpaperError("No pictures to choose from.")
            print(apply.set_wallpaper(random.choice(pool)))
        return 0
    if cmd == "rotate":
        sub = a[0] if a else "status"; a = a[1:]
        if sub == "status":
            r = state.load()["rotation"]
            print(("on" if r["enabled"] else "off") + f", every {r['every']} min, collection {r['collection']}, {'shuffled' if r['shuffle'] else 'in order'}" + (", at login" if r["on_login"] else ""))
        elif sub == "on":
            ev, col = opt(a, "--every"), opt(a, "--collection")
            ns, lg = opt(a, "--no-shuffle", flag=True), opt(a, "--login", flag=True)
            if col: state.collection_paths(col, "dark")
            apply.set_rotation(True, ev, col, False if ns else None, True if lg else None)
            spawn_daemon()
        elif sub == "off": apply.set_rotation(False)
        elif sub == "daemon":
            if os.environ.get("CARPATIC_SESSION") != "1" and not os.environ.get("CARPATIC_FORCE"):
                err("The wallpaper timer only runs inside a Carpatic session."); return 1
            apply.rotate_loop()
        elif sub == "resume":   # called by carpatic-session at login: advance once (At login) and start the timer when it is on
            r = state.load()["rotation"]
            if r["on_login"]: print(apply.advance())
            if r["enabled"]: spawn_daemon()
        elif sub == "login":
            if state.load()["rotation"]["on_login"]: print(apply.advance())
        else: raise apply.WallpaperError("rotate on|off|status")
        return 0
    if cmd == "collection":
        sub = a[0] if a else "list"; a = a[1:]
        st = state.load()
        if sub == "list":
            for k, v in state.VIRTUAL.items(): print(f"{k:16} {v}")
            for k, v in st["collections"].items(): print(f"{k:16} {len(v)} pictures")
        elif sub == "new": state.collection_new(a[0])
        elif sub == "add": state.collection_add(a[0], apply.validate(find_item(a[1])))
        elif sub == "rm": state.collection_remove(a[0], os.path.abspath(a[1]) if len(a) > 1 else None)
        elif sub == "show":
            for p in state.collection_paths(a[0], apply.theme_mode()): print(p)
        else: raise apply.WallpaperError("collection list|new|add|rm|show")
        return 0
    if cmd == "wallhaven":
        return run_wallhaven(a, client)
    if cmd == "accent":
        from . import color
        js_apply = opt(a, "--apply", flag=True)
        p = find_item(a[0]) if a else apply.current_wallpaper()
        hexv = color.accent_for(p, apply.theme_mode() == "dark")
        if not hexv: print("This picture has no clear colour; keeping the theme accent."); return 0
        print(hexv)
        if js_apply:
            return subprocess.run(["carpatic-theme", "set", apply.current_theme(), "--accent", hexv]).returncode
        return 0
    if cmd == "pair":
        if a and a[0] == "off": state.update(lambda d: d["pair"].update(enabled=False)); return 0
        kv = dict(zip(a[0::2], a[1::2]))
        if set(kv) != {"light", "dark"}: raise apply.WallpaperError("pair light PATH dark PATH")
        l, d = apply.validate(find_item(kv["light"])), apply.validate(find_item(kv["dark"]))
        state.update(lambda s: s["pair"].update(light=l, dark=d, enabled=True)); print(apply.sync() or "ok"); return 0
    if cmd == "sync":
        apply.sync(); return 0
    if cmd == "resolve":      # for carpatic-apply: the paired / per-theme picture, only when the THEME changed since the last look
        st = state.load()
        th = apply.current_theme()
        if st.get("last_theme") == th and "--force" not in a: return 0   # an apply without a theme change must not undo a picture picked by hand
        state.update(lambda d: d.update(last_theme=th))
        p = apply.resolve_for_theme(th, st)
        if p: print(p)
        return 0
    if cmd == "paint":        # Painting does not change saved wallpaper/per-monitor choices.
        requested_fill = "--fill" in a
        fill = opt(a, "--fill")
        if requested_fill and fill not in apply.FEH_FLAGS:
            raise apply.WallpaperError("paint --fill needs fill, fit, stretch, center or tile.")
        if len(a) > 1 or (a and a[0].startswith("--")):
            raise apply.WallpaperError("usage: carpatic wallpaper paint [PATH] [--fill MODE]")
        cur = apply.validate(a[0]) if a else apply.current_wallpaper()
        if not cur:
            raise apply.WallpaperError("No current wallpaper. Choose a picture or pass its path to paint.")
        if not apply.paint(cur, fill):
            raise apply.WallpaperError("Could not paint the wallpaper. Check the display and wallpaper backend.")
        return 0
    if cmd == "thumbs":
        from . import thumbs
        if "--prune" in a: print(thumbs.prune_cache())
        else: print(json.dumps(thumbs.cache_stats()))
        return 0
    print(USAGE, file=sys.stderr); return 2

def spawn_daemon():
    pid = os.path.join(paths.wp_config_dir(), "rotate.pid")
    try:
        os.kill(int(open(pid).read()), 0); return
    except (OSError, ValueError):
        pass
    p = subprocess.Popen([sys.argv[0] if os.path.basename(sys.argv[0]).startswith("carpatic") else "carpatic-wallpaper", "rotate", "daemon"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    paths.ensure(os.path.dirname(pid)); open(pid, "w").write(str(p.pid))

def run_wallhaven(a, client):
    sub = a[0] if a else ""; a = a[1:]
    if sub == "key":
        if a[:1] == ["clear"]: wallhaven.save_api_key(""); return 0
        wallhaven.save_api_key(sys.stdin.readline()); print("Saved (mode 600)."); return 0
    c = client or wallhaven.Client()
    if sub == "search":
        js = opt(a, "--json", flag=True)
        q = wallhaven.Query(sorting=opt(a, "--sort", "toplist"), top_range=opt(a, "--range", "1M"), page=int(opt(a, "--page", "1")))
        if not opt(a, "--all-sizes", flag=True):
            w, h = apply.display_size(); q.atleast = f"{w}x{h}"
        cats = []
        while "--category" in a: cats.append(opt(a, "--category"))
        if cats: q.categories = "".join("1" if k in cats else "0" for k, _ in wallhaven.CATEGORIES)
        q.text = " ".join(a)
        r = c.search(q)
        if js: print(json.dumps([w.__dict__ for w in r.items], indent=1))
        else:
            for w in r.items: print(f"{w.id}  {w.width}x{w.height:<5} {w.favorites:>5} fav  {w.url}")
            print(f"page {r.page} of {r.last_page}" + ("  (offline: showing saved results)" if r.stale else ""), file=sys.stderr)
        return 0
    if sub == "get":
        if not a: raise apply.WallpaperError("Which wallpaper id?")
        w = c.info(a[0])
        print(f"{w.id}  {w.resolution}  {w.file_size // 1024} KB  {w.file_type}\n{w.url}\n{w.attribution}\ntags: {', '.join(w.tags)}\nsource: {w.source or '-'}")
        if "--no-download" in a: return 0
        p = c.download(w); print("saved:", p)
        if "--set" in a: apply.set_wallpaper(p)
        return 0
    raise apply.WallpaperError("wallhaven search QUERY | get ID | key set|clear")
