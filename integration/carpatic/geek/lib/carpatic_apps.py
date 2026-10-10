"""Web apps and terminal apps as launcher entries (shared by carpatic-webapp and carpatic-tui).

Idea from Omarchy's omarchy-webapp-install / omarchy-tui-install and the launch-or-focus helpers (MIT, see NOTICE). Rebuilt around
.desktop files plus a small registry in ~/.config/carpatic/{webapps,tui}/<slug>.toml, so listing, removing and the menu never parse
launcher files. Python 3.11+ standard library.
"""
import hashlib
import html
import os
import re
import shutil
import subprocess
import sys
import tomllib
import urllib.parse
import urllib.request

CHROMIUM = ["chromium", "chromium-browser", "google-chrome-stable", "google-chrome", "brave-browser", "brave", "vivaldi", "microsoft-edge-stable"]
BADGE = ["#f0707a", "#7bd389", "#f2c25a", "#6cb4f0", "#a99bf0", "#5cc8a8", "#f2a65a"]   # ANSI colours of the design system


class Problem(Exception):
    pass


def home():
    return os.environ.get("HOME", "/root")


def cfg_dir():
    return os.environ.get("CARPATIC_CONFIG", os.path.join(home(), ".config", "carpatic"))


def apps_dir():
    return os.environ.get("CARPATIC_APPS_DIR", os.path.join(home(), ".local", "share", "applications"))


def data_dir():
    return os.environ.get("CARPATIC_DATA", os.path.join(home(), ".local", "share", "carpatic"))


def icon_dir():
    return os.path.join(home(), ".local", "share", "icons", "hicolor", "scalable", "apps")


def share_file(name):
    here = os.path.dirname(os.path.realpath(__file__))
    for d in (os.environ.get("CARPATIC_GEEK_SHARE"), os.path.join(here, "..", "share"), "/usr/local/share/carpatic/geek"):
        if d and os.path.exists(os.path.join(d, name)):
            return os.path.join(d, name)
    raise Problem(f"my list {name} is missing. Reinstalling the geek tools fixes it.")


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40]


def presets(kind):
    out = []
    for line in open(share_file(f"presets/{kind}.tsv")):
        if line.strip() and not line.startswith("#"):
            out.append([p.strip() for p in line.rstrip("\n").split("|")])
    return out


def toml_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def desktop_escape(s):
    """Values in a .desktop file: no newlines (they would inject keys), backslash escapes."""
    return s.replace("\\", "\\\\").replace("\n", " ").replace("\r", " ").replace("\t", " ")


def exec_quote(arg):
    return '"' + arg.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$").replace("%", "%%") + '"'


def registry(kind):
    return os.path.join(cfg_dir(), kind)


def load_entries(kind):
    out = []
    d = registry(kind)
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if f.endswith(".toml"):
                try:
                    with open(os.path.join(d, f), "rb") as fh:
                        e = tomllib.load(fh)
                    e["slug"] = f[:-5]
                    out.append(e)
                except (OSError, tomllib.TOMLDecodeError):
                    continue
    return out


def find_entry(kind, name):
    s = slug(name)
    for e in load_entries(kind):
        if e["slug"] == s or slug(e.get("name", "")) == s:
            return e
    return None


def write_entry(kind, e):
    os.makedirs(registry(kind), exist_ok=True)
    path = os.path.join(registry(kind), e["slug"] + ".toml")
    with open(path, "w") as f:
        for k, v in e.items():
            if k != "slug":
                f.write(f"{k} = {toml_str(str(v))}\n")
    return path


def desktop_path(kind, s):
    return os.path.join(apps_dir(), f"carpatic-{kind}-{s}.desktop")


def write_desktop(kind, e, categories, comment):
    os.makedirs(apps_dir(), exist_ok=True)
    s = e["slug"]
    cls = f"carpatic-{kind}-{s}"
    lines = ["[Desktop Entry]", "Type=Application", f"Name={desktop_escape(e['name'])}", f"Comment={desktop_escape(comment)}",
             f"Exec=carpatic-{kind} launch {exec_quote(s)}", f"Icon={desktop_escape(e.get('icon', ''))}" if e.get("icon") else "Icon=applications-internet",
             f"StartupWMClass={cls}", f"Categories={categories}", "StartupNotify=false", f"X-Carpatic-{kind}={s}"]
    if kind == "tui":
        lines.append("Terminal=false")
    p = desktop_path(kind, s)
    with open(p, "w") as f:
        f.write("\n".join(lines) + "\n")
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", apps_dir()], capture_output=True)
    return p


