"""Carpatic theme picker: row models, session state and the apply debouncer. Pure Python, no GTK, no timers of its own,
so every behaviour is unit-tested on the host (themepicker/tests/test-model.py).

A *state* is a plain dict of settings.conf keys (THEME, ACCENT, WALLPAPER, PROFILE, WINDOW_BUTTONS, ICON_THEME, CURSOR_THEME,
UI_FONT, UI_SIZE, MONO_FONT, BORDER_WIDTH, BORDER_ACTIVE, INNER_GAP, OUTER_GAP, CORNER_RADIUS). An empty value means "the theme / style default".
"""
import os, re, time
from tp_data import (ACCENT_SETS, WINDOW_BUTTONS, PROFILES, BORDER_COLORS, label_for, lum, default_for, theme_accent)

KEYS = ["THEME", "ACCENT", "WALLPAPER", "PROFILE", "WINDOW_BUTTONS", "ICON_THEME", "CURSOR_THEME", "UI_FONT", "UI_SIZE", "MONO_FONT",
        "BORDER_WIDTH", "BORDER_ACTIVE", "INNER_GAP", "OUTER_GAP", "CORNER_RADIUS"]
# the window-look keys carpatic-look can put on the desktop in ~30 ms (dwm reads them live from themes.toml); anything else needs carpatic-apply
LOOK_KEYS = ("BORDER_WIDTH", "BORDER_ACTIVE", "INNER_GAP", "OUTER_GAP", "CORNER_RADIUS")


# ---------------------------------------------------------------- settings.conf (same format as configurator/bin/carpatic-lib)
def read_settings(path):
    d = {}
    try:
        with open(path) as f:
            for line in f:
                m = re.match(r'^(\w+)="(.*)"$', line.rstrip("\n"))
                if m: d[m.group(1)] = re.sub(r'\\(["\\$`])', r'\1', m.group(2))
    except OSError:
        pass
    return d


def read_text(path):
    try:
        with open(path) as f: return f.read()
    except OSError:
        return None


def write_settings(path, changes):
    """Merge `changes` into settings.conf the way carpatic-lib's set_setting does (KEY="value", other keys untouched, atomic)."""
    old = read_text(path) or ""
    keep = [l for l in old.splitlines() if not re.match(r"^(%s)=" % "|".join(re.escape(k) for k in changes), l)]
    for k, v in changes.items():
        keep.append('%s="%s"' % (k, re.sub(r'(["\\$`])', r'\\\1', str(v).replace("\n", " ").replace("\r", " "))))
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = "%s.%d" % (path, os.getpid())
    with open(tmp, "w") as f: f.write("\n".join(keep) + "\n")
    os.replace(tmp, path)


def restore_settings(path, text):
    """Put back exactly what settings.conf held (or remove it when it did not exist)."""
    if text is None:
        try: os.remove(path)
        except OSError: pass
        return
    tmp = "%s.%d" % (path, os.getpid())
    with open(tmp, "w") as f: f.write(text)
    os.replace(tmp, path)


# ---------------------------------------------------------------- rows
class Option:
    __slots__ = ("value", "label", "meta")
    def __init__(self, value, label, meta=None):
        self.value, self.label, self.meta = value, label, meta or {}
    def __repr__(self): return "Option(%r, %r)" % (self.value, self.label)


class Row:
    """One line of the picker. `options(state)` returns the Left/Right values, `current(state)` the index of the one in use,
    `changes(state, option)` what to write into the state when it is chosen. `commit` rows apply only on Enter.
    `dflt(state)` is the value the row has when the state says "" (default); `value(state)` overrides how the current value is read."""
    def __init__(self, rid, label, hint, options, keys, changes=None, commit=False, dflt=None, value=None, marks=True):
        self._value = value; self.marks = marks      # marks: the row shows a dot when it overrides the default (not for theme / light-dark / style)
        self.id, self.label, self.hint, self._options, self.keys, self.commit, self.dflt = rid, label, hint, options, keys, commit, dflt
        self._changes = changes

    def options(self, state): return self._options(state)

    def current(self, state):
        opts = self.options(state)
        val = self._value(state) if self._value else state.get(self.keys[0], "")
        for i, o in enumerate(opts):
            if o.value == val: return i
        # empty value means "default": show the option that equals the default if there is one
        if val == "" and self.dflt:
            dv = self.dflt(state)
            for i, o in enumerate(opts):
                if o.value == dv: return i
        return -1

    def changes(self, state, opt):
        return self._changes(state, opt) if self._changes else {self.keys[0]: opt.value}

    def at_default(self, state):
        if self._value: return True
        return all(state.get(k, "") == "" for k in self.keys)

    def reset_changes(self, state):
        if self.id == "theme": return {}
        return {k: "" for k in self.keys}


