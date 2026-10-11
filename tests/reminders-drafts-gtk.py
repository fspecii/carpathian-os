#!/usr/bin/env python3
"""Actual Reminders draft protection on an owned private Xvfb/session bus."""
import ast
import os
from pathlib import Path
import re
import sys
import stat
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
tree=ast.parse((ROOT/'tests/notes-gui.py').read_text())
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='guard'],type_ignores=[]),'private GTK guard','exec'))
guard()
_import_data=tempfile.TemporaryDirectory(prefix='reminders-draft-import-')
os.environ['XDG_DATA_HOME']=_import_data.name
sys.path.insert(0,str(ROOT/'integration/carpatic/reminders/lib'))
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,Gio,GLib
from carpatic_reminders import app as editor
from carpatic_reminders.store import Store,StoreError


def pump(predicate):
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        while GLib.MainContext.default().pending():GLib.MainContext.default().iteration(False)
        if predicate():return
        time.sleep(.01)
    raise AssertionError('Reminder widget/storage timeout')


class Drafts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application=Gtk.Application(application_id='org.carpathian.Reminders.DraftTest',flags=Gio.ApplicationFlags.NON_UNIQUE)
        cls.application.register(None)
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='reminders-drafts-')
        self.env=patch.dict(os.environ,{'XDG_DATA_HOME':self.tmp.name});self.env.start()
        self.store=Store();self.item=self.store.add(title='Saved item',due_date='2026-10-11')
        self.window=editor.RemindersWindow(self.application)
        self.window.reload();pump(lambda:not self.window.busy)
    def tearDown(self):
        pump(lambda:not self.window.busy)
        if not self.window.closed:self.window.destroy()
        self.env.stop();self.tmp.cleanup()
    def draft(self):
        self.window.title.set_text('Unsaved draft')
        self.window.notes.get_buffer().set_text('Do not lose these notes')
    def row(self):return next(row for row in self.window.listbox.get_children() if hasattr(row,'item'))
    def test_new_keep_editing_preserves_fields(self):
        self.draft();before=self.window._draft()
        with patch.object(editor,'confirm_discard',return_value=False) as confirm:self.window.new()
        confirm.assert_called_once_with(self.window);self.assertEqual(self.window._draft(),before)
    def test_new_explicit_discard_clears_fields(self):
        self.draft()
        with patch.object(editor,'confirm_discard',return_value=True) as confirm:self.window.new()
        confirm.assert_called_once_with(self.window);self.assertEqual(self.window.title.get_text(),'')
    def test_selection_keep_editing_preserves_draft_and_identity(self):
        self.draft();before=self.window._draft()
        with patch.object(editor,'confirm_discard',return_value=False) as confirm:self.window.listbox.select_row(self.row())
        confirm.assert_called_once_with(self.window);self.assertEqual(self.window._draft(),before);self.assertIsNone(self.window.ident)
    def test_selection_explicit_discard_loads_selected_item(self):
        self.draft()
        with patch.object(editor,'confirm_discard',return_value=True):self.window.listbox.select_row(self.row())
        self.assertEqual(self.window.title.get_text(),'Saved item');self.assertEqual(self.window.ident,self.item['id'])
    def test_actual_close_keep_editing_then_discard(self):
        self.draft()
        with patch.object(editor,'confirm_discard',return_value=False) as confirm:
            self.window.close();pump(lambda:confirm.called)
        self.assertFalse(self.window.closed);self.assertEqual(self.window.title.get_text(),'Unsaved draft')
        with patch.object(editor,'confirm_discard',return_value=True):
            self.window.close();pump(lambda:self.window.closed)
    def test_external_new_keep_editing_preserves_day_and_fields(self):
        self.draft();before=self.window._draft();old_day=self.window.day
        with patch.object(editor,'confirm_discard',return_value=False):self.window.open_requested('2026-10-12',True)
        self.assertEqual(self.window._draft(),before);self.assertEqual(self.window.day,old_day)
    def test_failed_save_does_not_consume_queued_external_new_or_prompt(self):
        self.draft();before=self.window._draft();entered=threading.Event();release=threading.Event()
        def fail(**fields):
            entered.set()
            if not release.wait(3):raise AssertionError('Fixture not released')
            raise StoreError('Injected save failure')
        try:
            with patch.object(self.window.store,'add',side_effect=fail),patch.object(editor,'confirm_discard') as confirm:
                self.window.save();pump(entered.is_set)
                self.window.open_requested('2026-10-12',True)
                release.set();pump(lambda:not self.window.busy)
            confirm.assert_not_called();self.assertEqual(self.window._draft(),before)
            self.assertEqual(self.window.pending_request,('2026-10-12',True));self.assertIn('failure',self.window.status.get_text())
        finally:release.set()
    def test_busy_close_blocks_without_dialog(self):
        self.window.busy=True
        try:
            with patch.object(editor,'confirm_discard') as confirm:self.window.close()
            while GLib.MainContext.default().pending():GLib.MainContext.default().iteration(False)
            confirm.assert_not_called();self.assertFalse(self.window.closed)
        finally:self.window.busy=False
    def test_successful_save_then_navigation_needs_no_discard_prompt(self):
        self.draft();self.window.save();pump(lambda:not self.window.busy)
        with patch.object(editor,'confirm_discard') as confirm:self.window.new();self.window.open_requested('2026-10-12',True)
        pump(lambda:not self.window.busy);confirm.assert_not_called()
        self.assertTrue(any(item['title']=='Unsaved draft' for item in self.store.list()))

    def test_uncertain_new_save_adopts_id_and_repeat_save_updates_without_duplicate(self):
        self.draft();before=self.window._draft();real_sync=os.fsync
        def fail_directory(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):raise OSError('injected directory sync failure')
            return real_sync(fd)
        with patch('carpatic_reminders.store.os.fsync',side_effect=fail_directory):
            self.window.save();self.window.open_requested('2026-10-12',True);pump(lambda:not self.window.busy)
        self.assertEqual(self.window.pending_request,('2026-10-12',True))
        ident=self.window.ident
        self.assertIsNotNone(ident);self.assertEqual(self.window._draft(),before)
        self.assertIn('restart',self.window.status.get_text().lower())
        self.assertEqual(len(self.store.list()),2)
        with patch.object(editor,'confirm_discard') as confirm:self.assertTrue(self.window._guard_dirty())
        confirm.assert_not_called()
        self.window.title.set_text('Updated after uncertain commit')
        self.window.save();pump(lambda:not self.window.busy)
        items=self.store.list();self.assertEqual(len(items),2)
        self.assertEqual(next(item for item in items if item['id']==ident)['title'],'Updated after uncertain commit')
    def test_initial_completed_reminder_is_one_atomic_write(self):
        self.draft();self.window.completed.set_active(True)
        with patch.object(self.window.store,'_write',wraps=self.window.store._write) as write:
            self.window.save();pump(lambda:not self.window.busy)
        self.assertEqual(write.call_count,1)
        item=next(item for item in self.store.list() if item['title']=='Unsaved draft')
        self.assertTrue(item['completed'])
    def test_save_commit_followed_by_list_failure_retains_id_and_clean_baseline(self):
        self.draft();before=self.window._draft()
        with patch.object(self.window.store,'list',side_effect=StoreError('Injected list failure')):
            self.window.save();pump(lambda:not self.window.busy)
        ident=self.window.ident;self.assertIsNotNone(ident);self.assertEqual(self.window._draft(),before)
        with patch.object(editor,'confirm_discard') as confirm:self.assertTrue(self.window._guard_dirty())
        confirm.assert_not_called()
        self.assertEqual(len(self.store.list()),2)
        self.assertIn('refresh',self.window.status.get_text().lower())
        self.window.save();pump(lambda:not self.window.busy)
        self.assertEqual(len(self.store.list()),2)


    def test_delete_committed_then_list_failure_clears_deleted_identity(self):
        self.window.listbox.select_row(self.row())
        self.assertEqual(self.window.ident,self.item['id'])
        with patch.object(self.window.store,'list',side_effect=StoreError('Injected list failure')):
            self.window.delete();pump(lambda:not self.window.busy)
        self.assertIsNone(self.window.ident)
        self.assertEqual(self.window.title.get_text(),'')
        self.assertFalse(self.window.delete_button.get_sensitive())
        self.assertEqual(self.store.list(),[])
        self.assertIn('deleted',self.window.status.get_text().lower())
        self.assertIn('refresh',self.window.status.get_text().lower())
    def test_uncertain_delete_clears_identity_and_keeps_warning(self):
        self.window.listbox.select_row(self.row());real_sync=os.fsync
        def fail_directory(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):raise OSError('injected directory sync failure')
            return real_sync(fd)
        with patch('carpatic_reminders.store.os.fsync',side_effect=fail_directory):
            self.window.delete();pump(lambda:not self.window.busy)
        self.assertIsNone(self.window.ident);self.assertFalse(self.window.delete_button.get_sensitive())
        self.assertEqual(self.store.list(),[]);self.assertEqual(self.window.items,[])
        self.assertIn('restart',self.window.status.get_text().lower())
        self.assertFalse(self.window.closed)
    def test_completion_toggle_preserves_unsaved_title_and_updates_baseline(self):
        self.window.listbox.select_row(self.row())
        self.window.title.set_text('Unsaved selected title')
        self.window.toggle(self.item['id'],True);pump(lambda:not self.window.busy)
        self.assertEqual(self.window.title.get_text(),'Unsaved selected title')
        self.assertTrue(self.window.completed.get_active())
        self.assertTrue(self.store.list()[0]['completed'])
        self.assertEqual(self.store.list()[0]['title'],'Saved item')
        with patch.object(editor,'confirm_discard',return_value=False) as confirm:self.assertFalse(self.window._guard_dirty())
        confirm.assert_called_once_with(self.window)
        self.window.title.set_text('Saved item')
        with patch.object(editor,'confirm_discard') as confirm:self.assertTrue(self.window._guard_dirty())
        confirm.assert_not_called()


if __name__=='__main__':
    try:unittest.main()
    finally:_import_data.cleanup()
