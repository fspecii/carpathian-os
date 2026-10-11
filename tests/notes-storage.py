#!/usr/bin/env python3
"""Local Notes storage acceptance; no GTK, VM or user data."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'integration/carpatic/notes/lib'))
from carpatic_notes.store import Store, StoreError, ConflictError, ValidationError


class NotesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        env = patch.dict(os.environ, {'XDG_DATA_HOME': str(self.root)})
        env.start(); self.addCleanup(env.stop)
        self.store = Store()

    def test_persistence_revision_trash_restore(self):
        note = self.store.create('Title', 'Body')
        self.assertEqual(Store().get(note.id), note)
        changed = self.store.save(note.id, 'Renamed', 'Edited', note.revision)
        self.assertEqual(changed.revision, 2)
        self.assertEqual(changed.created_at, note.created_at)
        with self.assertRaises(ConflictError): self.store.save(note.id, 'Stale', '', 1)
        trash = self.store.set_trashed(note.id, True, 2)
        self.assertEqual(self.store.list(), [])
        self.assertEqual(self.store.list(trashed=True), [trash])
        restored = self.store.set_trashed(note.id, False, 3)
        self.assertFalse(restored.trashed)
        self.assertEqual(restored.revision, 4)

    def test_unicode_literal_search_and_limits(self):
        one = self.store.create('Straße café', '100% _ [square]')
        self.store.create('Other', 'text')
        for query in ('STRASSE', 'CAFÉ', '%', '_', '[square]'):
            self.assertEqual(self.store.list(query), [one])
        self.assertEqual(len(self.store.list(limit=1)), 1)
        self.assertEqual(self.store.list('missing'), [])
        with self.assertRaises(ValidationError): self.store.list(limit=True)
        with self.assertRaises(ValidationError): self.store.create('bad\nline')
        with self.assertRaises(ValidationError): self.store.create(body='\ud800')

    def test_privacy_and_symlink_refusal(self):
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.store.path.parent.stat().st_mode & 0o777, 0o700)
        link = self.root / 'link.db'; link.symlink_to(self.store.path)
        with self.assertRaises(StoreError): Store(link)
        directory = self.root / 'linked'; directory.symlink_to(self.store.path.parent)
        with self.assertRaises(StoreError): Store(directory / 'other.db')
        journal = Path(str(self.store.path) + '-journal')
        journal.symlink_to(self.root / 'victim')
        with self.assertRaises(StoreError): self.store.create()
        journal.unlink()
        with patch.dict(os.environ, {'XDG_DATA_HOME': 'relative'}):
            with self.assertRaises(ValidationError): Store()

    def test_unsupported_foreign_corrupt_preserved(self):
        for kind in ('future', 'foreign', 'corrupt', 'fake-schema'):
            path = self.root / (kind + '.db')
            if kind == 'corrupt': path.write_bytes(b'not a sqlite database')
            else:
                with sqlite3.connect(path) as db:
                    if kind == 'future': db.execute('PRAGMA user_version=42')
                    elif kind == 'foreign': db.execute('CREATE TABLE unrelated (x)')
                    else:
                        db.execute('CREATE TABLE notes (id,title,body,revision,created_at,updated_at,trashed)')
                        db.execute('PRAGMA user_version=1')
            before = path.read_bytes()
            with self.assertRaises(StoreError): Store(path)
            self.assertEqual(path.read_bytes(), before)

    def test_transaction_failure_preserves_note(self):
        note = self.store.create('Original', 'Keep')
        def interrupted_write(connection):
            connection.execute("UPDATE notes SET title='Partial write' WHERE id=?", (note.id,))
            raise sqlite3.OperationalError('simulated disk-full failure during transaction')
        with self.assertRaises(StoreError): self.store._run(interrupted_write, write=True)
        self.assertEqual(self.store.get(note.id), note)
        self.assertEqual(self.store.save(note.id, 'Now saved', '', 1).revision, 2)

    def test_concurrent_writers_one_revision_wins(self):
        note = self.store.create('Original')
        def save(index):
            try: return self.store.save(note.id, str(index), '', 1)
            except ConflictError: return None
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(save, range(6)))
        self.assertEqual(sum(item is not None for item in results), 1)
        self.assertEqual(self.store.get(note.id).revision, 2)

    def test_interrupted_transaction_recovers(self):
        note = self.store.create('Durable', 'Body')
        code = "import sqlite3,os,sys; c=sqlite3.connect(sys.argv[1]); c.execute('BEGIN IMMEDIATE'); c.execute(\"UPDATE notes SET title='Uncommitted'\"); os._exit(0)"
        subprocess.run([sys.executable, '-c', code, str(self.store.path)], check=True)
        self.assertEqual(Store().get(note.id), note)


if __name__ == '__main__': unittest.main(verbosity=2)
