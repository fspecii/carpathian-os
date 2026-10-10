"""Wi-Fi (NetworkManager via nmcli), Bluetooth (bluez via bluetoothctl) and Network (interfaces, VPN)."""
import os, re, glob, json
from gi.repository import Gtk, GLib
from .. import sysutil as su, ui
from ..app import Page
from ..ui import *

def split_t(line):
    """split an nmcli -t line on unescaped colons"""
    out = []; cur = ""; esc = False
    for ch in line:
        if esc: cur += ch; esc = False
        elif ch == "\\": esc = True
        elif ch == ":": out.append(cur); cur = ""
        else: cur += ch
    out.append(cur); return out

def parse_wifi_list(text):
    """nmcli -t -f IN-USE,SSID,SIGNAL,SECURITY dev wifi list -> unique networks, strongest first, connected first"""
    nets = {}
    for l in text.splitlines():
        f = split_t(l)
        if len(f) < 4 or not f[1]: continue
        use, ssid, sig, sec = f[0] == "*", f[1], int(f[2] or 0), f[3]
        n = nets.get(ssid)
        if n is None or sig > n["signal"] or use: nets[ssid] = {"ssid": ssid, "signal": max(sig, n["signal"] if n else 0), "secure": sec not in ("", "--"), "active": use or (n["active"] if n else False), "security": sec}
    return sorted(nets.values(), key=lambda n: (not n["active"], -n["signal"], n["ssid"].lower()))

def signal_icon(s):
    return "network-wireless-signal-excellent-symbolic" if s >= 75 else "network-wireless-signal-good-symbolic" if s >= 50 else "network-wireless-signal-ok-symbolic" if s >= 25 else "network-wireless-signal-weak-symbolic"

def has_wifi_hw():
    if os.environ.get("CSET_FAKE_HW"): return True
    return bool(glob.glob("/sys/class/net/*/wireless") or glob.glob("/sys/class/net/*/phy80211"))

class WifiPage(Page):
    id = "wifi"; title = "Wi-Fi"; icon = "network-wireless"; color = "#0a84ff"; group = 0
    keywords = "wifi wireless network internet connect password ssid hotspot"
    entries = (("Wi-Fi", "wifi wireless on off airplane", "wifi-switch"), ("Networks", "available ssid connect join known saved forget remembered", "nets"))
    def available(self): return su.which("nmcli") and has_wifi_hw()
    def build(self, pb):
        self.pb = pb; self.nets_rows = []
        g = pb.group()
        on = su.out("nmcli", "radio", "wifi") == "enabled"
        self.sw = SwitchRow("Wi-Fi", "", on, self.toggle, icon="network-wireless", color="#0a84ff", key="wifi-switch"); g.add(self.sw)
        self.nets = pb.group("Networks", None); self.nets.page = pb
        self.known = pb.group("Known networks", "Networks your computer remembers. Forgetting one means you will need the password again.")
        self.scan_row = ButtonRow("Looking for networks", "", "Scan again", self.scan, key="nets"); self.nets.add(self.scan_row)
        self.known.hide(); self.known.set_no_show_all(True)
        self.scan()
    def on_show(self):
        if self.pb: self.scan()
    def toggle(self, v):
        self.win.apply("nmcli", "radio", "wifi", "on" if v else "off", msg="Turning Wi-Fi " + ("on" if v else "off") + "...", done=lambda *_: GLib.timeout_add(1500, lambda: (self.scan(), False)[1]))
    def scan(self):
        self.scan_row.set_busy(True)
        def work():
            return (su.out("nmcli", "radio", "wifi") == "enabled", su.out("nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list", "--rescan", "auto", timeout=25),
                    su.lines("nmcli", "-t", "-f", "NAME,TYPE", "con", "show"))
        su.bg(work, self.fill)
    def fill(self, res):
        self.scan_row.set_busy(False)
        if isinstance(res, Exception): return
        enabled, text, cons = res
        self.sw.set_value_quiet(enabled); self.nets.set_sensitive(enabled)
        for r in self.nets_rows: self.nets.list.remove(r); self.nets.rows.remove(r)
        self.nets_rows = []
        saved = [split_t(c)[0] for c in cons if len(split_t(c)) > 1 and split_t(c)[1] in ("802-11-wireless", "wifi")]
        if not enabled:
            self.scan_row.set_title("Wi-Fi is off"); self.scan_row.set_sub("Turn it on to see networks nearby."); self.scan_row.buttons[0].hide(); return
        self.scan_row.buttons[0].show()
        nets = parse_wifi_list(text)
        self.scan_row.set_title("Networks nearby" if nets else "No networks found"); self.scan_row.set_sub("" if nets else "Move closer to your router, then scan again.")
        for n in nets:
            r = Row(n["ssid"], "Connected" if n["active"] else ("Saved" if n["ssid"] in saved else ("Password needed" if n["secure"] else "Open network")), n["signal"] and signal_icon(n["signal"]).replace("-symbolic", ""), "#0a84ff" if n["active"] else "#8e8e93", key="net-" + n["ssid"], activatable=True)
            if n["secure"]: r.ctl.pack_start(Gtk.Image.new_from_icon_name("changes-prevent-symbolic", Gtk.IconSize.BUTTON), False, False, 0)
            if n["active"]:
                b = Gtk.Button(label="Disconnect"); b.connect("clicked", lambda *_: self.win.apply("nmcli", "dev", "disconnect", self.wifi_dev(), msg="Disconnecting...", done=lambda *_: self.scan())); r.ctl.pack_start(b, False, False, 0)
            r.connect("activate", lambda _r, n=n, sv=saved: None if n["active"] else self.connect(n, n["ssid"] in sv))
            self.nets.add(r); self.nets_rows.append(r); r.show_all()
        self.known.clear()
        if saved:
            for name in saved:
                r = ButtonRow(name, "", "Forget", None, "destructive", key="known-" + name); r.buttons[0].connect("clicked", lambda b, nm=name: self.forget(nm)); self.known.add(r)
            self.known.set_no_show_all(False); self.known.show_all()
    def wifi_dev(self):
        for l in su.lines("nmcli", "-t", "-f", "DEVICE,TYPE", "dev"):
            f = split_t(l)
            if len(f) > 1 and f[1] == "wifi": return f[0]
        return ""
    def connect(self, n, saved):
        pw = None
        if n["secure"] and not saved:
            r = ui.ask_text(self.win, f"Join “{n['ssid']}”", "Type the Wi-Fi password.", "Password", True, "Join")
            if r is None: return
            pw = r[0]
        cmd = ["nmcli", "dev", "wifi", "connect", n["ssid"]] + (["--ask"] if pw else [])
        self.win.busy(f"Joining {n['ssid']}...")
        def work():
            rc, out = su.run_sync(*cmd, timeout=45, stdin=(pw + "\n") if pw else None); return rc, out
        def done(res):
            rc, out = res if not isinstance(res, Exception) else (1, "")
            self.win.idle("Connected." if rc == 0 else "Could not join that network. Check the password and try again.")
            self.scan()
        su.bg(work, done)
    def forget(self, name):
        if ui.confirm(self.win, f"Forget “{name}”?", "You will need the password to join it again.", "Forget", True):
            self.win.apply("nmcli", "con", "delete", name, msg="Forgetting...", done=lambda *_: self.scan())

