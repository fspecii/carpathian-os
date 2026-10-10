"""Mail client choice (Welcome, Settings > Default Apps, `carpatic-mail-choice`). Nothing is installed by default: the user picks
Webmail app (0 MB), Thunderbird (about 290 MB), Claws Mail (about 195 MB), Alpine (terminal, about 9 MB) or None.
The choice is stored as MAIL_CLIENT (+ MAIL_WEBMAIL provider) in settings.conf and as the mailto: default in ~/.config/mimeapps.list."""
import os, re, shutil, sys

CFG = os.environ.get("CARPATIC_CONFIG", os.path.expanduser("~/.config/carpatic"))
SETTINGS = os.path.join(CFG, "settings.conf")
APPS_DIR = os.path.expanduser("~/.local/share/applications")
MIMEAPPS = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "mimeapps.list")
# id, title, description, store catalog id (None = nothing to install), binary to look for, desktop id
CHOICES = [
    ("webmail", "Webmail app", "Gmail, Outlook or iCloud in its own window. Nothing to install (0 MB).", None, None, "carpatic-webmail.desktop"),
    ("thunderbird", "Thunderbird", "Full mail, calendar and contacts with Google and Microsoft sign-in. Large: about 290 MB.", "thunderbird", "thunderbird", "thunderbird.desktop"),
    ("claws", "Claws Mail", "Fast, classic desktop mail client. About 195 MB.", "claws-mail", "claws-mail", "claws-mail.desktop"),
    ("alpine", "Terminal mail", "A small text-only mail program (Alpine) that runs in a terminal window. For experienced users. About 9 MB.", "alpine", "alpine", "carpatic-mail.desktop"),
    ("none", "None", "I will use something else.", None, None, None),
]
PROVIDERS = [("gmail", "Gmail"), ("outlook", "Outlook"), ("icloud", "iCloud")]
MIMES = ("x-scheme-handler/mailto", "message/rfc822")

def choice(cid):
    for c in CHOICES:
        if c[0] == cid: return c
    return CHOICES[-1]

def _read_settings():
    out = []
    try: out = open(SETTINGS).read().splitlines()
    except OSError: pass
    return out

def get_setting(key, default=""):
    for line in _read_settings():
        m = re.match(r'%s="?([^"]*)"?\s*$' % re.escape(key), line)
        if m: return m.group(1)
    return default

def set_setting(key, value):
    lines = [l for l in _read_settings() if not re.match(r"%s=" % re.escape(key), l)]
    lines.append('%s="%s"' % (key, re.sub(r'(["\\$`])', r'\\\1', str(value).replace("\n", " ").replace("\r", " "))))
    os.makedirs(CFG, exist_ok=True)
    tmp = SETTINGS + ".new"; open(tmp, "w").write("\n".join(lines) + "\n"); os.replace(tmp, SETTINGS)

def current():
    """(choice id, webmail provider); ('', 'gmail') when the user was never asked"""
    return get_setting("MAIL_CLIENT", ""), get_setting("MAIL_WEBMAIL", "gmail") or "gmail"

def is_installed(cid):
    c = choice(cid)
    return c[4] is None or shutil.which(c[4]) is not None

def write_mimeapps(cid):
    """mailto: and message/rfc822 defaults follow the choice (removed for None). Other lines are kept."""
    c = choice(cid); desk = c[5]
    try: lines = open(MIMEAPPS).read().splitlines()
    except OSError: lines = []
    sec = None; out = []; seen = False
    for l in lines:
        m = re.match(r"\[(.+)\]\s*$", l)
        if m: 
            if sec == "Default Applications" and not seen and desk:
                out += ["%s=%s" % (k, desk) for k in MIMES]; seen = True
            sec = m.group(1)
        if sec == "Default Applications" and any(l.startswith(k + "=") for k in MIMES): continue
        out.append(l)
    if not seen and desk:
        if "[Default Applications]" not in out: out.append("[Default Applications]")
        i = out.index("[Default Applications]") + 1
        out[i:i] = ["%s=%s" % (k, desk) for k in MIMES]
    os.makedirs(os.path.dirname(MIMEAPPS), exist_ok=True)
    open(MIMEAPPS, "w").write("\n".join(out).rstrip("\n") + "\n")

