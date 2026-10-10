"""Carpatic store core: catalog loading and a unified apk + Flatpak backend. Stdlib only (Python 3.11+)."""
import difflib
import glob
import json
import os
import time
import re
import shutil
import subprocess
import sys
import tomllib

FLATHUB = "flathub"
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


class StoreError(Exception):
    """An error with a message that is safe to show to a newcomer."""


# ---------------------------------------------------------------- catalog
def catalog_dir():
    cands = [os.environ.get("CARPATIC_STORE_CATALOG", ""),
             "/usr/local/share/carpatic/store/catalog",
             os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "catalog")]
    for c in cands:
        if c and os.path.isdir(c):
            return os.path.abspath(c)
    raise StoreError("The app catalog was not found. Reinstall carpatic-store.")


class Catalog:
    def __init__(self, path=None):
        self.path = path or catalog_dir()
        self.categories, self.apps, self.bundles = [], {}, []
        for f in sorted(glob.glob(os.path.join(self.path, "*.toml"))):
            with open(f, "rb") as fh:
                try:
                    d = tomllib.load(fh)
                except tomllib.TOMLDecodeError as e:
                    raise StoreError(f"Catalog file {os.path.basename(f)} is broken: {e}")
            if "category" in d:
                cat = dict(d["category"])
                cat["apps"] = []
                for a in d.get("app", []):
                    a = dict(a)
                    a["category"] = cat["id"]
                    self.apps[a["id"]] = a
                    cat["apps"].append(a["id"])
                self.categories.append(cat)
            self.bundles += d.get("bundle", [])
        self.categories.sort(key=lambda c: c.get("order", 99))

    def resolve(self, ref):
        """ref: catalog id, 'apk:name' or 'flatpak:app.id'. Returns an app dict."""
        if ref in self.apps:
            return self.apps[ref]
        m = re.match(r"^(apk|flatpak|compat):(.+)$", ref)
        if m:
            return {"id": ref, "name": m.group(2), "pkg": m.group(2), "source": m.group(1),
                    "description": "(not in the curated catalog)", "category": "", "icon": "", "newcomer": False}
        for a in self.apps.values():  # also accept a flathub id / package name
            if a["pkg"] == ref:
                return a
        close = difflib.get_close_matches(ref, list(self.apps), n=3, cutoff=0.6)
        hint = f" Did you mean: {', '.join(close)}?" if close else ""
        raise StoreError(f"'{ref}' is not in the catalog.{hint} Try: carpatic-store search {ref}")

    def bundle(self, bid):
        for b in self.bundles:
            if b["id"] == bid:
                return b
        return None

    def search(self, q):
        q = q.lower()
        out = []
        for a in self.apps.values():
            hay = f'{a["id"]} {a["name"]} {a["description"]} {a["category"]}'.lower()
            if all(w in hay for w in q.split()):
                out.append(a)
        return out


# ---------------------------------------------------------------- process helpers
def is_root():
    return os.geteuid() == 0


def priv_prefix():
    if is_root():
        return []
    for t in ("doas", "sudo"):
        if shutil.which(t):
            return [t]
    raise StoreError("Installing system apps needs administrator rights, but neither doas nor sudo is available.")


def run(cmd, on_line=None, env=None, password=None, tty=False):
    """Run cmd, stream output (split on \\n and \\r) to on_line. Returns exit code. password: feed to a pty (doas/sudo)."""
    e = dict(os.environ)
    e.update(env or {})
    e.setdefault("LC_ALL", "C")
    if password is not None or tty:
        return _run_pty(cmd, on_line, e, password)
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=e)
    buf = b""
    while True:
        ch = p.stdout.read(1) if not hasattr(p.stdout, "read1") else p.stdout.read1(4096)
        if not ch:
            break
        buf += ch
        parts = re.split(rb"[\r\n]", buf)
        buf = parts.pop()
        for ln in parts:
            if on_line and ln.strip():
                on_line(ln.decode("utf-8", "replace"))
    if buf.strip() and on_line:
        on_line(buf.decode("utf-8", "replace"))
    return p.wait()


def _run_pty(cmd, on_line, env, password):
    import pty
    import select
    pid, fd = pty.fork()
    if pid == 0:
        os.execvpe(cmd[0], cmd, env)
    buf, sent = b"", False
    while True:
        try:
            r, _, _ = select.select([fd], [], [], 30)
            if not r:
                continue
            data = os.read(fd, 4096)
        except OSError:
            break
        if not data:
            break
        buf += data
        if password is not None and not sent and re.search(rb"[Pp]assword.*:\s*$", buf):
            os.write(fd, password.encode() + b"\n")
            sent, buf = True, b""
            continue
        parts = re.split(rb"[\r\n]", buf)
        buf = parts.pop()
        for ln in parts:
            if on_line and ln.strip():
                on_line(ANSI.sub("", ln.decode("utf-8", "replace")).replace("\xa0", " "))
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status)


