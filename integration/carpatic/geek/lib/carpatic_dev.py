"""Development environments in one command: install, check, remove. Python 3.11+ standard library.

Packages come from Alpine (musl-native, no compatibility box), apps from the store catalog, databases from containers.
Every environment is verified by running a small real program after installing it. See share/devenvs.toml.
"""
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib


class Problem(Exception):
    pass


class Usage(Problem):
    """The user asked for something that does not exist (exit status 2)."""


def home():
    return os.environ.get("HOME", "/root")


def cfg_dir():
    return os.environ.get("CARPATIC_CONFIG", os.path.join(home(), ".config", "carpatic"))


def here():
    return os.path.dirname(os.path.realpath(__file__))


def share(name):
    for d in (os.environ.get("CARPATIC_GEEK_SHARE"), os.path.join(here(), "..", "share"), "/usr/local/share/carpatic/geek"):
        if d and os.path.exists(os.path.join(d, name)):
            return os.path.join(d, name)
    raise Problem(f"my list {name} is missing. Reinstalling the geek tools fixes it.")


def envs():
    out = []
    for p in [share("devenvs.toml"), os.path.join(cfg_dir(), "devenvs.toml")]:
        if os.path.exists(p):
            with open(p, "rb") as f:
                for e in tomllib.load(f).get("env", []):
                    out = [x for x in out if x["id"] != e["id"]] + [e]
    return out


ALIASES = {"nodejs": "node", "golang": "go", "python3": "python", "py": "python", "c++": "c", "cpp": "c", "gcc": "c", "postgresql": "postgres",
           "pg": "postgres", "mariadb": "mysql", "valkey": "redis", "nvim": "neovim", "vim": "neovim", "hx": "helix", "code": "vscode",
           "codium": "vscodium", "jdk": "java", "openjdk": "java", "cargo": "rust"}


def get(name):
    n = ALIASES.get(name.lower(), name.lower())
    for e in envs():
        if e["id"] == n:
            return e
    names = ", ".join(e["id"] for e in envs())
    raise Usage(f"I do not know a dev environment called '{name}'. Choose one of: {names}.")


def have(cmd):
    return shutil.which(cmd) is not None


def runtime():
    """Container runtime for the databases: podman (rootless) first, docker second."""
    for r in ("podman", "docker"):
        if have(r):
            return r
    return None


def container_name(e):
    return f"carpatic-{e['id']}"


def container_state(e):
    rt = runtime()
    if not rt:
        return None
    r = subprocess.run([rt, "ps", "-a", "--filter", f"name=^{container_name(e)}$", "--format", "{{.Status}}"], capture_output=True, text=True)
    s = r.stdout.strip()
    if r.returncode != 0 or not s:
        return None
    return "running" if s.lower().startswith("up") else "stopped"


def installed(e):
    k = e["kind"]
    if k == "container":
        return container_state(e) is not None
    if k == "store":
        if e.get("binary") and have(e["binary"]):
            return True
        return store_installed(e["app"])
    if e.get("binary"):
        return have(e["binary"])
    return False


_STORE_CACHE = {}


def store_installed(app):
    if not have("carpatic-store"):
        return False
    if "out" not in _STORE_CACHE:
        _STORE_CACHE["out"] = subprocess.run(["carpatic-store", "-y", "list", "--installed"], capture_output=True, text=True).stdout
    return bool(re.search(rf"^\[x\]\s+{re.escape(app)}\s", _STORE_CACHE["out"], re.M))


def version(e):
    if not e.get("version") or not installed(e) or e["kind"] in ("container", "store"):
        return ""
    r = subprocess.run(["sh", "-c", e["version"]], capture_output=True, text=True, timeout=20)
    return (r.stdout.strip() or r.stderr.strip()).splitlines()[0] if (r.stdout.strip() or r.stderr.strip()) else ""


def nopass(tool):
    """True when `tool` (doas or sudo) works without asking for a password (a disposable test VM, or a rule you wrote yourself)."""
    return have(tool) and subprocess.run([tool, "-n", "true"], capture_output=True).returncode == 0


