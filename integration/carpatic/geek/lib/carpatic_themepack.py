"""Theme packs for Carpathian: export, import (Carpathian packs and Omarchy theme folders), conversion report, wallpapers.

Idea from Omarchy's theme install/set/remove tools (MIT, see NOTICE). Omarchy themes and Carpathian themes share the same colors.toml
palette format, so importing is mostly checking, filling gaps, shrinking wallpapers and keeping the extras (Neovim, VS Code files).
Python 3.11+ standard library; wallpapers are converted with GdkPixbuf, ImageMagick or ffmpeg when one of them is installed.
"""
import datetime
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.request

REQUIRED = ["background", "foreground", "accent", "red", "green", "yellow", "blue", "cyan"]
OPTIONAL_FILL = {"magenta": "red", "orange": "yellow", "brown": "red", "bright_red": "red", "bright_green": "green",
                 "bright_yellow": "yellow", "bright_blue": "blue", "bright_cyan": "cyan", "bright_magenta": "magenta",
                 "bright_foreground": "foreground", "dark_background": "background"}
KNOWN = set(REQUIRED) | set(OPTIONAL_FILL) | {"selection", "muted", "darker_background", "lighter_background", "dark_foreground", "light_foreground"}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
# files kept verbatim next to the palette (tools that understand them pick them up)
EXTRAS_KEPT = {"neovim.lua": "used by the Carpathian Neovim setup", "vscode.json": "VS Code / VSCodium colour theme",
               "icons.theme": "icon theme name", "preview.png": "preview picture", "chromium.theme": "browser colour",
               "btop.theme": "btop colours", "light.mode": "marks a light theme"}
EXTRAS_UNUSED = {"keyboard.rgb": "keyboard lighting (Omarchy hardware)", "shell.lock.toml": "Omarchy shell lock screen",
                 "unlock.png": "Omarchy unlock screen", "preview-unlock.png": "Omarchy unlock screen"}
ALLOWED_EXT = {".toml", ".jpg", ".jpeg", ".png", ".webp", ".lua", ".json", ".theme", ".md", ".txt", ".rgb", ".mode", ".svg", ".ttf",
               ".otf", ".sha256"}
MAX_PACK = 400 * 1024 * 1024
MAX_WALL = (2560, 1600)


class Problem(Exception):
    pass


def home():
    return os.environ.get("HOME", "/root")


def cfg_dir():
    return os.environ.get("CARPATIC_CONFIG", os.path.join(home(), ".config", "carpatic"))


def share_dir():
    return os.environ.get("CARPATIC_SHARE", "/usr/local/share/carpatic/configurator")


def user_themes():
    return os.path.join(cfg_dir(), "themes")


def system_theme_names():
    try:
        return sorted(os.listdir(os.path.join(share_dir(), "themes")))
    except OSError:
        return []


def user_theme_names():
    try:
        return sorted(d for d in os.listdir(user_themes()) if os.path.isfile(os.path.join(user_themes(), d, "colors.toml")))
    except OSError:
        return []


def theme_dir(name):
    u = os.path.join(user_themes(), name)
    if os.path.isfile(os.path.join(u, "colors.toml")):
        return u
    s = os.path.join(share_dir(), "themes", name)
    return s if os.path.isfile(os.path.join(s, "colors.toml")) else None


def slug(s):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:40]


# --------------------------------------------------------------------------------------------------------------- palette
def parse_palette(text):
    pal = {}
    for line in text.splitlines():
        line = re.sub(r"\s+#.*$", "", line)
        m = re.match(r'^\s*([A-Za-z0-9_]+)\s*=\s*"([^"]*)"\s*$', line)
        if m:
            pal[m.group(1)] = m.group(2)
    return pal


def lum(h):
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.299 * r + 0.587 * g + 0.114 * b


