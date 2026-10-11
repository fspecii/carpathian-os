#!/usr/bin/env python3
"""Real Cairo/GTK compact-calendar regressions on an owned private Xvfb bus."""
import datetime as dt
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace

if os.environ.get('WAYLAND_DISPLAY') or os.environ.get('XDG_CURRENT_DESKTOP') == 'COSMIC':
    raise SystemExit('Refuse desktop session')
match = re.fullmatch(r':([1-9][0-9]*)', os.environ.get('DISPLAY', ''))
private = False
if match and os.environ.get('CARPATIC_XVFB_TEST') == '1':
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            args = (proc / 'cmdline').read_bytes().split(b'\0')
            if proc.stat().st_uid == os.getuid() and Path(os.fsdecode(args[0])).name == 'Xvfb' and os.environ['DISPLAY'].encode() in args:
                private = True; break
        except OSError: pass
ancestor = os.getppid(); private_bus = False
while ancestor > 1:
    try:
        proc = Path('/proc') / str(ancestor)
        args = (proc / 'cmdline').read_bytes().split(b'\0')
        if Path(os.fsdecode(args[0])).name == 'dbus-run-session': private_bus = True; break
        ancestor = int(re.search(r'^PPid:\s*(\d+)', (proc / 'status').read_text(), re.M).group(1))
    except (OSError, AttributeError): break
if not private or not private_bus or os.environ.get('CARPATIC_PRIVATE_DBUS_TEST') != '1' or not os.environ.get('DBUS_SESSION_BUS_ADDRESS'):
    raise SystemExit('Verified owned Xvfb and private D-Bus required')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'integration/carpatic/panel/lib'))
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib
from carpatic_panel.flyout_cal import CalView, CalModel, SPECS
from carpatic_panel.events import Event
from carpatic_panel.notes import FakeNotes, Note
from carpatic_panel.theme import Theme
from carpatic_panel.kit import render_png, Canvas
from carpatic_panel.popup import Popup
from carpatic_panel import uiscale

ARTIFACTS = Path(os.environ.get('CARPATIC_COMPACT_EVIDENCE', ROOT / 'artifacts/calendar-compact-tests'))
ARTIFACTS.mkdir(parents=True, exist_ok=True)


def pump(predicate, seconds=4):
    context = GLib.MainContext.default(); deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        while context.pending(): context.iteration(False)
        if predicate(): return
        time.sleep(.01)
    raise AssertionError('GTK condition timed out')


