#!/usr/bin/env python3
"""duration-probe.py DIR: second white marker (row 14-22) x = plymouth's boot-progress `duration` * 100 (set in progress_cb). Prints (host time, duration)
change points: how often and how accurately plymouth reports wall time to the script."""
import sys, os
d = sys.argv[1]; t = [float(x) for x in open(os.path.join(d, "times.txt"))]; last = None
for i, ts in enumerate(t):
    f = os.path.join(d, "f%03d.ppm" % i)
    if not os.path.exists(f): continue
    b = open(f, "rb").read(); parts = b.split(b"\n", 3); w, h = map(int, parts[1].split()); px = parts[3]
    xs = []
    for y in (16, 18, 20):
        row = px[y * w * 3:(y + 1) * w * 3]
        xs += [x for x in range(w) if row[3 * x] > 190 and row[3 * x + 1] > 190]
    if xs:
        v = round((min(xs) + max(xs)) / 2 - 3.5)
        if v != last: print("host %.2fs  duration*100=%d" % (ts, v)); last = v
