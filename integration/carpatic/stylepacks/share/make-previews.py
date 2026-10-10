#!/usr/bin/env python3
"""make-previews.py : turn the VM screenshots docs/screenshots/stylepack-<pack>-<light|dark>-desktop.png into the Settings > Style thumbnails
stylepacks/<pack>/preview-<mode>.png (480x300). Run after stylepacks/tests/vm-e2e.sh. Needs PyGObject (GdkPixbuf)."""
import os, gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf
root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
shots = os.path.join(root, "..", "docs", "screenshots")
for pack in ("zen", "kylin"):
    for mode in ("light", "dark"):
        src = os.path.join(shots, f"stylepack-{pack}-{mode}-desktop.png")
        if os.path.isfile(src):
            GdkPixbuf.Pixbuf.new_from_file_at_scale(src, 480, 300, False).savev(os.path.join(root, pack, f"preview-{mode}.png"), "png", [], [])
            print("wrote", pack, mode)
