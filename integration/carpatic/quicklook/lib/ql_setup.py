"""Install the Space shortcut into the file manager. Thunar: a custom action ("Quick Look", command `carpatic-quicklook --toggle %F`) in uca.xml
plus the key `space` for it in accels.scm. Idempotent, keeps the user's own actions and keys, and only touches files when something changes."""
import os, re, sys, subprocess, time
import xml.etree.ElementTree as ET

UID = "1790000000000000-quicklook"
ACCEL_PATH = '<Actions>/ThunarActions/uca-action-%s' % UID
COMMAND = "carpatic-quicklook --toggle %F"

def _cfg(home): return os.path.join(home, ".config", "Thunar")

def ensure_uca(home):
    p = os.path.join(_cfg(home), "uca.xml")
    root = None
    if os.path.exists(p):
        try: root = ET.parse(p).getroot()
        except ET.ParseError: os.replace(p, p + ".broken"); root = None
    if root is None: root = ET.Element("actions")
    for a in root.findall("action"):
        if (a.findtext("unique-id") or "") == UID:
            if (a.findtext("command") or "") == COMMAND: return False
            root.remove(a)
    a = ET.SubElement(root, "action")
    for tag, val in (("icon", "view-reveal-symbolic"), ("name", "Quick Look"), ("submenu", ""), ("unique-id", UID), ("command", COMMAND),
                     ("description", "Preview the selected files without opening an app (Space)"), ("range", "*"), ("patterns", "*")):
        ET.SubElement(a, tag).text = val
    for tag in ("directories", "audio-files", "image-files", "other-files", "text-files", "video-files"): ET.SubElement(a, tag)
    ET.indent(root, space="\t")
    os.makedirs(_cfg(home), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n'); f.write(ET.tostring(root, encoding="unicode") + "\n")
    return True

def ensure_accel(home, key="space"):
    p = os.path.join(_cfg(home), "accels.scm")
    lines = []
    if os.path.exists(p): lines = open(p, encoding="utf-8").read().split("\n")
    want = '(gtk_accel_path "%s" "%s")' % (ACCEL_PATH, key)
    out, found, changed = [], False, False
    for l in lines:
        if ACCEL_PATH in l:
            found = True
            if l.strip() != want: l = want; changed = True
        elif re.search(r'\"%s\"\)\s*$' % re.escape(key), l) and l.strip().startswith('(gtk_accel_path') and 'ThunarActions' in l and ACCEL_PATH not in l:
            l = l.replace('"%s")' % key, '"")'); changed = True       # another action owns Space: Quick Look wins
        out.append(l)
    if not found:
        while out and not out[-1].strip(): out.pop()
        out += [want, ""]; changed = True
    if changed:
        os.makedirs(_cfg(home), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f: f.write("\n".join(out))
    return changed

def thunar_running():
    return subprocess.run(["pgrep", "-x", "thunar"], capture_output=True).returncode == 0

def setup(home=None, restart=True, quiet=False):
    """Returns True when something changed. A running Thunar is asked to quit first (it rewrites accels.scm when it exits) and is not restarted."""
    home = home or os.path.expanduser("~")
    was = thunar_running() if restart else False
    if was:
        subprocess.run(["thunar", "-q"], capture_output=True); time.sleep(0.6)
    c1 = ensure_uca(home); c2 = ensure_accel(home)
    if not quiet: print("Space now opens Quick Look in Files." + (" Reopen the Files window to use it." if was and (c1 or c2) else ""))
    return c1 or c2

def main():
    setup(); return 0

if __name__ == "__main__":
    sys.exit(main())