def write_webmail_entry(provider):
    name = dict(PROVIDERS).get(provider, "Gmail")
    os.makedirs(APPS_DIR, exist_ok=True)
    open(os.path.join(APPS_DIR, "carpatic-webmail.desktop"), "w").write(
        "[Desktop Entry]\nType=Application\nName=Mail (%s)\nGenericName=Email\nComment=%s in its own window\nExec=carpatic-webmail %s %%u\n"
        "Icon=mail-unread\nTerminal=false\nCategories=Network;Email;\nMimeType=x-scheme-handler/mailto;\nStartupWMClass=carpatic-webmail\n" % (name, name, provider))

def remove_webmail_entry():
    try: os.remove(os.path.join(APPS_DIR, "carpatic-webmail.desktop"))
    except OSError: pass

def store_install(cid, on_line=None, password=None):
    """Install the chosen client with the store's apk path. Raises RuntimeError with a plain-English message."""
    c = choice(cid)
    if c[3] is None or is_installed(cid): return
    sys.path[:0] = ["/usr/local/lib/carpatic-store", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "store", "lib")]
    try:
        import carpatic_store as cs
    except ImportError:
        raise RuntimeError("The App Store is not installed, so %s cannot be added right now. You can add it later from the App Store or Settings." % c[1])
    try:
        cs.install(cs.Catalog().resolve(c[3]), on_line, password)
    except cs.StoreError as e:
        msg = str(e)
        if re.search(r"tty is required|Authentication required|incorrect password|Permission denied", msg, re.I):
            msg = "Adding %s needs your administrator password, and it was not accepted." % c[1]
        raise RuntimeError(msg)

def apply(cid, provider="gmail", on_line=None, password=None, install=True):
    """Install if needed, then make it the default. Returns a one-line summary. Raises RuntimeError (friendly) when the install fails;
    nothing is changed in that case."""
    c = choice(cid)
    if install: store_install(cid, on_line, password)
    if cid == "webmail": write_webmail_entry(provider)
    if cid != "webmail": remove_webmail_entry()
    write_mimeapps(cid)
    set_setting("MAIL_CLIENT", cid)
    if cid == "webmail": set_setting("MAIL_WEBMAIL", provider)
    return "Mail: %s" % (c[1] if cid != "webmail" else "%s webmail" % dict(PROVIDERS).get(provider, "Gmail"))

# ------------------------------------------------------------------ GTK
def build_widget(initial="webmail", provider="gmail", on_change=None):
    """Radio cards for the five choices (+ provider pills under Webmail). Returns (box, get) with get() -> (choice id, provider)."""
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    state = {"c": initial or "webmail", "p": provider or "gmail"}
    group = None; radios = {}
    pills = Gtk.Box(spacing=6)
    pgroup = None
    for pid, pname in PROVIDERS:
        b = Gtk.RadioButton.new_with_label_from_widget(pgroup, pname) if pgroup else Gtk.RadioButton.new_with_label(None, pname)
        pgroup = pgroup or b; b.set_mode(False); b.get_style_context().add_class("pill"); b.get_style_context().add_class("cp-pill")
        b.set_active(pid == state["p"])
        b.connect("toggled", lambda w, pid=pid: (state.__setitem__("p", pid), on_change and on_change()) if w.get_active() else None)
        pills.pack_start(b, False, False, 0)
    for cid, title, desc, *_ in CHOICES:
        r = Gtk.RadioButton.new_from_widget(group) if group else Gtk.RadioButton()
        group = group or r; r.set_mode(False)
        for k in ("card", "cp-card"): r.get_style_context().add_class(k)
        inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        t = Gtk.Label(label=title, xalign=0); t.get_style_context().add_class("ctitle"); txt.pack_start(t, False, False, 0)
        d = Gtk.Label(label=desc, xalign=0, wrap=True); d.get_style_context().add_class("cdesc"); txt.pack_start(d, False, False, 0)
        inner.pack_start(txt, True, True, 0)
        if cid == "webmail": inner.pack_end(pills, False, False, 0)
        r.add(inner); r.set_active(cid == state["c"]); radios[cid] = r
        r.connect("toggled", lambda w, cid=cid: (state.__setitem__("c", cid), on_change and on_change()) if w.get_active() else None)
        box.pack_start(r, False, False, 0)
    return box, (lambda: (state["c"], state["p"]))