def as_root(cmd, out=print):
    """Run a shell command with administrator rights: as root directly; in a terminal with doas or sudo (asks for your password);
    from the launcher or menu with no terminal, a graphical password prompt (pkexec). Returns the exit status."""
    if os.geteuid() == 0:
        r = subprocess.run(["sh", "-c", cmd])
    elif nopass("doas"):
        r = subprocess.run(["doas", "sh", "-c", cmd])
    elif nopass("sudo"):
        r = subprocess.run(["sudo", "sh", "-c", cmd])
    elif sys.stdin.isatty() and have("doas"):
        r = subprocess.run(["doas", "sh", "-c", cmd])
    elif sys.stdin.isatty() and have("sudo"):
        r = subprocess.run(["sudo", "sh", "-c", cmd])
    elif os.environ.get("DISPLAY") and have("pkexec"):
        r = subprocess.run(["pkexec", "sh", "-c", cmd])
    else:
        raise Problem("this step needs administrator rights and I cannot ask for your password here. Open a terminal and run the same command again.")
    return r.returncode


def need_store():
    if not have("carpatic-store"):
        raise Problem("the app store tool (carpatic-store) is missing, so I cannot install packages. Reinstall it: doas sh store/system/setup-flatpak.sh")


def apk_install(packages, out=print):
    if not packages:
        return
    need_store()
    cmd = ["carpatic-store", "-y", "install"] + [f"apk:{p}" for p in packages]
    r = subprocess.run(cmd)
    if r.returncode != 0:
        raise Problem("the packages could not be installed. Check your internet connection and run the same command again.")


def verify(e, out=print):
    v = e.get("verify")
    if not v:
        return True
    env = dict(os.environ)
    env["PATH"] = "/usr/local/bin:" + env.get("PATH", "")
    try:
        r = subprocess.run(["sh", "-c", v], capture_output=True, text=True, timeout=300, env=env)
    except subprocess.TimeoutExpired:
        return False
    if r.returncode != 0:
        tail = (r.stderr or r.stdout).strip().splitlines()[-3:]
        for l in tail:
            out(f"    {l}")
    return r.returncode == 0


def run_hook(name, *args):
    if have("carpatic-hook"):
        subprocess.run(["carpatic-hook", "run", name, *args], capture_output=True)


# --------------------------------------------------------------------------------------------------------------- installers
def install(name, out=print, check=True):
    e = get(name)
    out(f"{e['title']}: {e['desc']}")
    k = e["kind"]
    if k == "apk":
        apk_install(e["packages"], out)
        for link in e.get("link", []):
            src, dst = link.split(":")
            if have(src) and not have(dst):
                as_root(f"ln -sf $(command -v {src}) /usr/local/bin/{dst}")
    elif k == "store":
        need_store()
        r = subprocess.run(["carpatic-store", "-y", "install", e["app"]])
        if r.returncode != 0:
            raise Problem(f"the store could not install {e['title']}. Run: carpatic store info {e['app']}")
    elif k == "container":
        install_container(e, out)
    elif e["id"] == "docker":
        install_docker(e, out)
    elif e["id"] == "podman":
        install_podman(e, out)
    elif e["id"] == "neovim":
        install_neovim(e, out)
    else:
        raise Problem(f"no installer for {e['id']}")
    if check and e.get("verify"):
        out("  Checking that it works...")
        if verify(e, out):
            v = version(e)
            out(f"  Works. {v}".rstrip())
        else:
            raise Problem(f"{e['title']} was installed but my check did not pass. Run: carpatic dev status")
    elif k == "store":
        out("  Installed. Find it in the launcher.")
    run_hook("dev-install", e["id"])
    return e


def install_docker(e, out):
    apk_install(e["packages"], out)
    user = os.environ.get("SUDO_USER") or os.environ.get("DOAS_USER") or getpass.getuser()
    # the init script wants a docker group (the package normally makes it)
    cmds = ["getent group docker >/dev/null || addgroup -S docker", "rc-update add docker default", "rc-service docker start"]
    if user != "root":
        cmds.append(f"addgroup {user} docker")
    if as_root("; ".join(cmds)) != 0:
        raise Problem("Docker is installed, but I could not start it. Try: doas rc-service docker start")
    if user != "root":
        out(f"  {user} was added to the docker group. Log out and in once so your terminals can use it without doas.")


