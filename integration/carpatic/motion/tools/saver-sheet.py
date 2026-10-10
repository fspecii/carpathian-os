#!/usr/bin/env python3
"""saver-sheet.py STREAM.ansi COLSxROWS OUT.png fps idx[:label] ...: replay a saver.awk stream (frames separated by 0x1e, MARK=1) into the terminal emulator and
snapshot the screen at the given frame indices; builds a contact sheet. Env: TITLE, COLS (sheet columns), THUMB (px)."""
import os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import vt2png, contact_sheet
stream, size, out, fps = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
cols, rows = map(int, size.split("x")); frames = open(stream, errors="ignore").read().split("\x1e")
want = {}
for a in sys.argv[5:]:
    i, _, lab = a.partition(":"); want[int(i)] = lab
sc = vt2png.Screen(cols, rows); tmp = tempfile.mkdtemp(); items = []
for n, f in enumerate(frames):
    sc.feed(f)
    if n in want:
        p = os.path.join(tmp, "%d.png" % n); sc.png(p, 8, 16); items.append((p, want[n] or "%.1f s" % (n / fps)))
contact_sheet.sheet(out, items, int(os.environ.get("COLS", 4)), int(os.environ.get("THUMB", 330)), os.environ.get("TITLE"))
print("wrote", out, len(items), "frames of", len(frames))
