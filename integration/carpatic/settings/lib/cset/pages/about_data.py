"""System facts for About (all GTK-free, host-testable)."""
import os, re, platform, shutil
from .. import sysutil as su

def os_release(path="/etc/os-release"):
    return su.read_env(path)

FAKE = bool(os.environ.get("CSET_FAKE_HW"))   # tests and documentation screenshots: demo values instead of this machine

def cpu_model(path="/proc/cpuinfo"):
    if FAKE: return "Intel Core i7-1255U (12 threads)"
    names = []; cores = 0
    try:
        for l in open(path):
            if l.startswith("model name"): names.append(l.split(":", 1)[1].strip()); cores += 1
            elif l.lower().startswith(("hardware", "cpu model")) and not names: names.append(l.split(":", 1)[1].strip())
    except OSError: pass
    if not names: return platform.machine()
    n = re.sub(r"\s+", " ", re.sub(r"\((R|TM)\)|CPU @.*|@ .*", "", names[0])).strip()
    return f"{n} ({cores} threads)" if cores > 1 else n

def mem_total(path="/proc/meminfo"):
    if FAKE: return 16 * 1000**3
    try:
        for l in open(path):
            if l.startswith("MemTotal"): return int(l.split()[1]) * 1024
    except OSError: pass
    return 0

def gpu_name():
    if FAKE: return "Intel Iris Xe Graphics"
    t = su.out("lspci", "-mm")
    for l in t.splitlines():
        if re.search(r'"(VGA compatible controller|3D controller|Display controller)"', l):
            f = re.findall(r'"([^"]*)"', l)
            if len(f) >= 3: return f[2]
    return ""

def uptime_text(path="/proc/uptime"):
    try:
        with open(path) as f: s = int(float(f.read().split()[0]))
    except (OSError, ValueError, IndexError): return ""
    d, r = divmod(s, 86400); h, r = divmod(r, 3600); m = r // 60
    parts = ([f"{d} day" + ("s" if d != 1 else "")] if d else []) + ([f"{h} hour" + ("s" if h != 1 else "")] if h else []) + ([f"{m} min"] if (m and not d) else [])
    return ", ".join(parts) or "less than a minute"

def disk_root():
    if FAKE: return 512 * 1000**3, 318 * 1000**3
    try:
        st = os.statvfs("/"); return st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize
    except OSError: return 0, 0

def hostname():
    if FAKE: return "carpatic-laptop"
    return su.read_file("/etc/hostname") or platform.node()

def machine_model():
    if FAKE: return "Carpatic Laptop 14"
    for p in ("/sys/class/dmi/id/product_name", "/sys/devices/virtual/dmi/id/product_name"):
        v = su.read_file(p)
        if v and v.lower() not in ("to be filled by o.e.m.", "system product name", "standard pc (i440fx + piix, 1996)"): return v
    v = su.read_file("/sys/class/dmi/id/product_name"); return v or ""
