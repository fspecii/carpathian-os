#!/usr/bin/env python3
"""Execute actual sidebar handlers without attaching to a display."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT / 'integration/carpatic/settings/lib/cset/app.py').read_text())
CLASS = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == 'SettingsWindow')
METHODS = {'toggle_sidebar', 'on_sidebar_allocation', 'set_sidebar_for', '_apply_sidebar'}

class Sidebar:
    def __init__(self): self.visible = True; self.changes = 0
    def get_visible(self): return self.visible
    def set_visible(self, visible): self.visible = visible; self.changes += 1
    def set_no_show_all(self, value): self.no_show_all = value

class Responsive(unittest.TestCase):
    def setUp(self):
        self.pending = []
        namespace = {'GLib': SimpleNamespace(idle_add=lambda callback: self.pending.append(callback))}
        module = ast.Module(body=[node for node in CLASS.body if isinstance(node, ast.FunctionDef) and node.name in METHODS], type_ignores=[])
        exec(compile(module, '<actual Settings sidebar handlers>', 'exec'), namespace)
        self.window = SimpleNamespace(side=Sidebar(), auto_hidden=False, _sidebar_manual=None,
                                      _sidebar_width=None, _sidebar_need=480, _sidebar_pending=False,
                                      get_size=lambda: (880, 620))
        for name in METHODS:
            setattr(self.window, name, namespace[name].__get__(self.window))
    def resize(self, width):
        self.window.on_sidebar_allocation(None, SimpleNamespace(width=width))
        callbacks, self.pending = self.pending, []
        for callback in callbacks: callback()
    def test_ordinary_narrow_then_wide_restores_sidebar(self):
        self.resize(600)
        self.assertFalse(self.window.side.visible)
        self.assertTrue(self.window.auto_hidden)
        self.resize(880)
        self.assertTrue(self.window.side.visible)
        self.assertFalse(self.window.auto_hidden)
    def test_manual_hide_survives_resize_and_page_switch(self):
        self.resize(880)
        self.window.toggle_sidebar()
        self.resize(600); self.resize(1000)
        self.window.set_sidebar_for(0)
        self.assertFalse(self.window.side.visible)
        self.window.toggle_sidebar()
        self.assertTrue(self.window.side.visible)
    def test_manual_show_narrow_survives_same_allocation_then_resumes_auto(self):
        self.resize(600)
        self.window.toggle_sidebar()
        self.assertTrue(self.window.side.visible)
        self.resize(600)
        self.assertTrue(self.window.side.visible)
        self.resize(620)
        self.assertFalse(self.window.side.visible)
    def test_raw_page_need_and_return_to_ordinary(self):
        self.resize(880)
        self.window.set_sidebar_for(800)
        self.assertFalse(self.window.side.visible)
        self.window.set_sidebar_for(0)
        self.assertTrue(self.window.side.visible)
    def test_hysteresis_and_no_allocation_recursion(self):
        self.resize(727)
        self.assertFalse(self.window.side.visible)
        changes = self.window.side.changes
        for _ in range(10): self.resize(727)
        self.assertEqual(self.window.side.changes, changes)
        self.resize(740)
        self.assertFalse(self.window.side.visible)
        self.resize(752)
        self.assertTrue(self.window.side.visible)
    def test_deferred_allocations_coalesce_use_latest_width(self):
        for width in (600, 650, 880):
            self.window.on_sidebar_allocation(None, SimpleNamespace(width=width))
        self.assertEqual(len(self.pending), 1)
        self.pending.pop()()
        self.assertTrue(self.window.side.visible)

if __name__ == '__main__': unittest.main()
