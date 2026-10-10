#!/usr/bin/env python3
"""Due scheduler tests with fake clock/sink; never send desktop notifications."""
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / 'integration/carpatic/reminders/lib'
sys.path.insert(0, str(LIB))
from carpatic_reminders.store import Store, StoreError
from carpatic_reminders.notifier import AlreadyRunning, InstanceLock, Ledger, Scheduler, due_epoch


class FakeSink:
    def __init__(self, accept=True):
        self.accept = accept
        self.items = []

    def __call__(self, item):
        self.items.append(dict(item))
        return self.accept


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env = patch.dict(os.environ, {'XDG_DATA_HOME': self.directory.name,
                                          'XDG_CONFIG_HOME': self.directory.name + '/config',
                                          'XDG_STATE_HOME': self.directory.name + '/state'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.store = Store()
        self.ledger = Ledger(self.store.path.parent)
        self.scheduler = Scheduler(self.ledger)
        self.sink = FakeSink()

    def timed(self, title='Timed reminder', day='2026-10-11', clock='09:00'):
        return self.store.add(title, notes='Private local notes', due_date=day, due_time=clock)

    def process(self, now):
        return self.scheduler.process(self.store.list(), now, self.sink)

    def test_timed_due_and_no_repetition(self):
        item = self.timed()
        due = due_epoch(item)
        self.assertEqual(self.process(due - 1), 0)
        self.assertEqual(self.sink.items, [])
        self.assertEqual(self.process(due), 1)
        self.assertEqual(self.process(due + 1), 0)
        self.assertEqual(len(self.sink.items), 1)
        self.assertIsNone(self.scheduler.next_delay(self.store.list(), due + 1))
        self.assertEqual(self.ledger.path.stat().st_mode & 0o777, 0o600)

    def test_normal_restart_and_overdue_login(self):
        item = self.timed()
        now = due_epoch(item) + 3600
        self.assertEqual(self.process(now), 1)
        self.scheduler = Scheduler(Ledger(self.store.path.parent))
        self.assertEqual(self.process(now + 100), 0)
        self.assertEqual(len(self.sink.items), 1)

    def test_untimed_date_only_and_completed_do_not_alert(self):
        self.store.add('No date')
        self.store.add('Date only', due_date='2026-10-11')
        item = self.timed()
        self.store.update(item['id'], completed=True)
        self.assertEqual(self.process(due_epoch(item) + 100), 0)
        self.assertEqual(self.sink.items, [])
        self.assertIsNone(self.scheduler.next_delay(self.store.list(), due_epoch(item)))

    def test_completion_and_delete_cancel_before_due(self):
        item = self.timed()
        due = due_epoch(item)
        self.process(due - 10)
        self.store.update(item['id'], completed=True)
        self.assertEqual(self.process(due + 10), 0)
        self.store.update(item['id'], completed=False)
        self.store.delete(item['id'])
        self.assertEqual(self.process(due + 20), 0)
        self.assertEqual(self.sink.items, [])

    def test_due_edit_reschedules_and_title_edit_keeps_delivery(self):
        item = self.timed()
        due = due_epoch(item)
        self.store.update(item['id'], due_time='11:00')
        self.assertEqual(self.process(due + 1), 0)
        self.assertEqual(self.process(due + 7200), 1)
        self.store.update(item['id'], title='Edited after notification', notes='Updated')
        self.assertEqual(self.process(due + 7300), 0)
        self.store.update(item['id'], due_time='12:00')
        self.assertEqual(self.process(due + 10800), 1)
        self.assertEqual(len(self.sink.items), 2)

    def test_reopen_delivered_reminder_does_not_duplicate(self):
        item = self.timed()
        due = due_epoch(item)
        self.process(due)
        self.store.update(item['id'], completed=True)
        self.process(due + 1)
        self.store.update(item['id'], completed=False)
        self.assertEqual(self.process(due + 2), 0)
        self.assertEqual(len(self.sink.items), 1)

    def test_failure_backoff_and_restart_retry_without_marking(self):
        item = self.timed()
        due = due_epoch(item)
        self.sink.accept = False
        self.assertEqual(self.process(due), 0)
        self.assertEqual(self.ledger.read(), {})
        self.process(due + 1)
        self.assertEqual(len(self.sink.items), 1)
        self.process(due + 5)
        self.assertEqual(len(self.sink.items), 2)
        self.assertEqual(self.scheduler.next_delay(self.store.list(), due + 5), 30)
        self.scheduler = Scheduler(self.ledger)
        self.sink.accept = True
        self.assertEqual(self.process(due + 6), 1)
        self.assertEqual(len(self.sink.items), 3)

    def test_exception_from_sink_is_failure(self):
        item = self.timed()
        def failing(_): raise RuntimeError('Fake notification server unavailable')
        self.assertEqual(self.scheduler.process(self.store.list(), due_epoch(item), failing), 0)
        self.assertEqual(self.ledger.read(), {})

    def test_bounded_catchup_batch_and_no_empty_idle_timer(self):
        items = [self.timed(f'Task {index}') for index in range(8)]
        now = due_epoch(items[0]) + 10
        self.assertEqual(self.process(now), 3)
        self.assertEqual(self.scheduler.next_delay(self.store.list(), now), .1)
        self.assertEqual(self.process(now + 1), 3)
        self.assertEqual(self.process(now + 2), 2)
        self.assertIsNone(self.scheduler.next_delay(self.store.list(), now + 2))
        self.assertIsNone(self.scheduler.next_delay([], now))

    def test_wall_clock_jump_revalidation_bound(self):
        item = self.timed()
        due = due_epoch(item)
        self.assertEqual(self.scheduler.next_delay(self.store.list(), due - 3600), 60)
        self.assertEqual(self.scheduler.next_delay(self.store.list(), due - 7), 7)
        self.assertEqual(self.process(due + 3600), 1)  # Resume/jump passes wall-time now, not a cached deadline.

    def test_damaged_ledger_preserved(self):
        self.ledger.path.parent.mkdir(parents=True)
        for raw in (b'broken', b'{"version":2,"delivered":{}}', b'{"version":1,"delivered":{"bad":"bad"}}'):
            self.ledger.path.write_bytes(raw)
            with self.assertRaises(StoreError): Scheduler(self.ledger)
            self.assertEqual(self.ledger.path.read_bytes(), raw)

    def test_delivery_flush_failure_not_repeated_in_same_process(self):
        item = self.timed()
        due = due_epoch(item)
        with patch.object(self.ledger, 'write', side_effect=OSError('Fake disk failure')):
            with self.assertRaises(OSError): self.process(due)
        self.assertEqual(len(self.sink.items), 1)
        self.assertEqual(self.process(due + 1), 0)
        self.assertEqual(len(self.sink.items), 1)
        self.assertIn(item['id'], self.ledger.read())

    def test_single_instance_across_processes_and_release(self):
        code = ('from carpatic_reminders.store import data_path; '
                'from carpatic_reminders.notifier import InstanceLock, AlreadyRunning; '
                '\ntry: lock=InstanceLock(data_path().parent)\nexcept AlreadyRunning: raise SystemExit(17)\n'
                'lock.close()')
        env = {**os.environ, 'PYTHONPATH': str(LIB)}
        with InstanceLock(self.store.path.parent):
            with self.assertRaises(AlreadyRunning): InstanceLock(self.store.path.parent)
            result = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 17, result.stderr)
        result = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_bounded_lock_handover_and_distinct_contention(self):
        old = InstanceLock(self.store.path.parent)
        timer = threading.Timer(.2, old.close)
        timer.start()
        try:
            with InstanceLock(self.store.path.parent, wait_seconds=1): pass
        finally:
            timer.join()
            old.close()
        with InstanceLock(self.store.path.parent):
            start = time.monotonic()
            with self.assertRaises(AlreadyRunning): InstanceLock(self.store.path.parent, wait_seconds=.1)
            self.assertLess(time.monotonic() - start, .5)

    @unittest.skipUnless(hasattr(time, 'tzset'), 'Local-zone test requires POSIX tzset')
    def test_local_dst_ambiguity_and_gap_policy(self):
        before = os.environ.get('TZ')
        try:
            os.environ['TZ'] = 'Europe/Bucharest'
            time.tzset()
            autumn = self.timed(day='2026-10-25', clock='03:30')
            spring = self.timed(day='2026-03-29', clock='03:30')
            self.assertEqual(dt.datetime.fromtimestamp(due_epoch(autumn), dt.timezone.utc),
                             dt.datetime(2026, 10, 25, 0, 30, tzinfo=dt.timezone.utc))
            self.assertEqual(dt.datetime.fromtimestamp(due_epoch(spring)).strftime('%Y-%m-%d %H:%M'),
                             '2026-03-29 04:30')
        finally:
            if before is None: os.environ.pop('TZ', None)
            else: os.environ['TZ'] = before
            time.tzset()


if __name__ == '__main__':
    unittest.main(verbosity=2)
