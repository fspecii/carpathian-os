"""About, Software Update, Storage, Default apps, Privacy."""
import os, re, glob, platform, shutil, subprocess
from gi.repository import GLib
from .. import sysutil as su, ui, theme
from ..app import Page
from ..ui import *
from . import about_data as ad

DESIGN = [os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "..", "..", "design", "brand"), "/usr/share/carpatic/brand", "/usr/local/share/carpatic/brand"]

def brand_icon(dark):
    for d in DESIGN:
        p = os.path.join(d, "carpatic-icon-%s.svg" % ("dark" if dark else "light"))
        if os.path.exists(p): return p
    return None

class AboutPage(Page):
    order = 3
    id = "about"; title = "About"; icon = "help-about"; color = "#8e8e93"; group = 5; big_title = False
    keywords = "system info version kernel processor memory ram disk graphics hostname computer name carpatic"
    entries = (("Computer name", "hostname", "name"), ("Version", "release os", "version"), ("Processor", "cpu", "cpu"), ("Memory", "ram", "ram"), ("Graphics", "gpu video", "gpu"),
               ("Kernel", "linux", "kernel"), ("Startup disk", "storage", "disk"), ("Copy system details", "report support clipboard", "copy"), ("Run the Welcome again", "setup assistant onboarding", "welcome"))
    optional = frozenset({"welcome"})
    def build(self, pb):
        osr = ad.os_release() if not ad.FAKE else {"VERSION_ID": "1.0", "PRETTY_NAME": "Carpathian OS 1.0"}
        top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4); top.set_halign(Gtk.Align.CENTER); top.set_margin_top(8); top.set_margin_bottom(8)
        p = brand_icon(self.win.pal["mode"] == "dark")
        if p: top.pack_start(hidpi_image(p, 96), False, False, 0)
        top.pack_start(label("Carpathian OS", "page-title", xalign=0.5), False, False, 4)
        top.pack_start(label("Version " + (osr.get("VERSION_ID") or osr.get("PRETTY_NAME", "")), "page-sub", xalign=0.5), False, False, 0)
        tag = label("Linux, with a view.", "muted", xalign=0.5); top.pack_start(tag, False, False, 0)
        pb.add(top)
        g = pb.group()
        self.name = EntryRow("Computer name", "", ad.hostname(), self.rename, key="name", width=220); g.add(self.name)
        mm = ad.machine_model()
        if mm: g.add(InfoRow("Model", mm, key="model"))
        g.add(InfoRow("Processor", ad.cpu_model(), key="cpu"))
        mem = ad.mem_total()
        if mem: g.add(InfoRow("Memory", su.human_bytes(mem), key="ram"))
        self.gpu = InfoRow("Graphics", "", key="gpu"); g.add(self.gpu); self.gpu.set_visible(False)
        su.bg(ad.gpu_name, lambda v: (self.gpu.set_value(v), self.gpu.set_visible(True)) if isinstance(v, str) and v else None)
        tot, free = ad.disk_root()
        if tot: g.add(InfoRow("Startup disk", f"{su.human_bytes(tot)}, {su.human_bytes(free)} free", key="disk"))
        h = pb.group("System")
        h.add(InfoRow("Version", osr.get("PRETTY_NAME", "Carpathian OS"), key="version"), InfoRow("Kernel", platform.release(), key="kernel"),
              InfoRow("Running for", ad.uptime_text(), key="uptime"))
        st = su.settings()
        style = st.get("PROFILE", "")
        if style: h.add(InfoRow("Desktop style", style.title(), key="style"))
        a = pb.group()
        a.add(ButtonRow("Copy system details", "For bug reports and the forum", "Copy", self.copy, key="copy"))
        if su.which("carpatic-welcome"): a.add(ButtonRow("Run the Welcome again", "Pick your desktop style and apps again", "Open", lambda: su.spawn("carpatic-welcome"), key="welcome"))
        pb.add(label("Carpathian OS is free software. Built on Alpine Linux, an original Rust window manager and many open-source projects; thank you to all of them.", "group-footer", xalign=0.5, wrap=True))
    def rename(self, name):
        name = name.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,62}", name):
            self.win.idle("Use letters, numbers and dashes only."); self.name.set_value_quiet(ad.hostname()); return
        self.win.busy("Renaming...")
        def done(rc, o): self.win.idle("Computer name changed. It applies after the next restart." if rc == 0 else "The name was not changed.")
        su.spawn(*su.pk("sh", "-c", f"echo {name} > /etc/hostname && hostname {name}"), done=done)
    def copy(self):
        osr = ad.os_release()
        txt = "\n".join([f"Carpathian OS {osr.get('VERSION_ID','')}", f"Kernel: {platform.release()}", f"CPU: {ad.cpu_model()}", f"Memory: {su.human_bytes(ad.mem_total())}", f"GPU: {ad.gpu_name()}", f"Style: {su.settings().get('PROFILE','')}  Theme: {su.settings().get('THEME','')}"])
        ui.copy_text(txt); self.win.idle("Copied.")


