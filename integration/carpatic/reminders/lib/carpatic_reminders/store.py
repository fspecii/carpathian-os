"""Validated, locked, atomic local reminder storage shared by GUI and CLI."""
from contextlib import contextmanager
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import tempfile
import time
import uuid

MAX_BYTES = 1024 * 1024
MAX_ITEMS = 1000


class StoreError(ValueError):
    pass


def data_path():
    root = Path(os.environ.get('XDG_DATA_HOME') or (Path.home() / '.local/share'))
    if not root.is_absolute():
        raise StoreError('XDG_DATA_HOME must be an absolute path')
    return root / 'carpatic/reminders/reminders.json'


def validate_fields(title, notes='', due_date=None, due_time=None):
    if (not isinstance(title, str) or not title.strip() or len(title) > 200
            or any(ord(character) < 32 for character in title)):
        raise StoreError('Enter a title of 1–200 characters on one line')
    if not isinstance(notes, str) or len(notes) > 4000 or '\0' in notes:
        raise StoreError('Notes must contain at most 4000 characters')
    if due_date is not None:
        try:
            if not isinstance(due_date, str) or dt.date.fromisoformat(due_date).isoformat() != due_date:
                raise ValueError()
        except ValueError:
            raise StoreError('Date must use YYYY-MM-DD') from None
    if due_time is not None:
        try:
            if (not due_date or not isinstance(due_time, str) or len(due_time) != 5
                    or dt.time.fromisoformat(due_time).strftime('%H:%M') != due_time):
                raise ValueError()
        except ValueError:
            raise StoreError('Time must use HH:MM and requires a date') from None
    return dict(title=title.strip(), notes=notes, due_date=due_date, due_time=due_time)


def validate_item(item):
    if not isinstance(item, dict) or set(item) != {'id', 'title', 'notes', 'due_date', 'due_time', 'completed', 'created_at'}:
        raise StoreError('Invalid reminder record')
    try:
        if str(uuid.UUID(item['id'])) != item['id']:
            raise ValueError()
        dt.datetime.fromisoformat(item['created_at'])
    except (ValueError, TypeError, KeyError, AttributeError):
        raise StoreError('Invalid reminder identifier or creation date') from None
    if type(item['completed']) is not bool:
        raise StoreError('Invalid completion state')
    fields = validate_fields(item['title'], item['notes'], item['due_date'], item['due_time'])
    return {**item, **fields}


class Store:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else data_path()

    def _read(self):
        try:
            with self.path.open('rb') as stream:
                raw = stream.read(MAX_BYTES + 1)
        except FileNotFoundError:
            return []
        except OSError as error:
            raise StoreError(f'Cannot read reminders: {error.strerror}') from None
        if len(raw) > MAX_BYTES:
            raise StoreError('Reminder data exceeds the 1 MiB safety limit')
        try:
            document = json.loads(raw)
            if (not isinstance(document, dict) or set(document) != {'version', 'items'}
                    or type(document['version']) is not int or document['version'] != 1
                    or not isinstance(document['items'], list) or len(document['items']) > MAX_ITEMS):
                raise StoreError('Unsupported or invalid reminder data')
            items = [validate_item(item) for item in document['items']]
            if len({item['id'] for item in items}) != len(items):
                raise StoreError('Duplicate reminder identifiers')
            return items
        except (UnicodeError, json.JSONDecodeError):
            raise StoreError('Reminder data is damaged; the original file was preserved') from None

    def list(self, day=None, pending=False):
        if day is not None:
            validate_fields('date query', due_date=day)
        items = self._read()
        items = [item for item in items if (day is None or item['due_date'] == day)
                 and (not pending or not item['completed'])]
        return sorted(items, key=lambda item: (item['completed'], item['due_date'] or '9999-12-31',
                                              item['due_time'] or '00:00', item['created_at'], item['id']))

    @contextmanager
    def _lock(self):
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = os.open(str(self.path) + '.lock', os.O_RDWR | os.O_CREAT, 0o600)
            with os.fdopen(fd, 'a') as lock:
                deadline = time.monotonic() + 2
                while True:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            raise StoreError('Reminders are being saved elsewhere; try again') from None
                        time.sleep(0.02)
                yield
        except OSError as error:
            raise StoreError(f'Cannot save reminders: {error.strerror}') from None

    def _write(self, items):
        data = (json.dumps({'version': 1, 'items': items}, ensure_ascii=False) + '\n').encode()
        if len(data) > MAX_BYTES:
            raise StoreError('Reminder data exceeds the 1 MiB safety limit')
        temporary = None
        try:
            fd, temporary = tempfile.mkstemp(prefix='.reminders-', dir=self.path.parent)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            temporary = None
            directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if temporary is not None:
                os.unlink(temporary)

    def add(self, title, notes='', due_date=None, due_time=None):
        fields = validate_fields(title, notes, due_date, due_time)
        with self._lock():
            items = self._read()
            if len(items) >= MAX_ITEMS:
                raise StoreError('At most 1000 reminders can be stored')
            item = dict(id=str(uuid.uuid4()), **fields, completed=False,
                        created_at=dt.datetime.now(dt.timezone.utc).isoformat())
            self._write(items + [item])
        return item

    def update(self, ident, **changes):
        if not changes or set(changes) - {'title', 'notes', 'due_date', 'due_time', 'completed'}:
            raise StoreError('Unsupported reminder update')
        with self._lock():
            items = self._read()
            for index, item in enumerate(items):
                if item['id'] == ident:
                    item = validate_item({**item, **changes})
                    items[index] = item
                    self._write(items)
                    return item
            raise StoreError('Reminder no longer exists; refresh the list')

    def delete(self, ident):
        with self._lock():
            items = self._read()
            remaining = [item for item in items if item['id'] != ident]
            if len(remaining) == len(items):
                raise StoreError('Reminder no longer exists; refresh the list')
            self._write(remaining)