def capture(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, "LC_ALL": "C"}, timeout=120).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


# ---------------------------------------------------------------- backends
def have_flatpak():
    return shutil.which("flatpak") is not None


def installed_flatpaks():
    if not have_flatpak():
        return set()
    return {l.strip() for l in capture(["flatpak", "list", "--app", "--columns=application"]).splitlines() if l.strip() and l != "Application ID"}


def installed_apks():
    out = set()
    for l in capture(["apk", "info"]).splitlines():
        if l.strip():
            out.add(l.strip())
    return out


def _ai_installed():
    try:
        import carpatic_ai
        return {tid for tid, _, inst, _ in carpatic_ai.status() if inst}
    except Exception:  # recipes missing or not on this system
        return set()


class State:
    """Snapshot of what is installed, so a GUI can colour many rows with two commands."""
    def __init__(self):
        self.refresh()

    def refresh(self):
        self.fp = installed_flatpaks()
        self.apk = installed_apks()
        self.ai = _ai_installed()

    def installed(self, app):
        if app["source"] == "compat":
            return compat_installed(app)
        if app["source"] == "ai":
            return app["pkg"] in self.ai
        return app["pkg"] in (self.apk if app["source"] == "apk" else self.fp)


def can_open(app):
    return app.get("launch") != "none"


# ---- glibc-only software through carpatic-compat (Ubuntu box). pkg = apt name | https URL to a .deb/AppImage | local path.
COMPAT_STATE = os.path.expanduser("~/.local/share/carpatic/compat")


def _compat_marker(app):
    return os.path.join(COMPAT_STATE, re.sub(r"[^A-Za-z0-9._-]", "_", app["id"]) + ".json")


def compat_installed(app):
    return os.path.exists(_compat_marker(app))


def compat_cmd(args, on_line=None, password=None):
    """Run carpatic-compat (the single owner of the glibc box). The first run may need the admin password to prepare podman."""
    exe = shutil.which("carpatic-compat")
    if not exe:
        raise StoreError("The compatibility box tool is missing. Install it with: doas sh compat/install.sh")
    if password is None and not is_root() and sys.stdin.isatty():
        return subprocess.call([exe] + args)          # interactive: it asks for the password itself
    return run([exe] + args, on_line, password=password if not is_root() else None, tty=(password is not None and not is_root()))


def friendly(source, name, code, lines):
    """Turn a failing backend run into one clear sentence."""
    txt = "\n".join(lines[-40:]).lower()
    if "no space left" in txt or "not enough disk space" in txt or "insufficient space" in txt:
        return f"Not enough free disk space to install {name}. Free some space and try again."
    if any(k in txt for k in ("temporary error", "could not resolve", "unable to select", "network", "connection", "timed out", "unreachable", "failed to fetch", "while fetching", "unable to load summary", "error resolving", "could not connect", "couldn't connect", "name or service", "no route")):
        if "unable to select" in txt and "network" not in txt and "fetch" not in txt:
            return f"The package for {name} was not found in the Alpine repositories. Try 'carpatic-store update' first."
        return f"Could not reach the internet to download {name}. Check your connection and try again."
    if "not found" in txt or "no remote refs found" in txt:
        return f"{name} was not found in {'Flathub' if source == 'flatpak' else 'the Alpine repositories'}."
    if "permission denied" in txt or "not permitted" in txt or "incorrect password" in txt or "authentication" in txt:
        return f"Permission denied while installing {name}. Administrator rights are needed."
    last = next((l for l in reversed(lines) if l.strip()), "no details")
    return f"Installing {name} failed (exit {code}). Last message: {last.strip()}"


FLATHUB_REPO_FILES = ["/usr/local/share/carpatic/store/flathub.flatpakrepo", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "system", "flathub.flatpakrepo")]


def ensure_user_remote():
    """Per-user installs need their own 'flathub' remote (the system one is not visible to --user). No root needed.
    Uses the .flatpakrepo file shipped with the store, so adding the remote works without network; only the install itself needs it."""
    if FLATHUB in capture(["flatpak", "remotes", "--user", "--columns=name"]).split():
        return
    src = next((f for f in FLATHUB_REPO_FILES if os.path.exists(f)), "https://dl.flathub.org/repo/flathub.flatpakrepo")
    r = subprocess.run(["flatpak", "remote-add", "--user", "--if-not-exists", FLATHUB, src], capture_output=True, text=True)
    if r.returncode != 0 and FLATHUB not in capture(["flatpak", "remotes", "--user", "--columns=name"]).split():
        raise StoreError("Could not set up the Flathub app source (" + (r.stderr.strip().splitlines() or ["no details"])[-1] + "). Check your internet connection and try again.")


