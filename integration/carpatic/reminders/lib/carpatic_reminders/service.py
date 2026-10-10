"""Opt-in Gio-only notifier: file monitor, next deadline timer, bounded worker."""
from concurrent.futures import ThreadPoolExecutor
import signal
import sys
import time

import gi
gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib
from .store import Store, StoreError
from .notifier import AlreadyRunning, InstanceLock, Ledger, Scheduler, signature


class NotificationSink:
    def __init__(self, connection=None, cancelled=None):
        self.connection = connection
        self.cancelled = cancelled or (lambda: False)

    def __call__(self, item):
        # User strings are typed D-Bus parameters, never commands or markup.
        if self.cancelled(): return False
        connection = self.connection or Gio.bus_get_sync(Gio.BusType.SESSION, None)
        body = 'Due ' + item['due_date'] + ' at ' + item['due_time']
        if item['notes']: body += '\n' + item['notes']
        capabilities = connection.call_sync('org.freedesktop.Notifications', '/org/freedesktop/Notifications',
                                            'org.freedesktop.Notifications', 'GetCapabilities', None,
                                            GLib.VariantType.new('(as)'), Gio.DBusCallFlags.NONE, 1500, None)
        if 'body-markup' in capabilities.unpack()[0]: body = GLib.markup_escape_text(body)
        if self.cancelled(): return False
        hints = {'urgency': GLib.Variant('y', 1),
                 'desktop-entry': GLib.Variant('s', 'org.carpatic.Reminders')}
        result = connection.call_sync('org.freedesktop.Notifications', '/org/freedesktop/Notifications',
                                      'org.freedesktop.Notifications', 'Notify',
                                      GLib.Variant('(susssasa{sv}i)', ('Reminders', 0, 'view-task-symbolic',
                                                                    item['title'], body,
                                                                    [], hints, -1)),
                                      GLib.VariantType.new('(u)'), Gio.DBusCallFlags.NONE, 1500, None)
        return result is not None and result.unpack()[0] > 0


class Service:
    def __init__(self, store, scheduler, sink, bus=None):
        self.store = store
        self.scheduler = scheduler
        self.sink = sink
        self.loop = GLib.MainLoop()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='reminder-notifier')
        self.busy = False
        self.active_future = None
        self.changed = False
        self.stopped = False
        self.timer = 0
        self.monitor = Gio.File.new_for_path(str(store.path.parent)).monitor_directory(Gio.FileMonitorFlags.NONE, None)
        self.monitor.connect('changed', self._file_changed)
        self.bus = bus
        self.bus_handler = None
        if bus is not None:
            # Gio's shared bus connection normally exits its process on closure.
            # Own orderly shutdown so accepted deliveries can flush their ledger.
            bus.set_exit_on_close(False)
            self.bus_handler = bus.connect('closed', self._bus_closed)
            if bus.is_closed(): self.stop()

    def _bus_closed(self, *_):
        print('Reminders notifier: session bus closed; stopping', file=sys.stderr)
        self.stop()

    def _file_changed(self, _monitor, file, other, _event):
        if file.get_basename() != self.store.path.name and (other is None or other.get_basename() != self.store.path.name):
            return
        self.changed = True
        self.arm(.25)

    def arm(self, delay):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0
        if delay is not None and not self.stopped:
            self.timer = GLib.timeout_add(max(1, int(delay * 1000)), self.tick)

    def tick(self):
        self.timer = 0
        if self.stopped: return False
        if self.busy:
            self.changed = True
            return False
        self.busy = True
        self.changed = False
        def work():
            items = self.store.list()
            now = time.time()
            def current_sink(item):
                if self.stopped: return False
                # A file event can arrive while this worker is delivering a batch.
                # Revalidate immediately before sending rather than alert from an
                # old snapshot after an edit/completion/delete already committed.
                current = next((value for value in self.store.list() if value['id'] == item['id']), None)
                if current is None or current['completed'] or signature(current) != signature(item):
                    return False
                if self.stopped: return False
                return self.sink(current)
            self.scheduler.process(items, now, current_sink)
            return self.scheduler.next_delay(items, time.time())
        future = self.executor.submit(work)
        self.active_future = future
        future.add_done_callback(lambda result: GLib.idle_add(self._finished, result))
        return False

    def _finished(self, result):
        self.busy = False
        self.active_future = None
        try:
            delay = result.result()
        except Exception as error:
            print('Reminders notifier: ' + str(error), file=sys.stderr)
            delay = 30
        if self.stopped: return False
        if self.changed: delay = .25
        self.arm(delay)
        return False

    def stop(self, *_):
        self.stopped = True
        self.arm(None)
        self.monitor.cancel()
        self.loop.quit()
        return False

    def run(self):
        signals = [GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, self.stop)
                   for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)]
        try:
            if not self.stopped:
                self.arm(.1)
                self.loop.run()
        finally:
            self.stop()
            # Complete the bounded in-flight delivery/ledger operation before
            # releasing the lifetime lock; no overlap with a replacement process.
            self.executor.shutdown(wait=True)
            if self.active_future is not None:
                try: self.active_future.result()
                except Exception as error:
                    print('Reminders notifier shutdown: ' + str(error), file=sys.stderr)
                self.active_future = None
            for source in signals:
                if GLib.MainContext.default().find_source_by_id(source) is not None:
                    GLib.source_remove(source)
            if self.bus_handler is not None:
                self.bus.disconnect(self.bus_handler)
                self.bus_handler = None


def run():
    store = Store()
    try:
        with InstanceLock(store.path.parent, wait_seconds=8):
            # Validate files before connecting/creating a service. Corruption
            # prevents startup and never starts a GTK UI or sends notifications.
            store.list()
            scheduler = Scheduler(Ledger(store.path.parent))
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            sink = NotificationSink(bus)
            service = Service(store, scheduler, sink, bus=bus)
            sink.cancelled = lambda: service.stopped
            service.run()
        return 0
    except AlreadyRunning as error:
        print(str(error), file=sys.stderr)
        return 75
    except (StoreError, OSError, GLib.Error) as error:
        print('Reminders notifier: ' + str(error), file=sys.stderr)
        return 1
