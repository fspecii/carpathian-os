"""Local due-time scheduler and durable delivery ledger; no GTK/network calls."""
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import tempfile
import time
import uuid
from .store import StoreError, validate_fields, MAX_ITEMS


class AlreadyRunning(StoreError):
    pass


class InstanceLock:
    """One notifier for the same user data store, even across login sessions."""
    def __init__(self, directory, wait_seconds=0):
        directory = Path(directory)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.fd = os.open(directory / 'notifier.lock', os.O_RDWR | os.O_CREAT, 0o600)
        deadline = time.monotonic() + max(0, wait_seconds)
        delay = .05
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    os.close(self.fd)
                    self.fd = None
                    raise AlreadyRunning('A reminders notifier is still running for this data store; retry after it exits') from None
                time.sleep(min(delay, remaining))
                delay = min(.5, delay * 2)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self): return self
    def __exit__(self, *_): self.close()


def signature(item):
    if item['due_date'] and item['due_time']:
        return item['due_date'] + 'T' + item['due_time']
    return None


def due_epoch(item):
    """Local-zone wall time; fold=0 picks the first ambiguous DST occurrence.

    A nonexistent spring-forward time maps forward by the transition gap through
    Python's local-time timestamp conversion. No date/time means no scheduled alert.
    """
    value = signature(item)
    return dt.datetime.fromisoformat(value).replace(fold=0).timestamp() if value else None


class Ledger:
    def __init__(self, directory):
        self.path = Path(directory) / 'delivery-ledger.json'

    def read(self):
        try:
            with self.path.open('rb') as stream: raw = stream.read(256 * 1024 + 1)
        except FileNotFoundError:
            return {}
        try:
            if len(raw) > 256 * 1024: raise ValueError()
            value = json.loads(raw)
            if (not isinstance(value, dict) or set(value) != {'version', 'delivered'}
                    or type(value['version']) is not int or value['version'] != 1
                    or not isinstance(value['delivered'], dict) or len(value['delivered']) > MAX_ITEMS):
                raise ValueError()
            for ident, when in value['delivered'].items():
                if str(uuid.UUID(ident)) != ident or not isinstance(when, str) or len(when) != 16:
                    raise ValueError()
                validate_fields('ledger', due_date=when[:10], due_time=when[11:])
                if when[10] != 'T': raise ValueError()
            return value['delivered']
        except (ValueError, TypeError, UnicodeError, AttributeError):
            raise StoreError('Reminder delivery ledger is damaged; it was preserved') from None

    def write(self, delivered):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        raw = (json.dumps({'version': 1, 'delivered': delivered}) + '\n').encode()
        temporary = None
        try:
            fd, temporary = tempfile.mkstemp(prefix='.delivery-', dir=self.path.parent)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            temporary = None
            directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(directory)
            finally: os.close(directory)
        finally:
            if temporary is not None: os.unlink(temporary)


class Scheduler:
    """Pure deadline/delivery logic. Caller owns InstanceLock and worker I/O.

    sink(item) must return True only after a notification server accepts delivery.
    One invocation attempts at most three alerts, with bounded retry per identity.
    """
    BACKOFF = (5, 30, 120, 300)

    def __init__(self, ledger):
        self.ledger = ledger
        self.delivered = ledger.read()
        self.retries = {}
        self.dirty = False

    def process(self, items, now, sink):
        # If a previous ledger flush failed, persist in-memory successes before
        # making any further deliveries. This avoids repeat alerts in this process.
        if self.dirty:
            self.ledger.write(self.delivered)
            self.dirty = False
        ids = {item['id'] for item in items}
        retained = {ident: when for ident, when in self.delivered.items() if ident in ids}
        if retained != self.delivered:
            self.delivered = retained
            self.dirty = True
            self.ledger.write(self.delivered)
            self.dirty = False
        current_keys = {(item['id'], signature(item)) for item in items}
        self.retries = {key: retry for key, retry in self.retries.items() if key in current_keys}
        attempted = 0
        delivered_count = 0
        for item in items:
            when = signature(item)
            if item['completed'] or when is None or self.delivered.get(item['id']) == when:
                continue
            due = due_epoch(item)
            key = (item['id'], when)
            attempt, retry_at = self.retries.get(key, (0, 0))
            if due > now or retry_at > now or attempted >= 3:
                continue
            attempted += 1
            try:
                accepted = sink(item) is True
            except Exception:
                accepted = False
            if accepted:
                self.delivered[item['id']] = when
                self.retries.pop(key, None)
                self.dirty = True
                self.ledger.write(self.delivered)
                self.dirty = False
                delivered_count += 1
            else:
                delay = self.BACKOFF[min(attempt, len(self.BACKOFF) - 1)]
                self.retries[key] = (attempt + 1, now + delay)
        return delivered_count

    def next_delay(self, items, now):
        pending = []
        for item in items:
            when = signature(item)
            if item['completed'] or when is None or self.delivered.get(item['id']) == when:
                continue
            retry_at = self.retries.get((item['id'], when), (0, 0))[1]
            pending.append(max(due_epoch(item), retry_at))
        if not pending and not self.dirty: return None
        # Revalidate at most every 60 seconds while scheduled work exists: timers
        # are monotonic but due times are wall clock and can cross suspend/settime.
        return min(60.0, max(0.1, min(pending) - now)) if pending else 30.0