def normalise_palette(pal):
    """Returns (palette, notes, problems). Missing optional colours are filled from the base ones, bad values are problems."""
    notes, problems = [], []
    out = {}
    ignored = []
    for k, v in pal.items():
        if k == "mode":
            out[k] = v
            continue
        if re.match(r"^[0-9a-fA-F]{6}$", v):
            v = "#" + v
        if HEX.match(v):
            out[k] = v.lower()
        elif k in KNOWN:
            problems.append(f"colour '{k}' is not a #rrggbb value ({v!r})")
        else:
            ignored.append(k)     # settings of another desktop (for example Hyprland borders): not colours of the palette
    if ignored:
        notes.append("ignored settings that are not palette colours: " + ", ".join(ignored))
    for k in REQUIRED:
        if k not in out:
            problems.append(f"the required colour '{k}' is missing")
    if problems:
        return out, notes, problems
    filled = []
    for k, src in OPTIONAL_FILL.items():
        if k not in out:
            out[k] = out.get(src, out[src] if src in out else out["red"])
            filled.append(k)
    if filled:
        notes.append("filled in from related colours: " + ", ".join(filled))
    if out.get("mode") not in ("dark", "light"):
        out["mode"] = "light" if lum(out["background"]) > 140 else "dark"
        notes.append(f"mode not set, taken from the background: {out['mode']}")
    return out, notes, problems


def palette_text(pal, origin):
    head = f'# {origin}\nmode = "{pal["mode"]}"\n\n'
    order = ["accent", "selection", "muted", "background", "dark_background", "darker_background", "lighter_background", "foreground",
             "dark_foreground", "light_foreground", "bright_foreground", "red", "yellow", "orange", "green", "cyan", "blue", "magenta",
             "brown", "bright_red", "bright_yellow", "bright_green", "bright_cyan", "bright_blue", "bright_magenta"]
    keys = [k for k in order if k in pal] + [k for k in pal if k not in order and k != "mode"]
    return head + "".join(f'{k} = "{pal[k]}"\n' for k in keys)


# ------------------------------------------------------------------------------------------------------------ wallpapers
def _pixbuf_to_jpeg(src, dst):
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    pb = GdkPixbuf.Pixbuf.new_from_file(src)
    w, h = pb.get_width(), pb.get_height()
    if w > MAX_WALL[0] or h > MAX_WALL[1]:
        f = min(MAX_WALL[0] / w, MAX_WALL[1] / h)
        pb = pb.scale_simple(int(w * f), int(h * f), GdkPixbuf.InterpType.BILINEAR)
    if pb.get_has_alpha():
        pb = pb.composite_color_simple(pb.get_width(), pb.get_height(), GdkPixbuf.InterpType.NEAREST, 255, 8, 0, 0)
    pb.savev(dst, "jpeg", ["quality"], ["88"])


def convert_wallpaper(src, dst):
    """Write a JPEG of at most 2560x1600 to dst. Returns the method used or raises Problem."""
    ext = os.path.splitext(src)[1].lower()
    size = os.path.getsize(src)
    try:
        _pixbuf_to_jpeg(src, dst)
        return "gdk-pixbuf"
    except Exception:
        pass
    if ext == ".webp" and shutil.which("dwebp"):      # Alpine has no webp loader for GdkPixbuf: decode with libwebp-tools first
        tmp = tempfile.mkdtemp(prefix="carpatic-webp-")
        try:
            png = os.path.join(tmp, "w.png")
            if subprocess.run(["dwebp", "-quiet", src, "-o", png], capture_output=True).returncode == 0:
                _pixbuf_to_jpeg(png, dst)
                return "dwebp"
        except Exception:
            pass
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    for tool in (["magick"], ["convert"]):
        if shutil.which(tool[0]):
            r = subprocess.run(tool + [src, "-resize", f"{MAX_WALL[0]}x{MAX_WALL[1]}>", "-quality", "88", dst], capture_output=True)
            if r.returncode == 0 and os.path.exists(dst):
                return tool[0]
    if shutil.which("ffmpeg"):
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-vf", f"scale='min({MAX_WALL[0]},iw)':-2", "-q:v", "3", dst],
                           capture_output=True)
        if r.returncode == 0 and os.path.exists(dst):
            return "ffmpeg"
    if ext in (".jpg", ".jpeg") and size < 6 * 1024 * 1024:
        shutil.copyfile(src, dst)
        return "copied"
    raise Problem(f"cannot convert {os.path.basename(src)}: install the webp tools (doas apk add libwebp-tools)")


