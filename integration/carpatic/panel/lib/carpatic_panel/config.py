"""panel.conf parsing, validation and live changes. File: ~/.config/carpatic/panel.conf (KEY=VALUE per line, # comments)."""
import os, signal
from . import designs

CFG_DIR = os.environ.get("CARPATIC_CONFIG", os.path.expanduser("~/.config/carpatic"))
PATH = os.path.join(CFG_DIR, "panel.conf")


class ConfigError(ValueError):
    """Message is plain English, safe to show."""


def parse(text):
    out = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip() if not line.strip().startswith("clock_format") else line.strip()
        if not line or "=" not in line: continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"')
    return out


def validate(key, value):
    """-> normalised string value or raises ConfigError."""
    if key not in designs.OPTIONS: raise ConfigError(f"'{key}' is not a panel setting. Run 'carpatic-panel options' to see them.")
    typ, rng, _ = designs.OPTIONS[key]; v = str(value).strip()
    if typ == "enum":
        if v not in rng: raise ConfigError(f"{key} can be: {', '.join(rng)}.")
    elif typ == "int":
        try: n = int(v)
        except ValueError: raise ConfigError(f"{key} needs a whole number.")
        if n not in (0, -1) and not (rng[0] <= n <= rng[1]): raise ConfigError(f"{key} must be between {rng[0]} and {rng[1]}.")
        v = str(n)
    elif typ == "bool":
        if v.lower() not in ("1", "0", "true", "false", "yes", "no", "on", "off"): raise ConfigError(f"{key} is on or off.")
        v = "1" if v.lower() in ("1", "true", "yes", "on") else "0"
    return v


def load(path=None):
    p = path or PATH
    try: raw = parse(open(p, encoding="utf-8").read())
    except OSError: raw = {}
    cfg = {}
    for k, v in raw.items():
        try: cfg[k] = validate(k, v)
        except ConfigError: continue            # a bad line never breaks the panel
    cfg.setdefault("design", "windows11")
    return cfg


def save(cfg, path=None):
    p = path or PATH
    os.makedirs(os.path.dirname(p), exist_ok=True)
    lines = ["# Carpatic panel. Change with: carpatic-panel set <key> <value>   (see: carpatic-panel options)"]
    for k in designs.OPTIONS:
        if k in cfg: lines.append(f"{k}={cfg[k]}")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: f.write("\n".join(lines) + "\n")
    os.replace(tmp, p)


def set_key(key, value, path=None):
    v = validate(key, value); cfg = load(path); cfg[key] = v; save(cfg, path); return v


def runtime_dir():
    """Where the panel keeps its lock, pid and state: XDG_RUNTIME_DIR, except the /tmp/runtime-<uid> fallback that /etc/profile.d gives a shell without an
    elogind session (`su -`, ssh): there the login session's /run/user/<uid> is used, or a second panel would not see the first."""
    x = os.environ.get("XDG_RUNTIME_DIR", "")
    if x and not x.startswith("/tmp/runtime-"): return x
    d = "/run/user/%d" % os.getuid()
    if os.path.isdir(d) and os.access(d, os.W_OK): return d
    return x or "/tmp"


def runtime_lock_path(): return os.path.join(runtime_dir(), "carpatic-panel.lock")


_LOCK_FD = None


def acquire_singleton(wait=0.0):
    """Take the per-session panel lock (flock on carpatic-panel.lock, pid written into it at once). Returns the open file, or None when another
    live panel holds it after `wait` seconds. The lock is released by the kernel when the process dies, so there is no stale state."""
    import fcntl, time
    global _LOCK_FD
    f = open(runtime_lock_path(), "a+"); end = time.time() + wait
    while True:
        try: fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB); break
        except OSError:
            if time.time() >= end: f.close(); return None
            time.sleep(0.1)
    f.seek(0); f.truncate(); f.write(str(os.getpid())); f.flush(); _LOCK_FD = f
    return f


def running_pid():
    """Pid of the live panel: the lock file first (written before the panel finishes starting), then the pid file."""
    for path in (runtime_lock_path(), runtime_pid_path()):
        try:
            pid = int(open(path).read().split()[0]); os.kill(pid, 0); return pid
        except (OSError, ValueError, IndexError): continue
    return 0


def runtime_pid_path(): return os.path.join(runtime_dir(), "carpatic-panel.pid")


def notify_running():
    """SIGUSR1 -> the panel re-reads panel.conf. Returns True when a panel was signalled."""
    try:
        pid = int(open(runtime_pid_path()).read().split()[0]); os.kill(pid, signal.SIGUSR1); return True  # pid file only: it appears once the handler is installed
    except (OSError, ValueError): return False
