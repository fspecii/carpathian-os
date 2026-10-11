#!/usr/bin/env python3
"""Local event mutation contract; all files live in private temporary directories."""
import datetime as dt
import sys
import os
import stat
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'integration/carpatic/panel/lib/carpatic_panel/local_events.py'
sys.path.insert(0, str(SOURCE.parent.parent))
from carpatic_panel import local_events as events
from carpatic_panel import events as calendar
DAY = dt.date(2026, 10, 11)


class LocalEvents(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name) / 'carpatic'
        self.directory = self.data / 'calendar'
        self.directory.mkdir(parents=True, mode=0o700)
        self.ident = uuid.uuid4().hex
        self.uid = self.ident + '@carpatic'
        self.path = self.directory / (self.ident + '.ics')
        self.write()

    def write(self, extra='', title='Original', uid=None):
        self.path.write_text('BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Carpathian OS//panel//EN\n'
                             'BEGIN:VEVENT\nUID:' + (uid or self.uid) + '\nDTSTAMP:20261011T080000Z\n'
                             'DTSTART:20261011T090000\nDTEND:20261011T100000\nSUMMARY:' + title + '\n' +
                             extra + 'END:VEVENT\nEND:VCALENDAR\n')
        self.path.chmod(0o600)

    def inspect(self, path=None, uid=None):
        return events.inspect_local(str(path or self.path), uid or self.uid, data=self.data)

    def update(self, snapshot, **kwargs):
        return events.update_local(str(self.path), self.uid, snapshot['revision'], kwargs.pop('title', 'Changed'),
                                   kwargs.pop('day', DAY), data=self.data, **kwargs)

    def delete(self, snapshot):
        return events.delete_local(str(self.path), self.uid, snapshot['revision'], data=self.data)

    def test_old_delete_helper_refuses_wrong_uid_and_unrelated_file(self):
        original = self.path.read_bytes()
        self.assertFalse(calendar.delete_event(str(self.path), uuid.uuid4().hex + '@carpatic', self.data))
        self.assertEqual(self.path.read_bytes(), original)
        unrelated = self.directory / 'unrelated.ics'; unrelated.write_text('keep')
        self.assertFalse(calendar.delete_event(str(unrelated), self.uid, self.data))
        self.assertEqual(unrelated.read_text(), 'keep')

    def test_group_writable_event_cannot_be_edited(self):
        self.path.chmod(0o664)
        with self.assertRaises(events.CalendarError): self.inspect()
        self.assertTrue(self.path.exists())

    def test_creation_rejects_invalid_time_range_before_writing(self):
        before = set(self.directory.iterdir())
        with self.assertRaises(events.CalendarError):
            calendar.write_event('Reversed', DAY, dt.time(13), dt.time(12), self.data)
        self.assertEqual(set(self.directory.iterdir()), before)

    def test_creation_escapes_lines_and_uses_private_file(self):
        fresh = self.data / 'new'
        path = Path(calendar.write_event('Title\nUID:injected', DAY, data=fresh))
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        snapshot = events.inspect_local(str(path), path.stem + '@carpatic', fresh)
        self.assertEqual(snapshot['title'], 'Title\nUID:injected')
        self.assertEqual(snapshot['uid'], path.stem + '@carpatic')

    def test_snapshot_fields(self):
        value = self.inspect()
        self.assertEqual(value['uid'], self.uid)
        self.assertEqual(Path(value['path']), self.path)
        self.assertEqual(value['title'], 'Original')
        self.assertEqual(value['day'], DAY)
        self.assertEqual(value['start'], dt.time(9))
        self.assertEqual(value['end'], dt.time(10))
        self.assertFalse(value['all_day'])
        self.assertTrue(value['revision'])

    def test_update_preserves_identity_and_sets_times(self):
        value = self.update(self.inspect(), start=dt.time(13), end=dt.time(14))
        self.assertEqual(value['uid'], self.uid)
        self.assertEqual(value['title'], 'Changed')
        self.assertEqual(value['start'], dt.time(13))
        self.assertEqual(value['end'], dt.time(14))
        self.assertEqual(self.path.read_text().count('UID:' + self.uid), 1)

    def test_update_all_day(self):
        value = self.update(self.inspect(), day=DAY + dt.timedelta(days=2))
        self.assertTrue(value['all_day'])
        self.assertIsNone(value['start'])
        self.assertIsNone(value['end'])
        self.assertEqual(value['day'], DAY + dt.timedelta(days=2))

    def test_title_cannot_inject_properties(self):
        title = 'Hello\r\nEND:VEVENT\nBEGIN:VEVENT, semi; slash\\'
        self.update(self.inspect(), title=title)
        raw = self.path.read_text()
        self.assertEqual(raw.count('\nBEGIN:VEVENT\n'), 1)
        self.assertEqual(raw.count('\nEND:VEVENT\n'), 1)
        self.assertNotIn('SUMMARY:Hello\nEND:VEVENT', raw)
        self.assertIn('\\,', raw)
        self.assertIn('\\;', raw)
        self.assertIn('\\\\', raw)

    def test_uid_mismatch_rejected(self):
        with self.assertRaises(events.CalendarError):
            self.inspect(uid=uuid.uuid4().hex + '@carpatic')

    def test_filename_uid_mismatch_rejected(self):
        self.write(uid=uuid.uuid4().hex + '@carpatic')
        with self.assertRaises(events.CalendarError):
            self.inspect()

    def test_unrelated_directory_rejected(self):
        unrelated = self.data / self.path.name
        unrelated.write_bytes(self.path.read_bytes())
        with self.assertRaises(events.CalendarError):
            self.inspect(path=unrelated)

    def test_imported_producer_rejected(self):
        self.path.write_text(self.path.read_text().replace('-//Carpathian OS//panel//EN', '-//Other//EN'))
        with self.assertRaises(events.CalendarError):
            self.inspect()

    def test_file_symlink_rejected(self):
        target = self.data / 'target.ics'
        self.path.rename(target)
        self.path.symlink_to(target)
        with self.assertRaises(events.CalendarError):
            self.inspect()

    def test_directory_symlink_rejected(self):
        target = self.data / 'target'
        self.directory.rename(target)
        self.directory.symlink_to(target, target_is_directory=True)
        with self.assertRaises(events.CalendarError):
            self.inspect()

    def test_hardlink_rejected(self):
        os.link(self.path, self.data / 'other.ics')
        with self.assertRaises(events.CalendarError):
            self.inspect()

    def test_multiple_events_rejected(self):
        raw = self.path.read_text()
        vevent = raw[raw.index('BEGIN:VEVENT'):raw.index('END:VEVENT') + len('END:VEVENT\n')]
        self.path.write_text(raw.replace('END:VCALENDAR', vevent + 'END:VCALENDAR'))
        with self.assertRaises(events.CalendarError):
            self.inspect()

    def test_recurrence_and_unknown_fields_rejected(self):
        for extra in ('RRULE:FREQ=DAILY\n', 'RECURRENCE-ID:20261011T090000\n', 'X-UNKNOWN:keep-me\n', 'DESCRIPTION:important\n'):
            with self.subTest(extra=extra):
                self.write(extra=extra)
                with self.assertRaises(events.CalendarError):
                    self.inspect()

    def test_stale_update_preserves_newer_edit(self):
        old = self.inspect()
        self.update(old, title='Newer')
        before = self.path.read_bytes()
        with self.assertRaises(events.CalendarError):
            self.update(old, title='Stale')
        self.assertEqual(self.path.read_bytes(), before)

    def test_stale_delete_preserves_newer_edit(self):
        old = self.inspect()
        self.update(old, title='Newer')
        before = self.path.read_bytes()
        with self.assertRaises(events.CalendarError):
            self.delete(old)
        self.assertEqual(self.path.read_bytes(), before)

    def test_replace_failure_preserves_original_and_cleans_temp(self):
        old = self.inspect()
        before = self.path.read_bytes()
        names = set(self.directory.iterdir())
        with patch.object(events.os, 'replace', side_effect=OSError('injected replacement failure')):
            with self.assertRaises(events.CalendarError):
                self.update(old)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(set(self.directory.iterdir()), names)

    def test_temp_fsync_failure_preserves_original(self):
        old = self.inspect()
        before = self.path.read_bytes()
        names = set(self.directory.iterdir())
        with patch.object(events.os, 'fsync', side_effect=OSError('injected disk failure')):
            with self.assertRaises(events.CalendarError):
                self.update(old)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(set(self.directory.iterdir()), names)

    def test_delete_unlink_failure_preserves_original(self):
        old = self.inspect()
        before = self.path.read_bytes()
        with patch.object(events.os, 'unlink', side_effect=PermissionError('injected permission failure')):
            with self.assertRaises(events.CalendarError):
                self.delete(old)
        self.assertEqual(self.path.read_bytes(), before)

    def test_writer_created_event_is_editable(self):
        path = events.events.write_event('Created', DAY, dt.time(9), dt.time(10), data=self.data)
        uid = Path(path).stem + '@carpatic'
        value = self.inspect(path=path, uid=uid)
        self.assertEqual(value['title'], 'Created')
        edited = events.update_local(str(path), uid, value['revision'], 'Edited', DAY, data=self.data)
        self.assertEqual(edited['uid'], uid)
        self.assertEqual(edited['title'], 'Edited')

    def test_invalid_update_keeps_original(self):
        old = self.inspect()
        before = self.path.read_bytes()
        for kwargs in ({'title': ''}, {'start': dt.time(11), 'end': dt.time(10)},
                       {'start': None, 'end': dt.time(10)}, {'day': dt.datetime(2026, 10, 11)}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(events.CalendarError):
                    self.update(old, **kwargs)
                self.assertEqual(self.path.read_bytes(), before)

    def test_delete_valid(self):
        self.assertIs(self.delete(self.inspect()), True)
        self.assertFalse(self.path.exists())


    def directory_sync_failure(self):
        real_fsync = os.fsync
        def fail_directory(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError('injected directory sync failure')
            return real_fsync(fd)
        return patch.object(events.os, 'fsync', side_effect=fail_directory)

    def test_directory_sync_failure_after_save_exposes_committed_revision(self):
        old = self.inspect()
        with self.directory_sync_failure():
            with self.assertRaises(events.CalendarCommitUncertain) as caught:
                self.update(old)
        failure = caught.exception
        self.assertEqual(failure.operation, 'save')
        actual = self.inspect()
        self.assertEqual(actual['title'], 'Changed')
        self.assertEqual(failure.snapshot, actual)
        self.assertNotEqual(actual['revision'], old['revision'])
        self.assertFalse(any(p.name.startswith('.edit-') for p in self.directory.iterdir()))
        saved = self.update(failure.snapshot, title='Saved again')
        self.assertEqual(saved['title'], 'Saved again')
        self.assertEqual(self.inspect(), saved)

    def test_directory_sync_failure_after_delete_reports_applied_deletion(self):
        old = self.inspect()
        with self.directory_sync_failure():
            with self.assertRaises(events.CalendarCommitUncertain) as caught:
                self.delete(old)
        self.assertEqual(caught.exception.operation, 'delete')
        self.assertIsNone(caught.exception.snapshot)
        self.assertFalse(self.path.exists())


if __name__ == '__main__':
    unittest.main()