# ---------------------------------------------------------------- Software Update
def parse_update_status(st):
    n = st.split("updates:")[-1].split(",")[0].strip() if "updates:" in st else "unknown"
    return n, "restart needed: yes" in st

def nice_snap(sid):
    d = sid[:15]
    try: return f"{d[6:8]}.{d[4:6]}.{d[0:4]} {d[9:11]}:{d[11:13]}"
    except Exception: return sid

def fs_of_root():
    try:
        for l in open("/proc/mounts"):
            p = l.split()
            if p[1] == "/" and p[2] not in ("rootfs",): return p[2]
    except OSError: pass
    return ""

class UpdatesPage(Page):
    order = 0
    id = "updates"; title = "Software Update"; icon = "software-update-available"; color = "#8e8e93"; group = 5
    aliases = ("update", "restore", "rollback")
    keywords = "upgrade packages apk restore points rollback snapshots restart check install"
    sub = "Keep Carpathian OS up to date. Nothing is installed without you asking."
    entries = (("Check for updates", "refresh apk upgrade new versions", "check"), ("Install updates", "upgrade apk", "install"), ("Restore points", "rollback snapshots btrfs undo", "restore"), ("Make a restore point now", "snapshot backup", "snap"))
    optional = frozenset({"restore", "snap"})
    def available(self): return su.which("carpatic-update")
    def build(self, pb):
        self.pb = pb
        g = pb.group()
        self.status = StatusRow("Carpathian OS", "Up to date", "ok", "", key="check"); g.add(self.status)
        self.btns = ButtonRow("Updates", "", "Check for updates", lambda: self.admin("check", ["carpatic-update", "check"], "Looking for updates..."), key="install")
        self.btn_apply = self.btns.add_button("Install updates", lambda: self.admin("apply", ["carpatic-update", "apply"], "Installing updates. This can take a few minutes..."), "suggested")
        self.btn_restart = self.btns.add_button("Restart now", lambda: su.spawn("loginctl", "reboot"), "default"); self.btn_restart.set_no_show_all(True); self.btn_restart.hide()
        g.add(self.btns)
        if su.which("carpatic-security"):
            ga = pb.group("Automatic updates", "Off unless you turn it on. When on, updates are installed once a day after a restore point is saved; the computer is never restarted for you.", key="auto")
            ga.add(SwitchRow("Install updates automatically", "Fixes arrive without you doing anything. Leave off to be only notified.", su.out("carpatic-security", "auto-updates", "status").strip() == "on",
                             lambda v: self.win.apply(*su.pk("carpatic-security", "auto-updates", "on" if v else "off"), msg="Saving..."), key="auto-updates"))
        self.snap = pb.group("Restore points", "Before every update Carpathian OS keeps a copy of the system. If something goes wrong, restore it and restart. Your files in the home folder are never changed.", key="restore")
        self.snap_rows = []
        self.make = ButtonRow("Make a restore point now", "", "Make", lambda: self.admin("snap", ["carpatic-rollback", "snapshot", "manual"], "Saving a restore point..."), key="snap")
        self.snap.add(self.make)
        self.refresh()
    def on_show(self):
        if self.pb: self.refresh()
    def refresh(self):
        def work():
            return su.out("carpatic-update", "status"), (su.lines("carpatic-rollback", "list") if su.which("carpatic-rollback") else None), fs_of_root()
        su.bg(work, self.fill)
    def fill(self, res):
        if isinstance(res, Exception): return
        st, snaps, fs = res; n, restart = parse_update_status(st)
        if restart: self.status.set_value("Restart needed"); self.status.set_sub("Restart to finish updating."); self.status.set_state("warn")
        elif n == "0": self.status.set_value("Up to date"); self.status.set_sub("Your system is up to date."); self.status.set_state("ok")
        elif n == "unknown": self.status.set_value("Not checked"); self.status.set_sub("Press \u201cCheck for updates\u201d to see if anything is new."); self.status.set_state("off")
        else: self.status.set_value("Updates available"); self.status.set_sub(f"{n} update{'s' if n != '1' else ''} ready to install."); self.status.set_state("warn")
        self.btn_restart.set_visible(restart); self.btn_restart.set_no_show_all(not restart); self.btn_apply.set_sensitive(n not in ("0", "unknown") or restart)
        for r in self.snap_rows: self.snap.list.remove(r); self.snap.rows.remove(r)
        self.snap_rows = []
        if snaps is None: self.snap.set_visible(False); return
        if fs != "btrfs":
            self.make.set_sensitive(False); self.make.set_sub("Restore points need the Btrfs disk layout, which the installer offers. This computer uses " + (fs or "a different one") + ".")
            return
        self.make.set_sensitive(True); self.make.set_sub("")
        if not snaps or snaps[0].startswith("No snapshots"):
            r = InfoRow("No restore points yet", "", key="snap-none"); self.snap.add(r); self.snap_rows.append(r); r.show_all()
        else:
            for s in snaps[:12]:
                sid, _, lab = s.partition("  ")
                r = ButtonRow(nice_snap(sid), lab.strip(), "Restore", None, key="snap-" + sid); r.buttons[0].connect("clicked", lambda _b, sid=sid: self.restore(sid)); self.snap.add(r); self.snap_rows.append(r); r.show_all()
    def restore(self, sid):
        if ui.confirm(self.win, "Go back to this restore point?", f"{nice_snap(sid)}\n\nYour computer will look like it did then after the next restart. Your files stay as they are, and you can undo this.", "Restore"):
            self.admin("restore", ["carpatic-rollback", "restore", sid], "Restoring...")
    def admin(self, what, cmd, msg):
        exe = shutil.which(cmd[0]) or cmd[0]
        if what == "check":     # quick: status in the toolbar
            def done(rc, o):
                self.win.idle("That did not finish. If you cancelled the password window, nothing was changed." if rc != 0 else "Done.")
                self.refresh()
            return self.win.apply(*su.pk(exe, *cmd[1:]), msg=msg, done=done)
        heading = {"apply": "Installing updates", "snap": "Saving a restore point", "restore": "Going back to the restore point"}.get(what, "Working")
        def after(ok):
            if ok: self.win.idle("Done. Restart your computer to go back to that restore point." if what == "restore" else "Done.")
            self.refresh()
        ui.ProgressSheet(self.win, heading, [(heading, msg, [exe] + cmd[1:], True, {})], after)

