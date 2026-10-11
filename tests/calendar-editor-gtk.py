#!/usr/bin/env python3
"""Actual calendar editor widgets, restricted to private Xvfb and session bus."""
import ast
import datetime as dt
import os
import stat
from pathlib import Path
import re
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
# Reuse the existing strict isolation gate without importing Notes or running it.
_guard_source = ROOT / 'tests/notes-gui.py'
_guard_tree = ast.parse(_guard_source.read_text())
_guard_node = next(node for node in _guard_tree.body if isinstance(node, ast.FunctionDef) and node.name == 'guard')
exec(compile(ast.Module(body=[_guard_node], type_ignores=[]), str(_guard_source), 'exec'))
guard()
sys.path.insert(0, str(ROOT / 'integration/carpatic/panel/lib'))
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib
from carpatic_panel import calendar_editor as editor, events, local_events

DAY = dt.date(2026, 10, 11)


def wait(predicate, seconds=6):
    deadline = time.monotonic() + seconds
    context = GLib.MainContext.default()
    while time.monotonic() < deadline:
        while context.pending(): context.iteration(False)
        if predicate(): return
        time.sleep(.01)
    raise AssertionError('Timed out waiting for actual calendar editor worker/widgets')


class CalendarEditorGTK(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='carpathian-calendar-editor-')
        self.data = Path(self.tmp.name) / 'carpatic'
        (self.data / 'calendar').mkdir(parents=True, mode=0o700)
        self.path = Path(events.write_event('Original', DAY, dt.time(9), dt.time(10), data=self.data))
        self.uid = self.path.stem + '@carpatic'
        self.selection = local_events.inspect_local(str(self.path), self.uid, data=self.data)
        self.window = None

    def tearDown(self):
        if self.window is not None:
            wait(lambda: not self.window.busy)
            if not self.window.closed: self.window.destroy()
        self.tmp.cleanup()

    def open(self, selection=None):
        self.window = editor.EventEditor(selection or self.selection, data=self.data)
        wait(lambda: self.window.ready and not self.window.busy)
        return self.window

    def test_save_preserves_uid_and_updates_actual_file(self):
        window = self.open()
        self.assertTrue(window.editable)
        window.title_entry.set_text('Updated from editor')
        window.date_entry.set_text('2026-10-12')
        window.start_entry.set_text('13:15')
        window.end_entry.set_text('14:45')
        window.save_event()
        wait(lambda: not window.busy)
        actual = local_events.inspect_local(str(self.path), self.uid, data=self.data)
        self.assertEqual(actual['uid'], self.uid)
        self.assertEqual(actual['title'], 'Updated from editor')
        self.assertEqual(actual['day'], DAY + dt.timedelta(days=1))
        self.assertEqual(actual['start'], dt.time(13, 15))
        self.assertEqual(actual['end'], dt.time(14, 45))
        self.assertEqual(window.snapshot['revision'], actual['revision'])
        self.assertIn('saved', window.status.get_text().lower())
        self.assertTrue(window.save_button.get_sensitive())

    def test_date_picker_changes_draft_before_save(self):
        window = self.open()
        old = self.path.read_bytes()
        window.date_button.clicked()
        self.assertIsNotNone(window.date_picker)
        window.date_picker.select_month(10, 2026); window.date_picker.select_day(20)
        window.date_picker.emit('day-selected-double-click')
        self.assertEqual(window.date_entry.get_text(), '2026-11-20')
        self.assertEqual(self.path.read_bytes(), old)

    def test_unchanged_save_preserves_whole_seconds(self):
        self.selection = local_events.update_local(str(self.path), self.uid, self.selection['revision'], 'Precise event', DAY, dt.time(9, 0, 45), dt.time(10, 0, 30), self.data)
        window = self.open()
        window.save_event(); wait(lambda: not window.busy)
        actual = local_events.inspect_local(str(self.path), self.uid, self.data)
        self.assertEqual(actual['start'], dt.time(9, 0, 45))
        self.assertEqual(actual['end'], dt.time(10, 0, 30))

    def test_changed_revision_preserves_draft_and_external_file(self):
        window = self.open()
        local_events.update_local(str(self.path), self.uid, self.selection['revision'], 'External edit', DAY, data=self.data)
        external = self.path.read_bytes()
        window.title_entry.set_text('Unsaved GUI draft')
        window.save_event()
        wait(lambda: not window.busy)
        self.assertEqual(window.title_entry.get_text(), 'Unsaved GUI draft')
        self.assertEqual(self.path.read_bytes(), external)
        self.assertIn('could not be saved', window.status.get_text().lower())
        self.assertFalse(window.closed)

    def test_cancelled_delete_keeps_event_and_window(self):
        window = self.open()
        before = self.path.read_bytes()
        with patch.object(editor, 'confirm_delete', return_value=False) as confirm:
            window.delete_event()
        confirm.assert_called_once_with(window)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(window.closed)
        self.assertFalse(window.busy)

    def test_confirmed_delete_removes_event_and_closes_window(self):
        window = self.open()
        with patch.object(editor, 'confirm_delete', return_value=True) as confirm:
            window.delete_event()
        confirm.assert_called_once_with(window)
        wait(lambda: window.closed)
        self.assertFalse(self.path.exists())

    def test_imported_event_read_only_controls_and_mutations(self):
        self.path.write_text(self.path.read_text().replace('-//Carpathian OS//panel//EN', '-//Imported calendar//EN'))
        before = self.path.read_bytes()
        window = self.open()
        self.assertFalse(window.editable)
        self.assertIn('read-only', window.status.get_text().lower())
        for widget in (window.title_entry, window.date_entry, window.start_entry, window.end_entry,
                       window.all_day, window.save_button, window.delete_button):
            self.assertFalse(widget.get_sensitive())
        with patch.object(editor, 'confirm_delete') as confirm:
            window.save_event(); window.delete_event()
        confirm.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(window.busy)

    def test_invalid_date_keeps_draft_and_file(self):
        window = self.open()
        before = self.path.read_bytes()
        window.title_entry.set_text('Draft retained')
        window.date_entry.set_text('2026-02-30')
        window.save_event()
        self.assertEqual(window.title_entry.get_text(), 'Draft retained')
        self.assertEqual(window.date_entry.get_text(), '2026-02-30')
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(window.busy)
        self.assertIn('valid date', window.status.get_text().lower())


    def test_keep_editing_blocks_actual_window_close_and_preserves_draft(self):
        window = self.open()
        before = self.path.read_bytes()
        window.title_entry.set_text('Keep this draft')
        with patch.object(editor, 'confirm_discard', return_value=False) as confirm:
            window.close()
            wait(lambda: confirm.called)
        confirm.assert_called_once_with(window)
        self.assertFalse(window.closed)
        self.assertEqual(window.title_entry.get_text(), 'Keep this draft')
        self.assertEqual(self.path.read_bytes(), before)

    def test_explicit_discard_allows_actual_window_close_without_saving(self):
        window = self.open()
        before = self.path.read_bytes()
        window.date_entry.set_text('2026-11-20')
        with patch.object(editor, 'confirm_discard', return_value=True) as confirm:
            window.close()
            wait(lambda: window.closed)
        confirm.assert_called_once_with(window)
        self.assertEqual(self.path.read_bytes(), before)

    def test_clean_and_saved_fields_close_without_discard_prompt(self):
        window = self.open()
        with patch.object(editor, 'confirm_discard') as confirm:
            self.assertFalse(window._request_close())
            window.title_entry.set_text('Saved before closing')
            window.save_event(); wait(lambda: not window.busy)
            window.close(); wait(lambda: window.closed)
        confirm.assert_not_called()
        self.assertEqual(local_events.inspect_local(str(self.path), self.uid, self.data)['title'], 'Saved before closing')

    def test_failed_save_retains_dirty_draft_for_close_confirmation(self):
        window = self.open()
        window.title_entry.set_text('Unsaved failure draft')
        with patch.object(editor, 'update_local', side_effect=local_events.CalendarError('injected save failure')):
            window.save_event(); wait(lambda: not window.busy)
        with patch.object(editor, 'confirm_discard', return_value=False) as confirm:
            self.assertTrue(window._request_close())
        confirm.assert_called_once_with(window)
        self.assertEqual(window.title_entry.get_text(), 'Unsaved failure draft')
        self.assertEqual(local_events.inspect_local(str(self.path), self.uid, self.data)['title'], 'Original')
        self.assertFalse(window.closed)

    def test_mutation_blocks_close_without_discard_prompt(self):
        window = self.open()
        window.title_entry.set_text('Draft during mutation')
        window._mutating = True
        try:
            with patch.object(editor, 'confirm_discard') as confirm:
                self.assertTrue(window._request_close())
            confirm.assert_not_called()
            self.assertFalse(window.closed)
        finally:
            window._mutating = False

    def test_real_discard_dialog_defaults_to_keep_editing(self):
        window = self.open()
        window.title_entry.set_text('Real dialog draft')
        observed = []
        deadline = time.monotonic() + 3
        def cancel_dialog():
            dialogs = [w for w in Gtk.Window.list_toplevels()
                       if isinstance(w, Gtk.MessageDialog) and w.get_transient_for() is window]
            if not dialogs:
                if time.monotonic() < deadline: return True
                observed.append('dialog missing')
                return False
            dialog = dialogs[0]
            default = dialog.get_default_widget()
            observed.append(default is not None and dialog.get_response_for_widget(default) == Gtk.ResponseType.CANCEL)
            dialog.response(Gtk.ResponseType.CANCEL)
            return False
        GLib.timeout_add(20, cancel_dialog)
        self.assertTrue(window._request_close())
        self.assertEqual(observed, [True])
        self.assertFalse(window.closed)
        self.assertEqual(window.title_entry.get_text(), 'Real dialog draft')

    def directory_sync_failure(self):
        real_fsync = os.fsync
        def fail_directory(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError('injected directory sync failure')
            return real_fsync(fd)
        return patch.object(local_events.os, 'fsync', side_effect=fail_directory)

    def test_uncertain_save_adopts_revision_and_allows_repeat_save(self):
        window = self.open()
        old_revision = window.snapshot['revision']
        window.title_entry.set_text('Visible but durability uncertain')
        with self.directory_sync_failure():
            window.save_event()
            wait(lambda: not window.busy)
        actual = local_events.inspect_local(str(self.path), self.uid, self.data)
        self.assertEqual(actual['title'], 'Visible but durability uncertain')
        self.assertEqual(window.snapshot, actual)
        self.assertNotEqual(window.snapshot['revision'], old_revision)
        status = window.status.get_text().lower()
        self.assertIn('restart', status)
        self.assertNotIn('could not be saved', status)
        self.assertFalse(window.closed)
        self.assertTrue(window.save_button.get_sensitive())
        window.title_entry.set_text('Saved after warning')
        window.save_event(); wait(lambda: not window.busy)
        actual = local_events.inspect_local(str(self.path), self.uid, self.data)
        self.assertEqual(actual['title'], 'Saved after warning')
        self.assertEqual(window.snapshot, actual)
        self.assertIn('saved', window.status.get_text().lower())

    def test_uncertain_delete_keeps_warning_and_disables_mutations(self):
        window = self.open()
        with self.directory_sync_failure(), patch.object(editor, 'confirm_delete', return_value=True):
            window.delete_event()
            wait(lambda: not window.busy)
        self.assertFalse(self.path.exists())
        self.assertFalse(window.closed)
        self.assertFalse(window.editable)
        status = window.status.get_text().lower()
        self.assertIn('restart', status)
        self.assertNotIn('could not be deleted', status)
        for widget in (window.title_entry, window.date_entry, window.date_button,
                       window.start_entry, window.end_entry, window.all_day,
                       window.save_button, window.delete_button):
            self.assertFalse(widget.get_sensitive())
        with patch.object(editor, 'confirm_delete') as confirm:
            window.save_event(); window.delete_event()
        confirm.assert_not_called()
        self.assertFalse(window.busy)
        self.assertFalse(self.path.exists())


if __name__ == '__main__':
    unittest.main()