def install_podman(e, out):
    if have("carpatic-compat"):
        r = as_root(f"carpatic-compat --system-setup {getpass.getuser()}") if os.geteuid() != 0 else 0
    apk_install(e["packages"], out)
    user = getpass.getuser()
    uid = os.getuid()
    base = 100000 + (uid % 1000) * 65536
    sub = []
    for f in ("/etc/subuid", "/etc/subgid"):
        try:
            if not re.search(rf"^{re.escape(user)}:", open(f).read(), re.M):
                sub.append(f"echo {user}:{base}:65536 >> {f}")
        except OSError:
            sub.append(f"echo {user}:{base}:65536 >> {f}")
    changed = bool(user != "root" and sub)
    if user != "root" and sub:
        if as_root("; ".join(sub)) != 0:
            raise Problem("Podman is installed, but I could not give your account its container ID range (/etc/subuid). Run: doas sh -c 'echo " + f"{user}:{base}:65536 >> /etc/subuid; echo {user}:{base}:65536 >> /etc/subgid'")
    as_root("modprobe tun 2>/dev/null; modprobe fuse 2>/dev/null; mount --make-rshared / 2>/dev/null; rc-update add cgroups default >/dev/null 2>&1; rc-service cgroups start >/dev/null 2>&1; true")
    # Podman keeps a helper process with the ID mapping it saw first. If that was "no ranges" (single mapping), images with files
    # owned by other users fail to unpack. `migrate` restarts it (and stops running containers), so only do it when needed.
    if changed or not podman_mapping_ok():
        subprocess.run(["podman", "system", "migrate"], capture_output=True)
        if user != "root" and not podman_mapping_ok():
            raise Problem("Podman is installed, but it still cannot use your container ID range. Log out and in once, then run the same command again.")


def podman_mapping_ok():
    """True when rootless Podman maps a full range of IDs (not just your own user)."""
    if os.geteuid() == 0:
        return True
    r = subprocess.run(["podman", "unshare", "cat", "/proc/self/uid_map"], capture_output=True, text=True)
    return any(len(l.split()) == 3 and int(l.split()[2]) >= 65536 for l in r.stdout.splitlines())


def install_container(e, out):
    rt = runtime()
    if not rt:
        out("  This needs a container engine. Installing Podman first...")
        install("podman", out)
        rt = runtime()
    name = container_name(e)
    st = container_state(e)
    if st == "running":
        out(f"  Already running. Connect with: {e['url']}")
        return
    if st == "stopped":
        subprocess.run([rt, "start", name], check=False)
    else:
        data = os.path.join(home(), ".local", "share", "carpatic", "db", e["id"])
        os.makedirs(data, exist_ok=True)
        cmd = [rt, "run", "-d", "--name", name, "-p", f"127.0.0.1:{e['port']}:{e['port']}", "-v", f"{data}:{e['data']}:Z"]
        for kv in e.get("env", []):
            cmd += ["-e", kv]
        cmd.append(e["image"])
        out(f"  Starting {e['image']} (downloads it the first time)...")
        r = subprocess.run(cmd)
        if r.returncode != 0:
            raise Problem(f"the container could not start. If port {e['port']} is taken, stop what uses it. Run: carpatic dev status")
    out(f"  Connect with: {e['url']}")
    out(f"  Stop it with: carpatic dev db {e['id']} stop   Data lives in ~/.local/share/carpatic/db/{e['id']}")


def container_cmd(name, action, out=print):
    e = get(name)
    if e["kind"] != "container":
        raise Problem(f"{e['title']} is not a database container. Databases: {', '.join(x['id'] for x in envs() if x['kind'] == 'container')}")
    rt = runtime()
    if not rt:
        raise Problem("no container engine is installed. Run: carpatic install dev podman")
    n = container_name(e)
    if action == "start":
        return subprocess.run([rt, "start", n]).returncode
    if action == "stop":
        return subprocess.run([rt, "stop", n]).returncode
    if action == "logs":
        return subprocess.run([rt, "logs", "--tail", "50", n]).returncode
    if action == "url":
        out(e["url"])
        return 0
    if action == "status":
        out(container_state(e) or "not created")
        return 0
    raise Problem("db actions: start, stop, logs, url, status")


def remove(name, out=print, purge=False):
    e = get(name)
    k = e["kind"]
    if k == "container":
        rt = runtime()
        if rt:
            subprocess.run([rt, "rm", "-f", container_name(e)], capture_output=True)
        d = os.path.join(home(), ".local", "share", "carpatic", "db", e["id"])
        if purge and os.path.isdir(d):
            # files made inside the container belong to subordinate IDs: delete them from inside the user namespace
            if rt == "podman":
                subprocess.run(["podman", "unshare", "rm", "-rf", d], capture_output=True)
            shutil.rmtree(d, ignore_errors=True)
            out(f"Removed {e['title']} and its data.")
        else:
            out(f"Removed the {e['title']} container. Your data is kept in {d} (remove it with --purge).")
        return
    if k == "store":
        need_store()
        r = subprocess.run(["carpatic-store", "-y", "remove", e["app"]])
        if r.returncode != 0:
            raise Problem(f"could not remove {e['title']}")
        return
    if e["id"] == "docker":
        as_root("rc-service docker stop 2>/dev/null; rc-update del docker default 2>/dev/null; true")
    pk = e.get("packages", [])
    # keep tools another environment still needs
    keep = set()
    for o in envs():
        if o["id"] != e["id"] and installed(o):
            keep |= set(o.get("packages", []))
    drop = [p for p in pk if p not in keep]
    if drop:
        as_root("apk del " + " ".join(drop))
    for link in e.get("link", []):
        dst = link.split(":")[1]
        as_root(f"rm -f /usr/local/bin/{dst}")
    out(f"Removed {e['title']}.")