# ---------------------------------------------------------------- Default apps
CATEGORIES = [("Web browser", "x-scheme-handler/http", ("x-scheme-handler/http", "x-scheme-handler/https", "text/html"), "web-browser", "#0a84ff"),
              ("Email", "x-scheme-handler/mailto", ("x-scheme-handler/mailto",), "mail-unread", "#5ac8fa"),
              ("Files", "inode/directory", ("inode/directory",), "system-file-manager", "#ff9f0a"),
              ("Text editor", "text/plain", ("text/plain",), "accessories-text-editor", "#8e8e93"),
              ("Images", "image/png", ("image/png", "image/jpeg", "image/gif", "image/webp"), "image-x-generic", "#af52de"),
              ("Videos", "video/mp4", ("video/mp4", "video/x-matroska", "video/webm"), "video-x-generic", "#ff3b30"),
              ("Music", "audio/mpeg", ("audio/mpeg", "audio/flac", "audio/ogg"), "audio-x-generic", "#ff2d55"),
              ("Documents (PDF)", "application/pdf", ("application/pdf",), "x-office-document", "#ff453a"),
              ("Archives", "application/zip", ("application/zip", "application/x-tar"), "package-x-generic", "#8e8e93")]

def candidates(mime, entries):
    return [(e[0], e[1]) for e in entries if mime in e[3]]

