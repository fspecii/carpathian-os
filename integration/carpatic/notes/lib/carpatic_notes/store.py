"""Private local notes with transactional, optimistic revision checks."""
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import stat
import uuid


class StoreError(ValueError):
    pass


class ConflictError(StoreError):
    pass


class ValidationError(StoreError):
    pass


@dataclass(frozen=True)
class Note:
    id: str
    title: str
    body: str
    revision: int
    created_at: str
    updated_at: str
    trashed: bool


_COLUMNS = ('id', 'title', 'body', 'revision', 'created_at', 'updated_at', 'trashed')
_SCHEMA = '''CREATE TABLE notes (
 id TEXT PRIMARY KEY NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
 revision INTEGER NOT NULL CHECK(revision >= 1), created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL, trashed INTEGER NOT NULL CHECK(trashed IN (0,1)))'''


def _text(title, body):
    if not isinstance(title, str) or len(title) > 300 or any(ord(c) < 32 for c in title):
        raise ValidationError('Use a title of at most 300 characters on one line')
    if not isinstance(body, str) or len(body) > 1000000 or '\0' in body:
        raise ValidationError('Use note text of at most one million characters without null characters')
    try:
        title.encode('utf-8'); body.encode('utf-8')
    except UnicodeError:
        raise ValidationError('Note text contains invalid Unicode') from None


def _identifier(ident):
    try:
        if not isinstance(ident, str) or str(uuid.UUID(ident)) != ident: raise ValueError()
    except ValueError:
        raise ValidationError('Invalid note identifier') from None


def _revision(value):
    if type(value) is not int or value < 1:
        raise ValidationError('Invalid note revision; reopen the note and try again')


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


class Store:
    def __init__(self, path=None):
        if path is None:
            root = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
            path = root / 'carpathian/notes/notes.sqlite3'
        self.path = Path(path)
        if not self.path.is_absolute():
            raise ValidationError('Notes storage must use an absolute location')
        self._connect().close()

    def _private_path(self):
        # Do not follow symlinks in either the database or its ancestry.
        for part in reversed((self.path.parent, *self.path.parent.parents)):
            if part.is_symlink(): raise StoreError('Notes storage uses an unsafe symbolic link')
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            info = self.path.parent.stat()
            if info.st_uid != os.getuid(): raise StoreError('Notes folder must belong to your account')
            self.path.parent.chmod(0o700)
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW
            try:
                descriptor = os.open(self.path, flags, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
            info = self.path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                raise StoreError('Notes database must be a private regular file owned by your account')
            # SQLite may create these adjacent files; never permit redirected writes.
            for suffix in ('-journal', '-wal', '-shm'):
                side = Path(str(self.path) + suffix)
                if side.is_symlink(): raise StoreError('Notes storage contains an unsafe journal link')
            self.path.chmod(0o600)
        except OSError:
            raise StoreError('Cannot access notes storage; check folder permissions and free space') from None

    def _connect(self):
        self._private_path()
        connection = None
        try:
            connection = sqlite3.connect(str(self.path), timeout=2)
            connection.execute('PRAGMA synchronous=FULL')
            connection.execute('BEGIN IMMEDIATE')
            version = connection.execute('PRAGMA user_version').fetchone()[0]
            tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if version == 0 and not tables:
                # Views/triggers also indicate an unrelated database.
                if connection.execute('SELECT count(*) FROM sqlite_master').fetchone()[0]:
                    raise StoreError('Unrecognized notes database; keep a backup and choose another location')
                connection.execute(_SCHEMA)
                connection.execute('PRAGMA user_version=1')
            elif version != 1 or tables != [('notes',)]:
                raise StoreError('Unsupported notes database version; preserve it and use a compatible app')
            columns = tuple(row[1] for row in connection.execute('PRAGMA table_info(notes)'))
            unexpected = connection.execute("SELECT name FROM sqlite_master WHERE NOT (type='table' AND name='notes') AND NOT (type='index' AND name='sqlite_autoindex_notes_1')").fetchall()
            if unexpected:
                raise StoreError('Unrecognized notes database objects; preserve it for recovery')
            schema = connection.execute("SELECT sql FROM sqlite_master WHERE name='notes'").fetchone()[0]
            if columns != _COLUMNS or schema != _SCHEMA:
                raise StoreError('Unrecognized notes database structure; preserve it for recovery')
            connection.commit()
            return connection
        except StoreError:
            if connection: connection.close()
            raise
        except sqlite3.Error:
            if connection: connection.close()
            raise StoreError('Cannot open notes database; preserve it and check permissions or restore a backup') from None

    def _run(self, action, write=False):
        connection = self._connect()
        try:
            if write: connection.execute('BEGIN IMMEDIATE')
            result = action(connection)
            connection.commit()
            return result
        except StoreError:
            connection.rollback()
            raise
        except sqlite3.Error:
            connection.rollback()
            raise StoreError('Notes could not be saved or read; check free space and permissions, then retry') from None
        finally:
            connection.close()

    @staticmethod
    def _note(row):
        if row is None: raise StoreError('This note no longer exists; refresh the list')
        return Note(*row[:-1], bool(row[-1]))

    def create(self, title='', body=''):
        _text(title, body)
        ident, stamp = str(uuid.uuid4()), _now()
        def action(connection):
            connection.execute('INSERT INTO notes VALUES (?,?,?,?,?,?,?)',
                               (ident, title, body, 1, stamp, stamp, 0))
            return self._note(connection.execute('SELECT * FROM notes WHERE id=?', (ident,)).fetchone())
        return self._run(action, True)

    def get(self, ident):
        _identifier(ident)
        return self._run(lambda c: self._note(c.execute('SELECT * FROM notes WHERE id=?', (ident,)).fetchone()))

    def _update(self, ident, revision, fields):
        _identifier(ident); _revision(revision)
        def action(connection):
            current = self._note(connection.execute('SELECT * FROM notes WHERE id=?', (ident,)).fetchone())
            if current.revision != revision:
                raise ConflictError('This note changed elsewhere; reopen it before saving your edits')
            assignments = ', '.join(key + '=?' for key in fields)
            connection.execute('UPDATE notes SET ' + assignments + ', revision=revision+1, updated_at=? WHERE id=?',
                               (*fields.values(), _now(), ident))
            return self._note(connection.execute('SELECT * FROM notes WHERE id=?', (ident,)).fetchone())
        return self._run(action, True)

    def save(self, ident, title, body, expected_revision):
        _text(title, body)
        return self._update(ident, expected_revision, {'title': title, 'body': body})

    def set_trashed(self, ident, trashed, expected_revision):
        if type(trashed) is not bool: raise ValidationError('Invalid trash state')
        return self._update(ident, expected_revision, {'trashed': int(trashed)})

    def list(self, query='', trashed=False, limit=200):
        if not isinstance(query, str) or len(query) > 1000:
            raise ValidationError('Search text must be at most 1000 characters')
        if type(trashed) is not bool or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValidationError('Invalid notes list options')
        needle = query.casefold()
        def action(connection):
            # Python casefold provides consistent Unicode literal search; SQL LIKE
            # would interpret wildcard characters and miss Unicode equivalences.
            result = []
            for row in connection.execute('SELECT * FROM notes WHERE trashed=? ORDER BY updated_at DESC, id', (int(trashed),)):
                if needle in row[1].casefold() or needle in row[2].casefold():
                    result.append(self._note(row))
                    if len(result) == limit: break
            return result
        return self._run(action)
