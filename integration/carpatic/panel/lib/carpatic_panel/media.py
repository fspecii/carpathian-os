"""Now Playing over MPRIS (Gio D-Bus, no extra dependencies). `Media.state()` -> dict or None; controls are fire-and-forget."""
import os
import gi
from gi.repository import Gio, GLib

MP = "org.mpris.MediaPlayer2.Player"


def parse_state(meta, status, position_us=0, identity=""):
    title = str(meta.get("xesam:title", "") or "")
    artists = meta.get("xesam:artist", [])
    artist = ", ".join(artists) if isinstance(artists, (list, tuple)) else str(artists or "")
    art = str(meta.get("mpris:artUrl", "") or "")
    length = int(meta.get("mpris:length", 0) or 0)
    return dict(title=title, artist=artist, album=str(meta.get("xesam:album", "") or ""), art=art[7:] if art.startswith("file://") else "",
                playing=status == "Playing", status=status, length=length / 1e6, position=position_us / 1e6, player=identity)


class Media:
    def __init__(self):
        try: self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error: self.bus = None

    def _call(self, name, path, iface, method, args=None, rt=None, timeout=800):
        return self.bus.call_sync(name, path, iface, method, args, GLib.VariantType.new(rt) if rt else None, Gio.DBusCallFlags.NONE, timeout, None)

    def players(self):
        if not self.bus: return []
        try:
            names = self._call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListNames", None, "(as)").unpack()[0]
        except GLib.Error: return []
        return [n for n in names if n.startswith("org.mpris.MediaPlayer2.")]

    def state(self):
        best = None
        for n in self.players():
            try:
                pr = self._call(n, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties", "GetAll", GLib.Variant("(s)", (MP,)), "(a{sv})").unpack()[0]
                ident = self._call(n, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties", "Get", GLib.Variant("(ss)", ("org.mpris.MediaPlayer2", "Identity")), "(v)").unpack()[0]
            except GLib.Error: continue
            st = parse_state(pr.get("Metadata", {}), pr.get("PlaybackStatus", "Stopped"), pr.get("Position", 0), ident)
            st["bus"] = n
            if not st["title"] and st["status"] == "Stopped": continue
            if best is None or (st["playing"] and not best["playing"]): best = st
        return best

    def control(self, bus, method):
        if not self.bus or not bus: return
        try: self.bus.call(bus, "/org/mpris/MediaPlayer2", MP, method, None, None, Gio.DBusCallFlags.NONE, 800, None, None, None)
        except GLib.Error: pass

    def play_pause(self, st): self.control(st.get("bus"), "PlayPause")
    def next(self, st): self.control(st.get("bus"), "Next")
    def prev(self, st): self.control(st.get("bus"), "Previous")


class FakeMedia:
    def __init__(self, st="demo"):
        self.st = dict(title="Dacia (Live at Sala Palatului)", artist="Subcarpați", album="Plai", art="", playing=True, status="Playing", length=244, position=96, player="Spotify", bus="x") if st == "demo" else st
        self.log = []
    def state(self): return dict(self.st) if self.st else None
    def play_pause(self, st): self.st["playing"] = not self.st["playing"]; self.log.append("pp")
    def next(self, st): self.log.append("next")
    def prev(self, st): self.log.append("prev")
