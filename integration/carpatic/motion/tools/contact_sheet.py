#!/usr/bin/env python3
"""contact_sheet.py OUT.png COLS THUMB_W frame1.png[:label] frame2.png[:label] ... : grid of thumbnails with small captions (pycairo only).
Also importable: sheet(out, items, cols, thumb_w)."""
import sys, cairo

BG = (0.043, 0.055, 0.075); FG = (0.906, 0.925, 0.953); MUT = (0.64, 0.68, 0.75)


def sheet(out, items, cols=4, thumb_w=320, title=None):
    imgs = [(cairo.ImageSurface.create_from_png(p), l) for p, l in items]
    pad, cap = 10, 22
    ths = [int(im.get_height() * thumb_w / im.get_width()) for im, _ in imgs]       # every thumbnail keeps its own aspect ratio
    rows = (len(imgs) + cols - 1) // cols; top = 34 if title else pad
    rh = [max(ths[r * cols:(r + 1) * cols]) for r in range(rows)]
    W = cols * (thumb_w + pad) + pad; H = top + sum(h + cap + pad for h in rh)
    s = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H); c = cairo.Context(s)
    c.set_source_rgb(*BG); c.paint(); c.select_font_face("DejaVu Sans")
    if title:
        c.set_source_rgb(*FG); c.set_font_size(15); c.move_to(pad, 23); c.show_text(title)
    for n, (im, label) in enumerate(imgs):
        r = n // cols; x = pad + (n % cols) * (thumb_w + pad); y = top + sum(h + cap + pad for h in rh[:r]); k = thumb_w / im.get_width(); th = ths[n]
        c.save(); c.translate(x, y); c.rectangle(0, 0, thumb_w, th); c.clip(); c.scale(k, k)
        c.set_source_surface(im, 0, 0); c.get_source().set_filter(cairo.FILTER_BEST); c.paint(); c.restore()
        c.set_source_rgb(0.2, 0.25, 0.32); c.set_line_width(1); c.rectangle(x - .5, y - .5, thumb_w + 1, th + 1); c.stroke()
        c.set_source_rgb(*MUT); c.set_font_size(12); c.move_to(x, y + th + 15); c.show_text(label)
    s.write_to_png(out)


if __name__ == "__main__":
    out, cols, tw = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    items = []
    for a in sys.argv[4:]:
        p, _, l = a.partition(":"); items.append((p, l))
    sheet(out, items, cols, tw)
