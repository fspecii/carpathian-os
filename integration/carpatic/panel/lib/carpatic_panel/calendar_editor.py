"""On-demand local event editor; imported or changed identities stay read-only."""
import datetime as dt
import threading
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib
from .local_events import CalendarError, CalendarCommitUncertain, inspect_local, update_local, delete_local


def confirm_delete(parent):
    dialog = Gtk.MessageDialog(transient_for=parent, modal=True,
        message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.NONE,
        text='Delete this calendar event?', secondary_text=parent.snapshot['title'] + '\n\nThis removes the saved event from your local calendar.')
    dialog.add_button('Cancel', Gtk.ResponseType.CANCEL)
    dialog.add_button('Delete', Gtk.ResponseType.OK)
    try: return dialog.run() == Gtk.ResponseType.OK
    finally: dialog.destroy()


def confirm_discard(parent):
    dialog = Gtk.MessageDialog(transient_for=parent, modal=True,
        message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.NONE,
        text='Discard your changes?', secondary_text='Your unsaved changes to this event will be lost.')
    dialog.add_button('Keep Editing', Gtk.ResponseType.CANCEL)
    dialog.add_button('Discard', Gtk.ResponseType.OK)
    dialog.set_default_response(Gtk.ResponseType.CANCEL)
    try: return dialog.run() == Gtk.ResponseType.OK
    finally: dialog.destroy()


