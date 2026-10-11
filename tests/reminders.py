#!/usr/bin/env python3
"""Host logic/CLI tests using isolated XDG data; no GUI or HOME overrides."""
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import re
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'integration/carpatic/reminders/lib'))
from carpatic_reminders.store import Store, StoreError, MAX_BYTES
CLI = ROOT / 'integration/carpatic/reminders/bin/carpatic-reminders'
GUI = '--gui' in sys.argv


def gui_guard():
    if 'WAYLAND_DISPLAY' in os.environ:
        raise SystemExit('GUI tests require WAYLAND_DISPLAY unset')
    display = os.environ.get('DISPLAY', '')
    match = re.fullmatch(r':([1-9][0-9]*)(?:\.0)?', display)
    if not match or os.environ.get('CARPATIC_XVFB_TEST') != '1':
        raise SystemExit('GUI tests require a marked private nonzero Xvfb display')
    for process in Path('/proc').iterdir():
        if not process.name.isdigit(): continue
        try:
            args = (process / 'cmdline').read_bytes().split(b'\0')
            if args and Path(os.fsdecode(args[0])).name == 'Xvfb' and (':' + match.group(1)).encode() in args:
                return
        except OSError:
            continue
    raise SystemExit('No matching live private Xvfb process')


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.env = patch.dict(os.environ, {'XDG_DATA_HOME': self.temporary.name,
                                          'XDG_CONFIG_HOME': self.temporary.name + '/config',
                                          'XDG_STATE_HOME': self.temporary.name + '/state',
                                          'CARPATIC_CONFIG': self.temporary.name + '/config/carpatic'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.store = Store()

    def cli(self, *args, success=True):
        result = subprocess.run([sys.executable, str(CLI), *args], text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0 if success else 1, result.stderr)
        return json.loads(result.stdout) if success else result

    def test_persistence_and_full_lifecycle(self):
        item = self.store.add('Pay bill', 'Account details stay local', '2026-10-11', '09:30')
        self.assertEqual(Store().list(), [item])
        edited = Store().update(item['id'], title='Pay electricity', notes='Edited notes', due_time=None)
        self.assertEqual(edited['title'], 'Pay electricity')
        self.assertIsNone(edited['due_time'])
        Store().update(item['id'], completed=True)
        self.assertEqual(Store().list(pending=True), [])
        self.assertEqual(len(Store().list()), 1)
        Store().update(item['id'], completed=False)
        self.assertEqual(len(Store().list(pending=True)), 1)
        Store().delete(item['id'])
        self.assertEqual(Store().list(), [])
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)

    def test_date_filter_and_order(self):
        self.store.add('Later', due_date='2026-10-12')
        first = self.store.add('First', due_date='2026-10-11', due_time='08:00')
        self.store.add('No date')
        last = self.store.add('Last', due_date='2026-10-11', due_time='19:00')
        self.assertEqual([item['id'] for item in self.store.list('2026-10-11')], [first['id'], last['id']])
        self.assertEqual(self.store.list()[0]['id'], first['id'])
        self.assertEqual(self.store.list('2026-10-13'), [])

    def test_validation_and_preserve_last_good(self):
        self.store.add('Valid')
        good = self.store.path.read_bytes()
        for fields in ({'title': ''}, {'title': 'x' * 201}, {'title': 'two\nlines'},
                       {'title': 'bad date', 'due_date': '2026-02-30'},
                       {'title': 'bad format', 'due_date': '20261011'},
                       {'title': 'time without date', 'due_time': '09:00'},
                       {'title': 'bad time', 'due_date': '2026-10-11', 'due_time': '25:00'},
                       {'title': 'bad notes', 'notes': 'x' * 4001}):
            with self.subTest(fields=fields), self.assertRaises(StoreError): self.store.add(**fields)
            self.assertEqual(self.store.path.read_bytes(), good)

    def test_corruption_not_overwritten(self):
        self.store.path.parent.mkdir(parents=True)
        for raw in (b'{broken', b'{"version":2,"items":[]}', b'x' * (MAX_BYTES + 1)):
            self.store.path.write_bytes(raw)
            with self.assertRaises(StoreError): self.store.add('Must not overwrite')
            self.assertEqual(self.store.path.read_bytes(), raw)

    def test_atomic_replace_failure_preserves_existing(self):
        self.store.add('Existing')
        good = self.store.path.read_bytes()
        with patch('carpatic_reminders.store.os.replace', side_effect=OSError('simulated failure')):
            with self.assertRaises(StoreError): self.store.add('Uncommitted')
        self.assertEqual(self.store.path.read_bytes(), good)
        self.assertEqual(list(self.store.path.parent.glob('.reminders-*')), [])

    def test_concurrent_cli_writers_no_lost_updates(self):
        def add(index): return self.cli('add', f'Concurrent {index}')['id']
        with ThreadPoolExecutor(max_workers=8) as executor:
            ids = list(executor.map(add, range(20)))
        self.assertEqual(len(set(ids)), 20)
        self.assertEqual({item['id'] for item in self.store.list()}, set(ids))

    def test_cli_calendar_api_and_edits(self):
        item = self.cli('add', 'CLI title', '--notes', 'Local notes', '--due-date', '2026-10-11', '--due-time', '10:00')
        self.assertEqual(self.cli('list', '--pending', '--date', '2026-10-11'), [item])
        self.cli('edit', item['id'], '--title', 'Edited', '--due-date', '')
        edited = self.cli('list')[0]
        self.assertIsNone(edited['due_date'])
        self.assertIsNone(edited['due_time'])
        self.cli('complete', item['id'])
        self.assertEqual(self.cli('list', '--pending'), [])
        self.cli('complete', item['id'], '--reopen')
        self.assertEqual(len(self.cli('list', '--pending')), 1)
        self.cli('delete', item['id'])
        self.assertEqual(self.cli('list'), [])
        bad = self.cli('add', '', success=False)
        self.assertIn('title', bad.stderr)

    def test_record_validation_rejects_duplicates_and_types(self):
        item = self.store.add('Valid')
        for invalid in ({**item, 'completed': 1}, {**item, 'id': '../invalid'}, {**item, 'due_time': '12:00'}):
            self.store.path.write_text(json.dumps({'version': 1, 'items': [invalid]}))
            with self.assertRaises(StoreError): self.store.list()
        self.store.path.write_text(json.dumps({'version': 1, 'items': [item, item]}))
        with self.assertRaises(StoreError): self.store.list()


@unittest.skipUnless(GUI, 'GUI checks require explicit --gui on marked private Xvfb')
class ReminderGuiTests(unittest.TestCase):
    setUp = ReminderTests.setUp

    def pump_until(self, predicate, timeout=4):
        from gi.repository import Gtk
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            while Gtk.events_pending(): Gtk.main_iteration_do(False)
            if predicate(): return
            time.sleep(.01)
        self.fail('Timed out waiting for GTK/storage result')

    def test_gui_persistent_editor_actions(self):
        gui_guard()
        import gi
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gtk, Gio
        from carpatic_reminders.app import RemindersWindow
        application = Gtk.Application(application_id='org.carpatic.Reminders.IsolatedTest',
                                      flags=Gio.ApplicationFlags.NON_UNIQUE)
        application.register(None)
        window = RemindersWindow(application)
        try:
            window.new('2026-10-11')
            window.title.set_text('GTK saved reminder')
            window.notes.get_buffer().set_text('A real editor write')
            window.time.set_text('09:15')
            window.save_button.clicked()
            self.pump_until(lambda: not window.busy)
            items = self.store.list()
            self.assertEqual(len(items), 1)
            self.assertEqual((items[0]['title'], items[0]['due_date'], items[0]['due_time']),
                             ('GTK saved reminder', '2026-10-11', '09:15'))
            row = next(row for row in window.listbox.get_children() if hasattr(row, 'item'))
            window.listbox.select_row(row)
            self.assertEqual(window.ident, items[0]['id'])
            window.title.set_text('Edited in GTK')
            window.completed.set_active(True)
            window.save_button.clicked()
            self.pump_until(lambda: not window.busy)
            edited = self.store.list()[0]
            self.assertEqual(edited['title'], 'Edited in GTK')
            self.assertTrue(edited['completed'])
            window.show_completed.set_active(True)
            row = next(row for row in window.listbox.get_children() if hasattr(row, 'item'))
            window.listbox.select_row(row)
            window.delete_button.clicked()
            self.pump_until(lambda: not window.busy)
            self.assertEqual(self.store.list(), [])
            window.new()
            window.title.set_text('Invalid due date')
            window.date.set_text('2026-02-30')
            window.save_button.clicked()
            self.assertIn('Date', window.status.get_text())
            self.assertEqual(self.store.list(), [])
        finally:
            window.destroy()

    def test_gui_calendar_count_and_date_route(self):
        gui_guard()
        import gi
        gi.require_version('Gtk', '3.0')
        sys.path.insert(0, str(ROOT / 'integration/carpatic/panel/lib'))
        from carpatic_panel.flyout_cal import CalModel, CalView
        from carpatic_panel.theme import Theme, DEFAULT_LIGHT
        self.store.add('Pending today', due_date='2026-10-11')
        completed = self.store.add('Completed today', due_date='2026-10-11')
        self.store.update(completed['id'], completed=True)
        cal = CalModel(today=dt.date(2026, 10, 11), data=self.temporary.name)
        cal.events_in_grid = lambda: {}  # No personal calendar discovery in this reminder-specific test.
        closed = []
        with patch.dict(os.environ, {'PATH': str(CLI.parent) + ':' + os.environ.get('PATH', '')}):
            view = CalView(Theme(DEFAULT_LIGHT), cal, None, on_close=lambda: closed.append(True))
            self.pump_until(lambda: view.reminders_day == cal.selected)
            self.assertEqual(view.reminders_count, 1)
            # The store atomically replaces JSON; the open flyout must observe
            # external creation/completion without reopening or changing date.
            subprocess.run([str(CLI), 'add', 'External today', '--due-date', '2026-10-11'],
                           env=os.environ.copy(), check=True, capture_output=True)
            self.pump_until(lambda: view.reminders_count == 2)
            external = next(item for item in self.store.list() if item['title'] == 'External today')
            self.store.update(external['id'], completed=True)
            self.pump_until(lambda: view.reminders_count == 1)
            self.assertEqual(cal.selected, dt.date(2026, 10, 11))
            nodes = {node.id: node for node in view.build() if node.id}
            self.assertIn('cal:reminders', nodes)
            self.assertIn('cal:new-reminder', nodes)
            cal.select(dt.date(2026, 10, 12))
            view.refresh()
            self.pump_until(lambda: view.reminders_day == cal.selected)
            self.assertEqual(view.reminders_count, 0)
            with patch('carpatic_panel.flyout_cal.subprocess.Popen') as launch:
                view._open_reminders(True)
                self.pump_until(lambda: bool(closed))
                argv = launch.call_args.args[0]
                self.assertEqual(argv[1:], ['--date', '2026-10-12', '--new'])
            # Unrelated notifier ledger churn must not trigger store I/O.
            from gi.repository import Gio
            view._reminders_changed(view._reminders_monitor,
                Gio.File.new_for_path(str(self.store.path.parent / 'delivery-ledger.json')),
                None, Gio.FileMonitorEvent.CHANGED)
            self.assertEqual(view._reminders_timer, 0)
            target = Gio.File.new_for_path(str(self.store.path))
            view._reminders_changed(view._reminders_monitor, target, None, Gio.FileMonitorEvent.CHANGED)
            scheduled = view._reminders_timer
            view._reminders_changed(view._reminders_monitor, target, None, Gio.FileMonitorEvent.CHANGED)
            self.assertEqual(view._reminders_timer, scheduled)
            monitor = view._reminders_monitor
            view.dispose()
            view.dispose()  # Popup teardown and application finally may both run.
            self.assertTrue(monitor.is_cancelled())
            self.assertEqual(view._reminders_timer, 0)
            count = view.reminders_count
            self.store.add('After dismissal', due_date='2026-10-12')
            view._load_reminders()
            self.assertEqual(view.reminders_count, count)


    def test_gui_calendar_first_use_directory_and_shutdown(self):
        gui_guard()
        sys.path.insert(0, str(ROOT / 'integration/carpatic/panel/lib'))
        from carpatic_panel.flyout_cal import CalModel, CalView
        from carpatic_panel.theme import Theme, DEFAULT_LIGHT
        data = Path(self.temporary.name) / 'new-data'
        with patch.dict(os.environ, {'XDG_DATA_HOME': str(data),
                                    'PATH': str(CLI.parent) + ':' + os.environ.get('PATH', '')}):
            cal = CalModel(today=dt.date(2026, 10, 11), data=self.temporary.name)
            view = CalView(Theme(DEFAULT_LIGHT), cal, None)
            self.addCleanup(view.dispose)
            self.pump_until(lambda: view.reminders_count == 0)
            self.assertFalse(data.exists())
            subprocess.run([str(CLI), 'add', 'First note', '--due-date', '2026-10-11'],
                           check=True, capture_output=True)
            self.pump_until(lambda: view.reminders_count == 1)
            self.assertEqual(view._reminders_watch_dir, data / 'carpatic/reminders')
            view.dispose()
            # Completion from an already running load may be queued after dispose;
            # it must never redraw/rearm the closed view.
            view.refresh = lambda: self.fail('Closed calendar refreshed')
            self.pump_until(lambda: not view._reminders_busy)


if __name__ == '__main__':
    if GUI:
        gui_guard()
        sys.argv.remove('--gui')
    unittest.main(verbosity=2)