def _flat(args, on_line, env=None):
    if not have_flatpak():
        raise StoreError("Flatpak is not installed. Run: doas sh /usr/local/share/carpatic/store/setup-flatpak.sh")
    if "--user" in args and args[0] == "install":
        ensure_user_remote()
    if on_line:   # hide Flatpak's permission/summary tables; show only the progress lines
        inner, shown = on_line, {"v": False}
        def on_line(line, inner=inner, shown=shown):
            if not shown["v"] and re.match(r"\s*(Installing|Updating|Uninstalling)\b", line):
                shown["v"] = True
            if shown["v"] or re.search(r"(?i)error|failed|unable|could not|couldn.t|not found|no remote|warning|resolv", line):
                inner(line)   # errors are always kept, only the permission/summary tables are hidden
    return run(["flatpak"] + args, on_line, env={"TERM": "xterm-256color", "LC_ALL": "C.UTF-8", **(env or {})}, tty=True)  # tty so Flatpak prints percentages


def _apk(args, on_line, password=None):
    return run(priv_prefix() + ["apk"] + args, on_line, password=password)


def install(app, on_line=None, password=None):
    lines = []
    def cb(l):
        lines.append(l)
        if on_line:
            on_line(l)
    if app["source"] == "ai":
        import carpatic_ai
        carpatic_ai.install(app["pkg"], cb, password)
        return
    if app["source"] == "compat":
        cb(f"Preparing the compatibility box if needed, then installing {app['name']}...")
        code = compat_cmd(["install", app["pkg"]], cb, password)
        if code != 0:
            raise StoreError(f"Could not install {app['name']} in the compatibility box. Check your internet connection and try again. Details: carpatic-compat status")
        os.makedirs(COMPAT_STATE, exist_ok=True)
        json.dump({"pkg": app["pkg"], "remove_as": app.get("remove_as", app["pkg"])}, open(_compat_marker(app), "w"))
        return
    if app["source"] == "flatpak":
        code = _flat(["install", "--user", "-y", FLATHUB, app["pkg"]], cb)
    else:
        code = _apk(["add", app["pkg"]], cb, password)
    if code != 0:
        raise StoreError(friendly(app["source"], app["name"], code, lines))


def remove(app, on_line=None, password=None):
    lines = []
    def cb(l):
        lines.append(l)
        if on_line:
            on_line(l)
    if app["source"] == "ai":
        import carpatic_ai
        carpatic_ai.remove(app["pkg"], cb, password)
        return
    if app["source"] == "compat":
        code = compat_cmd(["remove", app.get("remove_as", app["pkg"])], cb, password)
        if code != 0:
            raise StoreError(f"Removing {app['name']} failed. Try: carpatic-compat remove {app.get('remove_as', app['pkg'])}")
        try:
            os.remove(_compat_marker(app))
        except OSError:
            pass
        return
    if app["source"] == "flatpak":
        code = _flat(["uninstall", "--user", "-y", app["pkg"]], cb)
    else:
        code = _apk(["del", app["pkg"]], cb, password)
    if code != 0:
        raise StoreError(f"Removing {app['name']} failed (exit {code}): {(lines or ['no details'])[-1]}")


def pending_updates():
    """-> (apk_list, flatpak_list) of names with updates available (needs a refreshed index)."""
    apk = []
    for l in capture(["apk", "list", "-u"]).splitlines():
        m = re.match(r"^(\S+?)-\d", l)
        if m:
            apk.append(m.group(1))
    fp = []
    if have_flatpak():
        fp = [l.strip() for l in capture(["flatpak", "remote-ls", "--updates", "--app", "--columns=application", FLATHUB]).splitlines() if l.strip()]
    return apk, fp


def update_all(on_line=None, password=None, apk=True, flat=True):
    errs = []
    if apk:
        if _apk(["update"], on_line, password) != 0:
            errs.append("Could not refresh the Alpine package list (offline?).")
        elif _apk(["upgrade"], on_line, password) != 0:
            errs.append("Upgrading system packages failed.")
    if flat and have_flatpak():
        if _flat(["update", "--user", "-y"], on_line) != 0:
            errs.append("Updating Flatpak apps failed (offline?).")
    try:
        import carpatic_ai
        for tid, _, inst, _ in carpatic_ai.status():
            if inst:
                t = carpatic_ai.get_tool(tid)
                if t["kind"] in ("github-tarball", "native-script", "npm", "uv"):
                    try:
                        carpatic_ai.update(t, on_line, password)
                    except StoreError as e:
                        errs.append(str(e))
    except ImportError:
        pass
    if errs:
        raise StoreError(" ".join(errs))


# Alpine splits every program into sub-packages (docs, shell completions, headers, init scripts, translations). They are not apps: no icon,
# nothing to open, and listing them next to the real program only confuses people.
_NOT_APP_SUFFIXES = ("-doc", "-dev", "-dbg", "-lang", "-openrc", "-static", "-pyc", "-bash-completion", "-zsh-completion", "-fish-completion",
                     "-completion", "-common-doc", "-man", "-mandoc")