class AppsPage(Page):
    order = 1
    async_fill = True
    id = "apps"; title = "Default Apps"; icon = "emblem-default"; color = "#ff9f0a"; group = 5
    aliases = ("defaults", "default-apps", "mime")
    keywords = "default applications open with browser mail files editor pdf images video music xdg-mime associations"
    sub = "Which app opens what. Only apps that can open that kind of file are listed."
    entries = tuple((c[0], "default app open with " + c[1].split("/")[-1], "app-" + c[1]) for c in CATEGORIES)
    optional = frozenset("app-" + c[1] for c in CATEGORIES)
    def available(self): return su.which("xdg-mime")
    def build(self, pb):
        self.pb = pb; g = pb.group(); self.rows = {}
        def work():   # xdg-mime is a shell script (about 30 ms per call): never on the main thread
            ents = su.desktop_entries()
            return ents, {probe: su.out("xdg-mime", "query", "default", probe) for _, probe, _, _, _ in CATEGORIES}
        def fill(res):
            if isinstance(res, Exception): return
            ents, defaults = res
            for title, probe, mimes, icon, color in CATEGORIES:
                cands = candidates(probe, ents)
                if not cands: continue
                cur = defaults.get(probe, "")
                opts = [(i, n) for i, n in cands]
                if cur and cur not in dict(opts): opts.insert(0, (cur, cur[:-8] if cur.endswith(".desktop") else cur))
                r = PopupRow(title, "", opts, cur or opts[0][0], lambda v, mimes=mimes: self.set_default(v, mimes), key="app-" + probe, icon=icon, color=color); g.add(r)
            if su.which("carpatic-mail-choice"): g.add(ButtonRow("Mail app", "Webmail, Thunderbird, Claws Mail, Alpine or none: installs only what you pick", "Choose...", lambda: su.spawn("carpatic-mail-choice", "gui"), key="mail-choice"))
            self.win.on_page_filled(self)
        su.bg(work, fill)
    def set_default(self, desktop_id, mimes):
        self.win.apply("xdg-mime", "default", desktop_id, *mimes, msg="Saving...")

# ---------------------------------------------------------------- Storage
REAL_FS = {"ext4", "ext3", "ext2", "btrfs", "xfs", "f2fs", "vfat", "exfat", "ntfs", "ntfs3", "fuseblk", "jfs", "reiserfs", "zfs"}

def mounts(path="/proc/mounts"):
    """[(device, mountpoint, fstype, total, free)] for real filesystems, one per device"""
    res = []; seen = set()
    try: lines = open(path).read().splitlines()
    except OSError: return res
    for l in lines:
        p = l.split()
        if len(p) < 3 or p[2] not in REAL_FS or p[0] in seen: continue
        if p[1].startswith(("/var/lib/docker", "/snap", "/boot/efi")) and p[1] != "/": pass
        try: st = os.statvfs(p[1])
        except OSError: continue
        total = st.f_blocks * st.f_frsize
        if total <= 0: continue
        seen.add(p[0]); res.append((p[0], p[1].replace("\\040", " "), p[2], total, st.f_bavail * st.f_frsize))
    return res

def dir_size(path, timeout=20):
    t = su.out("du", "-sk", path, timeout=timeout)
    try: return int(t.split()[0]) * 1024
    except (ValueError, IndexError): return 0