def run_apply_with_progress(parent, cid, provider, done):
    """GUI helper: password dialog (when needed), a progress window while installing, friendly error dialog. done(ok: bool) runs on the main loop."""
    import gi, threading, subprocess
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib
    c = choice(cid)
    pw = None
    if c[3] and not is_installed(cid) and os.geteuid() != 0 and subprocess.run(["doas", "-n", "true"], capture_output=True).returncode != 0:
        d = Gtk.Dialog(title="Administrator password", transient_for=parent, modal=True)
        box = d.get_content_area(); box.set_border_width(18); box.set_spacing(10)
        box.add(Gtk.Label(label="Adding %s needs your password. It is used once and never saved." % c[1], xalign=0, wrap=True))
        e = Gtk.Entry(visibility=False, activates_default=True); box.add(e)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL); ok = d.add_button("Continue", Gtk.ResponseType.OK); ok.get_style_context().add_class("suggested-action"); d.set_default_response(Gtk.ResponseType.OK)
        d.set_keep_above(True); d.set_position(Gtk.WindowPosition.CENTER_ON_PARENT); d.show_all(); d.present(); r = d.run(); pw = e.get_text(); d.destroy()
        if r != Gtk.ResponseType.OK: done(False); return
    if not (c[3] and not is_installed(cid)):
        try: apply(cid, provider)
        except RuntimeError: done(False); return
        done(True); return
    win = Gtk.Window(title="Adding %s" % c[1], transient_for=parent, modal=True, resizable=False); win.set_default_size(460, -1)
    v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12); v.set_border_width(24); win.add(v)
    h = Gtk.Label(label="Adding %s" % c[1], xalign=0); h.get_style_context().add_class("ctitle"); v.add(h)
    line = Gtk.Label(label="Starting...", xalign=0, ellipsize=3); line.get_style_context().add_class("cdesc"); v.add(line)
    bar = Gtk.ProgressBar(); v.add(bar)
    win.set_keep_above(True); win.set_position(Gtk.WindowPosition.CENTER_ON_PARENT); win.show_all(); win.present(); pulse = GLib.timeout_add(120, lambda: (bar.pulse(), True)[1])
    res = {}
    def on_line(l):
        l = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b[78]", "", l)
        m = re.findall(r"(\d{1,3})%", l)
        if m: GLib.idle_add(set_pct, min(int(m[-1]), 100) / 100.0)
        t = re.sub(r"[#]+|\s+", " ", re.sub(r"\d{1,3}%", "", l)).strip()
        if t: GLib.idle_add(line.set_text, t[:90])
    def set_pct(f):
        nonlocal pulse
        if pulse: GLib.source_remove(pulse); pulse = 0
        bar.set_fraction(f)
    def work():
        try: apply(cid, provider, on_line, pw)
        except RuntimeError as e: res["err"] = str(e)
        GLib.idle_add(finish)
    def finish():
        pulse and GLib.source_remove(pulse); win.destroy()
        if "err" in res:
            m = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.CLOSE, text="%s was not added" % c[1], secondary_text=res["err"] + "\n\nNothing was changed. You can try again later from Settings > Default Apps.")
            m.set_keep_above(True); m.run(); m.destroy(); done(False)
        else: done(True)
        return False
    threading.Thread(target=work, daemon=True).start()