# ---------------------------------------------------------------- Bluetooth
def parse_bt_info(text):
    d = {}
    for l in text.splitlines():
        if ":" in l:
            k, v = l.strip().split(":", 1); d[k.strip()] = v.strip()
    return d

class BluetoothPage(Page):
    id = "bluetooth"; title = "Bluetooth"; icon = "bluetooth"; color = "#0a84ff"; group = 0
    keywords = "wireless pair headphones speaker mouse keyboard devices"
    entries = (("Bluetooth", "on off wireless", "bt-switch"), ("My devices", "paired connect headphones speaker", "bt-devices"), ("Find new devices", "pair scan discoverable", "bt-scan"))
    def available(self): return su.which("bluetoothctl") and (bool(os.environ.get("CSET_FAKE_HW")) or bool(glob.glob("/sys/class/bluetooth/hci*")))
    def build(self, pb):
        self.pb = pb; self.rows = []
        g = pb.group(None, "This computer can be found as “" + (__import__("cset.pages.about_data", fromlist=["x"]).hostname() or "this computer") + "” while Bluetooth settings are open.")
        powered = parse_bt_info(su.out("bluetoothctl", "show")).get("Powered") == "yes"
        self.sw = SwitchRow("Bluetooth", "", powered, lambda v: self.win.apply("bluetoothctl", "power", "on" if v else "off", msg="Turning Bluetooth " + ("on" if v else "off") + "...", done=lambda *_: self.refresh()), icon="bluetooth", color="#0a84ff", key="bt-switch"); g.add(self.sw)
        self.dev = pb.group("My devices")
        self.empty = InfoRow("No devices paired yet", "", key="bt-devices"); self.dev.add(self.empty)
        self.find = pb.group("Nearby devices")
        self.find_row = ButtonRow("Find new devices", "Put the device in pairing mode first", "Scan", self.scan, key="bt-scan"); self.find.add(self.find_row)
        self.nearby = []
        self.refresh()
    def on_show(self):
        if self.pb: self.refresh()
    def refresh(self):
        def work():
            powered = parse_bt_info(su.out("bluetoothctl", "show")).get("Powered") == "yes"; devs = []
            for l in su.lines("bluetoothctl", "devices"):
                p = l.split(" ", 2)
                if len(p) == 3 and p[0] == "Device": devs.append((p[1], p[2], parse_bt_info(su.out("bluetoothctl", "info", p[1]))))
            return powered, devs
        su.bg(work, self.fill)
    ICONS = {"audio-headphones": "audio-headphones", "audio-headset": "audio-headset", "audio-card": "audio-speakers", "input-keyboard": "input-keyboard", "input-mouse": "input-mouse", "input-gaming": "input-gaming", "phone": "phone"}
    def fill(self, res):
        if isinstance(res, Exception): return
        powered, devs = res; self.sw.set_value_quiet(powered)
        for r in self.rows: self.dev.list.remove(r); self.dev.rows.remove(r)
        self.rows = []; self.dev.set_sensitive(powered); self.find.set_sensitive(powered)
        paired = [d for d in devs if d[2].get("Paired") == "yes"]
        self.empty.set_visible(not paired); self.empty.set_no_show_all(bool(paired))
        for mac, name, info in sorted(paired, key=lambda d: (d[2].get("Connected") != "yes", d[1].lower())):
            con = info.get("Connected") == "yes"
            r = ButtonRow(name, "Connected" if con else "Not connected", "", None, icon=self.ICONS.get(info.get("Icon", ""), "bluetooth"), color="#0a84ff" if con else "#8e8e93", key="dev-" + mac)
            r.buttons[0].set_label("Disconnect" if con else "Connect")
            r.buttons[0].connect("clicked", lambda b, mac=mac, con=con: self.win.apply("bluetoothctl", "disconnect" if con else "connect", mac, msg="Working...", done=lambda *_: self.refresh()))
            r.add_button("Forget", lambda mac=mac, name=name: self.forget(mac, name), "destructive")
            self.dev.add(r); self.rows.append(r); r.show_all()
    def forget(self, mac, name):
        if ui.confirm(self.win, f"Forget “{name}”?", "You will need to pair it again.", "Forget", True):
            self.win.apply("bluetoothctl", "remove", mac, msg="Removing...", done=lambda *_: self.refresh())
    def scan(self):
        self.find_row.set_busy(True)
        def work():
            su.run_sync("bluetoothctl", "--timeout", "8", "scan", "on", timeout=15)
            known = {l.split(" ", 2)[1] for l in su.lines("bluetoothctl", "paired-devices") if l.count(" ") >= 2}
            return [(l.split(" ", 2)[1], l.split(" ", 2)[2]) for l in su.lines("bluetoothctl", "devices") if l.count(" ") >= 2 and l.split(" ", 2)[1] not in known and not re.fullmatch(r"[0-9A-F]{2}(-[0-9A-F]{2}){5}", l.split(" ", 2)[2])]
        def done(res):
            self.find_row.set_busy(False)
            for r in self.nearby: self.find.list.remove(r); self.find.rows.remove(r)
            self.nearby = []
            if isinstance(res, Exception): return
            for mac, name in res:
                r = ButtonRow(name, "Ready to pair", "Pair", None, "suggested", icon="bluetooth", color="#8e8e93", key="near-" + mac)
                r.buttons[0].connect("clicked", lambda b, mac=mac: self.win.apply("sh", "-c", f"bluetoothctl pair {mac} && bluetoothctl trust {mac} && bluetoothctl connect {mac}", msg="Pairing...", done=lambda *_: self.refresh()))
                self.find.add(r); self.nearby.append(r); r.show_all()
            self.find_row.set_sub("" if res else "Nothing new found. Put the device in pairing mode and scan again.")
        su.bg(work, done)

