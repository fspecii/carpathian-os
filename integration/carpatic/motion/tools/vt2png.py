#!/usr/bin/env python3
"""vt2png.py: tiny terminal emulator that renders ANSI text to PNG with pycairo (no Pillow). Understands what the Carpathian animations emit:
cursor addressing (CSI r;c H, A/B/C/D, G, K, J), SGR (0,1,2,7,22,27, 30-37, 40-47, 90-97, 100-107, 38/48;5;n, 38/48;2;r;g;b), \\r \\n, ?25 h/l.
API: Screen(cols, rows).feed(text); Screen.png(path, cell_w=9, cell_h=18). CLI: vt2png.py COLS ROWS out.png < ansi.txt
Palette: the Carpathian dark ANSI colours from design/tokens/tokens.toml (what the live console uses)."""
import re, sys, os, tomllib
import cairo

HERE = os.path.dirname(os.path.abspath(__file__))
_t = tomllib.load(open(os.path.join(HERE, "..", "..", "design", "tokens", "tokens.toml"), "rb"))
PAL16 = _t["color"]["dark"]["ansi"]
BG_HEX, FG_HEX = _t["color"]["dark"]["bg_deep"], _t["color"]["dark"]["fg"]


def hx(h): h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def c256(n):
    if n < 16: return hx(PAL16[n])
    if n < 232:
        n -= 16; f = lambda v: 0 if v == 0 else (55 + 40 * v) / 255
        return (f(n // 36), f((n // 6) % 6), f(n % 6))
    v = (8 + (n - 232) * 10) / 255; return (v, v, v)


class Screen:
    def __init__(self, cols, rows):
        self.cols, self.rows = cols, rows
        self.cells = [[(" ", None, None, 0) for _ in range(cols)] for _ in range(rows)]
        self.x = self.y = 0; self.fg = self.bg = None; self.attr = 0
    def put(self, ch):
        if self.x >= self.cols: self.x = 0; self.y = min(self.y + 1, self.rows - 1)
        self.cells[self.y][self.x] = (ch, self.fg, self.bg, self.attr); self.x += 1
    def sgr(self, params):
        p = [int(v) if v else 0 for v in params.split(";")] if params != "" else [0]; i = 0
        while i < len(p):
            c = p[i]
            if c == 0: self.fg = self.bg = None; self.attr = 0
            elif c == 1: self.attr |= 1
            elif c == 2: self.attr |= 2
            elif c == 7: self.attr |= 4
            elif c in (22,): self.attr &= ~3
            elif c == 27: self.attr &= ~4
            elif 30 <= c <= 37: self.fg = c256(c - 30)
            elif 90 <= c <= 97: self.fg = c256(c - 90 + 8)
            elif 40 <= c <= 47: self.bg = c256(c - 40)
            elif 100 <= c <= 107: self.bg = c256(c - 100 + 8)
            elif c == 39: self.fg = None
            elif c == 49: self.bg = None
            elif c in (38, 48) and i + 1 < len(p):
                if p[i + 1] == 5 and i + 2 < len(p): col = c256(p[i + 2]); i += 2
                elif p[i + 1] == 2 and i + 4 < len(p): col = tuple(v / 255 for v in p[i + 2:i + 5]); i += 4
                else: col = None
                if c == 38: self.fg = col
                else: self.bg = col
            i += 1
    def feed(self, text):
        i = 0; n = len(text)
        while i < n:
            ch = text[i]
            if ch == "\x1b":
                m = re.compile(r"\x1b\[([?0-9;]*)([A-Za-z])").match(text, i)
                if m:
                    a, f = m.group(1), m.group(2); i = m.end()
                    nums = [int(v) if v else 0 for v in a.lstrip("?").split(";")] if a.lstrip("?") else []
                    g = lambda k, d: (nums[k] if len(nums) > k and nums[k] else d)
                    if f == "m": self.sgr(a)
                    elif f in "Hf": self.y = min(g(0, 1) - 1, self.rows - 1); self.x = min(g(1, 1) - 1, self.cols - 1)
                    elif f == "A": self.y = max(0, self.y - g(0, 1))
                    elif f == "B": self.y = min(self.rows - 1, self.y + g(0, 1))
                    elif f == "C": self.x = min(self.cols - 1, self.x + g(0, 1))
                    elif f == "D": self.x = max(0, self.x - g(0, 1))
                    elif f == "G": self.x = min(self.cols - 1, g(0, 1) - 1)
                    elif f == "K":
                        for xx in range(self.x, self.cols): self.cells[self.y][xx] = (" ", None, self.bg, 0)
                    elif f == "J" and g(0, 0) == 2:
                        for yy in range(self.rows):
                            for xx in range(self.cols): self.cells[yy][xx] = (" ", None, None, 0)
                    continue
                m = re.compile(r"\x1b[78()=>].?").match(text, i)
                i = m.end() if m else i + 1; continue
            if ch == "\r": self.x = 0
            elif ch == "\n": self.y = min(self.y + 1, self.rows - 1); self.x = 0      # tty onlcr
            elif ch == "\x08": self.x = max(0, self.x - 1)
            elif ch >= " ": self.put(ch)
            i += 1
    def png(self, path, cw=9, ch=18, font="DejaVu Sans Mono"):
        W, H = self.cols * cw, self.rows * ch
        s = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H); c = cairo.Context(s)
        c.set_source_rgb(*hx(BG_HEX)); c.paint()
        c.select_font_face(font, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL); c.set_font_size(ch * 0.78)
        fe = c.font_extents(); base = (ch - (fe[0] + fe[1])) / 2 + fe[0]
        for y, line in enumerate(self.cells):
            for x, (t, fg, bg, at) in enumerate(line):
                f, b = fg or hx(FG_HEX), bg
                if at & 4: f, b = (b or hx(BG_HEX)), f
                if b: c.set_source_rgb(*b); c.rectangle(x * cw, y * ch, cw, ch); c.fill()
                if t != " ":
                    if at & 2: f = tuple(v * 0.55 + z * 0.45 for v, z in zip(f, hx(BG_HEX)))
                    c.set_source_rgb(*f); c.move_to(x * cw, y * ch + base)
                    c.select_font_face(font, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD if at & 1 else cairo.FONT_WEIGHT_NORMAL)
                    c.show_text(t)
        s.write_to_png(path)


if __name__ == "__main__":
    sc = Screen(int(sys.argv[1]), int(sys.argv[2])); sc.feed(sys.stdin.read()); sc.png(sys.argv[3])
