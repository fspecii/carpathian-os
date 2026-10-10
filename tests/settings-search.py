#!/usr/bin/env python3
"""GTK-free search regressions using actual page metadata and index methods.

Availability is deliberately not simulated: the fixture includes all registered
pages. This tests discoverability/index pruning, not visible rows or hardware.
Only selected metadata expressions and the two GTK-free index methods execute.
"""
import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
CSET = ROOT / "integration/carpatic/settings/lib/cset"
spec = importlib.util.spec_from_file_location("carpatic_search_test_subject", CSET / "search.py")
search = importlib.util.module_from_spec(spec)
spec.loader.exec_module(search)


def assignments(nodes):
    return {target.id: node.value for node in nodes if isinstance(node, ast.Assign)
            for target in node.targets if isinstance(target, ast.Name)}


def metadata():
    registry = assignments(ast.parse((CSET / "pages/__init__.py").read_text()).body)
    modules = ast.literal_eval(registry["_MODULES"])
    pages = []
    for name in modules:
        tree = ast.parse((CSET / "pages" / (name + ".py")).read_text())
        top = assignments(tree.body)
        classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
        for ref in top["PAGES"].elts:
            values = assignments(classes[ref.id].body)
            fields = {}
            context = {"__builtins__": {}, "tuple": tuple, "frozenset": frozenset}
            if "CATEGORIES" in top:
                context["CATEGORIES"] = ast.literal_eval(top["CATEGORIES"])
            for field in ("id", "title", "keywords", "entries", "optional", "group", "order"):
                if field not in values:
                    continue
                expr = values[field]
                try:
                    fields[field] = ast.literal_eval(expr)
                except ValueError:
                    # Existing derived Default Apps metadata and frozenset sets.
                    # No module imports, UI methods or availability probes execute.
                    fields[field] = eval(compile(ast.Expression(expr), str(CSET / "pages" / (name + ".py")), "eval"), context)
            fields.setdefault("optional", frozenset())
            fields.setdefault("order", 0)
            fields["pb"] = None
            pages.append(SimpleNamespace(**fields))
    return sorted(pages, key=lambda p: (p.group, p.order))


def index_methods():
    tree = ast.parse((CSET / "app.py").read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SettingsWindow")
    methods = [n for n in cls.body if isinstance(n, ast.FunctionDef)
               and n.name in ("build_index", "on_page_filled")]
    if len(methods) != 2:
        raise AssertionError("Actual Settings index methods changed; review this fixture")
    scope = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=methods, type_ignores=[])), str(CSET / "app.py"), "exec"), scope)
    return scope


class SettingsSearch(unittest.TestCase):
    def setUp(self):
        self.pages = metadata()
        self.subject = SimpleNamespace(pages=self.pages, index=search.SearchIndex())
        self.methods = index_methods()
        self.methods["build_index"](self.subject)
        self.index = self.subject.index

    def identities(self, query):
        return [(e.page, e.anchor) for e in self.index.query(query)]

    def test_daily_queries_reach_real_setting_or_page(self):
        cases = {"wi-fi": ("wifi", "wifi-switch"),
                 "sound output": ("sound", "out-dev"),
                 "scale": ("displays", "scale"),
                 "default browser": ("apps", "app-x-scheme-handler/http"),
                 "lock now": ("lock", "lock-now"),
                 "reduce motion": ("animations", "reduced")}
        for query, target in cases.items():
            with self.subTest(query=query):
                self.assertIn(target, self.identities(query))

    def test_wifi_without_punctuation(self):
        self.assertIn(("wifi", "wifi-switch"), self.identities("wifi"),
                      "WiFi spelling must reveal the actual network toggle")

    def test_reduced_motion_common_wording(self):
        self.assertIn(("animations", "reduced"), self.identities("reduced motion"),
                      "Common accessibility wording must reveal the real Reduce motion setting")

    def test_exact_title_precedes_broad_page_keyword(self):
        hits = self.identities("scale")
        self.assertLess(hits.index(("displays", "scale")), hits.index(("displays", None)))
        hits = self.identities("output device")
        self.assertEqual(hits[0], ("sound", "out-dev"))

    def test_accents_case_prefix_and_multiple_words(self):
        self.assertEqual(self.identities("Scále"), self.identities("scale"))
        self.assertIn(("sound", "out-dev"), self.identities("OUTP DEV"))
        self.assertIn(("animations", "reduced"), self.identities("réduce mót"))
        self.assertEqual(self.identities("output zzznotametadataword"), [])

    def test_empty_queries_and_limits(self):
        for query in ("", " \t\n", "---", "!!!"):
            with self.subTest(query=query):
                self.assertEqual(self.identities(query), [])
        all_hits = self.index.query("screen")
        self.assertGreater(len(all_hits), 2)
        self.assertEqual(self.index.query("screen", limit=2), all_hits[:2])

    def test_optional_unavailable_rows_are_pruned_by_actual_app_method(self):
        page = next(p for p in self.pages if p.id == "displays")
        self.assertIn("scale", page.optional)
        self.assertIn(("displays", "scale"), self.identities("scale"))
        present = {"screens"}
        page.pb = SimpleNamespace(find=lambda anchor: object() if anchor in present else None)
        unrelated_before = [(e.page, e.anchor) for e in self.index.entries if e.page != page.id]
        self.methods["on_page_filled"](self.subject, page)
        self.assertNotIn(("displays", "scale"), self.identities("scale"))
        self.assertIn(("displays", None), self.identities("scale"))
        self.assertIn(("displays", "screens"), self.identities("resolution"))
        self.assertEqual([(e.page, e.anchor) for e in self.index.entries if e.page != page.id], unrelated_before)

    def test_remove_page_removes_only_requested_page(self):
        self.assertIn(("wifi", None), self.identities("wi-fi"))
        before = [(e.page, e.anchor) for e in self.index.entries if e.page != "wifi"]
        self.index.remove_page("wifi")
        self.assertFalse(any(e.page == "wifi" for e in self.index.entries))
        self.assertEqual([(e.page, e.anchor) for e in self.index.entries], before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
