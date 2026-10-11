"""Small, GTK-free helpers shared by every page: run commands (foreground, background, with polkit), read the Carpathian OS state files,
parse the output of the system tools. Everything is testable on the host: set CSET_DRY=1 and no command that changes the system
is executed (the command line is appended to $CSET_DRY_LOG instead)."""
import os, re, shutil, subprocess, threading, time

CFG = os.environ.get("CARPATIC_CONFIG") or os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "carpatic")
SHARE = os.environ.get("CARPATIC_SHARE", "/usr/local/share/carpatic/configurator")
DRY = bool(os.environ.get("CSET_DRY"))
_dry_log = os.environ.get("CSET_DRY_LOG", "/tmp/cset-dry.log")

def which(cmd):
    return shutil.which(cmd) is not None

def _log_dry(cmd):
    try:
        with open(_dry_log, "a") as f: f.write(" ".join(map(str, cmd)) + "\n")
    except OSError:
        pass

def out(*cmd, timeout=15, env=None):
    """stdout of a read-only command, '' on any failure (missing tool, timeout, non-zero exit is still returned)."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env).stdout.strip()
    except Exception:
        return ""

def lines(*cmd, **kw):
    return [l for l in out(*cmd, **kw).split("\n") if l.strip()]

def run_sync(*cmd, timeout=60, stdin=None):
    """Run a command that may change the system. Returns (returncode, output). Dry-run aware."""
    if DRY:
        _log_dry(cmd); return 0, ""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=stdin)
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    except FileNotFoundError:
        return 127, "not installed"
    except Exception as e:
        return 1, str(e)

def pk(*cmd):
    """Same command through polkit (asks for the password in a native dialog)."""
    if os.geteuid() == 0 or not which("pkexec"): return cmd
    return ("pkexec",) + cmd

def bg(fn, done=None):
    """Run fn() in a thread; call done(result) on the GTK main loop. Without GTK main loop (tests) done is called in the thread."""
    def work():
        try: res = fn()
        except Exception as e: res = e
        if done:
            try:
                from gi.repository import GLib
                GLib.idle_add(lambda: (done(res), False)[1])
            except Exception:
                done(res)
    t = threading.Thread(target=work, daemon=True); t.start(); return t

def spawn(*cmd, done=None):
    """Fire-and-forget background command; done(returncode, output) on the main loop."""
    return bg(lambda: run_sync(*cmd), (lambda r: done(*r)) if done else None)

# ---- state files ----
def read_env(path):
    d = {}
    try:
        with open(path) as f:
            for line in f:
                m = re.match(r'\s*(?:export\s+)?(\w+)=("?)(.*?)\2\s*$', line)
                if m: d[m.group(1)] = m.group(3)
    except OSError:
        pass
    return d

def settings():
    return read_env(os.path.join(CFG, "settings.conf"))

def kv_lines(*cmd):
    """Parse 'key   value' output (carpatic-touchpad status, carpatic-a11y status)."""
    d = {}
    for l in lines(*cmd):
        p = l.split(None, 1)
        d[p[0]] = p[1].strip() if len(p) == 2 else ""
    return d

def human_bytes(n):
    n = float(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or u == "TB":
            return (f"{n:.0f} {u}" if u in ("B", "KB") else (f"{n:.1f} {u}" if n < 100 else f"{n:.0f} {u}"))
        n /= 1000.0

def read_file(path, default=""):
    try:
        with open(path) as f: return f.read().strip()
    except OSError:
        return default

def install_packs(win, packs, heading, after=None, apply_after=False):
    """Install theme/icon/font packs with a progress sheet inside the app (no terminal). packs: [(id, display name, kind)]; kind 'apk' needs administrator rights (pkexec, or doas/sudo with our own password dialog)."""
    from . import runner, ui
    steps = []
    for pid, name, kind in packs:
        cmd, needs_root = runner.pack_command(pid, kind)
        steps.append((f"Installing {name}", f"Downloading {name}...", cmd, needs_root, {"CARPATIC_PROGRESS": "1"}))
    if apply_after: steps.append(("Applying the look", "Applying the look...", [shutil.which("carpatic-apply") or "carpatic-apply"], False, {}))
    return ui.ProgressSheet(win, heading, steps, after)

def desktop_entries():
    """All visible .desktop applications: [(id, name, icon, [mimetypes], exec)]. Parsed with a small reader (no GIO needed)."""
    seen = {}; res = []
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    if not os.path.isabs(data_home): data_home = os.path.expanduser("~/.local/share")
    bases = [data_home] + (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    for base in bases:
        if not os.path.isabs(base): continue
        d = os.path.join(base, "applications")
        for parent, folders, names in os.walk(d):
            folders.sort()
            for filename in sorted(names):
                if not filename.endswith(".desktop"): continue
                path = os.path.join(parent, filename)
                n = os.path.relpath(path, d).replace(os.sep, "-")
                if n in seen: continue
                seen[n] = 1; kv = {}
                try:
                    sec = False
                    with open(path, errors="replace") as source:
                        lines = source.readlines()
                    for line in lines:
                        line = line.strip()
                        if line.startswith("["): sec = line == "[Desktop Entry]"; continue
                        if sec and "=" in line:
                            k, v = line.split("=", 1)
                            if k not in kv: kv[k] = v
                except OSError:
                    continue
                if kv.get("NoDisplay") == "true" or kv.get("Hidden") == "true" or kv.get("Type", "Application") != "Application": continue
                res.append((n, kv.get("Name", n[:-8]), kv.get("Icon", ""), [m for m in kv.get("MimeType", "").split(";") if m], kv.get("Exec", "")))
    return res


# Display scale choices shared by Settings > Displays and Settings > Appearance > Fonts (policy: configurator/bin/carpatic-scale)
SCALE_CHOICES = [("auto", "Auto"), ("100", "100%"), ("125", "125%"), ("150", "150%"), ("175", "175%"), ("200", "200%"), ("250", "250%"), ("300", "300%")]
SCALE_NOTE = "Windows, the panel, bars and Carpathian OS apps change straight away. Apps that were already open (a browser, for example) take the new size when you close and open them again."


def scale_value():
    """The SCALE setting as a choice id: 'auto' or '100'..'300'."""
    v = (settings().get("SCALE") or "auto").strip()
    return v if v == "auto" or v.isdigit() else "auto"


def scale_status():
    """'Auto: 150% (3840x2160, 600 x 340 mm)' from carpatic-scale, or ''."""
    return out("carpatic-scale", "status").strip() if which("carpatic-scale") else ""


def reopen_after_scale(page):
    """The display scale changed: this window was laid out at the old size, so Settings opens itself again on `page` (about a second later)."""
    import sys
    from gi.repository import GLib

    def go():
        try: os.execv(sys.executable, [sys.executable, sys.argv[0], page])
        except OSError: pass
        return False
    GLib.timeout_add(1200, go)
