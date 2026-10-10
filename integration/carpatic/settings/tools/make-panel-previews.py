#!/usr/bin/env python3
"""Make the 320x180 design thumbnails shown by Settings > Desktop & Dock from the panel's screenshots (docs/screenshots/panel-<design>-<mode>.png).
usage: make-panel-previews.py [OUTDIR]   (default settings/share/panel-previews)"""
import os, sys, glob, cairo
here = os.path.dirname(os.path.abspath(__file__)); repo = os.path.join(here, "..", "..")
out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "..", "share", "panel-previews"); os.makedirs(out, exist_ok=True)
for f in sorted(glob.glob(os.path.join(repo, "docs", "screenshots", "panel-*-*.png"))):
    name = os.path.basename(f)[len("panel-"):]
    if name.count("-") != 1: continue
    src = cairo.ImageSurface.create_from_png(f); W, H = 320, 180
    dst = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H); cr = cairo.Context(dst)
    k = max(W / src.get_width(), H / src.get_height()); cr.scale(k, k)
    cr.set_source_surface(src, (W / k - src.get_width()) / 2, (H / k - src.get_height()) / 2); cr.get_source().set_filter(cairo.FILTER_BEST); cr.paint()
    dst.write_to_png(os.path.join(out, name)); print(name)
