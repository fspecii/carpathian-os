"""Printers and scanners (CUPS)."""
import re
from .. import sysutil as su, ui
from ..app import Page
from ..ui import *

def parse_lpstat_printers(text):
    """lpstat -p -d -> ([{name, state, enabled, desc}], default)"""
    res = []; default = None
    for l in text.splitlines():
        m = re.match(r"^printer (\S+) (?:is )?(.*?)\.? (?:since|enabled|disabled).*$", l)
        m = re.match(r"^printer (\S+) (.*)$", l)
        if m:
            rest = m.group(2); st = "idle" if rest.startswith("is idle") or "idle" in rest[:12] else "printing" if "now printing" in rest else "disabled" if "disabled" in rest else "idle"
            res.append({"name": m.group(1), "state": st})
        m = re.match(r"^system default destination: (\S+)", l)
        if m: default = m.group(1)
    return res, default

class PrintersPage(Page):
    id = "printers"; title = "Printers & Scanners"; icon = "printer"; color = "#8e8e93"; group = 3
    aliases = ("printer", "scanners")
    keywords = "print cups scan scanner paper queue default printer ink"
    entries = (("Printers", "cups queue default printer print a test page", "printers"), ("Add a printer", "network usb discover", "add"))
    optional = frozenset({"add"})
    def available(self): return su.which("lpstat")
    def build(self, pb):
        self.pb = pb; self.g = pb.group("Printers", key="printers"); self.row_add = None
        self.tail = pb.group(); self.refresh()
    def on_show(self):
        if self.pb: self.refresh()
    def refresh(self):
        su.bg(lambda: (su.out("lpstat", "-r"), su.out("lpstat", "-p", "-d"), su.out("lpstat", "-v")), self.fill)
    def fill(self, res):
        if isinstance(res, Exception): return
        sched, pd, uris = res; self.g.clear(); self.tail.clear()
        if "not running" in sched or "scheduler" in sched and "is running" not in sched:
            self.g.add(StatusRow("Printing is turned off", "Off", "warn", "The print service is not running.", key="printers"))
            if su.which("rc-service"): self.tail.add(ButtonRow("Start printing", "Starts the print service now and at every start", "Start", lambda: self.win.apply(*su.pk("sh", "-c", "rc-update add cupsd default; rc-service cupsd start"), msg="Starting...", done=lambda *_: self.refresh()), "suggested", key="start"))
            return
        printers, default = parse_lpstat_printers(pd)
        if not printers: self.g.add(InfoRow("No printers yet", "", "Add one below. Most network printers are found automatically.", key="printers"))
        for p in printers:
            r = Row(p["name"].replace("_", " "), ("Default printer, " if p["name"] == default else "") + p["state"].title(), "printer", "#8e8e93", key="printer-" + p["name"])
            if p["name"] != default:
                b = Gtk.Button(label="Make default"); b.connect("clicked", lambda _b, n=p["name"]: self.win.apply("lpoptions", "-d", n, msg="Saving...", done=lambda *_: self.refresh())); r.ctl.pack_start(b, False, False, 0)
            b = Gtk.Button(label="Test page"); b.connect("clicked", lambda _b, n=p["name"]: su.spawn("sh", "-c", f"lp -d {n} /usr/share/cups/data/testprint 2>/dev/null || echo 'Printer test' | lp -d {n}")); r.ctl.pack_start(b, False, False, 0)
            b = Gtk.Button(label="Remove"); ui.cls(b, "destructive-action"); b.connect("clicked", lambda _b, n=p["name"]: self.remove(n)); r.ctl.pack_start(b, False, False, 0)
            self.g.add(r); r.show_all()
        if su.which("system-config-printer"): self.tail.add(ButtonRow("Add a printer", "Search the network and USB (starts the network discovery service for this session)", "Add...", lambda: self.win.apply(*su.pk("rc-service", "avahi-daemon", "start"), msg="Searching the network...", done=lambda *_: su.spawn("system-config-printer")), "suggested", key="add"))
        else: self.tail.add(ButtonRow("Add a printer", "Opens the printer manager in your browser", "Open", lambda: su.spawn("xdg-open", "http://localhost:631/admin"), "suggested", key="add"))
    def remove(self, n):
        if ui.confirm(self.win, f"Remove {n.replace('_', ' ')}?", "Jobs waiting for it are cancelled.", "Remove", True):
            self.win.apply(*su.pk("lpadmin", "-x", n), msg="Removing...", done=lambda *_: self.refresh())

from gi.repository import Gtk
PAGES = [PrintersPage]