# ------------------------------------------------------------------------------------------------------------------ neovim
MARK = "carpatic-starter"


def nvim_target():
    d = os.path.join(home(), ".config", "nvim")
    init = os.path.join(d, "init.lua")
    if not os.path.exists(d) or (os.path.exists(init) and MARK in open(init).read()) or not os.listdir(d):
        return d, False
    return os.path.join(home(), ".config", "carpatic-nvim"), True


def install_neovim(e, out):
    apk_install(e["packages"], out)
    d, separate = nvim_target()
    os.makedirs(d, exist_ok=True)
    dst = os.path.join(d, "init.lua")
    if not os.path.exists(dst):
        shutil.copyfile(share("nvim/init.lua"), dst)
        out(f"  Starter setup written to {dst}")
    else:
        out("  Your starter setup is already in place and was left alone.")
    nvim_theme(out=out, target=d)
    install_theme_hook(d)
    if separate:
        out("  You already have a Neovim setup in ~/.config/nvim, so I left it alone.")
        out("  Try mine with: NVIM_APPNAME=carpatic-nvim nvim")
    else:
        out("  Start it with: nvim   (press Space then ? for the key list)")


def read_palette():
    st = {}
    try:
        for line in open(os.path.join(cfg_dir(), "settings.conf")):
            m = re.match(r'^(\w+)="(.*)"$', line.strip())
            if m:
                st[m.group(1)] = m.group(2)
    except OSError:
        pass
    theme = st.get("THEME", "carpatic")
    share_dir = os.environ.get("CARPATIC_SHARE", "/usr/local/share/carpatic/configurator")
    for d in (os.path.join(cfg_dir(), "themes", theme), os.path.join(share_dir, "themes", theme)):
        p = os.path.join(d, "colors.toml")
        if os.path.exists(p):
            pal = {}
            for line in open(p):
                m = re.match(r'^\s*(\w+)\s*=\s*"([^"]*)"', line)
                if m:
                    pal[m.group(1)] = m.group(2)
            if st.get("ACCENT"):
                pal["accent"] = st["ACCENT"]
            return theme, pal
    raise Problem("I could not read your current theme colours.")


