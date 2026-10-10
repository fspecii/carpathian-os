#!/usr/bin/env python3
"""Gio service/file-monitor tests with fake sink/DBus; no desktop notifications."""
import datetime as dt
import os
from pathlib import Path
import sys
import tempfile
import time
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'integration/carpatic/reminders/lib'))
try:
    import gi
    gi.require_version('Gio', '2.0')
    from gi.repository import Gio, GLib
    from carpatic_reminders.service import Service, NotificationSink
    from carpatic_reminders.service import run as run_service
    GIO = True
except ImportError:
    GIO = False
from carpatic_reminders.store import Store
from carpatic_reminders.notifier import AlreadyRunning, InstanceLock, Ledger, Scheduler


class FakeBus:
    def __init__(self):
        self.closed = False
        self.handlers = {}
        self.exit_on_close = True

    def set_exit_on_close(self, value): self.exit_on_close = value
    def is_closed(self): return self.closed
    def connect(self, name, callback):
        self.handlers[1] = callback
        return 1
    def disconnect(self, handler): self.handlers.pop(handler, None)
    def close(self):
        self.closed = True
        for callback in list(self.handlers.values()): callback(self, True, None)
        return False


@unittest.skipUnless(GIO, 'Gio/PyGObject unavailable; service tests not executed')
class GioServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        env = patch.dict(os.environ, {'XDG_DATA_HOME': self.directory.name,
                                      'XDG_CONFIG_HOME': self.directory.name + '/config',
                                      'XDG_STATE_HOME': self.directory.name + '/state'})
        env.start()
        self.addCleanup(env.stop)
        self.store = Store()
        self.lock = InstanceLock(self.store.path.parent)
        self.addCleanup(self.lock.close)

    def pump(self, predicate, timeout=4):
        context = GLib.MainContext.default()
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            while context.pending(): context.iteration(False)
            if predicate(): return
            time.sleep(.01)
        self.fail('Gio notifier condition timed out')

    def test_monitor_atomic_edits_cancel_and_reschedule(self):
        future = dt.datetime.now() + dt.timedelta(days=1)
        item = self.store.add('Future', due_date=future.date().isoformat(), due_time=future.strftime('%H:%M'))
        accepted = []
        service = Service(self.store, Scheduler(Ledger(self.store.path.parent)), lambda item: (accepted.append(item), True)[1])
        try:
            service.tick()
            self.pump(lambda: not service.busy and service.timer != 0)
            self.assertEqual(accepted, [])
            overdue = dt.datetime.now() - dt.timedelta(minutes=2)
            self.store.update(item['id'], due_date=overdue.date().isoformat(), due_time=overdue.strftime('%H:%M'))
            self.pump(lambda: bool(accepted) and not service.busy)
            self.assertEqual(len(accepted), 1)
            self.assertEqual(accepted[0]['id'], item['id'])
            self.assertEqual(service.timer, 0)
            # A completed pending task and then its deletion produce no alerts.
            second = self.store.add('Cancelled', due_date=future.date().isoformat(), due_time=future.strftime('%H:%M'))
            self.store.update(second['id'], completed=True)
            self.store.delete(second['id'])
            self.pump(lambda: not service.busy and service.timer == 0 and not service.changed)
            self.assertEqual(len(accepted), 1)
        finally:
            service.stop()
            service.executor.shutdown(wait=True)

    def test_payload_is_structured_and_body_escaped(self):
        item = self.store.add('Title $(never execute)', '<b>private notes</b>', '2026-10-11', '09:00')
        with patch('carpatic_reminders.service.Gio.bus_get_sync') as bus:
            connection = bus.return_value
            connection.call_sync.side_effect = [GLib.Variant('(as)', (['body-markup'],)), GLib.Variant('(u)', (42,))]
            self.assertTrue(NotificationSink()(item))
            args = connection.call_sync.call_args.args
            self.assertEqual(args[0:4], ('org.freedesktop.Notifications', '/org/freedesktop/Notifications',
                                        'org.freedesktop.Notifications', 'Notify'))
            payload = args[4].unpack()
            self.assertEqual(payload[3], item['title'])
            self.assertIn('&lt;b&gt;private notes&lt;/b&gt;', payload[4])
            self.assertEqual(args[7], 1500)
            connection.call_sync.side_effect = [GLib.Variant('(as)', ([],)), GLib.Variant('(u)', (0,))]
            self.assertFalse(NotificationSink()(item))
            self.assertIn('<b>private notes</b>', connection.call_sync.call_args.args[4].unpack()[4])

    def test_closed_bus_stops_even_without_pending_timer(self):
        bus = FakeBus()
        service = Service(self.store, Scheduler(Ledger(self.store.path.parent)), lambda item: True, bus=bus)
        try:
            service.tick()
            self.pump(lambda: not service.busy)
            self.assertEqual(service.timer, 0)
            self.assertFalse(bus.exit_on_close)
            bus.close()
            self.assertTrue(service.stopped)
            self.assertEqual(service.timer, 0)
            service.executor.shutdown(wait=True)
            self.lock.close()  # Service runner releases this only after worker shutdown.
            with InstanceLock(self.store.path.parent): pass
        finally:
            service.stop()
            service.executor.shutdown(wait=True)

    def test_runner_bus_close_releases_owned_lifetime_lock(self):
        self.lock.close()
        bus = FakeBus()
        with InstanceLock(self.store.path.parent):
            service = Service(self.store, Scheduler(Ledger(self.store.path.parent)), lambda item: True, bus=bus)
            GLib.timeout_add(150, bus.close)
            service.run()
            self.assertTrue(service.stopped)
            self.assertEqual(bus.handlers, {})
        with InstanceLock(self.store.path.parent): pass

    def test_contended_startup_has_distinct_retry_status(self):
        with patch('carpatic_reminders.service.InstanceLock', side_effect=AlreadyRunning('still shutting down')):
            self.assertEqual(run_service(), 75)

    def test_stop_mid_batch_finishes_accepted_ledger_only(self):
        overdue = dt.datetime.now() - dt.timedelta(minutes=2)
        for number in range(3):
            self.store.add(f'Batch {number}', due_date=overdue.date().isoformat(), due_time=overdue.strftime('%H:%M'))
        bus = FakeBus()
        accepted = []
        cancelled = threading.Event()
        def sink(item):
            accepted.append(item)
            def close_bus():
                bus.close()
                cancelled.set()
                return False
            GLib.idle_add(close_bus)
            if not cancelled.wait(2): raise RuntimeError('Fake bus close did not dispatch')
            return True  # Already accepted server call must still be durably recorded.
        service = Service(self.store, Scheduler(Ledger(self.store.path.parent)), sink, bus=bus)
        try:
            service.tick()
            self.pump(lambda: service.stopped and not service.busy)
            service.executor.shutdown(wait=True)
            self.assertEqual(len(accepted), 1)
            self.assertEqual(set(Ledger(self.store.path.parent).read()), {accepted[0]['id']})
            self.lock.close()
            with InstanceLock(self.store.path.parent):
                restarted = Scheduler(Ledger(self.store.path.parent))
                sink_items = []
                restarted.process(self.store.list(), time.time(), lambda item: (sink_items.append(item), True)[1])
                self.assertEqual(len(sink_items), 2)
                self.assertNotIn(accepted[0]['id'], [item['id'] for item in sink_items])
        finally:
            service.stop()
            service.executor.shutdown(wait=True)

    def test_sink_cancellation_between_capabilities_and_notify(self):
        item = self.store.add('Cancel before Notify', due_date='2026-10-11', due_time='09:00')
        checks = iter([False, True])
        with patch('carpatic_reminders.service.Gio.bus_get_sync') as bus:
            bus.return_value.call_sync.return_value = GLib.Variant('(as)', ([],))
            self.assertFalse(NotificationSink(cancelled=lambda: next(checks))(item))
            self.assertEqual(bus.return_value.call_sync.call_count, 1)
            self.assertEqual(bus.return_value.call_sync.call_args.args[3], 'GetCapabilities')

    def test_corrupt_startup_does_not_connect_or_start_ui(self):
        self.lock.close()
        self.store.path.write_bytes(b'{broken')
        with patch('carpatic_reminders.service.Gio.bus_get_sync') as bus, patch('carpatic_reminders.service.Service') as service:
            self.assertEqual(run_service(), 1)
            bus.assert_not_called()
            service.assert_not_called()
        self.assertEqual(self.store.path.read_bytes(), b'{broken')


if __name__ == '__main__':
    unittest.main(verbosity=2)