def is_app_package(name):
    return not name.endswith(_NOT_APP_SUFFIXES)


def search_remote(q, on_status=None):
    """Search beyond the catalog: -> list of app dicts (source apk|flatpak)."""
    res = []
    for l in capture(["apk", "search", "-v", "-d", q]).splitlines()[:120]:
        m = re.match(r"^(\S+?)-\d\S*\s*-?\s*(.*)$", l)
        if m and is_app_package(m.group(1)):
            res.append({"id": "apk:" + m.group(1), "name": m.group(1), "pkg": m.group(1), "source": "apk",
                        "description": m.group(2) or "", "category": "", "icon": "", "newcomer": False})
    if have_flatpak():
        res += search_flathub(q, on_status)
    return res


def _flat_search_lines(q):
    return capture(["flatpak", "search", "--user", "--columns=name,description,application", q]).splitlines()[:40]


def search_flathub(q, on_status=None):
    """Search Flathub as a NORMAL user: through the per-user Flathub remote, whose app list (appstream) a user may refresh without root.
    The system remote's app list can only be updated by root, so a plain 'flatpak search' finds nothing for a user. The first search (or one
    after a day) refreshes the list; on_status("Updating the app list...") lets a GUI show that. Offline -> one friendly StoreError."""
    ensure_user_remote()
    stamp = os.path.expanduser("~/.cache/carpatic/store/flathub-appstream")
    fresh = os.path.exists(stamp) and time.time() - os.path.getmtime(stamp) < 86400
    lines = _flat_search_lines(q) if fresh else []
    if not any(len(l.split("\t")) >= 3 for l in lines):
        if on_status:
            on_status("Updating the app list...")
        r = subprocess.run(["flatpak", "update", "--user", "--appstream", "-y", FLATHUB], capture_output=True, text=True)
        if r.returncode != 0:
            lines = _flat_search_lines(q)            # offline: an older local app list may still answer
            if not any(len(l.split("\t")) >= 3 for l in lines):
                raise StoreError("Could not update the Flathub app list. Check your internet connection and try again.")
        else:
            os.makedirs(os.path.dirname(stamp), exist_ok=True)
            open(stamp, "w").write("ok\n")
            lines = _flat_search_lines(q)
    out = []
    for l in lines:
        cols = l.split("\t")
        if len(cols) >= 3 and "." in cols[2] and not l.startswith("No matches"):
            out.append({"id": "flatpak:" + cols[2], "name": cols[0], "pkg": cols[2], "source": "flatpak",
                        "description": cols[1], "category": "", "icon": "", "newcomer": False})
    return out


def launch_command(app):
    if app.get("launch") == "none":
        return None
    if app["source"] == "compat" and not app.get("exec") and not app.get("term"):
        return None   # compat apps get their own launcher entry (desktop file); the store shows them as installed
    if app.get("term"):
        return ["st", "-e", "sh", "-c", app["term"] + "; exec sh"]
    if app.get("exec"):
        return app["exec"].split()
    if app["source"] == "flatpak":
        return ["flatpak", "run", app["pkg"]]
    if app["source"] == "apk" and str(app.get("id", "")).startswith("apk:") and not has_desktop_entry(app["pkg"]):   # raw search hits only; catalog apps declare their own launch
        # a command-line program has no window: show it in a terminal instead of starting it invisibly
        return ["st", "-e", "sh", "-c", app["pkg"] + "; exec sh"]
    return [app["pkg"]]


def has_desktop_entry(pkg):
    dirs = [os.path.join(d, "applications") for d in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":") if d]
    dirs.append(os.path.expanduser("~/.local/share/applications"))
    return any(os.path.exists(os.path.join(d, pkg + ".desktop")) for d in dirs)


def doctor():
    """-> list of (name, ok, detail)."""
    r = []
    r.append(("flatpak installed", have_flatpak(), shutil.which("flatpak") or "missing"))
    if have_flatpak():
        rem = capture(["flatpak", "remotes", "--columns=name"])
        r.append(("Flathub remote", FLATHUB in rem, "configured" if FLATHUB in rem else "missing: run setup-flatpak.sh"))
    xd = os.environ.get("XDG_DATA_DIRS", "")
    r.append(("Flatpak apps in XDG_DATA_DIRS", "flatpak/exports/share" in xd, xd or "unset"))
    r.append(("XDG_RUNTIME_DIR", bool(os.environ.get("XDG_RUNTIME_DIR")), os.environ.get("XDG_RUNTIME_DIR", "unset")))
    r.append(("dbus session", bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS")), os.environ.get("DBUS_SESSION_BUS_ADDRESS", "unset")))
    return r