def nvim_theme(out=print, target=None):
    theme, c = read_palette()
    g = lambda k, d: c.get(k, d)
    bg, fg = g("background", "#11151c"), g("foreground", "#e7ecf3")
    dark = g("dark_background", bg)
    light = g("lighter_background", bg)
    muted = g("muted", "#6b778c")
    dimfg = g("dark_foreground", muted)
    acc = g("accent", "#5cc8a8")
    sel = g("selection", light)
    lua = f'''-- Generated by carpatic dev nvim-theme from the Carpatic theme "{theme}". It follows your theme: do not edit.
vim.cmd("highlight clear"); if vim.fn.exists("syntax_on") == 1 then vim.cmd("syntax reset") end
vim.g.colors_name = "carpatic"
vim.o.background = "{g('mode', 'dark')}"
local c = {{ bg = "{bg}", fg = "{fg}", dark = "{dark}", light = "{light}", muted = "{muted}", dim = "{dimfg}", accent = "{acc}", sel = "{sel}",
  red = "{g('red', '#f0707a')}", green = "{g('green', '#7bd389')}", yellow = "{g('yellow', '#f2c25a')}", blue = "{g('blue', '#6cb4f0')}",
  magenta = "{g('magenta', '#a99bf0')}", cyan = "{g('cyan', '#5cc8a8')}", orange = "{g('orange', '#f2a65a')}" }}
local function hl(n, v) vim.api.nvim_set_hl(0, n, v) end
hl("Normal", {{ fg = c.fg, bg = c.bg }}); hl("NormalFloat", {{ fg = c.fg, bg = c.dark }}); hl("FloatBorder", {{ fg = c.muted, bg = c.dark }})
hl("Cursor", {{ fg = c.bg, bg = c.accent }}); hl("CursorLine", {{ bg = c.light }}); hl("CursorLineNr", {{ fg = c.accent, bold = true }})
hl("LineNr", {{ fg = c.muted }}); hl("SignColumn", {{ bg = c.bg }}); hl("ColorColumn", {{ bg = c.light }}); hl("NonText", {{ fg = c.muted }})
hl("Visual", {{ bg = c.sel }}); hl("Search", {{ fg = c.bg, bg = c.yellow }}); hl("IncSearch", {{ fg = c.bg, bg = c.accent }})
hl("MatchParen", {{ fg = c.accent, bold = true, underline = true }}); hl("Pmenu", {{ fg = c.fg, bg = c.dark }}); hl("PmenuSel", {{ fg = c.bg, bg = c.accent }})
hl("StatusLine", {{ fg = c.fg, bg = c.light }}); hl("StatusLineNC", {{ fg = c.muted, bg = c.dark }}); hl("VertSplit", {{ fg = c.light }}); hl("WinSeparator", {{ fg = c.light }})
hl("Comment", {{ fg = c.dim, italic = true }}); hl("String", {{ fg = c.green }}); hl("Character", {{ fg = c.green }}); hl("Number", {{ fg = c.orange }})
hl("Boolean", {{ fg = c.orange }}); hl("Constant", {{ fg = c.orange }}); hl("Identifier", {{ fg = c.fg }}); hl("Function", {{ fg = c.blue }})
hl("Statement", {{ fg = c.magenta }}); hl("Keyword", {{ fg = c.magenta }}); hl("Conditional", {{ fg = c.magenta }}); hl("Operator", {{ fg = c.cyan }})
hl("PreProc", {{ fg = c.cyan }}); hl("Type", {{ fg = c.yellow }}); hl("Special", {{ fg = c.cyan }}); hl("Title", {{ fg = c.accent, bold = true }})
hl("Error", {{ fg = c.red }}); hl("Todo", {{ fg = c.bg, bg = c.yellow, bold = true }}); hl("Directory", {{ fg = c.blue }})
hl("DiagnosticError", {{ fg = c.red }}); hl("DiagnosticWarn", {{ fg = c.yellow }}); hl("DiagnosticInfo", {{ fg = c.blue }}); hl("DiagnosticHint", {{ fg = c.cyan }})
hl("DiagnosticUnderlineError", {{ undercurl = true, sp = c.red }}); hl("DiagnosticUnderlineWarn", {{ undercurl = true, sp = c.yellow }})
hl("DiffAdd", {{ bg = c.light, fg = c.green }}); hl("DiffChange", {{ bg = c.light, fg = c.yellow }}); hl("DiffDelete", {{ bg = c.light, fg = c.red }}); hl("DiffText", {{ bg = c.sel }})
hl("@variable", {{ fg = c.fg }}); hl("@function", {{ fg = c.blue }}); hl("@keyword", {{ fg = c.magenta }}); hl("@string", {{ fg = c.green }}); hl("@type", {{ fg = c.yellow }})
hl("@property", {{ fg = c.cyan }}); hl("@constant", {{ fg = c.orange }}); hl("@comment", {{ fg = c.dim, italic = true }}); hl("@punctuation", {{ fg = c.muted }})
'''
    dirs = [target] if target else [d for d in (os.path.join(home(), ".config", "nvim"), os.path.join(home(), ".config", "carpatic-nvim")) if os.path.isdir(d)]
    for d in dirs:
        os.makedirs(os.path.join(d, "colors"), exist_ok=True)
        with open(os.path.join(d, "colors", "carpatic.lua"), "w") as f:
            f.write(lua)
    out(f"  Neovim colours follow your theme ({theme}).")
    return dirs


def install_theme_hook(d):
    hd = os.path.join(cfg_dir(), "hooks", "theme-set.d")
    os.makedirs(hd, exist_ok=True)
    p = os.path.join(hd, "50-carpatic-neovim")
    with open(p, "w") as f:
        f.write("#!/bin/sh\n# Keeps the Neovim colour scheme in step with the Carpatic theme (made by carpatic install dev neovim).\n"
                "command -v carpatic-dev >/dev/null 2>&1 && carpatic-dev nvim-theme >/dev/null 2>&1\nexit 0\n")
    os.chmod(p, 0o755)


def listing(plain=False):
    rows = []
    for e in envs():
        rows.append((e["id"], "installed" if installed(e) else "available", e["desc"], e.get("group", ""), e.get("size_mb", 0), e["title"]))
    return rows
