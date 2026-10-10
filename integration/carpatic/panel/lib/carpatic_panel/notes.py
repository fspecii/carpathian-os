"""Notification history from dunst (`dunstctl history`), grouped by app. No GTK; parsing is unit tested with captured JSON."""
import json, os, shutil, subprocess, time


class Note:
    __slots__ = ("id", "app", "summary", "body", "icon", "age", "urgency")

    def __init__(self, id, app, summary, body="", icon="", age=0.0, urgency="NORMAL"):
        self.id, self.app, self.summary, self.body, self.icon, self.age, self.urgency = id, app, summary, body, icon, age, urgency


def _v(x):
    return x.get("data") if isinstance(x, dict) else x


def parse_dunst_history(text, mono_now_us=None):
    try: js = json.loads(text)
    except ValueError: return []
    rows = js.get("data", [[]])[0] if isinstance(js, dict) else []
    now = mono_now_us if mono_now_us is not None else time.monotonic() * 1e6
    out = []
    for r in rows:
        try:
            ts = _v(r.get("timestamp", 0)) or 0
            age = max(0.0, (now - ts) / 1e6) if ts else 0.0
            out.append(Note(int(_v(r["id"])), str(_v(r.get("appname", "")) or "System"), str(_v(r.get("summary", "")) or ""), str(_v(r.get("body", "")) or ""),
                            str(_v(r.get("icon_path", "")) or _v(r.get("icon_name", "")) or ""), age, str(_v(r.get("urgency", "NORMAL")))))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def group_by_app(notes):
    groups = {}
    for n in notes: groups.setdefault(n.app, []).append(n)
    for g in groups.values(): g.sort(key=lambda n: n.age)
    return sorted(groups.items(), key=lambda kv: kv[1][0].age)


def age_text(sec):
    if sec < 45: return "now"
    if sec < 3600: return f"{int(sec // 60) or 1} min ago"
    if sec < 86400: return f"{int(sec // 3600)} h ago"
    return f"{int(sec // 86400)} d ago"


class Dunst:
    def history(self):
        if not shutil.which("dunstctl"): return []
        try: return parse_dunst_history(subprocess.run(["dunstctl", "history"], capture_output=True, text=True, timeout=3).stdout)
        except (OSError, subprocess.TimeoutExpired): return []

    def remove(self, id_):
        if shutil.which("dunstctl"): subprocess.run(["dunstctl", "history-rm", str(id_)], capture_output=True)

    def clear(self):
        if shutil.which("dunstctl"): subprocess.run(["dunstctl", "history-clear"], capture_output=True)

    def available(self): return shutil.which("dunstctl") is not None


class FakeNotes:
    def __init__(self, notes=None): self.notes = list(notes if notes is not None else DEMO)
    def history(self): return list(self.notes)
    def remove(self, id_): self.notes = [n for n in self.notes if n.id != id_]
    def clear(self): self.notes = []
    def available(self): return True


DEMO = [Note(1, "Messages", "Ana", "Are we still on for lunch at 13:00?", "", 120), Note(2, "Messages", "Mihai", "Sent you the photos from Bucegi", "", 900),
        Note(3, "Software Updates", "Updates are ready", "12 packages can be updated. Restart is not needed.", "", 4000),
        Note(4, "Firefox", "Download complete", "carpatic-0.9.iso (425 MB)", "", 7600)]