def _num_options(values, suffix=" px", zero=None):
    def f(state):
        return [Option(str(v), (zero if (v == 0 and zero) else "%d%s" % (v, suffix))) for v in values]
    return f


GAP_PRESETS = [("0:0", "None"), ("4:4", "Tight"), ("8:8", "Normal"), ("10:12", "Cosy"), ("16:16", "Roomy"), ("24:24", "Zen")]


def build_rows(cat):
    """The rows in display order. `cat` is a tp_data.Catalog (or a stand-in with the same methods)."""
    D = lambda key: (lambda state: default_for(cat, state, key))

    def themes(state):
        return [Option(n, label_for(n), {"mode": cat.mode(n)}) for n in cat.theme_names()]

    def theme_changes(state, opt):  # a new theme brings its own wallpaper and accent: the old overrides would mask it
        return {"THEME": opt.value, "ACCENT": "", "WALLPAPER": "", "BORDER_ACTIVE": ""}   # the theme's look file is read by carpatic-apply itself

    def mode_opts(state):
        return [Option("dark", "Dark"), Option("light", "Light")]

    def mode_changes(state, opt):
        cur = state.get("THEME") or "carpatic"
        n = cat.counterpart(cur, opt.value)
        return {"THEME": n, "ACCENT": "", "WALLPAPER": "", "BORDER_ACTIVE": ""} if n != cur else {}

    def walls(state):
        t = state.get("THEME") or "carpatic"
        return [Option("", "Theme wallpaper", {"path": cat.default_wallpaper(t)})] + [Option(p, l, {"path": p}) for p, l in cat.wallpapers(t)]

    def accents(state):
        t = state.get("THEME") or "carpatic"
        c = cat.colors(t); mode = c.get("mode", "dark")
        base = theme_accent(cat, dict(state, ACCENT=""))
        out = [Option("", "Theme colour", {"color": base})]
        seen = {base.lower()}
        for name, dk, lt in ACCENT_SETS:
            v = dk if mode == "dark" else lt
            if v.lower() in seen: continue
            seen.add(v.lower()); out.append(Option(v, name, {"color": v}))
        for k in ("red", "orange", "yellow", "green", "cyan", "blue", "magenta"):
            v = c.get(k)
            if v and v.lower() not in seen:
                seen.add(v.lower()); out.append(Option(v, k.capitalize(), {"color": v}))
        cur = (state.get("ACCENT") or "").lower()
        if cur and cur not in seen:
            out.append(Option(state["ACCENT"], "Custom " + state["ACCENT"].upper(), {"color": state["ACCENT"], "custom": True}))
        return out

    def border_colors(state):
        t = state.get("THEME") or "carpatic"; c = cat.colors(t)
        acc = theme_accent(cat, state)
        out = [Option("", "Accent", {"color": acc})]; seen = {acc.lower()}
        for k, l in BORDER_COLORS:
            v = c.get(k)
            if v and v.lower() not in seen: seen.add(v.lower()); out.append(Option(v, l, {"color": v}))
        cur = (state.get("BORDER_ACTIVE") or "").lower()
        if cur and cur not in seen: out.append(Option(state["BORDER_ACTIVE"], "Custom " + state["BORDER_ACTIVE"].upper(), {"color": state["BORDER_ACTIVE"]}))
        return out

    def nums(values, suffix=" px", zero=None):
        return lambda state: [Option(str(v), (zero if (v == 0 and zero) else "%d%s" % (v, suffix))) for v in values]

    def gap_opts(state):
        out = [Option(v, l) for v, l in GAP_PRESETS]
        cur = gap_value(state)
        if cur not in [o.value for o in out]:
            i, o = cur.split(":"); out.append(Option(cur, "Custom %s/%s px" % (i, o)))
        return out

    def gap_value(state):
        i = state.get("INNER_GAP") or default_for(cat, state, "INNER_GAP"); o = state.get("OUTER_GAP") or default_for(cat, state, "OUTER_GAP")
        return "%s:%s" % (i, o)

    def gap_changes(state, opt):
        i, o = opt.value.split(":"); return {"INNER_GAP": i, "OUTER_GAP": o}

    def with_default(items, key, what="Desktop style default"):
        def f(state):
            d = default_for(cat, state, key)
            return [Option("", "Default (%s)" % d if d else what)] + [Option(v, v) for v in items()]
        return f

    def buttons(state):
        d = dict(WINDOW_BUTTONS).get(default_for(cat, state, "WINDOW_BUTTONS"), "")
        return [Option("", "Default (%s)" % d if d else "Desktop style default")] + [Option(v, l) for v, l in WINDOW_BUTTONS]

    def sizes(state):
        return [Option(str(n), "%d pt" % n) for n in range(8, 16)]

    return [
        Row("theme", "Theme", "Left and right switch the whole desktop", themes, ["THEME"], theme_changes, marks=False),
        Row("mode", "Light or dark", "Picks the matching light or dark theme", mode_opts, ["THEME"], mode_changes,
            value=lambda st: cat.mode(st.get("THEME") or "carpatic"), marks=False),
        Row("wallpaper", "Wallpaper", "The theme's pictures, Carpathian scenes and your own", walls, ["WALLPAPER"]),
        Row("accent", "Accent colour", "Press # to type your own", accents, ["ACCENT"]),
        Row("border", "Window border", "Width of the line around windows", nums([0, 1, 2, 3, 4, 6, 8], zero="None"), ["BORDER_WIDTH"], dflt=D("BORDER_WIDTH")),
        Row("bordercolor", "Border colour", "Colour of the focused window's border", border_colors, ["BORDER_ACTIVE"]),
        Row("corners", "Corners", "Rounded window corners", nums([0, 4, 8, 10, 14, 18], zero="Square"), ["CORNER_RADIUS"], dflt=D("CORNER_RADIUS")),
        Row("gaps", "Gaps", "Space between and around tiled windows", gap_opts, ["INNER_GAP", "OUTER_GAP"], gap_changes, value=gap_value),
        Row("buttons", "Window buttons", "Close, minimise and maximise", buttons, ["WINDOW_BUTTONS"]),
        Row("icons", "Icons", "Icon pack for apps and folders", with_default(cat.icon_themes, "ICON_THEME"), ["ICON_THEME"]),
        Row("cursor", "Cursor", "Mouse pointer theme", with_default(cat.cursor_themes, "CURSOR_THEME"), ["CURSOR_THEME"]),
        Row("font", "Font", "Interface font", with_default(cat.ui_fonts, "UI_FONT"), ["UI_FONT"]),
        Row("fontsize", "Font size", "Interface text size", sizes, ["UI_SIZE"], dflt=D("UI_SIZE")),
        Row("mono", "Code font", "Terminal and editor font", with_default(cat.mono_fonts, "MONO_FONT"), ["MONO_FONT"]),
        Row("style", "Desktop style", "Bars and shortcuts. Applies on Enter",
            lambda s: [Option(v, l) for v, l in PROFILES], ["PROFILE"],
            lambda st, o: {"PROFILE": o.value, "WINDOW_BUTTONS": ""}, commit=True, marks=False),
    ]