def find_wallpapers(d):
    out = []
    for sub in ("backgrounds", "wallpapers", "."):
        p = os.path.join(d, sub)
        if os.path.isdir(p):
            for f in sorted(os.listdir(p)):
                if re.match(r"^(wallpaper.*|[^.].*)\.(jpg|jpeg|png|webp)$", f, re.I) and not f.startswith(("preview", "unlock")) \
                        and os.path.isfile(os.path.join(p, f)):
                    out.append(os.path.join(p, f))
        if out and sub != ".":
            break
    return out


# ---------------------------------------------------------------------------------------------------------------- import
class Report:
    def __init__(self, name):
        self.name = name
        self.lines = []
        self.ok = True

    def add(self, label, text):
        self.lines.append((label, text))

    def fail(self, text):
        self.ok = False
        self.add("problem", text)

    def text(self):
        out = [f"Theme {self.name}"]
        for k, v in self.lines:
            out.append(f"  {k:<12} {v}")
        out.append(f"  {'result':<12} " + ("OK" if self.ok else "cannot be imported"))
        return "\n".join(out)


def read_source_dir(d):
    """A theme folder (Omarchy or Carpathian format). Returns (name, palette text, folder)."""
    cp = os.path.join(d, "colors.toml")
    if not os.path.isfile(cp):
        raise Problem(f"{d} has no colors.toml, so it is not a theme folder")
    return os.path.basename(os.path.abspath(d)), open(cp).read(), d


def convert_dir(src, dest, name, report, wallpapers=True, origin="omarchy"):
    """Convert theme folder `src` into Carpathian layout at `dest` (created). Fills the report."""
    pal_in = parse_palette(open(os.path.join(src, "colors.toml")).read())
    pal, notes, problems = normalise_palette(pal_in)
    for p in problems:
        report.fail(p)
    if problems:
        return None
    report.add("palette", f"ok, {len(pal_in)} colours, {pal['mode']}" + ("" if not notes else " (" + "; ".join(notes) + ")"))
    os.makedirs(dest, exist_ok=True)
    with open(os.path.join(dest, "colors.toml"), "w") as f:
        f.write(palette_text(pal, f"Carpathian theme '{name}' (imported from {origin}; palette checked by carpatic theme import)"))
    walls = find_wallpapers(src)
    done, before, after, methods = 0, 0, 0, set()
    if wallpapers:
        for i, w in enumerate(walls):
            dst = os.path.join(dest, "wallpaper.jpg" if i == 0 else f"wallpaper-{i + 1}.jpg")
            try:
                methods.add(convert_wallpaper(w, dst))
                before += os.path.getsize(w)
                after += os.path.getsize(dst)
                done += 1
            except Problem as e:
                report.add("warning", str(e))
    if walls:
        report.add("wallpapers", f"{done} of {len(walls)} converted ({before / 1e6:.1f} MB to {after / 1e6:.1f} MB, {', '.join(sorted(methods)) or 'skipped'})")
    else:
        report.add("wallpapers", "none in the theme (the current wallpaper stays)")
    kept = []
    for f, why in EXTRAS_KEPT.items():
        if os.path.isfile(os.path.join(src, f)):
            shutil.copyfile(os.path.join(src, f), os.path.join(dest, f))
            kept.append(f)
    if kept:
        report.add("extras kept", ", ".join(kept))
    unused = [f for f in EXTRAS_UNUSED if os.path.isfile(os.path.join(src, f))]
    if unused:
        report.add("not used", ", ".join(unused) + " (made for Omarchy hardware or screens)")
    return pal


def manifest_text(name, pal, origin, extras=None):
    lines = ["[theme]", f'name = "{name}"', f'mode = "{pal["mode"]}"', f'origin = "{origin}"',
             f'created = "{datetime.date.today().isoformat()}"', 'format = 1']
    if extras:
        lines.append("")
        lines.append("[recommends]")
        for k, v in extras.items():
            if v:
                lines.append(f'{k} = "{v}"')
    return "\n".join(lines) + "\n"


