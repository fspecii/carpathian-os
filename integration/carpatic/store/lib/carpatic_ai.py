"""Carpatic AI: one-click installers for AI tools on Alpine/musl. Stdlib only.

Tiers (hidden from the user): native (apk, static musl binary, upstream installer), rootless podman container, glibc
compat container (distrobox). Installs go to ~/.local (no root) unless an apk package is involved. No API keys are stored.
"""
import json
import os
import re
import shutil
import subprocess
import hashlib
import sys
import tarfile
import tempfile
import time
import tomllib
import urllib.error
import urllib.request

import carpatic_store as cs
import carpatic_drivers as drv

HOME = os.path.expanduser("~")
BIN = os.path.join(HOME, ".local", "bin")
STATE = os.path.join(HOME, ".local", "share", "carpatic", "ai")
SHARE_DIRS = ["/usr/local/share/carpatic/store/ai", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ai")]


def ai_dir():
    for d in (os.environ.get("CARPATIC_AI_DIR", ""), *SHARE_DIRS):
        if d and os.path.exists(os.path.join(d, "tools.toml")):
            return os.path.abspath(d)
    raise cs.StoreError("AI tool recipes not found. Reinstall carpatic-store.")


def load(name):
    with open(os.path.join(ai_dir(), name), "rb") as f:
        return tomllib.load(f)


def tools():
    return {t["id"]: t for t in load("tools.toml")["tool"]}


def models():
    return load("models.toml")["model"]


def get_tool(tid):
    t = tools()
    if tid in t:
        return t[tid]
    alias = {"claude": "claude-code", "gemini": "gemini-cli", "llama": "llama-cpp", "llama.cpp": "llama-cpp", "webui": "open-webui", "compat": "compat-container"}
    if tid in alias:
        return t[alias[tid]]
    raise cs.StoreError(f"Unknown AI tool '{tid}'. Available: {', '.join(t)}")


# ------------------------------------------------------------------ state
def _state_file(tid):
    return os.path.join(STATE, tid + ".json")


def read_state(tid):
    try:
        with open(_state_file(tid)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_state(tid, **kw):
    os.makedirs(STATE, exist_ok=True)
    with open(_state_file(tid), "w") as f:
        json.dump(dict(kw, time=int(time.time())), f)


LAST_SHA = {}   # tool id -> sha256 of the archive/installer script that was just downloaded


def is_pinned(tid):
    return bool((read_state(tid) or {}).get("pinned"))


def set_pinned(tid, pinned):
    """Pin = keep this exact version: `update` will skip it until it is unpinned. Nothing ever updates by itself."""
    st = read_state(tid)
    if st is None:
        raise cs.StoreError(f"{tid} is not installed.")
    st["pinned"] = bool(pinned)
    write_state(tid, **{k: v for k, v in st.items() if k != "time"})


def details(tid):
    """What was installed: version, sha256 of the download (when we saw it), pinned flag."""
    st = read_state(tid) or {}
    return {"version": st.get("version", ""), "tag": st.get("tag", ""), "sha256": st.get("sha256", ""), "pinned": bool(st.get("pinned"))}


def clear_state(tid):
    try:
        os.remove(_state_file(tid))
    except OSError:
        pass


def path_env():
    e = dict(os.environ)
    e["PATH"] = BIN + ":" + e.get("PATH", "")
    return e


def which(b):
    return shutil.which(b, path=path_env()["PATH"])


def is_installed(t):
    k = t["kind"]
    if k in ("apk", "apk-service"):
        return all(cs_apk_has(p) for p in t["apk"][:1])
    if k == "container":
        st = read_state(t["id"])
        return bool(st) and shutil.which("podman") is not None
    if k == "compat":
        if read_state(t["id"]):
            return True
        return shutil.which("carpatic-compat") is not None and subprocess.run(["carpatic-compat", "status"], capture_output=True).returncode == 0
    return bool(read_state(t["id"])) and bool(which(t["bin"]))


_apk_cache = {}


def cs_apk_has(pkg):
    if pkg not in _apk_cache:
        _apk_cache[pkg] = subprocess.run(["apk", "info", "-e", pkg], capture_output=True).returncode == 0
    return _apk_cache[pkg]


def version_of(t):
    cmd = t.get("version_cmd")
    if not cmd:
        return ""
    try:
        r = subprocess.run(cmd.split(), capture_output=True, text=True, timeout=30, env=path_env())
        out = r.stdout + r.stderr
        m = re.search(r"version:\s*(\d+)", out) or re.search(r"\d+\.\d+(\.\d+)?", out)
        return (m.group(1) if m.re.groups and "version" in m.re.pattern else m.group(0)) if m else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


# ------------------------------------------------------------------ helpers
def say(on_line, msg):
    if on_line:
        on_line(msg)


def apk_add(pkgs, on_line, password):
    need = [p for p in pkgs if not subprocess.run(["apk", "info", "-e", p], capture_output=True).returncode == 0]
    if not need:
        return
    say(on_line, "Installing system packages: " + " ".join(need))
    code = cs.run(cs.priv_prefix() + ["apk", "add"] + need, on_line, password=password)
    for p in need:
        _apk_cache.pop(p, None)
    if code != 0:
        raise cs.StoreError("Could not install the needed system packages (" + " ".join(need) + "). Are you online? Try 'carpatic-store update'.")


def priv(cmd, on_line, password):
    return cs.run(cs.priv_prefix() + cmd, on_line, password=password)


def download(url, dest, on_line, label=""):
    """Download with percentage lines ("  42%") for the progress UIs."""
    if not url.startswith("https://"):
        raise cs.StoreError(f"Refusing to download {label or url} over an unencrypted connection.")
    req = urllib.request.Request(url, headers={"User-Agent": "carpatic-store"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got, last = 0, -1
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b)
                got += len(b)
                if total:
                    pct = got * 100 // total
                    if pct != last and pct % 2 == 0:
                        last = pct
                        say(on_line, f"Downloading {label} {pct}%")
    except urllib.error.HTTPError as e:
        raise cs.StoreError(f"Download failed ({e.code}) for {label or url}. The release may have been renamed; try again later.")
    except (urllib.error.URLError, OSError) as e:
        raise cs.StoreError(f"Could not download {label or url}: no internet connection? ({getattr(e, 'reason', e)})")


def latest_tag(repo):
    """Tag of the latest GitHub release via the redirect (no API rate limit)."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    op = urllib.request.build_opener(NoRedirect)
    try:
        op.open(urllib.request.Request(f"https://github.com/{repo}/releases/latest", method="HEAD", headers={"User-Agent": "carpatic-store"}), timeout=30)
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location", "")
        m = re.search(r"/tag/(.+)$", loc)
        if m:
            return m.group(1)
    except OSError:
        pass
    return ""


def ensure_path_hint():
    """~/.local/bin must be on PATH for new shells; /etc/profile.d/carpatic-localbin.sh (installed by setup) does it."""
    if BIN not in os.environ.get("PATH", "").split(":") and not os.path.exists("/etc/profile.d/carpatic-localbin.sh"):
        prof = os.path.join(HOME, ".profile")
        line = 'export PATH="$HOME/.local/bin:$PATH"  # carpatic'
        try:
            txt = open(prof).read() if os.path.exists(prof) else ""
            if "# carpatic" not in txt and ".local/bin" not in txt:
                with open(prof, "a") as f:
                    f.write("\n" + line + "\n")
        except OSError:
            pass


# ------------------------------------------------------------------ installers
def _github(t, on_line):
    tag = latest_tag(t["repo"])
    url = f"https://github.com/{t['repo']}/releases/latest/download/{t['asset']}"
    os.makedirs(BIN, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        arc = os.path.join(td, "a.tgz")
        download(url, arc, on_line, t["name"])
        with open(arc, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        LAST_SHA[t["id"]] = digest
        say(on_line, f"{t['name']} {tag or 'latest'} downloaded from github.com/{t['repo']} over https, sha256 {digest}")   # vendor 'latest' build: recorded, not pinned
        say(on_line, f"Unpacking {t['name']}...")
        with tarfile.open(arc) as tf:
            mem = next((m for m in tf.getmembers() if m.isfile() and os.path.basename(m.name) == t["member"]), None)
            if mem is None:
                raise cs.StoreError(f"The {t['name']} download did not contain '{t['member']}'. Upstream changed its release layout.")
            src = tf.extractfile(mem)
            tmp = os.path.join(BIN, "." + t["bin"] + ".new")
            with open(tmp, "wb") as o:
                shutil.copyfileobj(src, o, 1 << 20)
        os.chmod(tmp, 0o755)
        os.replace(tmp, os.path.join(BIN, t["bin"]))
    return tag


def _native_script(t, on_line, password):
    apk_add(t.get("apk", []), on_line, password)
    with tempfile.TemporaryDirectory() as td:
        sp = os.path.join(td, "install.sh")
        download(t["url"], sp, on_line, t["name"] + " installer")
        with open(sp, "rb") as fh:
            LAST_SHA[t["id"]] = hashlib.sha256(fh.read()).hexdigest()
        say(on_line, f"{t['name']} installer script sha256 {LAST_SHA[t['id']]}")
        env = path_env()
        env.update(t.get("env", {}))
        say(on_line, f"Running the official {t['name']} installer...")
        code = cs.run(["bash", sp], on_line, env=env)
        if code != 0:
            raise cs.StoreError(f"The official {t['name']} installer failed (exit {code}).")


def _npm(t, on_line, password):
    apk_add(t.get("apk", []), on_line, password)
    os.makedirs(BIN, exist_ok=True)
    env = path_env()
    env["NPM_CONFIG_PREFIX"] = os.path.join(HOME, ".local")
    say(on_line, f"Installing {t['package']} with npm (this takes a minute)...")
    code = cs.run(["npm", "install", "-g", t["package"]], on_line, env=env)
    if code != 0:
        raise cs.StoreError(f"npm could not install {t['package']}. Check your internet connection.")


def _uv(t, on_line, password):
    apk_add(t.get("apk", []), on_line, password)
    say(on_line, f"Installing {t['package']} with uv (downloads its own Python {t['python']})...")
    code = cs.run(["uv", "tool", "install", "--python", t["python"], "--upgrade", t["package"]], on_line, env=path_env())
    if code != 0:
        raise cs.StoreError(f"uv could not install {t['package']}. Check your internet connection.")


def _service_files(t):
    d = os.path.join(ai_dir(), "services")
    return os.path.join(d, t["service"] + ".initd"), os.path.join(d, t["service"] + ".confd")


def _apk_service(t, on_line, password):
    apk_add(t["apk"], on_line, password)
    svc = t["service"]
    initd, confd = _service_files(t)
    say(on_line, f"Setting up the {svc} service...")
    if priv(["sh", "-c", f"id {svc} >/dev/null 2>&1 || adduser -S -D -h /var/lib/{svc} -s /sbin/nologin {svc}; "
                         f"addgroup -S {svc} 2>/dev/null; adduser {svc} {svc} 2>/dev/null; true"], on_line, password) != 0:
        raise cs.StoreError(f"Could not create the {svc} system user.")
    priv(["install", "-Dm755", initd, f"/etc/init.d/{svc}"], on_line, password)
    priv(["sh", "-c", f"[ -f /etc/conf.d/{svc} ] || install -Dm644 {confd} /etc/conf.d/{svc}"], on_line, password)
    priv(["rc-update", "add", svc, "default"], on_line, password)
    if priv(["rc-service", svc, "restart"], on_line, password) != 0:
        raise cs.StoreError(f"The {svc} service did not start. See: logread | grep {svc}")


def _setup_podman(t, on_line, password):
    apk_add(t["apk"], on_line, password)
    user = os.environ.get("USER") or subprocess.run(["id", "-un"], capture_output=True, text=True).stdout.strip()
    # rootless containers need a subuid/subgid range for the user and cgroups
    priv(["sh", "-c", f"grep -q '^{user}:' /etc/subuid 2>/dev/null || echo '{user}:100000:65536' >> /etc/subuid; "
                      f"grep -q '^{user}:' /etc/subgid 2>/dev/null || echo '{user}:100000:65536' >> /etc/subgid; "
                      f"rc-update add cgroups boot >/dev/null 2>&1; rc-service cgroups start >/dev/null 2>&1; modprobe tun 2>/dev/null; true"], on_line, password)
    if not os.environ.get("XDG_RUNTIME_DIR"):
        os.environ["XDG_RUNTIME_DIR"] = f"/tmp/runtime-{os.getuid()}"
        os.makedirs(os.environ["XDG_RUNTIME_DIR"], mode=0o700, exist_ok=True)
    subprocess.run(["podman", "system", "migrate"], capture_output=True)   # picks up new subuid/subgid ranges


def _container(t, on_line, password):
    _setup_podman(t, on_line, password)
    say(on_line, f"Downloading the {t['name']} image ({t['size_mb']} MB)...")
    code = cs.run(["podman", "pull", t["image"]], on_line, tty=True)
    if code != 0:
        raise cs.StoreError("Could not pull the container image (offline, or rootless podman is not working: run 'carpatic-ai doctor').")
    name = t["container"]
    subprocess.run(["podman", "rm", "-f", name], capture_output=True)
    code = subprocess.run(["podman", "create", "--name", name, "--network=host", "-e", f"PORT={t['port']}",
                           "-e", "OLLAMA_BASE_URL=http://127.0.0.1:11434", "-v", f"{name}:/app/backend/data", t["image"]],
                          capture_output=True, text=True)
    if code.returncode != 0:
        raise cs.StoreError("Could not create the container: " + code.stderr.strip()[-200:])


def _compat(t, on_line, password):
    """The glibc box is owned by carpatic-compat (compat/). Migration note: boxes created by earlier store versions used the same
    name (carpatic-compat) and Ubuntu 24.04 image, so they are picked up as they are; the store no longer creates containers itself."""
    say(on_line, "Preparing the compatibility box (about 3 minutes the first time)...")
    if cs.compat_cmd(["setup"], on_line, password) != 0:
        raise cs.StoreError("The compatibility box could not be prepared. Run 'carpatic-compat status' for details.")


def _llama(t, on_line, password):
    pk = list(t["apk"])
    gv = {g["vendor"] for g in drv.gpus()}
    pk.append("mesa-vulkan-ati" if "0x1002" in gv else "")
    if "0x8086" in gv:
        pk.append("mesa-vulkan-intel")
    if "0x10de" in gv:
        pk.append("mesa-vulkan-nouveau")
    if not (gv & {"0x1002", "0x8086", "0x10de"}):
        pk.append("mesa-vulkan-swrast")
    apk_add([p for p in pk if p], on_line, password)


def install(t, on_line=None, password=None, force=False):
    """Install (or reinstall with force/update). Idempotent: returns 'already' when nothing was needed."""
    if isinstance(t, str):
        t = get_tool(t)
    if is_installed(t) and not force:
        say(on_line, f"{t['name']} is already installed.")
        return "already"
    k = t["kind"]
    tag = ""
    if k == "github-tarball":
        tag = _github(t, on_line)
    elif k == "native-script":
        _native_script(t, on_line, password)
    elif k == "npm":
        _npm(t, on_line, password)
    elif k == "uv":
        _uv(t, on_line, password)
    elif k == "apk-service":
        _apk_service(t, on_line, password)
    elif k == "apk":
        if t["id"] == "llama-cpp":
            _llama(t, on_line, password)
        apk_add(t["apk"], on_line, password)
    elif k == "container":
        _container(t, on_line, password)
    elif k == "compat":
        _compat(t, on_line, password)
    else:
        raise cs.StoreError(f"Unknown recipe kind {k}")
    ensure_path_hint()
    was_pinned = is_pinned(t["id"])
    write_state(t["id"], kind=k, tag=tag, version=version_of(t), sha256=LAST_SHA.get(t["id"], ""), pinned=was_pinned)
    if t.get("bin") and k not in ("apk", "apk-service") and not which(t["bin"]):
        raise cs.StoreError(f"{t['name']} installed but '{t['bin']}' is not on PATH. Log out and in again, or run: export PATH=\"$HOME/.local/bin:$PATH\"")
    say(on_line, "DONE: " + t.get("post", ""))
    return "installed"


def remove(t, on_line=None, password=None):
    if isinstance(t, str):
        t = get_tool(t)
    k = t["kind"]
    say(on_line, f"Removing {t['name']}...")
    if k == "github-tarball":
        _rm(os.path.join(BIN, t["bin"]))
    elif k == "native-script":
        _rm(os.path.join(BIN, t["bin"]))
        shutil.rmtree(os.path.join(HOME, ".local", "share", "claude"), ignore_errors=True)
    elif k == "npm":
        cs.run(["npm", "rm", "-g", t["package"]], on_line, env={**path_env(), "NPM_CONFIG_PREFIX": os.path.join(HOME, ".local")})
    elif k == "uv":
        cs.run(["uv", "tool", "uninstall", t["package"]], on_line, env=path_env())
    elif k == "apk-service":
        priv(["rc-service", t["service"], "stop"], on_line, password)
        priv(["rc-update", "del", t["service"], "default"], on_line, password)
        priv(["apk", "del"] + t["apk"], on_line, password)
        priv(["rm", "-f", f"/etc/init.d/{t['service']}"], on_line, password)
        say(on_line, f"Downloaded models were kept in /var/lib/{t['service']} (delete them by hand if you want the space back).")
    elif k == "apk":
        priv(["apk", "del"] + t["apk"], on_line, password)
    elif k == "container":
        subprocess.run(["podman", "rm", "-f", t["container"]], capture_output=True)
        subprocess.run(["podman", "rmi", t["image"]], capture_output=True)
        say(on_line, "Your chats are kept in the podman volume 'open-webui' (podman volume rm open-webui to delete).")
    elif k == "compat":
        if shutil.which("carpatic-compat"):
            cs.compat_cmd(["reset"], on_line, password)
    clear_state(t["id"])
    _apk_cache.clear()


def _rm(p):
    try:
        os.remove(p)
    except OSError:
        pass


def update(t, on_line=None, password=None):
    """Update one tool. Returns 'updated' | 'current'."""
    if isinstance(t, str):
        t = get_tool(t)
    k = t["kind"]
    if not is_installed(t):
        raise cs.StoreError(f"{t['name']} is not installed.")
    if is_pinned(t["id"]):
        say(on_line, f"{t['name']} is pinned to {details(t['id'])['version'] or 'this version'}; run 'carpatic-ai unpin {t['id']}' to allow updates.")
        return "pinned"
    if k == "github-tarball":
        st = read_state(t["id"]) or {}
        tag = latest_tag(t["repo"])
        if tag and tag == st.get("tag"):
            say(on_line, f"{t['name']} is up to date ({tag}).")
            return "current"
        install(t, on_line, password, force=True)
        return "updated"
    if k in ("native-script", "npm", "uv", "container"):
        install(t, on_line, password, force=True)
        return "updated"
    if k in ("apk", "apk-service"):
        cs.run(cs.priv_prefix() + ["apk", "add", "-u"] + t["apk"], on_line, password=password)
        if k == "apk-service":
            priv(["rc-service", t["service"], "restart"], on_line, password)
        return "updated"
    return "current"


# ------------------------------------------------------------------ ollama / models
def ollama_up():
    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/version", timeout=3).read()
        return True
    except (OSError, ValueError):
        return False


def need_ollama():
    if not shutil.which("ollama"):
        raise cs.StoreError("Ollama is not installed. Install it with: carpatic-ai install ollama")
    if not ollama_up():
        raise cs.StoreError("The Ollama service is not running. Start it with: doas rc-service ollama start (or: carpatic-ai install ollama)")


def local_models():
    need_ollama()
    d = json.load(urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=10))
    return [(m["name"], m["size"] // 1048576) for m in d.get("models", [])]


def free_mb(path="/var/lib"):
    p = path if os.path.exists(path) else "/"
    s = os.statvfs(p)
    return s.f_bavail * s.f_frsize // 1048576


def mem_mb():
    m = re.search(r"MemTotal:\s+(\d+) kB", open("/proc/meminfo").read())
    return int(m.group(1)) // 1024 if m else 0


def pull_model(name, on_line=None, assume_yes=True):
    need_ollama()
    cat = {m["id"]: m for m in models()}
    info = cat.get(name)
    if info:
        if info["size_mb"] > free_mb():
            raise cs.StoreError(f"Not enough free disk space for {name}: needs {info['size_mb']} MB, only {free_mb()} MB free in /var/lib.")
        if info["ram_gb"] * 1024 > mem_mb():
            say(on_line, f"WARNING: {name} likes about {info['ram_gb']} GB of RAM and this computer has {mem_mb() // 1024} GB. It may be very slow.")
        say(on_line, f"Downloading {info['name']} ({info['size_mb']} MB)...")
    req = urllib.request.Request("http://127.0.0.1:11434/api/pull", data=json.dumps({"name": name}).encode(), headers={"Content-Type": "application/json"})
    last = -1
    try:
        with urllib.request.urlopen(req, timeout=3600) as r:
            for raw in r:
                d = json.loads(raw)
                if "error" in d:
                    raise cs.StoreError(f"Ollama said: {d['error']}")
                if d.get("total") and d.get("completed") is not None:
                    pct = d["completed"] * 100 // d["total"]
                    if pct != last:
                        last = pct
                        say(on_line, f"Downloading {name} {pct}%")
                elif d.get("status"):
                    say(on_line, d["status"])
    except (urllib.error.URLError, OSError) as e:
        raise cs.StoreError(f"Could not download the model: {getattr(e, 'reason', e)}")


def run_model(name, prompt=None):
    need_ollama()
    cmd = ["ollama", "run", name] + ([prompt] if prompt else [])
    return subprocess.call(cmd)


def remove_model(name):
    need_ollama()
    if subprocess.run(["ollama", "rm", name], capture_output=True).returncode != 0:
        raise cs.StoreError(f"Model '{name}' is not installed. See: carpatic-ai models list")


def generate(name, prompt, n=16):
    d = json.dumps({"model": name, "prompt": prompt, "stream": False, "options": {"num_predict": n}}).encode()
    r = urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:11434/api/generate", data=d, headers={"Content-Type": "application/json"}), timeout=300)
    return json.load(r).get("response", "")


# ------------------------------------------------------------------ container controls
def container_state(name):
    r = subprocess.run(["podman", "inspect", "-f", "{{.State.Status}}", name], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else "missing"


def webui(action):
    t = get_tool("open-webui")
    if read_state(t["id"]) is None:
        raise cs.StoreError("Open WebUI is not installed. Install it with: carpatic-ai install open-webui")
    os.environ.setdefault("XDG_RUNTIME_DIR", f"/tmp/runtime-{os.getuid()}")
    n = t["container"]
    if action == "start":
        r = subprocess.run(["podman", "start", n], capture_output=True, text=True)
        if r.returncode != 0:
            raise cs.StoreError("Could not start Open WebUI: " + r.stderr.strip()[-200:])
        return f"Open WebUI is starting (first start takes about 40 seconds): http://127.0.0.1:{t['port']}"
    if action == "stop":
        subprocess.run(["podman", "stop", n], capture_output=True)
        return "Open WebUI stopped."
    return f"Open WebUI: {container_state(n)}  (http://127.0.0.1:{t['port']})"


# ------------------------------------------------------------------ status / doctor
def status():
    rows = []
    for t in tools().values():
        inst = is_installed(t)
        rows.append((t["id"], t["name"], inst, (read_state(t["id"]) or {}).get("version") or (version_of(t) if inst else "")))
    return rows


def doctor(deep=False):
    """-> list of (name, ok, detail). ok None = informational/warning."""
    r = []
    inpath = BIN in os.environ.get("PATH", "").split(":")
    r.append(("~/.local/bin on PATH", inpath, BIN if inpath else "missing: log out and in again, or add it to ~/.profile"))
    g = drv.gpus()
    r.append(("GPU detected", bool(g), ", ".join(f"{x['vendor_name']} ({x['driver'] or 'no driver'})" for x in g) or "none"))
    vd = drv.vulkan_devices()
    if vd is None:
        r.append(("Vulkan (vulkaninfo)", None, "vulkan-tools not installed: carpatic-ai install llama-cpp"))
    else:
        soft = all("llvmpipe" in d or "lavapipe" in d.lower() for d in vd) if vd else False
        r.append(("Vulkan device", bool(vd), ", ".join(vd) or "none") if not soft else ("Vulkan device", None, ", ".join(vd) + "  (software only, no GPU acceleration)"))
    for t in tools().values():
        if not is_installed(t):
            continue
        k = t["kind"]
        if t.get("version_cmd"):
            v = version_of(t)
            r.append((f"{t['name']} runs", bool(v), v or f"'{t['bin']} --version' failed"))
        if k == "apk-service":
            up = ollama_up()
            r.append((f"{t['name']} service answering on :11434", up, "ok" if up else "start it: doas rc-service ollama start"))
        if k == "container":
            r.append((f"{t['name']} container", container_state(t["container"]) != "missing", container_state(t["container"])))
        if k == "compat":
            ok = shutil.which("carpatic-compat") is not None and subprocess.run(["carpatic-compat", "status"], capture_output=True).returncode == 0
            r.append(("Compatibility box (carpatic-compat)", ok, "ready" if ok else "not set up: carpatic-ai install compat-container"))
    if shutil.which("podman"):
        ok = subprocess.run(["podman", "info"], capture_output=True, env={**os.environ, "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", f"/tmp/runtime-{os.getuid()}")}).returncode == 0
        r.append(("Rootless podman works", ok, "ok" if ok else "needs subuid/subgid: carpatic-ai install compat-container"))
    if deep:
        if shutil.which("llama-server"):
            r.append(("llama-server --version", subprocess.run(["llama-server", "--version"], capture_output=True).returncode == 0, ""))
        if ollama_up():
            try:
                names = [m[0] for m in local_models()]
                tiny = "smollm2:135m"
                if tiny not in names:
                    pull_model(tiny)
                out = generate(tiny, "Hello", 8)
                r.append(("Ollama generates text (smollm2:135m)", bool(out.strip()), out.strip()[:40]))
            except (cs.StoreError, OSError, ValueError) as e:
                r.append(("Ollama generates text", False, str(e)))
    return r