# ---------------------------------------------------------------- Network
def parse_ip_addr(text):
    """ip -j addr -> [{name, state, mac, addrs[]}] without loopback"""
    try: data = json.loads(text)
    except ValueError: return []
    res = []
    for i in data:
        if i.get("ifname") == "lo": continue
        res.append({"name": i["ifname"], "state": i.get("operstate", "UNKNOWN").lower(), "mac": i.get("address", ""), "addrs": [a["local"] for a in i.get("addr_info", []) if a.get("family") == "inet"], "addrs6": [a["local"] for a in i.get("addr_info", []) if a.get("family") == "inet6" and a.get("scope") == "global"]})
    return res

def kind_of(name):
    if name.startswith(("wl", "wlan")): return "Wi-Fi"
    if name.startswith(("en", "eth")): return "Ethernet"
    if name.startswith(("tun", "tap", "wg", "ppp")): return "VPN"
    if name.startswith(("docker", "br", "veth", "virbr")): return "Virtual"
    return "Other"

class NetworkPage(Page):
    id = "network"; title = "Network"; icon = "network-workgroup"; color = "#0a84ff"; group = 0
    keywords = "ethernet ip address dns gateway vpn proxy internet lan connection"
    entries = (("Connections", "ethernet interfaces status ip address ipv4 ipv6 vpn wireguard openvpn tunnel", "ifaces"), ("DNS servers", "resolver nameserver", "dns"))
    def available(self): return True
    def build(self, pb):
        self.pb = pb; self.g = pb.group("Connections", key="ifaces"); self.vpn = pb.group("VPN"); self.vpn.hide(); self.vpn.set_no_show_all(True)
        self.info = pb.group("This computer")
        self.info.add(InfoRow("Computer name", __import__("cset.pages.about_data", fromlist=["x"]).hostname(), key="host"))
        dns = [l.split()[1] for l in (su.read_file("/etc/resolv.conf") or "").splitlines() if l.startswith("nameserver")]
        self.dns = InfoRow("DNS servers", ", ".join(dns) or "Automatic", key="dns"); self.info.add(self.dns)
        self.refresh()
    def on_show(self):
        if self.pb: self.refresh()
    def refresh(self):
        su.bg(lambda: (su.out("ip", "-j", "addr"), su.out("ip", "-j", "route") if False else su.out("ip", "route"), su.lines("nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "con", "show") if su.which("nmcli") else []), self.fill)
    def fill(self, res):
        if isinstance(res, Exception): return
        ipj, route, cons = res; ifs = parse_ip_addr(ipj)
        gw = re.search(r"default via (\S+)", route or ""); gwv = gw.group(1) if gw else ""
        self.g.clear()
        shown = [i for i in ifs if kind_of(i["name"]) in ("Wi-Fi", "Ethernet", "Other") or i["addrs"]]
        shown = [i for i in shown if kind_of(i["name"]) != "Virtual"]
        if not shown: self.g.add(InfoRow("No connections", "", key="ifaces"))
        for i in shown:
            up = i["state"] == "up" or bool(i["addrs"])
            r = NavRow(kind_of(i["name"]) if kind_of(i["name"]) != "Other" else i["name"], (", ".join(i["addrs"]) if i["addrs"] else ("Not connected" if kind_of(i["name"]) != "Wi-Fi" else "Not connected")), "network-wired" if kind_of(i["name"]) == "Ethernet" else "network-wireless", "#34c759" if up else "#8e8e93",
                       "Connected" if up else "Off", lambda i=i: self.push(i["name"], lambda pb: self.detail(pb, i, gwv)), key="if-" + i["name"])
            self.g.add(r); r.show_all()
        vp = [split_t(c) for c in cons]; vp = [c for c in vp if len(c) > 2 and c[1] in ("vpn", "wireguard")]
        self.vpn.clear()
        if vp:
            for name, typ, dev in vp:
                s = SwitchRow(name, "VPN (" + typ + ")", bool(dev), lambda v, name=name: self.win.apply("nmcli", "con", "up" if v else "down", name, msg="Working...", done=lambda *_: self.refresh()), key="vpn-" + name); self.vpn.add(s); s.show_all()
            self.vpn.set_no_show_all(False); self.vpn.show_all()
    def detail(self, pb, i, gw):
        g = pb.group(kind_of(i["name"]) if kind_of(i["name"]) != "Other" else i["name"])
        g.add(InfoRow("Status", "Connected" if i["addrs"] else "Not connected"), InfoRow("Device", i["name"]))
        for a in i["addrs"]: g.add(InfoRow("IPv4 address", a))
        for a in i["addrs6"][:2]: g.add(InfoRow("IPv6 address", a))
        if gw and i["addrs"]: g.add(InfoRow("Router", gw))
        if i["mac"]: g.add(InfoRow("Hardware address", i["mac"]))
        sp = su.read_file(f"/sys/class/net/{i['name']}/speed")
        if sp.isdigit() and int(sp) > 0: g.add(InfoRow("Link speed", f"{sp} Mb/s"))
        if su.which("nmcli"):
            h = pb.group()
            h.add(ButtonRow("Reconnect", "Ask for a fresh address from the router", "Reconnect", lambda: self.win.apply("sh", "-c", f"nmcli dev disconnect {i['name']}; nmcli dev connect {i['name']}", msg="Reconnecting...", done=lambda *_: self.refresh())))

PAGES = [WifiPage, BluetoothPage, NetworkPage]