# ---------------------------------------------------------------- session
def valid_hex(s):
    return bool(re.fullmatch(r"#[0-9a-fA-F]{6}", s or ""))


class Session:
    """What the user is doing right now: the snapshot taken when the picker opened, the candidate state, which row has focus."""
    def __init__(self, cat, snapshot, rows=None):
        self.cat = cat
        self.rows = rows or build_rows(cat)
        snapshot = dict(snapshot)
        snapshot.setdefault("THEME", "carpatic"); snapshot.setdefault("PROFILE", "tiling")    # what carpatic-apply assumes when settings.conf says nothing
        self.snapshot = snapshot                 # settings as they were: Esc goes back to this
        self.state = dict(snapshot)
        self.focus = 0
        self.filter = ""
        self.hex_entry = None                    # None, or the text typed so far while choosing a custom accent
        self.save_entry = None                   # None, or the name typed so far in "Save as my theme"
        self.revision = 0                        # bumped by every change that needs an apply

    @property
    def row(self): return self.rows[self.focus]

    def visible_options(self, row=None):
        """[(index in row options, Option)] that match the type-to-filter text."""
        row = row or self.row
        opts = row.options(self.state)
        f = self.filter.lower().strip()
        return [(i, o) for i, o in enumerate(opts) if not f or f in o.label.lower() or f in str(o.value).lower()]

    def move_row(self, d):
        self.hex_entry = None; self.filter = ""
        self.focus = (self.focus + d) % len(self.rows)

    def goto_row(self, i):
        self.hex_entry = None; self.filter = ""
        self.focus = max(0, min(len(self.rows) - 1, i))

    def _apply_changes(self, ch):
        ch = {k: v for k, v in ch.items() if self.state.get(k, "") != v}
        if not ch: return False
        self.state.update(ch); self.revision += 1
        return True

    def change(self, d):
        """Left/Right: next or previous option of the focused row (wraps, skips what the filter hides). True when the state changed."""
        row = self.row
        vis = self.visible_options(row)
        if not vis: return False
        cur = row.current(self.state)
        pos = -1
        for n, (i, _) in enumerate(vis):
            if i == cur: pos = n
        if pos < 0:
            pos = 0 if d > 0 else len(vis) - 1
            # nothing matches the current value (e.g. a hidden default): start from the first/last visible
        else:
            pos = (pos + d) % len(vis)
        opt = vis[pos][1]
        return self._apply_changes(row.changes(self.state, opt))

    def choose(self, row_index, opt_index):
        """Mouse/touch: pick one option of a row directly."""
        self.goto_row(row_index)
        opts = self.row.options(self.state)
        if not 0 <= opt_index < len(opts): return False
        return self._apply_changes(self.row.changes(self.state, opts[opt_index]))

    def reset_row(self):
        row = self.row
        ch = row.reset_changes(self.state)
        if row.id == "theme":
            ch = {k: self.snapshot.get(k, "") for k in ("THEME", "ACCENT", "WALLPAPER", "BORDER_ACTIVE")}
        if row.id == "mode": return False
        return self._apply_changes(ch)

    def reset_all(self):
        return self._apply_changes({k: self.snapshot.get(k, "") for k in KEYS})

    # custom accent
    def begin_hex(self):
        if self.row.id == "accent":
            self.hex_entry = "#"
            return True
        return False

    def hex_type(self, ch):
        if self.hex_entry is None: return
        if ch == "\b":
            self.hex_entry = self.hex_entry[:-1] or "#"
        elif re.fullmatch(r"[0-9a-fA-F]", ch) and len(self.hex_entry) < 7:
            self.hex_entry += ch.lower()
        # live preview as soon as 6 digits are typed
        if valid_hex(self.hex_entry): self._apply_changes({"ACCENT": self.hex_entry})

    def hex_done(self, accept):
        e = self.hex_entry; self.hex_entry = None
        if accept and valid_hex(e): return self._apply_changes({"ACCENT": e})
        if not accept:
            return self._apply_changes({"ACCENT": self.snapshot.get("ACCENT", "")})
        return False

    # save as my theme
    def begin_save(self):
        self.hex_entry = None; self.save_entry = ""
        return True

    def save_type(self, ch):
        if self.save_entry is None: return
        if ch == "\b": self.save_entry = self.save_entry[:-1]
        elif ch.isprintable() and len(self.save_entry) < 32: self.save_entry += ch

    def save_cancel(self): self.save_entry = None

    def save_commit(self):
        """The typed name (or None when empty); the caller writes the theme and then calls adopt_saved()."""
        n = (self.save_entry or "").strip(); self.save_entry = None
        return n or None

    def adopt_saved(self, slug):
        """After the theme was written the picker is *on* it: accent and wallpaper are now part of the theme itself."""
        self._apply_changes({"THEME": slug, "ACCENT": "", "WALLPAPER": "", "BORDER_ACTIVE": ""})

    def entering(self): return self.hex_entry is not None or self.save_entry is not None

    def type_filter(self, ch):
        if ch == "\b": self.filter = self.filter[:-1]
        else: self.filter += ch
        # keep the focused value where it is; Left/Right now walk the matches

    def dirty(self):
        return any(self.state.get(k, "") != self.snapshot.get(k, "") for k in KEYS)

    def changed_keys(self):
        return [k for k in KEYS if self.state.get(k, "") != self.snapshot.get(k, "")]

    def live_state(self):
        """What goes to the real desktop while browsing: everything except the commit-on-Enter rows (desktop style)."""
        s = dict(self.state); s["PROFILE"] = self.snapshot.get("PROFILE", s.get("PROFILE", ""))
        return s

    # effective values for drawing the mock (empty = default)
    def eff(self, key):
        v = self.state.get(key, "")
        return v if v != "" else default_for(self.cat, self.state, key)


