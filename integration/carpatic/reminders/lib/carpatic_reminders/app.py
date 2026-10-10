"""GTK3 reminder editor. Storage jobs run off the UI thread; no idle polling."""
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import os
from pathlib import Path
import sys

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, Gio, GLib
from .store import Store, validate_fields


class RemindersWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title='Reminders')
        self.set_default_size(880, 560)
        self.store = Store()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='reminders-storage')
        self.closed = False
        self.busy = False
        self.pending_request = None
        self.ident = None
        self.day = None
        self.items = []
        self.connect('destroy', self._destroy)
        self.connect('key-press-event', self._key)
        self._theme()
        header = Gtk.HeaderBar(title='Reminders', subtitle='On this device')
        header.set_show_close_button(True)
        self.set_titlebar(header)
        new = Gtk.Button.new_from_icon_name('list-add-symbolic', Gtk.IconSize.BUTTON)
        new.set_tooltip_text('New reminder (Ctrl+N)')
        new.connect('clicked', lambda *_: self.new())
        header.pack_start(new)
        refresh = Gtk.Button.new_from_icon_name('view-refresh-symbolic', Gtk.IconSize.BUTTON)
        refresh.set_tooltip_text('Refresh reminders (Ctrl+R)')
        refresh.connect('clicked', lambda *_: self.reload())
        header.pack_end(refresh)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root.set_border_width(16)
        self.add(root)
        self.status = Gtk.Label(xalign=0)
        self.status.set_line_wrap(True)
        root.pack_start(self.status, False, False, 0)
        panes = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        root.pack_start(panes, True, True, 0)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        filters = Gtk.Box(spacing=8)
        self.filter_label = Gtk.Label(label='All reminders', xalign=0)
        filters.pack_start(self.filter_label, True, True, 0)
        all_button = Gtk.Button(label='Show all')
        all_button.connect('clicked', lambda *_: self.set_day(None))
        filters.pack_end(all_button, False, False, 0)
        left.pack_start(filters, False, False, 0)
        self.show_completed = Gtk.CheckButton(label='Show completed')
        self.show_completed.connect('toggled', lambda *_: self.render_list())
        left.pack_start(self.show_completed, False, False, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.connect('row-selected', self._selected)
        scroll.add(self.listbox)
        left.pack_start(scroll, True, True, 0)
        panes.pack1(left, resize=True, shrink=False)
        self.editor = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.editor.set_margin_start(20)
        panes.pack2(self.editor, resize=True, shrink=False)
        self.editor_title = Gtk.Label(label='New reminder', xalign=0)
        self.editor_title.get_style_context().add_class('reminders-heading')
        self.editor.pack_start(self.editor_title, False, False, 0)
        self.title = Gtk.Entry()
        self.title.set_max_length(200)
        self.title.set_placeholder_text('What would you like to remember?')
        self._field('Title', self.title)
        self.notes = Gtk.TextView()
        self.notes.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        notes_scroll = Gtk.ScrolledWindow()
        notes_scroll.set_min_content_height(100)
        notes_scroll.add(self.notes)
        self._field('Notes (optional)', notes_scroll)
        self.date = Gtk.Entry()
        self.date.set_placeholder_text('YYYY-MM-DD or leave blank')
        self._field('Due date (optional)', self.date)
        self.time = Gtk.Entry()
        self.time.set_placeholder_text('HH:MM, local time')
        self._field('Due time (optional)', self.time)
        self.completed = Gtk.CheckButton(label='Completed')
        self.editor.pack_start(self.completed, False, False, 0)
        actions = Gtk.Box(spacing=8)
        self.save_button = Gtk.Button(label='Save reminder')
        self.save_button.get_style_context().add_class('suggested-action')
        self.save_button.connect('clicked', lambda *_: self.save())
        actions.pack_start(self.save_button, True, True, 0)
        self.delete_button = Gtk.Button(label='Delete')
        self.delete_button.get_style_context().add_class('destructive-action')
        self.delete_button.connect('clicked', lambda *_: self.delete())
        actions.pack_end(self.delete_button, False, False, 0)
        self.editor.pack_start(actions, False, False, 0)
        hint = Gtk.Label(label='Stored locally. Due alerts require the optional Reminders notifier.', xalign=0)
        hint.set_line_wrap(True)
        hint.get_style_context().add_class('dim-label')
        root.pack_end(hint, False, False, 0)
        panes.set_position(380)
        self.show_all()
        self.new()

    def _theme(self):
        palette = {'bg': '#f6f7f9', 'fg': '#172029', 'accent': '#16806a'}
        for location in (Path('/usr/local/lib/carpatic-settings'),
                         Path(__file__).resolve().parents[3] / 'settings/lib'):
            if location.is_dir(): sys.path.insert(0, str(location))
        try:
            from cset.theme import palette as active_palette, norm_hex
            palette.update(active_palette())
            palette = {key: norm_hex(palette[key]) for key in ('bg', 'fg', 'accent')}
        except (ImportError, OSError, ValueError):
            pass
        provider = Gtk.CssProvider()
        css = ('window { background-color: %(bg)s; color: %(fg)s; } '
               '.reminders-heading { font-size: 20px; font-weight: bold; } '
               'entry:focus { border-color: %(accent)s; }') % palette
        provider.load_from_data(css.encode())
        Gtk.StyleContext.add_provider_for_screen(self.get_screen(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def _field(self, label, widget):
        name = Gtk.Label(label=label, xalign=0)
        name.set_mnemonic_widget(widget)
        self.editor.pack_start(name, False, False, 0)
        self.editor.pack_start(widget, False, False, 0)
        widget.get_accessible().set_name(label)

    def _destroy(self, *_):
        self.closed = True
        self.executor.shutdown(wait=False)

    def _key(self, _, event):
        if event.state & Gdk.ModifierType.CONTROL_MASK:
            if event.keyval in (Gdk.KEY_n, Gdk.KEY_N): self.new(); return True
            if event.keyval in (Gdk.KEY_s, Gdk.KEY_S): self.save(); return True
            if event.keyval in (Gdk.KEY_r, Gdk.KEY_R): self.reload(); return True
        return False

    def job(self, action, success):
        if self.busy: return
        self.busy = True
        self.editor.set_sensitive(False)
        self.listbox.set_sensitive(False)
        self.status.set_text('Working…')
        future = self.executor.submit(action)
        def ready(result):
            if self.closed: return
            GLib.idle_add(deliver, result)
        def deliver(result):
            if self.closed: return False
            self.busy = False
            self.editor.set_sensitive(True)
            self.listbox.set_sensitive(True)
            try:
                value = result.result()
            except Exception as error:
                self.status.set_text(str(error))
            else:
                self.status.set_text('')
                success(value)
            if self.pending_request is not None:
                day, new = self.pending_request
                self.pending_request = None
                self.open_requested(day, new)
            return False
        future.add_done_callback(ready)

    def reload(self):
        self.job(self.store.list, self._loaded)

    def open_requested(self, day, new):
        if self.busy:
            self.pending_request = (day, new)
            return
        self.set_day(day)
        if new: self.new(day)
        self.reload()

    def _loaded(self, items):
        self.items = items
        self.render_list()

    def set_day(self, day):
        self.day = day
        self.filter_label.set_text(day if day else 'All reminders')
        self.render_list()

    def render_list(self):
        for row in self.listbox.get_children(): self.listbox.remove(row)
        visible = [item for item in self.items if (not self.day or item['due_date'] == self.day)
                   and (self.show_completed.get_active() or not item['completed'])]
        for item in visible:
            row = Gtk.ListBoxRow()
            row.item = item
            box = Gtk.Box(spacing=8)
            box.set_border_width(8)
            check = Gtk.CheckButton()
            check.set_active(item['completed'])
            check.get_accessible().set_name('Complete ' + item['title'])
            check.connect('toggled', lambda control, ident=item['id']: self.toggle(ident, control.get_active()))
            box.pack_start(check, False, False, 0)
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            title = Gtk.Label(label=item['title'], xalign=0)
            title.set_line_wrap(True)
            col.pack_start(title, False, False, 0)
            due = (item['due_date'] or 'No due date') + (' · ' + item['due_time'] if item['due_time'] else '')
            if item['completed']: due += ' · Completed'
            label = Gtk.Label(label=due, xalign=0)
            label.get_style_context().add_class('dim-label')
            col.pack_start(label, False, False, 0)
            box.pack_start(col, True, True, 0)
            row.add(box)
            self.listbox.add(row)
        if not visible:
            row = Gtk.ListBoxRow()
            row.set_selectable(False)
            row.add(Gtk.Label(label='No reminders for this day.' if self.day else 'No reminders yet. Choose + to add one.'))
            self.listbox.add(row)
        self.listbox.show_all()

    def _selected(self, _, row):
        if row is None or not hasattr(row, 'item'): return
        item = row.item
        self.ident = item['id']
        self.editor_title.set_text('Edit reminder')
        self.title.set_text(item['title'])
        self.notes.get_buffer().set_text(item['notes'])
        self.date.set_text(item['due_date'] or '')
        self.time.set_text(item['due_time'] or '')
        self.completed.set_active(item['completed'])
        self.delete_button.set_sensitive(True)

    def new(self, day=None):
        if self.busy: return
        self.ident = None
        self.editor_title.set_text('New reminder')
        self.title.set_text('')
        self.notes.get_buffer().set_text('')
        self.date.set_text(day or self.day or '')
        self.time.set_text('')
        self.completed.set_active(False)
        self.delete_button.set_sensitive(False)
        self.title.grab_focus()

    def save(self):
        if self.busy: return
        buffer = self.notes.get_buffer()
        try:
            fields = validate_fields(self.title.get_text(), buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True),
                                     self.date.get_text().strip() or None, self.time.get_text().strip() or None)
        except ValueError as error:
            self.status.set_text(str(error)); return
        ident = self.ident
        completed = self.completed.get_active()
        def action():
            if ident:
                self.store.update(ident, **fields, completed=completed)
            else:
                item = self.store.add(**fields)
                if completed: self.store.update(item['id'], completed=True)
            return self.store.list()
        self.job(action, lambda items: (self._loaded(items), self.new()))

    def toggle(self, ident, completed):
        def action():
            self.store.update(ident, completed=completed)
            return self.store.list()
        self.job(action, self._loaded)

    def delete(self):
        if self.busy or not self.ident: return
        ident = self.ident
        def action():
            self.store.delete(ident)
            return self.store.list()
        self.job(action, lambda items: (self._loaded(items), self.new()))


class RemindersApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='org.carpatic.Reminders', flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.window = None

    def do_command_line(self, command):
        args = command.get_arguments()[1:]
        day = None
        for index, arg in enumerate(args):
            if arg == '--date' and index + 1 < len(args): day = args[index + 1]
        if day:
            try: validate_fields('date query', due_date=day)
            except ValueError: return 1
        if self.window is None:
            self.window = RemindersWindow(self)
            self.window.connect('destroy', lambda *_: setattr(self, 'window', None))
        self.window.open_requested(day, '--new' in args)
        self.window.present()
        return 0


def run(day=None, new=False):
    args = ['carpatic-reminders']
    if day: args += ['--date', day]
    if new: args += ['--new']
    return RemindersApplication().run(args)
