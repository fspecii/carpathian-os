"""Context menus drawn with the kit (same radii, hover, glyphs as the flyouts). Items: dict(label, glyph=None, action=callable, sep=False,
disabled=False, checked=False, danger=False, hint='')."""
from . import gfx
from .kit import View, Node, p_button

ROW = 32; PAD = 6; SEP = 9


class MenuView(View):
    radius = 10

    def __init__(self, theme, items, on_done):
        super().__init__(theme)
        self.items = items; self.on_done = on_done
        sc = gfx._scratch()
        mw = max([gfx.text_size(sc, i.get("label", ""), 13, 500, theme.font)[0] + (gfx.text_size(sc, i.get("hint", ""), 11.5, 400, theme.font)[0] + 24 if i.get("hint") else 0)
                  for i in items if not i.get("sep")] or [80])
        self.W = int(max(190, mw + 28 + 36 + PAD * 2))
        self.H = int(PAD * 2 + sum(SEP if i.get("sep") else ROW for i in items))

    def build(self):
        t = self.theme; nodes = []; y = PAD; x = PAD; w = self.W - 2 * PAD
        for k, it in enumerate(self.items):
            if it.get("sep"):
                nodes.append(Node(x=x + 6, y=y + 4, w=w - 12, h=1, paint=lambda cr, n, s: (cr.set_source_rgba(*t.border), cr.rectangle(n.x, n.y, n.w, 1), cr.fill())))
                y += SEP; continue
            def paint(cr, n, s, it=it):
                dis = it.get("disabled")
                if not dis: p_button(t, 6)(cr, n, s)
                col = t.danger if it.get("danger") else (t.fg_subtle if dis else t.fg)
                if it.get("glyph"): gfx.glyph(cr, it["glyph"], n.x + 20, n.y + n.h / 2, 16, col if not it.get("danger") else t.danger)
                if it.get("checked"): gfx.glyph(cr, "check", n.x + 20, n.y + n.h / 2, 15, t.accent, lw=2)
                gfx.text(cr, it["label"], n.x + 40, n.y + n.h / 2, 13, col, 500, maxw=n.w - 50)
                if it.get("hint"): gfx.text(cr, it["hint"], n.x + n.w - 10, n.y + n.h / 2, 11.5, t.fg_subtle, 400, "r")
            act = it.get("action")
            nd = Node(id=f"m{k}", x=x, y=y, w=w, h=ROW, paint=paint, radius=6, focusable=not it.get("disabled"))
            if not it.get("disabled") and act:
                nd.on_click = (lambda n, a=act: (self.on_done(), a()))
            nodes.append(nd); y += ROW
        return nodes