class EventEditor(Gtk.Window):
    def __init__(self, selection, data=None):
        super().__init__(title='Calendar event')
        self.selection = dict(selection); self.data = data; self.snapshot = None
        self.editable = False; self.ready = False; self.busy = False; self.closed = False; self._mutating = False
        self.set_default_size(430, 420)
        self.set_icon_name('x-office-calendar')
        self.connect('delete-event', self._request_close)
        self.connect('destroy', self._destroyed)
        header = Gtk.HeaderBar(title='Calendar event'); header.set_show_close_button(True); self.set_titlebar(header)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12); box.set_border_width(20); self.add(box)
        self.status = Gtk.Label(label='Checking calendar event…', xalign=0); self.status.set_line_wrap(True); box.pack_start(self.status, False, False, 0)
        self.title_entry = Gtk.Entry(); self.title_entry.set_max_length(2000)
        self.date_entry = Gtk.Entry(); self.date_entry.set_placeholder_text('YYYY-MM-DD')
        self.date_picker = None
        self.date_button = Gtk.Button.new_from_icon_name('x-office-calendar-symbolic', Gtk.IconSize.BUTTON)
        self.date_button.set_tooltip_text('Choose a date')
        self.date_button.connect('clicked', self.choose_date)
        self.start_entry = Gtk.Entry(); self.start_entry.set_placeholder_text('HH:MM')
        self.end_entry = Gtk.Entry(); self.end_entry.set_placeholder_text('HH:MM or leave empty')
        for label, entry in (('Title', self.title_entry), ('Date', self.date_entry), ('Start time', self.start_entry), ('End time', self.end_entry)):
            row = Gtk.Box(spacing=12); row.pack_start(Gtk.Label(label=label, xalign=0), False, False, 0)
            row.pack_start(entry, True, True, 0)
            if label == 'Date': row.pack_end(self.date_button, False, False, 0)
            box.pack_start(row, False, False, 0)
        self.all_day = Gtk.CheckButton(label='All day'); self.all_day.connect('toggled', lambda *_: self._controls()); box.pack_start(self.all_day, False, False, 0)
        self.source = Gtk.Label(label='Source: ' + str(selection.get('path', '')), xalign=0); self.source.set_line_wrap(True); self.source.set_selectable(True); box.pack_start(self.source, False, False, 0)
        actions = Gtk.Box(spacing=8)
        self.delete_button = Gtk.Button(label='Delete'); self.delete_button.connect('clicked', lambda *_: self.delete_event()); actions.pack_start(self.delete_button, False, False, 0)
        self.save_button = Gtk.Button(label='Save'); self.save_button.get_style_context().add_class('suggested-action'); self.save_button.connect('clicked', lambda *_: self.save_event()); actions.pack_end(self.save_button, False, False, 0)
        close = Gtk.Button(label='Close'); close.connect('clicked', lambda *_: self.close()); actions.pack_end(close, False, False, 0)
        box.pack_end(actions, False, False, 0)
        self._fill(selection); self.show_all(); self._controls()
        self._job(lambda: inspect_local(selection['path'], selection['uid'], data), self._loaded)

    def _destroyed(self, *_): self.closed = True
    def _draft(self):
        return (self.title_entry.get_text(), self.date_entry.get_text(),
                self.start_entry.get_text(), self.end_entry.get_text(), self.all_day.get_active())
    def _request_close(self, *_):
        if self._mutating: return True
        return self.editable and self._draft() != self._baseline and not confirm_discard(self)
    def _fill(self, item):
        self.title_entry.set_text(str(item.get('title', '')))
        self.date_entry.set_text(str(item.get('day', '')))
        self.start_entry.set_text(item['start'].isoformat() if item.get('start') else '')
        self.end_entry.set_text(item['end'].isoformat() if item.get('end') else '')
        self.all_day.set_active(bool(item.get('all_day')))
        self._baseline = self._draft()
    def _controls(self):
        enabled = self.editable and not self.busy
        for widget in (self.title_entry, self.date_entry, self.date_button, self.all_day, self.save_button, self.delete_button): widget.set_sensitive(enabled)
        for widget in (self.start_entry, self.end_entry): widget.set_sensitive(enabled and not self.all_day.get_active())
    def _job(self, work, done, mutating=False):
        if self.busy or self.closed: return
        self.busy = True; self._mutating = mutating; self._controls()
        def finished(value):
            if self.closed: return False
            self.busy = False; self._mutating = False
            done(value); self._controls(); return False
        def worker():
            try: value = work()
            except Exception as error: value = error
            GLib.idle_add(finished, value)
        threading.Thread(target=worker, name='calendar-editor-storage', daemon=True).start()
    def _loaded(self, value):
        self.ready = True
        if isinstance(value, Exception):
            self.status.set_text('Read-only event. ' + str(value)); return
        self.snapshot = value; self.editable = True; self._fill(value); self.status.set_text('Your local calendar')
    def choose_date(self, *_):
        if self.busy or not self.editable: return
        try: day = dt.date.fromisoformat(self.date_entry.get_text().strip())
        except ValueError: day = dt.date.today()
        popover = Gtk.Popover.new(self.date_button)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); box.set_border_width(12)
        calendar = Gtk.Calendar(); calendar.select_month(day.month - 1, day.year); calendar.select_day(day.day)
        self.date_picker = calendar; box.pack_start(calendar, False, False, 0)
        def selected(*_):
            if self.busy or not self.editable: return
            year, month, day = calendar.get_date()
            self.date_entry.set_text(dt.date(year, month + 1, day).isoformat()); popover.popdown()
        calendar.connect('day-selected-double-click', selected)
        use = Gtk.Button(label='Use date'); use.connect('clicked', selected); box.pack_end(use, False, False, 0)
        popover.add(box); popover.connect('closed', lambda *_: popover.destroy()); popover.show_all(); popover.popup()

    def save_event(self):
        if self.busy or not self.editable: return
        try:
            title = self.title_entry.get_text()
            day = dt.date.fromisoformat(self.date_entry.get_text().strip())
            start = None if self.all_day.get_active() else dt.time.fromisoformat(self.start_entry.get_text().strip())
            end_text = self.end_entry.get_text().strip()
            end = None if start is None or not end_text else dt.time.fromisoformat(end_text)
        except ValueError:
            self.status.set_text('Enter a valid date and time. Your changes were kept.'); return
        old = self.snapshot
        self.status.set_text('Saving event…')
        self._job(lambda: update_local(old['path'], old['uid'], old['revision'], title, day, start, end, self.data), self._saved, True)
    def _saved(self, value):
        if isinstance(value, CalendarCommitUncertain) and value.operation == 'save':
            self.snapshot = value.snapshot; self._fill(value.snapshot)
            self.status.set_text('Your changes are visible now, but persistence after a restart could not be confirmed.')
            return
        if isinstance(value, Exception): self.status.set_text('Event could not be saved. ' + str(value)); return
        self.snapshot = value; self._fill(value); self.status.set_text('Event saved.')
    def delete_event(self):
        if self.busy or not self.editable or not confirm_delete(self): return
        old = self.snapshot; self.status.set_text('Deleting event…')
        self._job(lambda: delete_local(old['path'], old['uid'], old['revision'], self.data), self._deleted, True)
    def _deleted(self, value):
        if isinstance(value, CalendarCommitUncertain) and value.operation == 'delete':
            self.editable = False
            self.status.set_text('The event is deleted now, but persistence after a restart could not be confirmed.')
            return
        if isinstance(value, Exception): self.status.set_text('Event could not be deleted. ' + str(value)); return
        self.destroy()


def run(selection):
    window = EventEditor(selection); window.connect('destroy', lambda *_: Gtk.main_quit())
    Gtk.main(); return 0