def sums_for(dirpath):
    out = []
    for root, _, files in os.walk(dirpath):
        for f in sorted(files):
            if f == "SHA256SUMS":
                continue
            p = os.path.join(root, f)
            out.append((hashlib.sha256(open(p, "rb").read()).hexdigest(), os.path.relpath(p, dirpath)))
    return sorted(out, key=lambda x: x[1])


def safe_extract(tar_path, dest, allow_fonts=False):
    """Extract a theme pack: regular files only, relative paths only, allow-listed extensions, size limits."""
    total = 0
    with tarfile.open(tar_path, "r:*") as t:
        members = t.getmembers()
        tops = {m.name.split("/")[0] for m in members if m.name not in (".", "")}
        if len(tops) != 1:
            raise Problem("the pack must contain exactly one folder")
        for m in members:
            n = m.name
            if n.startswith("/") or ".." in n.split("/") or "\\" in n:
                raise Problem(f"the pack contains an unsafe path: {n}")
            if m.isdir():
                continue
            if not m.isreg():
                raise Problem(f"the pack contains something that is not a plain file: {n}")
            ext = os.path.splitext(n)[1].lower()
            base = os.path.basename(n)
            if base != "SHA256SUMS" and ext not in ALLOWED_EXT:
                raise Problem(f"the pack contains a file type I will not install: {n}")
            total += m.size
            if total > MAX_PACK:
                raise Problem("the pack is bigger than 400 MB")
        t.extractall(dest, members=[m for m in members if m.isreg() or m.isdir()], filter="data")
    return os.path.join(dest, tops.pop())


def verify_sums(folder):
    sp = os.path.join(folder, "SHA256SUMS")
    if not os.path.isfile(sp):
        return False
    listed = {}
    for line in open(sp):
        h, _, f = line.strip().partition("  ")
        if h:
            listed[f] = h
    actual = dict((f, h) for h, f in sums_for(folder))
    for f, h in actual.items():
        if listed.get(f) != h:
            raise Problem(f"{f} does not match its checksum: the pack was changed after it was made. Nothing was installed.")
    for f in listed:
        if f not in actual:
            raise Problem(f"{f} is listed but missing from the pack. Nothing was installed.")
    return True


def fetch(url, sha256=None):
    if not url.startswith(("http://", "https://")):
        raise Problem("only http and https links are supported")
    if not sha256:
        raise Problem("for a download I need the pack's checksum so I can check it: add --sha256 HASH (the person who shared it can read it from `carpatic theme share`).")
    tmp = tempfile.mkdtemp(prefix="carpatic-dl-")
    dst = os.path.join(tmp, "pack.tar.gz")
    try:
        with urllib.request.urlopen(url, timeout=30) as r, open(dst, "wb") as f:
            n = 0
            while True:
                b = r.read(1 << 16)
                if not b:
                    break
                n += len(b)
                if n > MAX_PACK:
                    raise Problem("the download is bigger than 400 MB")
                f.write(b)
    except OSError as e:
        raise Problem(f"could not download it ({e}). Check the link and your connection.")
    if hashlib.sha256(open(dst, "rb").read()).hexdigest() != sha256.lower():
        raise Problem("the download does not match the checksum you gave. Nothing was installed.")
    return dst