class Compact(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='compact-calendar-data-')
        self.old_data = os.environ.get('XDG_DATA_HOME')
        os.environ['XDG_DATA_HOME'] = self.temp.name
        self.views = []
    def tearDown(self):
        for view in self.views: view.dispose()
        self.temp.cleanup()
        if self.old_data is None: os.environ.pop('XDG_DATA_HOME', None)
        else: os.environ['XDG_DATA_HOME'] = self.old_data
    def view(self, look='win', height=520, count=0, weeks=True, notes=True):
        model = CalModel(today=dt.date(2026, 3, 15), first=0, week_numbers=weeks, data=self.temp.name)
        # Explicit event/notification input fixtures exercise real View/layout.
        events = [Event('Event ' + str(i), model.today, uid=str(i), color=i) for i in range(count)]
        model.events_in_grid = lambda: {model.today: events}
        history = [Note(1, 'Files', 'A real-render input fixture', 'Notification body')] if notes else []
        view = CalView(Theme.from_palette({'mode': 'dark'}), model, FakeNotes(history), look=look, max_h=height)
        self.views.append(view); return view
    def assert_geometry(self, view, nodes):
        self.assertLessEqual(view.H, view.max_h)
        for group in view.groups.values():
            self.assertGreater(group.w, 0); self.assertGreater(group.h, 0)
            self.assertGreaterEqual(group.y, 0); self.assertLessEqual(group.y + group.h, view.H)
        for node in nodes:
            if node.group: continue  # Scroll contents intentionally extend past viewport.
            self.assertGreaterEqual(node.y, 0, node.id)
            self.assertGreaterEqual(node.h, 0, node.id)
            self.assertLessEqual(node.y + node.h, view.H, node.id)
        if view.entry_rect:
            x, y, w, h = view.entry_rect
            self.assertGreaterEqual(y, 0); self.assertLessEqual(y+h, view.H)
    def test_layout_matrix_sixweek_weeknumbers_and_all_events(self):
        original = json.dumps(SPECS, sort_keys=True)
        cases = 0
        for look in SPECS:
            for height in (520, 720):
                for count in (0, 1, 8):
                    for week_numbers in (False, True):
                        for populated in (False, True):
                            with self.subTest(look=look,height=height,count=count,weeks=week_numbers,notes=populated):
                                view = self.view(look,height,count,week_numbers,populated)
                                name = f'{look}-{height}-events{count}-weeks{int(week_numbers)}-notes{int(populated)}'
                                nodes = render_png(view, str(ARTIFACTS / (name + '-calendar.png')))
                                self.assert_geometry(view, nodes)
                                self.assertEqual(len([n for n in nodes if n.id and n.id.startswith('day:')]), 42)
                                if height == 520:
                                    self.assertTrue(view.compact)
                                    self.assertEqual(len([n for n in nodes if n.id and n.id.startswith('ev:')]), count)
                                    if count:
                                        group = view.groups['agenda']
                                        self.assertGreaterEqual(group.h, 40)
                                        next_button = next(n for n in nodes if n.id == 'cal:agenda-next')
                                        for _ in range(count): next_button.on_click(next_button)
                                        self.assertEqual(group.target, group.max_offset)
                                    view._set_mode('notifications')
                                    nodes = render_png(view, str(ARTIFACTS / (name + '-notifications.png')))
                                    self.assert_geometry(view, nodes)
                                    self.assertIsNone(view.entry_rect)
                                    self.assertNotIn('agenda',view.groups)
                                    self.assertIn('dnd',[n.id for n in nodes])
                                    if populated: self.assertIn('clear',[n.id for n in nodes])
                                    view._set_mode('calendar'); view.build()
                                    self.assertNotIn('notes',view.groups)
                                cases += 1
        self.assertEqual(json.dumps(SPECS, sort_keys=True),original)
        print('Verified layout cases:',cases)
    def test_scaled_actual_popup_entry_and_all_looks(self):
        old_factor = uiscale.factor()
        uiscale.set_factor(2)
        try:
            for look in SPECS:
                for height in (520,720):
                    view = self.view(look,height,count=8)
                    popup = Popup(view,view.theme,(10,10),slide=False)
                    try:
                        pump(lambda: popup._paint_ready and popup.entry is not None)
                        nodes = render_png(view,str(ARTIFACTS / f'{look}-{height}-scale2.png'),scale=2)
                        self.assert_geometry(view,nodes)
                        self.assertGreaterEqual(popup.canvas.get_allocated_height(),view.H*2)
                        self.assertEqual(popup.entry.get_margin_top(),uiscale.devr(view.entry_rect[1]))
                        self.assertEqual(popup.entry.get_accessible().get_name(),'Add calendar event')
                    finally: popup.close_me()
        finally: uiscale.set_factor(old_factor)

    def test_actual_popup_entry_draft_focus_mode_return_and_keyboard_agenda(self):
        view = self.view(count=8)
        popup = Popup(view, view.theme, (20,20), slide=False)
        try:
            pump(lambda: popup._paint_ready and popup.entry is not None)
            draft = 'Lunch tomorrow 13:00'
            popup.entry.set_text(draft)
            pump(lambda: view.entry_text == draft)
            selected = view.cal.selected
            popup.canvas.grab_focus()
            notification = popup.canvas.node_by_id('cal:mode-notifications')
            notification.on_click(notification)
            pump(lambda: popup.entry is None)
            self.assertEqual(view.entry_text,draft)
            calendar = popup.canvas.node_by_id('cal:mode-calendar'); calendar.on_click(calendar)
            pump(lambda: popup.entry is not None and popup.entry.get_text() == draft)
            pump(lambda: popup.entry.has_focus())
            self.assertEqual(popup.entry.get_accessible().get_name(),'Add calendar event')
            self.assertEqual(view.cal.selected,selected)
            original_entry = popup.entry
            view._set_mode('notifications'); popup.canvas.rebuild()
            view._set_mode('calendar'); popup.canvas.rebuild()
            pump(lambda: popup.entry is original_entry and popup.entry.get_text() == draft and view.live_entry)
            self.assertEqual(popup.entry.get_text(),draft)
            popup.canvas.grab_focus(); popup.canvas.focus_id = None
            for _ in range(60):
                popup.canvas.handle_key(SimpleNamespace(keyval=Gdk.KEY_Tab,state=0))
                if popup.canvas.focus_id == 'cal:agenda-next': break
            self.assertEqual(popup.canvas.focus_id,'cal:agenda-next')
            for _ in range(8): popup.canvas.handle_key(SimpleNamespace(keyval=Gdk.KEY_Return,state=0))
            self.assertEqual(view.groups['agenda'].target,view.groups['agenda'].max_offset)
            pump(lambda: abs(view.groups['agenda'].offset-view.groups['agenda'].target)<.5)
            self.assertEqual(popup.entry.get_text(),draft)
        finally: popup.close_me()
if __name__ == '__main__': unittest.main(verbosity=2)
