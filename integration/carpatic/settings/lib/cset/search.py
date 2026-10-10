"""Live search over every setting. GTK-free so it is unit-tested on the host. The index is built at start-up from page metadata
(Page.entries), never by building the pages."""
import re, unicodedata

def norm(s):
    s = unicodedata.normalize("NFKD", s or "").lower()
    return "".join(c for c in s if not unicodedata.combining(c))

def words(s):
    return re.findall(r"[a-z0-9]+", norm(s))

class Entry:
    __slots__ = ("page", "page_title", "title", "keywords", "anchor", "sub", "_t", "_k", "_p")
    def __init__(self, page, page_title, title, keywords="", anchor=None, sub=None):
        self.page, self.page_title, self.title, self.keywords, self.anchor, self.sub = page, page_title, title, keywords, anchor, sub
        self._t, self._k, self._p = norm(title), norm(keywords), norm(page_title)
    def __repr__(self): return f"<Entry {self.page}/{self.anchor}: {self.title}>"

class SearchIndex:
    def __init__(self):
        self.entries = []
    def add(self, page, page_title, title, keywords="", anchor=None, sub=None):
        self.entries.append(Entry(page, page_title, title, keywords, anchor, sub))
    def remove_page(self, page):
        self.entries = [e for e in self.entries if e.page != page]
    @staticmethod
    def _score_text(tok, text, ws, w_exact, w_prefix, w_sub):
        if not text: return 0
        if tok in ws:
            return w_exact if text == tok else w_prefix + 10
        if any(w.startswith(tok) for w in ws): return w_prefix
        if tok in text: return w_sub
        return 0
    def score(self, e, toks):
        total = 0
        tw, kw, pw = words(e.title), words(e.keywords), words(e.page_title)
        for tok in toks:
            s = max(self._score_text(tok, e._t, tw, 100, 60, 35), self._score_text(tok, e._k, kw, 30, 24, 14), self._score_text(tok, e._p, pw, 12, 10, 6))
            if s == 0: return 0
            total += s
        if e.anchor is None: total += 5   # the page itself ranks just above its own settings
        return total
    def query(self, q, limit=40):
        toks = words(q)
        if not toks: return []
        scored = [(self.score(e, toks), i, e) for i, e in enumerate(self.entries)]
        scored = [t for t in scored if t[0] > 0]
        scored.sort(key=lambda t: (-t[0], t[1]))
        return [e for _, _, e in scored[:limit]]