def run_hook(name, *args):
    if shutil.which("carpatic-hook"):
        subprocess.run(["carpatic-hook", "run", name, *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def do_import(src, name=None, force=False, dry=False, fonts=False, unverified=False, sha256=None, wallpapers=True, verify=None, sig=None,
              identity=None, out=print):
    tmp = tempfile.mkdtemp(prefix="carpatic-theme-")
    try:
        origin = "omarchy"
        pack_verified = False
        if src.startswith(("http://", "https://")):
            src = fetch(src, sha256)
        if os.path.isfile(src):
            if sha256 and hashlib.sha256(open(src, "rb").read()).hexdigest() != sha256.lower():
                raise Problem("the file does not match the checksum you gave. Nothing was installed.")
            if verify:
                sigf = sig or src + ".sig"
                if not os.path.exists(sigf):
                    raise Problem(f"no signature file found ({sigf})")
                r = subprocess.run(["ssh-keygen", "-Y", "verify", "-f", verify, "-I", identity or "carpatic", "-n", "carpatic-theme",
                                    "-s", sigf], stdin=open(src, "rb"), capture_output=True, text=True)
                if r.returncode != 0:
                    raise Problem("the signature does not match. Nothing was installed. " + r.stdout.strip())
                out("Signature is valid.")
            folder = safe_extract(src, tmp)
            pack_verified = verify_sums(folder)
            if not pack_verified and not unverified:
                raise Problem("this pack has no checksums, so it was not made by `carpatic theme export`. "
                              "If you trust it, add --unverified.")
            origin = "carpatic-pack"
        elif os.path.isdir(src):
            folder = src
            if os.path.isfile(os.path.join(src, "SHA256SUMS")):
                pack_verified = verify_sums(src)
                origin = "carpatic-folder"
        else:
            raise Problem(f"I cannot find {src}")
        tname = slug(name or os.path.basename(os.path.abspath(folder)))
        if not tname:
            raise Problem("the theme needs a name: add --name my-theme")
        rep = Report(tname)
        if tname in system_theme_names() and not name and not dry:
            raise Problem(f"a theme called '{tname}' already comes with Carpathian. Import this one under another name: --name {tname}-2")
        if tname in user_theme_names() and not force and not dry:
            raise Problem(f"you already imported a theme called '{tname}'. Replace it with --force.")
        stage = os.path.join(tmp, "stage", tname)
        # a Carpathian pack is already in final layout; an Omarchy folder is converted
        if origin == "carpatic-pack":
            os.makedirs(stage)
            pal_in = parse_palette(open(os.path.join(folder, "colors.toml")).read())
            pal, notes, problems = normalise_palette(pal_in)
            for p in problems:
                rep.fail(p)
            if problems:
                out(rep.text())
                return 1
            for f in os.listdir(folder):
                p = os.path.join(folder, f)
                if f in ("SHA256SUMS",):
                    continue
                if os.path.isdir(p):
                    if f in ("fonts", "icons") and not fonts:
                        continue
                    shutil.copytree(p, os.path.join(stage, f))
                else:
                    shutil.copyfile(p, os.path.join(stage, f))
            rep.add("palette", f"ok, {len(pal_in)} colours, {pal['mode']}")
            n = len(find_wallpapers(stage))
            rep.add("wallpapers", f"{n} in the pack")
            rep.add("verified", "checksums match" if pack_verified else "not verified (--unverified)")
            if os.path.isdir(os.path.join(folder, "fonts")) and not fonts:
                rep.add("fonts", "the pack has fonts; they were not installed (add --fonts to install them)")
            pal_final = pal
        else:
            pal_final = convert_dir(folder, stage, tname, rep, wallpapers=wallpapers, origin=origin)
            if pal_final is None:
                out(rep.text())
                return 1
            with open(os.path.join(stage, "theme.toml"), "w") as f:
                f.write(manifest_text(tname, pal_final, origin))
        if dry:
            rep.add("dry run", "nothing was installed")
            out(rep.text())
            return 0
        dest = os.path.join(user_themes(), tname)
        os.makedirs(user_themes(), exist_ok=True)
        if os.path.exists(dest):
            shutil.rmtree(dest)
        shutil.move(stage, dest)
        if fonts and os.path.isdir(os.path.join(dest, "fonts")):
            fd = os.path.join(home(), ".local", "share", "fonts", "carpatic-" + tname)
            os.makedirs(os.path.dirname(fd), exist_ok=True)
            shutil.copytree(os.path.join(dest, "fonts"), fd, dirs_exist_ok=True)
            if shutil.which("fc-cache"):
                subprocess.run(["fc-cache", "-f", fd], capture_output=True)
            rep.add("fonts", "installed in ~/.local/share/fonts")
        rep.add("installed", f"{dest}")
        out(rep.text())
        out(f"\nUse it with: carpatic theme set {tname}")
        run_hook("theme-import", tname)
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------------------------------------------- export
def read_settings():
    d = {}
    try:
        for line in open(os.path.join(cfg_dir(), "settings.conf")):
            m = re.match(r'^(\w+)="(.*)"$', line.strip())
            if m:
                d[m.group(1)] = re.sub(r'\\(["\\$`])', r'\1', m.group(2))
    except OSError:
        pass
    return d


def find_font_files(family):
    if not shutil.which("fc-list"):
        return []
    out = subprocess.run(["fc-list", f"{family}", "file"], capture_output=True, text=True).stdout
    files = []
    for line in out.splitlines():
        p = line.split(":")[0].strip()
        if os.path.isfile(p) and p.lower().endswith((".ttf", ".otf")) and p not in files:
            files.append(p)
    return files


def do_export(name, out_path=None, fonts=(), sign=None, out=print):
    td = theme_dir(name)
    if not td:
        raise Problem(f"I do not know a theme called '{name}'. See: carpatic theme list")
    st = read_settings()
    tmp = tempfile.mkdtemp(prefix="carpatic-export-")
    try:
        stage = os.path.join(tmp, name)
        os.makedirs(stage)
        pal, notes, problems = normalise_palette(parse_palette(open(os.path.join(td, "colors.toml")).read()))
        if problems:
            raise Problem("this theme's palette has problems: " + "; ".join(problems))
        for f in sorted(os.listdir(td)):
            p = os.path.join(td, f)
            if os.path.isfile(p) and (os.path.splitext(f)[1].lower() in ALLOWED_EXT) and f != "SHA256SUMS":
                shutil.copyfile(p, os.path.join(stage, f))
        if st.get("WALLPAPER") and os.path.isfile(st["WALLPAPER"]) and st.get("THEME") == name \
                and not any(f.startswith("wallpaper") for f in os.listdir(stage)):
            convert_wallpaper(st["WALLPAPER"], os.path.join(stage, "wallpaper.jpg"))
        rec = {"ui_font": st.get("UI_FONT"), "mono_font": st.get("MONO_FONT"), "icons": st.get("ICON_THEME"), "cursor": st.get("CURSOR_THEME")} \
            if st.get("THEME") == name else {}
        with open(os.path.join(stage, "theme.toml"), "w") as f:
            f.write(manifest_text(name, pal, "carpatic", rec))
        for fam in fonts:
            files = find_font_files(fam)
            if not files:
                out(f"Note: I could not find the font '{fam}', so it is not in the pack.")
                continue
            os.makedirs(os.path.join(stage, "fonts"), exist_ok=True)
            for p in files[:12]:
                shutil.copyfile(p, os.path.join(stage, "fonts", os.path.basename(p)))
            out(f"Included {len(files[:12])} file(s) of '{fam}'. Check that its licence lets you share it.")
        with open(os.path.join(stage, "SHA256SUMS"), "w") as f:
            f.write("".join(f"{h}  {n}\n" for h, n in sums_for(stage)))
        dst = out_path or os.path.join(os.getcwd(), f"{name}.carpatic-theme.tar.gz")
        if os.path.isdir(dst):
            dst = os.path.join(dst, f"{name}.carpatic-theme.tar.gz")
        with tarfile.open(dst, "w:gz") as t:
            def flt(ti):
                ti.uid = ti.gid = 0
                ti.uname = ti.gname = ""
                ti.mtime = 0
                ti.mode = 0o755 if ti.isdir() else 0o644
                return ti
            t.add(stage, arcname=name, filter=flt)
        digest = hashlib.sha256(open(dst, "rb").read()).hexdigest()
        with open(dst + ".sha256", "w") as f:
            f.write(f"{digest}  {os.path.basename(dst)}\n")
        if sign:
            r = subprocess.run(["ssh-keygen", "-Y", "sign", "-f", sign, "-n", "carpatic-theme", dst], capture_output=True, text=True)
            if r.returncode != 0:
                raise Problem("could not sign the pack: " + r.stderr.strip())
            out(f"Signed: {dst}.sig")
        out(f"{dst}")
        out(f"sha256 {digest}")
        run_hook("theme-export", name, dst)
        return dst, digest
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def do_remove(name, out=print):
    if name in system_theme_names() and name not in user_theme_names():
        raise Problem(f"'{name}' comes with Carpathian and cannot be removed. You can only remove themes you imported.")
    if name not in user_theme_names():
        raise Problem(f"you have not imported a theme called '{name}'. See: carpatic theme packs, or carpatic-themepack list --imported")
    cur = read_settings().get("THEME")
    if cur == name:
        raise Problem(f"'{name}' is the theme in use. Switch to another one first: carpatic theme set carpatic")
    shutil.rmtree(os.path.join(user_themes(), name))
    out(f"Removed {name}.")


# ------------------------------------------------------------------------------------------------------------ wallpapers
def set_setting(key, value):
    p = os.path.join(cfg_dir(), "settings.conf")
    os.makedirs(cfg_dir(), exist_ok=True)
    lines = [l for l in open(p).read().splitlines() if not l.startswith(key + "=")] if os.path.exists(p) else []
    lines.append('%s="%s"' % (key, re.sub(r'(["\\$`])', r'\\\1', str(value).replace("\n", " ").replace("\r", " "))))   # settings.conf is sourced by shell: no code from values
    tmp = p + f".{os.getpid()}"
    with open(tmp, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, p)


def wallpaper_list():
    """[(path, label, group)] for the current theme, shared wallpapers and ~/Pictures/Wallpapers."""
    cur = read_settings().get("THEME", "carpatic")
    out, seen = [], set()

    def add(path, label, group):
        rp = os.path.realpath(path)
        if rp not in seen and os.path.isfile(path):
            seen.add(rp)
            out.append((path, label, group))
    td = theme_dir(cur)
    if td:
        for f in sorted(os.listdir(td)):
            if re.match(r"^wallpaper.*\.(jpg|png)$", f):
                add(os.path.join(td, f), f"{cur} {f.replace('.jpg', '').replace('.png', '').replace('wallpaper', '').strip('-') or '1'}", cur)
    for sd in (os.path.join(share_dir(), "wallpapers"), os.path.join(share_dir(), "share", "wallpapers")):
        if os.path.isdir(sd):
            mode = ""
            for f in sorted(os.listdir(sd)):
                if f.lower().endswith((".jpg", ".png")):
                    add(os.path.join(sd, f), os.path.splitext(f)[0].replace("-", " ").replace("_", " "), "Carpathian")
    pd = os.path.join(home(), "Pictures", "Wallpapers")
    if os.path.isdir(pd):
        for f in sorted(os.listdir(pd)):
            if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                add(os.path.join(pd, f), os.path.splitext(f)[0], "Your pictures")
    return out


def apply_wallpaper(path, out=print):
    set_setting("WALLPAPER", path)
    try:
        with open(os.path.join(cfg_dir(), "wallpaper"), "w") as f:
            f.write(path + "\n")
    except OSError:
        pass
    if os.environ.get("DISPLAY") and shutil.which("feh") and os.environ.get("CARPATIC_NO_RELOAD") != "1":
        subprocess.run(["feh", "--no-fehbg", "--bg-fill", path], capture_output=True)
    run_hook("wallpaper-set", path)


def wallpaper_next(out=print):
    lst = wallpaper_list()
    if not lst:
        raise Problem("I found no wallpapers for this theme.")
    cur = read_settings().get("WALLPAPER", "")
    paths = [p for p, _, _ in lst]
    i = paths.index(cur) + 1 if cur in paths else 0
    nxt = paths[i % len(paths)]
    apply_wallpaper(nxt, out)
    out(f"Wallpaper: {lst[i % len(lst)][1]}")


def theme_list():
    names = []
    for n in system_theme_names() + user_theme_names():
        if n not in names:
            names.append(n)
    return names


def theme_next(out=print):
    names = theme_list()
    cur = read_settings().get("THEME", "carpatic")
    i = (names.index(cur) + 1) % len(names) if cur in names else 0
    r = subprocess.run(["carpatic-theme", "set", names[i]])
    if r.returncode != 0:
        raise Problem("the theme tool could not apply it")
    out(f"Theme: {names[i]}")