# ---------------------------------------------------------------------------------------------------------------- icons
def letter_icon(name, dest):
    """Offline icon: a squircle with the first letter (design system: letter badge, ANSI colour at 85 % on bg)."""
    col = BADGE[int(hashlib.sha256(name.encode()).hexdigest(), 16) % len(BADGE)]
    ch = html.escape((name.strip() or "?")[0].upper())
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">
<rect width="128" height="128" rx="29" fill="#11151c"/><rect width="128" height="128" rx="29" fill="{col}" fill-opacity="0.85"/>
<text x="64" y="86" font-family="Inter, DejaVu Sans, sans-serif" font-size="68" font-weight="600" text-anchor="middle" fill="#0b0e13">{ch}</text></svg>
'''
    with open(dest, "w") as f:
        f.write(svg)
    return dest


def fetch_icon(url, dest_noext, timeout=6):
    """Site icon (apple-touch-icon, then /favicon.ico via the site). Returns a path or None. Network errors are never fatal."""
    def get(u):
        req = urllib.request.Request(u, headers={"User-Agent": "carpatic-webapp/1"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(2_000_000), r.headers.get("Content-Type", "")
    try:
        origin = "{0.scheme}://{0.netloc}".format(urllib.parse.urlparse(url))
        cands = []
        try:
            page, _ = get(url)
            txt = page[:200000].decode("utf-8", "ignore")
            for m in re.finditer(r"<link[^>]*rel=[\"'][^\"']*(apple-touch-icon|icon)[^\"']*[\"'][^>]*>", txt, re.I):
                h = re.search(r"href=[\"']([^\"']+)", m.group(0))
                if h:
                    cands.append((0 if "apple" in m.group(0).lower() else 1, urllib.parse.urljoin(url, h.group(1))))
        except OSError:
            pass
        cands = [u for _, u in sorted(cands)] + [origin + "/apple-touch-icon.png", origin + "/favicon.ico"]
        for u in cands:
            try:
                data, ct = get(u)
            except OSError:
                continue
            if len(data) < 200:
                continue
            ext = ".png" if data[:4] == b"\x89PNG" else ".svg" if b"<svg" in data[:400] else ".ico" if data[:4] == b"\x00\x00\x01\x00" else None
            if ext in (".png", ".svg"):
                with open(dest_noext + ext, "wb") as f:
                    f.write(data)
                return dest_noext + ext
    except Exception:
        return None
    return None


# ------------------------------------------------------------------------------------------------------------ web apps
def normalise_url(url):
    url = url.strip()
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", url):
        url = "https://" + url
    if re.search(r"\s", url):
        raise Problem("the address must not contain spaces.")
    if not re.match(r"^https?://[^/\s]+", url, re.I):
        raise Problem("a web app needs an http or https address, for example https://example.com")
    return url


def find_browser(prefer=None):
    for b in ([prefer] if prefer else []) + CHROMIUM:
        if b and shutil.which(b):
            return ("chromium", b)
    if shutil.which("firefox"):
        return ("firefox", "firefox")
    raise Problem("I found no browser to run web apps. Install one: carpatic install app firefox")


def webapp_add(name, url, icon=None, browser=None, fetch=True, out=print):
    if not name.strip() or "/" in name:
        raise Problem("the name must not be empty or contain '/'. Give a short name like Notion.")
    url = normalise_url(url)
    s = slug(name)
    if not s:
        raise Problem("please use letters or numbers in the name.")
    kind, binary = find_browser(browser)
    os.makedirs(icon_dir(), exist_ok=True)
    dest = os.path.join(icon_dir(), f"carpatic-webapp-{s}")
    ic = None
    if icon and os.path.isfile(icon):
        ext = os.path.splitext(icon)[1].lower() or ".png"
        ic = dest + ext
        shutil.copyfile(icon, ic)
    elif icon and icon.startswith(("http://", "https://")):
        ic = fetch_icon(icon, dest)
    if not ic and fetch and os.environ.get("CARPATIC_OFFLINE") != "1":
        ic = fetch_icon(url, dest)
    if not ic:
        ic = letter_icon(name, dest + ".svg")
    e = {"slug": s, "name": name.strip(), "url": url, "browser": binary, "mode": kind, "icon": ic}
    write_entry("webapp", e)
    write_desktop("webapp", e, "Network;WebBrowser;", f"{name.strip()} in its own window")
    if kind == "firefox":
        prepare_firefox_profile(s)
    out(f"Added {name.strip()}. Find it in the launcher, or run: carpatic webapp launch {s}")
    if kind == "firefox":
        out("It uses Firefox with its own profile. For a true app window install a Chromium-based browser: carpatic install app chromium")
    run_hook("webapp-add", name.strip(), url)
    return e


def profile_dir(s):
    return os.path.join(data_dir(), "webapps", s)


def prepare_firefox_profile(s):
    """A profile that looks like an app: no tabs, no toolbar (userChrome.css), and its own cookies."""
    d = os.path.join(profile_dir(s), "firefox")
    os.makedirs(os.path.join(d, "chrome"), exist_ok=True)
    with open(os.path.join(d, "user.js"), "w") as f:
        f.write('user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);\n'
                'user_pref("browser.shell.checkDefaultBrowser", false);\nuser_pref("browser.startup.homepage_override.mstone", "ignore");\n'
                'user_pref("browser.aboutwelcome.enabled", false);\nuser_pref("datareporting.policy.dataSubmissionEnabled", false);\n'
                'user_pref("browser.tabs.warnOnClose", false);\nuser_pref("browser.toolbars.bookmarks.visibility", "never");\n')
    with open(os.path.join(d, "chrome", "userChrome.css"), "w") as f:
        f.write("#TabsToolbar, #nav-bar, #PersonalToolbar, #sidebar-header { visibility: collapse !important; }\n"
                "#navigator-toolbox { border: 0 !important; }\n")
    return d


def run_hook(name, *args):
    if shutil.which("carpatic-hook"):
        subprocess.run(["carpatic-hook", "run", name, *args], capture_output=True)


def webapp_command(e):
    s, url = e["slug"], e["url"]
    cls = f"carpatic-webapp-{s}"
    b = e.get("browser", "chromium")
    if e.get("mode") == "firefox":
        d = prepare_firefox_profile(s)
        return [b, "--no-remote", "--profile", d, "--class", cls, "--new-window", url]
    d = os.path.join(profile_dir(s), "chromium")
    os.makedirs(d, exist_ok=True)
    return [b, f"--app={url}", f"--class={cls}", f"--user-data-dir={d}", "--no-first-run", "--no-default-browser-check", "--disable-features=Translate"]


def focus_class(cls):
    """Raise an existing window of this class. True when there was one."""
    if not shutil.which("xdotool") or not os.environ.get("DISPLAY"):
        return False
    r = subprocess.run(["xdotool", "search", "--onlyvisible", "--class", cls], capture_output=True, text=True)
    ids = r.stdout.split()
    if r.returncode == 0 and ids:
        subprocess.run(["xdotool", "windowactivate", ids[-1]], capture_output=True)
        return True
    return False


def launch(kind, e, dry=False):
    cls = f"carpatic-{kind}-{e['slug']}"
    if kind == "webapp":
        cmd = webapp_command(e)
    else:
        cmd = tui_command(e)
    if dry:
        return cmd
    if focus_class(cls):
        return cmd
    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return cmd


def remove(kind, name, keep_data=False, out=print):
    e = find_entry(kind, name)
    if not e:
        raise Problem(f"you have no {'web app' if kind == 'webapp' else 'terminal app'} called '{name}'. See: carpatic {kind} list")
    s = e["slug"]
    for p in (desktop_path(kind, s), os.path.join(registry(kind), s + ".toml")):
        if os.path.exists(p):
            os.unlink(p)
    if kind == "webapp":
        for ext in (".svg", ".png"):
            p = os.path.join(icon_dir(), f"carpatic-webapp-{s}{ext}")
            if os.path.exists(p):
                os.unlink(p)
        if not keep_data and os.path.isdir(profile_dir(s)):
            shutil.rmtree(profile_dir(s))
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", apps_dir()], capture_output=True)
    out(f"Removed {e['name']}.")


# -------------------------------------------------------------------------------------------------------------- TUI apps
def tui_command(e):
    cls = f"carpatic-tui-{e['slug']}"
    font = ""
    try:
        font = open(os.path.join(cfg_dir(), "term-font")).read().strip()
    except OSError:
        pass
    font = font or "JetBrains Mono:size=10"
    osc = os.path.join(os.environ.get("CARPATIC_STATE", os.path.join(home(), ".local", "state", "carpatic")), "current", "osc")
    return ["st", "-c", cls, "-t", "Carpatic: " + e["name"], "-g", "110x34", "-f", font, "-e", "sh", "-c",
            'cat "$0" 2>/dev/null; exec ' + e["command"], osc]


def tui_add(name, command, icon=None, out=print):
    if not name.strip() or "/" in name:
        raise Problem("the name must not be empty or contain '/'.")
    if not command.strip():
        raise Problem("what should it run? For example: carpatic tui add Top htop")
    s = slug(name)
    e = {"slug": s, "name": name.strip(), "command": command.strip(), "icon": icon or "utilities-terminal"}
    write_entry("tui", e)
    write_desktop("tui", e, "System;ConsoleOnly;", f"{name.strip()} in a terminal window")
    out(f"Added {name.strip()}. Find it in the launcher, or run: carpatic tui launch {s}")
    return e
