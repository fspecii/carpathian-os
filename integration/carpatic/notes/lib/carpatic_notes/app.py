"""On-demand plain-text Notes. All persistent work runs on one worker thread."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import tempfile
import gi

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, Gio, GLib
from .store import Store, StoreError, ConflictError, ValidationError


def export_text(filename, text):
    """Replace a chosen export only after the complete UTF-8 file is written."""
    target = Path(filename)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent,
                                         prefix='.carpathian-notes-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def accessible(widget, name):
    widget.get_accessible().set_name(name)
    return widget


class NotesWindow(Gtk.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application, title='Notes')
        self.set_icon_name('accessories-text-editor')
        self.set_default_size(900, 620)
        self.set_size_request(360, 360)
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='notes-store')
        self.store = None
        self.note = None
        self.dirty = False
        self.loading_editor = False
        self.saving = False
        self.moving = False
        self.editor_generation = 0
        self.closed = False
        self.query_generation = 0
        self.selection_guard = False
        self.list_manual = None
        self.last_width = 0
        self.pending_layout = False
        self.pending_dialog = False
        self._build()
        self.connect('delete-event', self.on_close)
        self.connect('key-press-event', self.on_key)
        self.connect('destroy', self.on_destroy)
        self.show_all()
        self.status.set_text('Opening your notes…')
        self.submit(lambda: Store(), self.opened)

    def _build(self):
        header = Gtk.HeaderBar(title='Notes', show_close_button=True)
        self.set_titlebar(header)
        self.nav = self.button('Show or hide note list', 'view-list-symbolic', self.toggle_list)
        header.pack_start(self.nav)
        self.new_button = self.button('New note (Ctrl+N)', 'document-new-symbolic', self.new_note)
        header.pack_start(self.new_button)
        self.export_button = self.button('Export note as text', 'document-save-as-symbolic', self.export_note)
        header.pack_end(self.export_button)
        self.trash_button = self.button('Move note to Trash', 'user-trash-symbolic', self.trash_note)
        header.pack_end(self.trash_button)
        self.save_button = self.button('Save note (Ctrl+S)', 'document-save-symbolic', self.save_note)
        header.pack_end(self.save_button)
        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(main)
        self.root = Gtk.Box()
        main.pack_start(self.root, True, True, 0)
        self.root.connect('size-allocate', self.allocated)
        self.side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.side.set_size_request(240, -1)
        self.side.set_margin_start(10); self.side.set_margin_end(10)
        self.side.set_margin_top(12); self.side.set_margin_bottom(12)
        self.root.pack_start(self.side, False, False, 0)
        self.search = accessible(Gtk.SearchEntry(), 'Search notes')
        self.search.set_placeholder_text('Search notes')
        self.search.connect('search-changed', lambda *_: self.refresh())
        self.side.pack_start(self.search, False, False, 0)
        self.trash_view = accessible(Gtk.CheckButton(label='Show Trash'), 'Show Trash')
        self.trash_view.connect('toggled', self.changed_view)
        self.side.pack_start(self.trash_view, False, False, 0)
        self.list = accessible(Gtk.ListBox(), 'Notes')
        self.list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list.connect('row-selected', self.selected)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.list)
        self.side.pack_start(scroll, True, True, 0)
        self.empty = Gtk.Label(label='No notes yet. Create your first note.')
        self.empty.set_line_wrap(True)
        self.side.pack_start(self.empty, False, False, 0)
        editor = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        editor.set_margin_start(16); editor.set_margin_end(16)
        editor.set_margin_top(16); editor.set_margin_bottom(12)
        self.root.pack_start(editor, True, True, 0)
        self.title_entry = accessible(Gtk.Entry(), 'Note title')
        self.title_entry.set_placeholder_text('Title')
        self.title_entry.connect('changed', self.edited)
        editor.pack_start(self.title_entry, False, False, 0)
        self.body = accessible(Gtk.TextView(), 'Note text')
        self.body.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.body.set_left_margin(4); self.body.set_right_margin(4)
        self.body.get_buffer().connect('changed', self.edited)
        text_scroll = Gtk.ScrolledWindow()
        text_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        text_scroll.add(self.body)
        editor.pack_start(text_scroll, True, True, 0)
        self.status = accessible(Gtk.Label(xalign=0), 'Note status')
        self.status.set_line_wrap(True)
        self.status.set_margin_start(16); self.status.set_margin_end(16)
        self.status.set_margin_bottom(10)
        main.pack_start(self.status, False, False, 0)
        self.recovery = accessible(Gtk.Button(label='Reopen saved note'), 'Reopen saved note')
        self.recovery.set_no_show_all(True)
        self.recovery.connect('clicked', lambda *_: self.guard_dirty(lambda: self.read_note(self.note.id)) if self.note else None)
        main.pack_start(self.recovery, False, False, 0)
        self.update_controls()

    @staticmethod
    def button(name, icon, callback):
        button = accessible(Gtk.Button(), name)
        button.add(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON))
        button.set_tooltip_text(name)
        button.connect('clicked', lambda *_: callback())
        return button

    def submit(self, operation, completed):
        future = self.worker.submit(operation)
        def done(result):
            try:
                value, error = result.result(), None
            except Exception as exception:
                value, error = None, exception
            GLib.idle_add(deliver, value, error)
        def deliver(value, error):
            if not self.closed:
                completed(value, error)
            return False
        future.add_done_callback(done)

    def opened(self, store, error):
        if error:
            self.error('Your notes could not be opened. Check available disk space and access to your data folder. You can still write and export a draft.', error)
        else:
            self.store = store
            self.status.set_text('Create a note or select one from the list.')
            self.refresh()
        self.update_controls()

    def error(self, message, error):
        # Store exceptions must describe operation failures without exposing text.
        if isinstance(error, ConflictError):
            message = 'This note changed elsewhere. Your draft is preserved. Export it, then reopen the saved note to see the latest version.'
            self.recovery.show()
        elif isinstance(error, ValidationError):
            message = 'The note could not be saved. Shorten its title or text and try again. Your draft is preserved.'
        elif isinstance(error, StoreError):
            message += ' ' + str(error)
        self.status.set_text(message)

    def contents(self):
        buffer = self.body.get_buffer()
        return self.title_entry.get_text(), buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)

    def edited(self, *_):
        if self.loading_editor:
            return
        current = self.contents()
        baseline = (self.note.title, self.note.body) if self.note else ('', '')
        self.dirty = current != baseline
        self.status.set_text('Unsaved changes' if self.dirty else ('Saved' if self.note else 'New note'))
        self.update_controls()

    def update_controls(self):
        trashed = bool(self.note and self.note.trashed)
        self.title_entry.set_editable(not trashed and not self.moving)
        self.body.set_editable(not trashed and not self.moving)
        self.save_button.set_sensitive(bool(self.store) and self.dirty and not self.saving and not trashed)
        self.trash_button.set_sensitive(bool(self.store and self.note) and not self.saving)
        name = 'Restore note' if trashed else 'Move note to Trash'
        self.trash_button.set_tooltip_text(name)
        accessible(self.trash_button, name)
        self.trash_button.get_child().set_from_icon_name('edit-undo-symbolic' if trashed else 'user-trash-symbolic', Gtk.IconSize.BUTTON)

    def load_editor(self, note):
        self.editor_generation += 1
        self.loading_editor = True
        self.note = note
        self.recovery.hide()
        self.title_entry.set_text(note.title if note else '')
        self.body.get_buffer().set_text(note.body if note else '')
        self.loading_editor = False
        self.dirty = False
        self.status.set_text('In Trash — restore to edit' if note and note.trashed else ('Saved' if note else 'New note'))
        self.update_controls()

    def refresh(self):
        if not self.store:
            return
        self.query_generation += 1
        generation = self.query_generation
        query, trashed = self.search.get_text(), self.trash_view.get_active()
        self.submit(lambda: self.store.list(query=query, trashed=trashed),
                    lambda notes, error: self.listed(notes, error, generation))

    def listed(self, notes, error, generation):
        if generation != self.query_generation:
            return
        if error:
            self.error('The note list could not be read. Your open draft is preserved. Try searching again, or export the draft.', error)
            return
        self.selection_guard = True
        for row in self.list.get_children():
            self.list.remove(row)
        selected = None
        for note in notes:
            row = Gtk.ListBoxRow()
            row.note_id = note.id
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            box.set_margin_top(9); box.set_margin_bottom(9)
            box.set_margin_start(8); box.set_margin_end(8)
            title = Gtk.Label(label=note.title or 'Untitled note', xalign=0)
            title.set_ellipsize(3)
            box.pack_start(title, False, False, 0)
            preview = Gtk.Label(label=note.body.replace('\n', ' ')[:90], xalign=0)
            preview.set_ellipsize(3)
            box.pack_start(preview, False, False, 0)
            row.add(box); self.list.add(row)
            if self.note and note.id == self.note.id:
                selected = row
        self.list.show_all()
        if selected:
            self.list.select_row(selected)
        self.selection_guard = False
        self.empty.set_text('No matching notes.' if self.search.get_text() else ('Trash is empty.' if self.trash_view.get_active() else 'No notes yet. Create your first note.'))
        self.empty.set_visible(not notes)

    def selected(self, _list, row):
        if self.selection_guard or row is None or (self.note and row.note_id == self.note.id):
            return
        note_id = row.note_id
        self.guard_dirty(lambda: self.read_note(note_id), cancelled=self.reselect)

    def reselect(self):
        self.selection_guard = True
        selected = next((row for row in self.list.get_children() if self.note and row.note_id == self.note.id), None)
        self.list.select_row(selected)
        self.selection_guard = False

    def read_note(self, note_id):
        # Keep typing safe while a read is in flight: apply only if the draft did
        # not change after the user chose navigation.
        snapshot = self.contents()
        self.editor_generation += 1
        generation = self.editor_generation
        self.submit(lambda: self.store.get(note_id),
                    lambda note, error: self.read_done(note, error, snapshot, generation))

    def read_done(self, note, error, snapshot, generation):
        if generation != self.editor_generation: return
        if error or note is None:
            self.error('The note could not be opened. Your draft is preserved.', error)
            self.reselect()
        elif self.contents() != snapshot:
            self.status.set_text('Your new edits are preserved. Select the note again when ready.')
            self.reselect()
        else:
            self.load_editor(note)

    def new_note(self):
        self.guard_dirty(lambda: (self.load_editor(None), self.reselect(), self.title_entry.grab_focus()))

    def changed_view(self, *_):
        # Switching the list filter never replaces the current editor.
        self.refresh()

    def save_note(self, completed=None):
        if self.saving or not self.store or (self.note and self.note.trashed):
            if completed: completed(False)
            return
        title, body = self.contents()
        old = self.note
        self.saving = True
        self.status.set_text('Saving…'); self.update_controls()
        operation = (lambda: self.store.save(old.id, title, body, expected_revision=old.revision)) if old else (lambda: self.store.create(title=title, body=body))
        def saved(note, error):
            self.saving = False
            if error:
                self.error('The note could not be saved. Your draft is preserved. Check disk space and access, then try again or export it.', error)
                self.update_controls()
                if completed: completed(False)
                return
            self.note = note
            # A successful older snapshot must never mark newer typing saved.
            self.dirty = self.contents() != (title, body)
            self.status.set_text('Unsaved changes' if self.dirty else 'Saved')
            self.update_controls(); self.refresh()
            if completed: completed(not self.dirty)
        self.submit(operation, saved)

    def guard_dirty(self, action, cancelled=None):
        if self.saving:
            self.status.set_text('Wait for this save to finish before switching notes.')
            if cancelled: cancelled()
            return
        if not self.dirty:
            action(); return
        if self.pending_dialog:
            return
        self.pending_dialog = True
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                   text='Save changes to this note?', secondary_text='Your unsaved text will be lost if you discard it.')
        dialog.add_buttons('Cancel', Gtk.ResponseType.CANCEL, 'Discard', Gtk.ResponseType.REJECT, 'Save', Gtk.ResponseType.ACCEPT)
        dialog.set_default_response(Gtk.ResponseType.CANCEL)
        response = dialog.run(); dialog.destroy(); self.pending_dialog = False
        if response == Gtk.ResponseType.ACCEPT:
            self.save_note(lambda success: action() if success else (cancelled() if cancelled else None))
        elif response == Gtk.ResponseType.REJECT:
            action()
        elif cancelled:
            cancelled()

    def trash_note(self):
        if not self.note or not self.store:
            return
        self.guard_dirty(self.move_trash)

    def move_trash(self):
        note = self.note
        target = not note.trashed
        self.saving = True; self.moving = True; self.update_controls()
        def moved(updated, error):
            self.saving = False; self.moving = False
            if error:
                self.error('The note could not be moved. Your draft is preserved.', error)
                self.update_controls()
            else:
                self.load_editor(updated); self.refresh()
        self.submit(lambda: self.store.set_trashed(note.id, target, expected_revision=note.revision), moved)

    def export_note(self):
        title, body = self.contents()
        dialog = Gtk.FileChooserDialog(title='Export note', transient_for=self, action=Gtk.FileChooserAction.SAVE)
        dialog.add_buttons('Cancel', Gtk.ResponseType.CANCEL, 'Export', Gtk.ResponseType.ACCEPT)
        dialog.set_do_overwrite_confirmation(True)
        dialog.set_current_name('note.txt')
        response = dialog.run()
        filename = dialog.get_filename() if response == Gtk.ResponseType.ACCEPT else None
        dialog.destroy()
        if not filename: return
        text = (title + '\n\n' if title else '') + body
        def exported(_value, error):
            if error: self.error('The export could not be written. Choose a writable folder and try again. Your draft is preserved.', error)
            else: self.status.set_text('Exported. Unsaved changes remain.' if self.dirty else 'Exported.')
        self.submit(lambda: export_text(filename, text), exported)

    def toggle_list(self):
        self.list_manual = not self.side.get_visible()
        self.layout()

    def allocated(self, _root, allocation):
        if allocation.width == self.last_width: return
        self.last_width = allocation.width
        if self.list_manual is True: self.list_manual = None
        if not self.pending_layout:
            self.pending_layout = True; GLib.idle_add(self.layout)

    def layout(self):
        self.pending_layout = False
        show = self.list_manual if self.list_manual is not None else self.last_width >= 700
        self.side.set_no_show_all(not show)
        if self.side.get_visible() != show: self.side.set_visible(show)
        return False

    def on_key(self, _window, event):
        if not event.state & Gdk.ModifierType.CONTROL_MASK: return False
        if event.keyval in (Gdk.KEY_s, Gdk.KEY_S): self.save_note(); return True
        if event.keyval in (Gdk.KEY_n, Gdk.KEY_N): self.new_note(); return True
        if event.keyval in (Gdk.KEY_w, Gdk.KEY_W): self.on_close(); return True
        if event.keyval in (Gdk.KEY_e, Gdk.KEY_E): self.export_note(); return True
        if event.keyval in (Gdk.KEY_b, Gdk.KEY_B): self.toggle_list(); return True
        if event.keyval in (Gdk.KEY_f, Gdk.KEY_F):
            self.list_manual = True; self.layout(); self.search.grab_focus(); return True
        return False

    def on_close(self, *_):
        self.guard_dirty(self.destroy)
        return True

    def on_destroy(self, *_):
        self.closed = True
        self.worker.shutdown(wait=False)


class NotesApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='org.carpathian.Notes', flags=Gio.ApplicationFlags.FLAGS_NONE)

    def do_activate(self):
        window = self.get_active_window()
        if window is None: window = NotesWindow(self)
        window.present()


def main(argv=None):
    import sys
    return NotesApplication().run(sys.argv if argv is None else argv)
