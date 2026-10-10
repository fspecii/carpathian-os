#!/usr/bin/env python3
"""ansi-sheet.py FRAMEDIR OUT.png COLSxROWS fps frame_index[:label] ... : render selected NNNN.ansi frames (carpatic-greeter-anim --dump / screensaver --dump) and make a contact sheet."""
import os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import vt2png, contact_sheet
d, out, size, fps = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
cols, rows = map(int, size.split("x")); tmp = tempfile.mkdtemp(); items = []; title = os.environ.get("TITLE")
for a in sys.argv[5:]:
    i, _, lab = a.partition(":")
    sc = vt2png.Screen(cols, rows); sc.feed(open(os.path.join(d, "%04d.ansi" % int(i)), errors="ignore").read())
    p = os.path.join(tmp, i + ".png"); sc.png(p); items.append((p, lab or "%.2f s" % (int(i) / fps)))
contact_sheet.sheet(out, items, int(os.environ.get("COLS", 4)), int(os.environ.get("THUMB", 330)), title)
print("wrote", out)
