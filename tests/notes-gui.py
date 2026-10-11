#!/usr/bin/env python3
"""Actual GTK widgets on verified private Xvfb and a private dbus-run-session.

Run with WAYLAND_DISPLAY unset, CARPATIC_XVFB_TEST=1 and
CARPATIC_PRIVATE_DBUS_TEST=1 inside an owned dbus-run-session.
Injected write failures are fault controls, not native storage qualification.
"""
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


def guard():
    if 'WAYLAND_DISPLAY' in os.environ or os.environ.get('XDG_CURRENT_DESKTOP') == 'COSMIC':
        raise SystemExit('Refuse host desktop environment')
    runtime = Path(os.environ.get('XDG_RUNTIME_DIR', '/run/user'))
    if (not runtime.is_absolute() or runtime.is_symlink() or not runtime.is_dir()
            or str(runtime).startswith('/run/user/') or runtime.stat().st_uid != os.getuid()
            or runtime.stat().st_mode & 0o777 != 0o700
            or os.environ.get('GSETTINGS_BACKEND') != 'memory'
            or os.environ.get('GIO_USE_VFS') != 'local'):
        raise SystemExit('Require owned private runtime, memory settings, and local test VFS')
    match = re.fullmatch(r':([1-9][0-9]*)(?:\.0)?', os.environ.get('DISPLAY', ''))
    verified = False
    if match and os.environ.get('CARPATIC_XVFB_TEST') == '1':
        target = (':' + match.group(1)).encode()
        for proc in Path('/proc').iterdir():
            if not proc.name.isdigit(): continue
            try:
                args = (proc / 'cmdline').read_bytes().split(b'\0')
                if proc.stat().st_uid == os.getuid() and args and Path(os.fsdecode(args[0])).name == 'Xvfb' and target in args:
                    verified = True; break
            except OSError: pass
    ancestor = os.getppid()
    private_bus = False
    while ancestor > 1:
        try:
            proc = Path('/proc') / str(ancestor)
            args = (proc / 'cmdline').read_bytes().split(b'\0')
            if args and Path(os.fsdecode(args[0])).name == 'dbus-run-session':
                private_bus = True; break
            ancestor = int(re.search(r'^PPid:\s*(\d+)', (proc / 'status').read_text(), re.M).group(1))
        except (OSError, AttributeError): break
    if not verified or not private_bus or os.environ.get('CARPATIC_PRIVATE_DBUS_TEST') != '1' or not os.environ.get('DBUS_SESSION_BUS_ADDRESS'):
        raise SystemExit('Requires live owned private Xvfb plus private dbus-run-session ancestor')


guard()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'integration/carpatic/notes/lib'))
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib
from carpatic_notes.app import NotesApplication, NotesWindow, export_text
from carpatic_notes.store import Store, StoreError


def wait(predicate, seconds=6):
    deadline = time.monotonic() + seconds
    context = GLib.MainContext.default()
    while time.monotonic() < deadline:
        while context.pending(): context.iteration(False)
        if predicate(): return
        time.sleep(.01)
    raise AssertionError('Timed out waiting for genuine GTK/worker state')


def answer(response):
    def respond():
        dialogs = [w for w in Gtk.Window.list_toplevels() if isinstance(w, Gtk.MessageDialog) and w.get_visible()]
        if not dialogs: return True
        if len(dialogs) != 1: raise AssertionError('Ambiguous dialog')
        dialogs[0].response(response)
        return False
    return GLib.timeout_add(10, respond)


class NotesGUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = NotesApplication()
        cls.application.register(None)
    def setUp(self):
        self.data = tempfile.TemporaryDirectory(prefix='carpathian-notes-gui-')
        self.previous_data = os.environ.get('XDG_DATA_HOME')
        os.environ['XDG_DATA_HOME'] = self.data.name
        self.window = NotesWindow(self.application)
        self.release = None
        wait(lambda: self.window.store is not None)
    def tearDown(self):
        if self.release: self.release.set()
        if not self.window.closed: self.window.destroy()
        self.window.worker.shutdown(wait=True)
        self.data.cleanup()
        if self.previous_data is None: os.environ.pop('XDG_DATA_HOME', None)
        else: os.environ['XDG_DATA_HOME'] = self.previous_data
    def edit(self, title, body):
        self.window.title_entry.set_text(title)
        self.window.body.get_buffer().set_text(body)
    def save(self):
        self.window.save_button.emit('clicked')
        wait(lambda: not self.window.saving and self.window.note is not None)
    def test_unicode_save_reopen_search_trash_restore(self):
        self.window.new_button.emit('clicked')
        self.edit('Munții 🏔', 'Bună ziua\n日本語 Ελληνικά')
        self.save()
        ident = self.window.note.id
        self.assertFalse(self.window.dirty)
        saved = Store(self.window.store.path).get(ident)
        self.assertEqual(saved.body, 'Bună ziua\n日本語 Ελληνικά')
        self.window.new_button.emit('clicked')
        wait(lambda: len(self.window.list.get_children()) == 1)
        self.window.list.select_row(self.window.list.get_children()[0])
        wait(lambda: self.window.note is not None)
        self.assertEqual(self.window.contents(), (saved.title, saved.body))
        self.window.search.set_text('missing-query')
        wait(lambda: not self.window.list.get_children())
        self.assertEqual(self.window.contents(), (saved.title, saved.body))
        self.window.search.set_text('日本語')
        wait(lambda: len(self.window.list.get_children()) == 1)
        self.window.trash_button.emit('clicked')
        wait(lambda: not self.window.saving and self.window.note.trashed)
        self.assertFalse(self.window.body.get_editable())
        self.window.trash_view.set_active(True)
        wait(lambda: len(self.window.list.get_children()) == 1)
        self.window.trash_button.emit('clicked')
        wait(lambda: not self.window.saving and not self.window.note.trashed)
        self.assertTrue(self.window.body.get_editable())
        self.assertFalse(Store(self.window.store.path).get(ident).trashed)
    def test_dirty_navigation_cancel_discard_save(self):
        self.edit('One', 'original'); self.save()
        self.edit('One', 'draft-cancel')
        answer(Gtk.ResponseType.CANCEL); self.window.new_button.emit('clicked')
        self.assertEqual(self.window.contents(), ('One', 'draft-cancel'))
        answer(Gtk.ResponseType.REJECT); self.window.new_button.emit('clicked')
        self.assertEqual(self.window.contents(), ('', ''))
        self.edit('Saved on navigation', 'draft')
        answer(Gtk.ResponseType.ACCEPT); self.window.new_button.emit('clicked')
        wait(lambda: not self.window.saving and self.window.contents() == ('', ''))
        self.assertEqual(len(Store(self.window.store.path).list()), 2)
    def test_dirty_close_cancel_save_and_discard(self):
        self.edit('Keep', 'text')
        answer(Gtk.ResponseType.CANCEL); self.window.on_close()
        self.assertFalse(self.window.closed)
        answer(Gtk.ResponseType.ACCEPT); self.window.on_close()
        wait(lambda: self.window.closed)
        self.assertEqual(Store(Path(self.data.name) / 'carpathian/notes/notes.sqlite3').list()[0].title, 'Keep')
        self.window.worker.shutdown(wait=True)
        self.window = NotesWindow(self.application)
        wait(lambda: self.window.store is not None)
        self.edit('Discard', 'unsaved')
        answer(Gtk.ResponseType.REJECT); self.window.on_close()
        self.assertTrue(self.window.closed)
        self.assertEqual(len(Store(Path(self.data.name) / 'carpathian/notes/notes.sqlite3').list()), 1)
    def test_injected_write_failure_preserves_draft(self):
        self.edit('Original', 'persisted'); self.save()
        old_revision = self.window.note.revision
        self.edit('Original', 'must survive failed write')
        def fail(*args, **kwargs): raise StoreError('Injected test write failure')
        self.window.store.save = fail
        self.window.save_button.emit('clicked')
        wait(lambda: not self.window.saving)
        self.assertEqual(self.window.contents(), ('Original', 'must survive failed write'))
        self.assertTrue(self.window.dirty)
        self.assertEqual(self.window.note.revision, old_revision)
        self.assertIn('could not be saved', self.window.status.get_text())
    def test_real_revision_conflict_preserves_draft_and_reopens(self):
        self.edit('Conflict', 'original'); self.save()
        ident, revision = self.window.note.id, self.window.note.revision
        external = Store(self.window.store.path)
        external.save(ident, 'Conflict', 'another writer', expected_revision=revision)
        self.edit('Conflict', 'my unsaved draft')
        self.window.save_button.emit('clicked')
        wait(lambda: not self.window.saving)
        self.assertTrue(self.window.dirty)
        self.assertEqual(self.window.contents(), ('Conflict', 'my unsaved draft'))
        self.assertTrue(self.window.recovery.get_visible())
        answer(Gtk.ResponseType.CANCEL); self.window.recovery.emit('clicked')
        self.assertEqual(self.window.contents(), ('Conflict', 'my unsaved draft'))
        answer(Gtk.ResponseType.REJECT); self.window.recovery.emit('clicked')
        wait(lambda: self.window.contents() == ('Conflict', 'another writer'))
        self.assertFalse(self.window.dirty)
        self.assertFalse(self.window.recovery.get_visible())

    def test_corrupt_database_preserved_and_draft_export_still_works(self):
        database = self.window.store.path
        self.window.destroy(); self.window.worker.shutdown(wait=True)
        damaged = b'corrupt database fixture; preserve these bytes'
        database.write_bytes(damaged)
        self.window = NotesWindow(self.application)
        wait(lambda: 'could not be opened' in self.window.status.get_text())
        self.assertIsNone(self.window.store)
        self.assertEqual(database.read_bytes(), damaged)
        self.export_draft()
        self.assertEqual(database.read_bytes(), damaged)
        self.assertFalse(self.window.save_button.get_sensitive())

    def test_actual_export_keeps_unsaved_unicode_draft(self):
        self.export_draft()

    def test_actual_export_overwrite_confirmation(self):
        self.export_draft(overwrite=True)

    def export_draft(self, overwrite=False):
        self.edit('Export 🏔', 'unsaved 日本語')
        destination = Path(self.data.name) / 'export.txt'
        confirmed = []
        if overwrite: destination.write_text('prior chosen file')
        def confirm():
            dialogs = [w for w in Gtk.Window.list_toplevels() if isinstance(w, Gtk.MessageDialog) and w.get_visible()]
            if not dialogs: return True
            confirmed.append(True)
            dialogs[0].response(Gtk.ResponseType.ACCEPT)
            return False
        confirm_source = GLib.timeout_add(10, confirm) if overwrite else None
        def choose():
            dialogs = [w for w in Gtk.Window.list_toplevels() if isinstance(w, Gtk.FileChooserDialog) and w.get_visible()]
            if not dialogs: return True
            dialogs[0].set_current_folder(self.data.name)
            dialogs[0].set_current_name(destination.name)
            GLib.timeout_add(100, lambda: (dialogs[0].response(Gtk.ResponseType.ACCEPT), False)[1])
            return False
        GLib.timeout_add(10, choose)
        self.window.export_button.emit('clicked')
        wait(lambda: destination.exists() and destination.read_text() == 'Export 🏔\n\nunsaved 日本語')
        if confirm_source and not confirmed: GLib.source_remove(confirm_source)
        if overwrite: self.assertTrue(confirmed, 'genuine overwrite confirmation must appear')
        self.assertEqual(destination.read_text(), 'Export 🏔\n\nunsaved 日本語')
        self.assertTrue(self.window.dirty)
        self.assertEqual(self.window.contents(), ('Export 🏔', 'unsaved 日本語'))

    def test_atomic_export_replace_failure_preserves_prior_file(self):
        destination = Path(self.data.name) / 'chosen.txt'
        destination.write_text('existing contents')
        with patch('carpatic_notes.app.os.replace', side_effect=OSError('Injected replace failure')):
            with self.assertRaises(OSError): export_text(destination, 'replacement 日本語')
        self.assertEqual(destination.read_text(), 'existing contents')
        self.assertEqual(sorted(p.name for p in Path(self.data.name).iterdir()), ['carpathian', 'chosen.txt'])

    def test_old_async_save_keeps_newer_typing(self):
        self.edit('Race', 'original'); self.save()
        self.edit('Race', 'submitted')
        started = threading.Event(); self.release = threading.Event()
        original = self.window.store.save
        def blocked(*args, **kwargs):
            started.set()
            if not self.release.wait(5): raise StoreError('Test synchronization timeout')
            return original(*args, **kwargs)
        self.window.store.save = blocked
        self.window.save_button.emit('clicked')
        wait(started.is_set)
        self.edit('Race', 'newer text')
        self.release.set(); wait(lambda: not self.window.saving)
        self.assertTrue(self.window.dirty)
        self.assertEqual(self.window.contents(), ('Race', 'newer text'))
        self.assertEqual(Store(self.window.store.path).get(self.window.note.id).body, 'submitted')
    def test_actual_narrow_wide_sidebar_and_manual_toggle(self):
        self.window.resize(600, 500)
        wait(lambda: self.window.last_width < 700 and not self.window.side.get_visible())
        self.window.nav.emit('clicked')
        self.assertTrue(self.window.side.get_visible())
        self.window.resize(900, 620)
        wait(lambda: self.window.last_width >= 700 and self.window.side.get_visible())
        self.window.nav.emit('clicked')
        self.window.resize(920, 620)
        wait(lambda: self.window.last_width >= 920)
        self.assertFalse(self.window.side.get_visible())


if __name__ == '__main__': unittest.main(verbosity=2)
