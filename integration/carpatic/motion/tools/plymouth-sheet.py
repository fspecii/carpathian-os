#!/usr/bin/env python3
"""plymouth-sheet.py FRAMEDIR OUT.png [--times t1,t2,...] [--cols 4] [--title ...]: contact sheet from plymouth-frames.py output (nearest captured frame per time)."""
import argparse, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import contact_sheet
ap = argparse.ArgumentParser(); ap.add_argument("dir"); ap.add_argument("out"); ap.add_argument("--times", default="0.1,0.3,0.5,0.7,0.9,1.1,1.4,2.0,3.0,4.5,6.0,8.5")
ap.add_argument("--cols", type=int, default=4); ap.add_argument("--title", default="Plymouth, QEMU"); ap.add_argument("--w", type=int, default=320)
a = ap.parse_args()
t = [float(x) for x in open(os.path.join(a.dir, "times.txt"))]
tmp = tempfile.mkdtemp(); items = []
for want in map(float, a.times.split(",")):
    i = min(range(len(t)), key=lambda j: abs(t[j] - want))
    png = os.path.join(tmp, "f%d.png" % i)
    subprocess.run([sys.executable, "-I", os.path.join(HERE, "..", "..", "desktop", "ppm2png.py"), os.path.join(a.dir, "f%03d.ppm" % i), png], check=True)
    items.append((png, "%.1f s" % t[i]))
contact_sheet.sheet(a.out, items, a.cols, a.w, a.title)
print("wrote", a.out)
