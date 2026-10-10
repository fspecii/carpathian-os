"""Window motion preferences, applied live through carpatic-animations."""
import json
from .. import sysutil as su
from ..app import Page
from ..ui import SwitchRow, PopupRow, ButtonRow, StatusRow

class AnimationsPage(Page):
    id = "animations"; title = "Animations"; icon = "preferences-desktop-effects"
    color = "#5e5ce6"; group = 2; order = 5
    aliases = ("motion", "effects")
    keywords = "animation movement minimise minimize maximise maximize snap opening closing windows macos speed reduce reduced motion transitions"
    sub = "Smooth window movement, at your own pace. Changes apply immediately."
    entries = (("Window animations", "enable effects movement", "enabled"),
               ("Style", "macos subtle", "style"), ("Speed", "fast slow duration", "speed"),
               ("Open windows", "launch apps opening", "open"), ("Close windows", "closing", "close"),
               ("Minimise and restore", "minimize dock shrink", "minimize"),
               ("Maximise and snap", "maximize tiling resizing", "geometry"),
               ("Switch workspaces", "desktops spaces", "workspaces"),
               ("Menus and popovers", "opening things popup", "menus"),
               ("Reduce motion", "accessibility movement reduced motion", "reduced"))

    def available(self): return su.which("carpatic-animations")
    def on_show(self): self.refresh()

    def state(self):
        try: return json.loads(su.out("carpatic-animations", "get", "--json"))
        except (ValueError, TypeError): return {}

    def change(self, key, value):
        if isinstance(value, bool): value = "on" if value else "off"
        self.win.apply("carpatic-animations", "set", key, value,
                       msg="Updating animations...", done=lambda rc, _out: self.refresh() if rc == 0 else None)

    def build(self, pb):
        self.rows = {}; state = self.state()
        general = pb.group("Window movement", "A gentle zoom when apps open, smooth resizing, and windows that shrink towards the dock.")
        self.rows["enabled"] = SwitchRow("Window animations", "", state.get("enabled", True),
                                           lambda v: self.change("enabled", v), key="enabled", setting="animations:enabled")
        general.add(self.rows["enabled"])
        self.status = StatusRow("Current mode", "", key="status"); general.add(self.status)
        self.effects = pb.group("Feel and pace")
        for key, label, values in (("style", "Style", [("macos", "macOS-inspired"), ("subtle", "Subtle")]),
                                   ("speed", "Speed", [("slow", "Relaxed"), ("normal", "Balanced"), ("fast", "Quick")])):
            row = PopupRow(label, "", values, state.get(key, "macos" if key == "style" else "normal"),
                           lambda v, k=key: self.change(k, v), key=key, setting=f"animations:{key}")
            self.rows[key] = row; self.effects.add(row)
        self.transitions = pb.group("Individual effects")
        for key, title in (("open", "Open windows"), ("close", "Close windows"),
                           ("minimize", "Minimise and restore"), ("geometry", "Maximise and snap"),
                           ("workspaces", "Switch workspaces"), ("menus", "Menus and popovers")):
            row = SwitchRow(title, "", state.get(key, True), lambda v, k=key: self.change(k, v),
                            key=key, setting=f"animations:{key}")
            self.rows[key] = row; self.transitions.add(row)
        accessibility = pb.group("Comfort")
        self.reduced = SwitchRow("Reduce motion", "Keep windows, login effects and the screensaver still.",
                                 state.get("reduced", False), self.reduce, key="reduced", setting="MOTION")
        accessibility.add(self.reduced)
        actions = pb.group()
        actions.add(ButtonRow("Try your settings", "A preview window maximises, minimises and comes back.",
                              "Preview", lambda: su.spawn("carpatic-animations", "preview"), key="preview"))
        actions.add(ButtonRow("Restore defaults", "Return to balanced macOS-inspired movement.", "Restore",
                              lambda: self.win.apply("carpatic-animations", "reset", done=lambda rc, _out: self.refresh() if rc == 0 else None), key="reset"))
        self.refresh()

    def reduce(self, enabled):
        self.win.apply("carpatic-set-motion", "reduced" if enabled else "full",
                       msg="Updating motion...", done=lambda rc, _out: self.refresh() if rc == 0 else None)

    def refresh(self):
        if not hasattr(self, "rows"): return
        state = self.state()
        for key, row in self.rows.items():
            if key in state: row.set_value_quiet(state[key])
        self.reduced.set_value_quiet(state.get("reduced", False))
        active = state.get("enabled", True) and not state.get("reduced", False)
        self.effects.set_sensitive(active); self.transitions.set_sensitive(active)
        self.status.set_value("Reduced motion" if state.get("reduced") else
                              "On" if state.get("running") else "Not running" if state.get("enabled") else "Off")
        self.status.set_state("ok" if state.get("running") and active else "off")

PAGES = [AnimationsPage]
