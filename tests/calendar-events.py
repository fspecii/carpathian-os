#!/usr/bin/env python3
"""Calendar import resilience using actual parser and private source fixtures."""
import datetime as dt
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'integration/carpatic/panel/lib/carpatic_panel/events.py'
spec = importlib.util.spec_from_file_location('calendar_events_under_test', SOURCE)
events = importlib.util.module_from_spec(spec)
spec.loader.exec_module(events)
LO, HI = dt.date(2026, 10, 1), dt.date(2026, 10, 31)


def record(title, properties='DTSTART:20261011T090000'):
    return 'BEGIN:VEVENT\nSUMMARY:' + title + '\n' + properties + '\nEND:VEVENT\n'


def calendar(*records):
    return 'BEGIN:VCALENDAR\nVERSION:2.0\n' + ''.join(records) + 'END:VCALENDAR\n'


class CalendarEvents(unittest.TestCase):
    def assert_isolated(self, bad):
        issues = []
        result = events.parse_ics(calendar(record('Before'), record('Broken', bad), record('After')),
                                  LO, HI, issues=issues)
        self.assertEqual([value.title for value in result], ['Before', 'After'])
        self.assertTrue(issues, 'Rejected calendar data must produce a diagnostic')

    def test_invalid_start_isolated(self):
        self.assert_isolated('DTSTART:20261332T090000')

    def test_invalid_all_day_isolated(self):
        self.assert_isolated('DTSTART;VALUE=DATE:20260230')

    def test_unrecognized_start_isolated(self):
        self.assert_isolated('DTSTART:not-a-date')

    def test_invalid_end_isolated(self):
        self.assert_isolated('DTSTART:20261011T090000\nDTEND:20261011T250000')

    def test_invalid_exdate_isolated(self):
        self.assert_isolated('DTSTART:20261011T090000\nRRULE:FREQ=DAILY;COUNT=2\nEXDATE:20261032T090000')

    def test_invalid_recurrence_interval_isolated(self):
        self.assert_isolated('DTSTART:20261011T090000\nRRULE:FREQ=DAILY;INTERVAL=oops')

    def test_yearly_overflow_isolated(self):
        self.assert_isolated('DTSTART:20261011T090000\nRRULE:FREQ=YEARLY;INTERVAL=10000')

    def test_monthly_overflow_isolated(self):
        self.assert_isolated('DTSTART:20261011T090000\nRRULE:FREQ=MONTHLY;INTERVAL=120000')

    def test_daily_overflow_isolated(self):
        self.assert_isolated('DTSTART:20261011T090000\nRRULE:FREQ=DAILY;INTERVAL=99999999999999999999')

    def test_explicit_datetime_parameter_preserves_time(self):
        result = events.parse_ics(calendar(record('Timed', 'DTSTART;VALUE=DATE-TIME:20261011T090000')), LO, HI)
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0].all_day)
        self.assertEqual(result[0].start, dt.time(9))

    def test_date_parameter_rejects_trailing_datetime(self):
        self.assert_isolated('DTSTART;VALUE=DATE:20261011T090000')

    def test_oversized_source_reports_warning_and_preserves_other_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            oversized = root / 'large.ics'; oversized.write_bytes(b'x' * (2 * 1024 * 1024 + 1))
            valid = root / 'valid.ics'; valid.write_text(calendar(record('Valid')))
            issues = []
            with patch.object(events, 'sources', return_value=[str(oversized), str(valid)]):
                result = events.load_events(LO, HI, directory, issues=issues)
            self.assertEqual([item.title for item in result], ['Valid'])
            self.assertTrue(any('too large' in issue for issue in issues))

    def test_valid_import_has_no_issues(self):
        issues = []
        result = events.parse_ics(calendar(record('Valid')), LO, HI, issues=issues)
        self.assertEqual([item.title for item in result], ['Valid'])
        self.assertEqual(issues, [])

    def test_optional_issues_preserves_original_api(self):
        result = events.parse_ics(calendar(record('Before'), record('Broken', 'DTSTART:20261332T090000'),
                                           record('After')), LO, HI)
        self.assertEqual([item.title for item in result], ['Before', 'After'])

    def test_bad_record_does_not_hide_same_or_other_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / 'first.ics', root / 'second.ics'
            first.write_text(calendar(record('Before'), record('Broken', 'DTSTART:20261332T090000'), record('After')))
            second.write_text(calendar(record('Other file')))
            issues = []
            with patch.object(events, 'sources', return_value=[str(first), str(second)]) as sources:
                result = events.load_events(LO, HI, directory, issues=issues)
            sources.assert_called_once_with(directory)
            self.assertEqual({item.title for item in result}, {'Before', 'After', 'Other file'})
            self.assertTrue(issues)

    def test_unreadable_file_does_not_hide_other_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            valid = root / 'valid.ics'
            valid.write_text(calendar(record('Valid')))
            issues = []
            with patch.object(events, 'sources', return_value=[str(root / 'missing.ics'), str(valid)]):
                result = events.load_events(LO, HI, directory, issues=issues)
            self.assertEqual([item.title for item in result], ['Valid'])
            self.assertTrue(issues)


if __name__ == '__main__':
    unittest.main()