class StoragePage(Page):
    order = 2
    id = "storage"; title = "Storage"; icon = "drive-harddisk"; color = "#8e8e93"; group = 5
    aliases = ("disks", "disk")
    keywords = "disk space free used drives partitions home downloads cache trash clean snapshots btrfs ext4 usb"
    sub = "How much space is used and what takes it."
    entries = (("Disks", "drives partitions free space usage", "disks"), ("Your home folder", "documents downloads pictures music videos cache", "home"), ("Empty the Trash", "delete bin", "trash"), ("Clear cached thumbnails", "free space cache", "cache"))
    def available(self): return True
    def build(self, pb):
        self.pb = pb; g = pb.group("Disks", key="disks")
        for dev, mp, fs, total, free in mounts():
            used = total - free; name = "Startup disk" if mp == "/" else os.path.basename(mp.rstrip("/")) or mp
            g.add(ProgressRow(name, f"{mp}  \u00b7  {fs}  \u00b7  {su.human_bytes(total)}", used / total, f"{su.human_bytes(free)} free", icon="drive-harddisk" if mp == "/" else "drive-removable-media", color="#8e8e93" if mp == "/" else "#ff9f0a", key="disk-" + mp))
        self.home = pb.group("Your home folder", "Sizes are measured in the background.", key="home")
        self.home_rows = {}
        for name in ("Documents", "Downloads", "Pictures", "Music", "Videos", ".cache"):
            p = os.path.join(os.path.expanduser("~"), name)
            if not os.path.isdir(p): continue
            r = InfoRow("Cache" if name == ".cache" else name, "Measuring...", key="home-" + name); r.set_busy(True); self.home.add(r); self.home_rows[p] = r
        su.bg(lambda: {p: dir_size(p) for p in self.home_rows}, self.fill_home)
        self.trash = os.path.expanduser("~/.local/share/Trash/files")
        h = pb.group("Free up space")
        tsz = dir_size(self.trash, 5) if os.path.isdir(self.trash) else 0
        self.trash_row = ButtonRow("Empty the Trash", su.human_bytes(tsz) + " in the Trash" if tsz else "The Trash is empty", "Empty", self.empty_trash, "destructive", key="trash"); self.trash_row.buttons[0].set_sensitive(tsz > 0); h.add(self.trash_row)
        h.add(ButtonRow("Clear cached thumbnails", "They are made again when needed", "Clear", lambda: self.win.apply("sh", "-c", "rm -rf ~/.cache/thumbnails ~/.cache/carpatic/thumbs", msg="Clearing...", done=lambda *_: self.win.idle("Cleared.")), key="cache"))
        if su.which("carpatic-rollback") and fs_of_root() == "btrfs":
            snaps = [l for l in su.lines("carpatic-rollback", "list") if not l.startswith("No snapshots")]
            h.add(NavRow("Restore points", f"{len(snaps)} saved", "document-save", "#34c759", "", lambda: self.win.open_page("updates"), key="snapshots"))
    def fill_home(self, res):
        if isinstance(res, Exception): return
        tot = sum(res.values()) or 1
        for p, sz in res.items():
            r = self.home_rows[p]; r.set_busy(False); r.set_value(su.human_bytes(sz))
    def empty_trash(self):
        if ui.confirm(self.win, "Empty the Trash?", "Everything in it is deleted for good.", "Empty", True):
            self.win.apply("sh", "-c", "rm -rf ~/.local/share/Trash/files/* ~/.local/share/Trash/info/*", msg="Emptying the Trash...", done=lambda *_: (self.trash_row.set_sub("The Trash is empty"), self.trash_row.buttons[0].set_sensitive(False)))

# ---------------------------------------------------------------- Privacy & Security
def secure_boot():
    for f in glob.glob("/sys/firmware/efi/efivars/SecureBoot-*"):
        try: return open(f, "rb").read()[-1] == 1
        except OSError: return None
    return False if os.path.isdir("/sys/firmware/efi") else None

def encrypted_root():
    t = su.out("lsblk", "-rno", "TYPE,MOUNTPOINT")
    if not t: return None
    return any(l.split()[0] == "crypt" and len(l.split()) > 1 for l in t.splitlines() if l.split())

def service_state(name):
    if not os.path.exists(f"/etc/init.d/{name}"): return None
    t = su.out("rc-service", name, "status") if su.which("rc-service") else ""
    return "started" in t