# ---------------------------------------------------------------- apply debouncer
class Applier:
    """Debounce + coalesce: request() may be called 60 times a second by a held arrow key. The real work (`run`) starts once the keys
    have been quiet for `delay` seconds, never runs twice at once, and while it runs only the newest request is remembered.

    run(job, done) starts the work and calls done() when finished (any thread/callback).  schedule(delay, fn) -> handle, cancel(handle) are
    injected (GLib timeouts in the app, a fake clock in the tests).  clock() -> float seconds, used for the statistics."""
    def __init__(self, run, schedule, cancel, delay=0.15, clock=time.monotonic, abort=None):
        self.run, self.schedule, self.cancel, self.delay, self.clock = run, schedule, cancel, delay, clock
        self.abort = abort       # abort(job) stops the running job early (it must still call done()); only used for superseded live jobs
        self.current = None
        self.timer = None; self.running = False
        self.latest = None; self.dirty = False
        self.aborting = False
        self.stats = []          # (requested_at, started_at, finished_at, coalesced_count)
        self._req_t = None; self._count = 0; self._t0 = None
        self.on_idle = []        # callbacks run once nothing is pending or running

    def busy(self): return self.running or self.timer is not None or self.dirty

    def request(self, job, immediate=False):
        """Ask for `job` to be applied. Replaces any job that has not started yet."""
        self.latest = job; self.dirty = True; self._count += 1
        if self._req_t is None: self._req_t = self.clock()
        if self.timer is not None:
            self.cancel(self.timer); self.timer = None
        if immediate:
            self._fire()
        else:
            self.timer = self.schedule(self.delay, self._fire)

    def drop(self):
        """Forget everything not started yet (used when the picker closes without keeping anything)."""
        if self.timer is not None: self.cancel(self.timer); self.timer = None
        self.latest = None; self.dirty = False; self._req_t = None; self._count = 0

    def _fire(self):
        self.timer = None
        if self.running:
            # a newer request is due while an older apply still runs: stop the old one, its result is already out of date
            if self.dirty and self.abort and self.current is not None and not self.aborting: self.aborting = True; self.abort(self.current)
            return
        if not self.dirty: return
        job, self.latest, self.dirty = self.latest, None, False
        n, self._count = self._count, 0
        req_t, self._req_t = self._req_t, None
        self.running = True; started = self.clock(); self.current = job; self.aborting = False

        def done():
            self.running = False; self.current = None; self.aborting = False
            self.stats.append((req_t, started, self.clock(), n))
            if self.dirty and self.timer is None:
                self._fire()          # a newer request arrived while we worked and its timer already fired (or none was set)
            elif not self.busy():
                cbs, self.on_idle = self.on_idle, []
                for cb in cbs: cb()
        self.run(job, done)

    def when_idle(self, cb):
        if self.busy(): self.on_idle.append(cb)
        else: cb()
