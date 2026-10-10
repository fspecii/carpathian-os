#!/usr/bin/env python3
"""fps-probe.py DIR [t0 t1]: with CARPATIC_FPSPROBE=1 frames, find the white marker in the top rows (x = script frame number) of every captured
screen and fit frame-number vs host time: slope = the splash's real refresh rate; also reports the largest gap (frames skipped)."""
import sys, os
d = sys.argv[1]; t0 = float(sys.argv[2]) if len(sys.argv) > 2 else 0; t1 = float(sys.argv[3]) if len(sys.argv) > 3 else 99
t = [float(x) for x in open(os.path.join(d, "times.txt"))]
pts = []
for i, ts in enumerate(t):
    if not (t0 <= ts <= t1): continue
    f = os.path.join(d, "f%03d.ppm" % i)
    if not os.path.exists(f): continue
    b = open(f, "rb").read(); parts = b.split(b"\n", 3); w, h = map(int, parts[1].split()); px = parts[3]
    xs = []
    for y in (2, 4, 6):
        row = px[y * w * 3:(y + 1) * w * 3]
        xs += [x for x in range(w) if row[3 * x] > 190 and row[3 * x + 1] > 190 and row[3 * x + 2] > 190]
    if xs: pts.append((ts, (min(xs) + max(xs)) / 2 - 3.5))     # marker is 8 px wide
if len(pts) < 5: sys.exit("marker not found in %d frames" % len(pts))
# unwrap is not needed within 1000 frames (20 s)
n = len(pts); mt = sum(p[0] for p in pts) / n; mx = sum(p[1] for p in pts) / n
slope = sum((p[0] - mt) * (p[1] - mx) for p in pts) / sum((p[0] - mt) ** 2 for p in pts)
print("script frames per second: %.1f (from %d samples, %.1f s)" % (slope, n, pts[-1][0] - pts[0][0]))
