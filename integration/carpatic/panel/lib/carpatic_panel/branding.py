"""Carpathian OS mark: website canonical 36x30 geometry, palette-coloured.

No bitmap loading or GTK dependency. The snow notch is a real transparent hole,
so the mark stays recognisable on every panel/background colour.
"""
NAME = 'Carpathian OS'
VIEWBOX = (36, 30)
RIDGE = ((2, 26), (15, 4), (21, 14), (25, 8), (34, 26), (2, 26))
NOTCH = ((10, 15), (15, 7), (20, 15), (15, 12))


def draw_mark(cr, cx, cy, width, color):
    """Paint at the supplied centre; width determines scale, preserving 36:30."""
    cr.save()
    try:
        scale = width / VIEWBOX[0]
        cr.translate(cx - width / 2, cy - VIEWBOX[1] * scale / 2)
        cr.scale(scale, scale)
        cr.set_source_rgba(*color)
        cr.set_fill_rule(1)  # cairo.FillRule.EVEN_ODD
        cr.new_path()
        for points in (RIDGE, NOTCH):
            cr.move_to(*points[0])
            for point in points[1:]: cr.line_to(*point)
            cr.close_path()
        cr.fill()
    finally:
        cr.restore()
