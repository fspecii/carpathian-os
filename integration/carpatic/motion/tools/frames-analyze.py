#!/usr/bin/env python3
"""frames-analyze.py DIR [t0 t1]: from plymouth-frames.py output (f*.ppm + times.txt) count how many DISTINCT screens were shown per second.
Because the capture runs faster than the splash refreshes, distinct-screen transitions per second between t0 and t1 = the splash's real frame rate
(a frame that did not change anything, e.g. an idle bar, is not counted: use a window where something moves)."""
import sys, zlib, os
d = sys.argv[1]
t = [float(x) for x in open(os.path.join(d, "times.txt"))]
t0 = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
t1 = float(sys.argv[3]) if len(sys.argv) > 3 else 1.4
prev = None; stamps = []
for i, ts in enumerate(t):
    if ts < t0 or ts > t1: continue
    f = os.path.join(d, "f%03d.ppm" % i)
    if not os.path.exists(f): continue
    c = zlib.crc32(open(f, "rb").read())
    if c != prev: stamps.append(ts); prev = c
if len(stamps) > 2:
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    print("distinct screens %d in %.2fs -> %.1f per second; gap median %.1f ms, max %.1f ms" % (
        len(stamps), stamps[-1] - stamps[0], (len(stamps) - 1) / (stamps[-1] - stamps[0]), sorted(gaps)[len(gaps)//2] * 1000, max(gaps) * 1000))
else: print("too few changes", len(stamps))