class PrivacyPage(Page):
    async_fill = True
    id = "privacy"; title = "Privacy & Security"; icon = "preferences-system-privacy"; color = "#0a84ff"; group = 4
    aliases = ("security", "firewall")
    keywords = "firewall nftables encryption luks secure boot lock password permissions flatpak network access ssh"
    sub = "How well this computer is protected."
    entries = (("Firewall", "nftables block incoming connections protection", "firewall"), ("Disk encryption", "luks encrypted protect files", "encryption"), ("Secure Boot", "uefi signed", "secureboot"),
               ("Remote login (SSH)", "sshd remote access", "ssh"), ("Lock screen", "password idle", "lock"), ("App permissions", "flatpak sandbox network files", "apps"))
    optional = frozenset({"firewall", "ssh", "apps", "secureboot"})
    def available(self): return True
    def build(self, pb):
        self.pb = pb
        g = pb.group("Protection")
        fw = service_state("nftables")
        if fw is not None:
            self.fw = SwitchRow("Firewall", "Blocks connections coming in from the network", fw, self.set_fw, key="firewall"); g.add(self.fw)
        self.enc = StatusRow("Disk encryption", "...", "off", "", key="encryption"); g.add(self.enc)
        def work(): return encrypted_root()
        def done(v):
            if isinstance(v, Exception) or v is None: self.enc.set_value("Unknown"); return
            self.enc.set_value("On" if v else "Off"); self.enc.set_state("ok" if v else "warn"); self.enc.set_sub("Your files are unreadable without your passphrase." if v else "Anyone with the disk can read your files. The installer can encrypt a new install.")
        su.bg(work, done)
        sb = secure_boot()
        if sb is not None: g.add(StatusRow("Secure Boot", "On" if sb else "Off", "ok" if sb else "off", "Only signed boot software may start" if sb else "", key="secureboot"))
        ssh = service_state("sshd")
        if ssh is not None:
            g.add(SwitchRow("Remote login (SSH)", "Lets other computers log in over the network", ssh, self.set_ssh, key="ssh"))
        g2 = pb.group("Passwords and locking")
        g2.add(NavRow("Lock screen", "When the screen locks and how", "system-lock-screen", "#8e8e93", "", lambda: self.win.open_page("lock"), key="lock"))
        g2.add(NavRow("Users & Groups", "Passwords and administrators", "system-users", "#0a84ff", "", lambda: self.win.open_page("users")))
        if su.which("flatpak"):
            def fill_fp(res):
                if isinstance(res, Exception) or not res: return
                g3 = pb.group("App permissions", "Apps from Flathub run in a box. Choose what each may reach.", key="apps")
                for aid, name in [(a[0], a[1] if len(a) > 1 else a[0]) for a in res]:
                    g3.add(NavRow(name, aid, None, "#8e8e93", "", lambda aid=aid, name=name: self.push(name, lambda pb: self.perms(pb, aid, name)), key="fp-" + aid))
                g3.show_all()
            def fill_all(res):
                fill_fp(res); self.win.on_page_filled(self)
            su.bg(lambda: [l.split("\t") for l in su.lines("flatpak", "list", "--app", "--columns=application,name")], fill_all)
        else: GLib.idle_add(lambda: (self.win.on_page_filled(self), False)[1])
    def set_fw(self, v):
        self.win.apply(*su.pk("sh", "-c", f"rc-update {'add' if v else 'del'} nftables default; rc-service nftables {'start' if v else 'stop'}"), msg="Changing the firewall...", done=lambda rc, o: (self.win.idle("" if rc == 0 else "The firewall was not changed."), rc != 0 and self.fw.set_value_quiet(not v)))
    def set_ssh(self, v):
        self.win.apply(*su.pk("carpatic-security", "remote-login", "on" if v else "off"), msg="Changing remote login...")
    def perms(self, pb, aid, name):
        txt = su.out("flatpak", "info", "--show-permissions", aid); sh_ = {}
        for l in txt.splitlines():
            if "=" in l: k, v = l.split("=", 1); sh_[k.strip()] = v.strip()
        ov = su.out("flatpak", "override", "--user", "--show", aid)
        net = "network" in sh_.get("shared", "") and "!network" not in ov
        g = pb.group("Access")
        g.add(SwitchRow("Internet", "", net, lambda v: self.win.apply("flatpak", "override", "--user", "--share=network" if v else "--unshare=network", aid, msg="Saving...")))
        fs = sh_.get("filesystems", "")
        home = "host" in fs or "home" in fs
        g.add(SwitchRow("Your files", "All files in your home folder", home and "!home" not in ov, lambda v: self.win.apply("flatpak", "override", "--user", "--filesystem=home" if v else "--nofilesystem=home", aid, msg="Saving...")))
        devs = sh_.get("devices", "")
        g.add(SwitchRow("Camera, sound and GPU devices", "", "all" in devs, lambda v: self.win.apply("flatpak", "override", "--user", "--device=all" if v else "--nodevice=all", aid, msg="Saving...")))
        pb.group().add(ButtonRow("Reset to the app's defaults", "", "Reset", lambda: self.win.apply("flatpak", "override", "--user", "--reset", aid, msg="Resetting...", done=lambda *_: self.win.back()), "destructive"))

PAGES = [AboutPage, UpdatesPage, AppsPage, StoragePage, PrivacyPage]
