#!/usr/bin/env python3
"""MIT-SHM failure injection: no X server or IPC system calls."""
import ctypes as c
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('shared_snapshot', Path(__file__).parent / 'debug/shared_snapshot.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Function:
    def __init__(self, operation):
        self.operation = operation
    def __call__(self, *args):
        return self.operation(*args)


class Fixture:
    def __init__(self, attach_error=False, sync_failure=False):
        self.calls = []
        self.handler = None
        self.attach_error = attach_error
        self.sync_failure = sync_failure
        self.pending = False
        self.header = m.Header(width=4, height=4, bits_per_pixel=32,
                               byte_order=0, bytes_per_line=16,
                               red_mask=0xff0000, green_mask=0xff00, blue_mask=0xff)
        self.buffer = c.create_string_buffer(64)
        def record(name, result):
            return Function(lambda *args: self.calls.append(name) or result)
        def handler(pointer):
            old = self.handler
            self.handler = pointer
            return old
        def attach(*args):
            self.calls.append('attach')
            self.pending = True
            return 1
        def sync():
            if self.pending:
                self.pending = False
                if self.sync_failure:
                    raise RuntimeError('injected sync failure')
                if self.attach_error:
                    error = m.XError(error_code=8, request_code=130, minor_code=4)
                    c.CFUNCTYPE(c.c_int, c.c_void_p, c.c_void_p)(self.handler.value)(None, c.addressof(error))
        self.display = SimpleNamespace(handle=1, root=2, sync=sync)
        self.display.x = SimpleNamespace(
            XDefaultVisual=record('visual', 1), XDefaultDepth=record('depth', 24),
            XDestroyImage=record('destroy_image', 0),
            XSetErrorHandler=Function(handler))
        self.ext = SimpleNamespace(
            XShmQueryExtension=record('extension', 1),
            XShmCreateImage=record('image', c.addressof(self.header)),
            XShmAttach=Function(attach), XShmDetach=record('detach_server', 1),
            XShmGetImage=record('capture', 1))
        self.lib = SimpleNamespace(
            shmget=record('shmget', 17), shmat=record('shmat', c.addressof(self.buffer)),
            shmdt=record('shmdt', 0), shmctl=record('rmid', 0))

    def create(self):
        def library(name, **kwargs):
            return self.ext if name else self.lib
        with patch.dict(m.os.environ, {'DISPLAY': ':0', 'CARPATIC_VM_TEST': '1'}, clear=True), \
                patch.object(m.Path, 'exists', return_value=True), patch.object(m.c, 'CDLL', side_effect=library):
            return m.Snapshot(self.display, 4, 4)


class Tests(unittest.TestCase):
    def assert_released(self, fixture):
        for operation in ('detach_server', 'destroy_image', 'shmdt', 'rmid'):
            self.assertIn(operation, fixture.calls)
        self.assertIsNone(fixture.handler)

    def test_attach_server_error_cleans_all_resources(self):
        fixture = Fixture(attach_error=True)
        with self.assertRaisesRegex(RuntimeError, 'XShmAttach rejected'):
            fixture.create()
        self.assert_released(fixture)

    def test_attach_sync_failure_cleans_all_resources(self):
        fixture = Fixture(sync_failure=True)
        with self.assertRaisesRegex(RuntimeError, 'injected sync failure'):
            fixture.create()
        self.assert_released(fixture)

    def test_capture_server_error_restores_handler(self):
        fixture = Fixture()
        snapshot = fixture.create()
        fixture.attach_error = True
        def capture(*args):
            fixture.pending = True
            # XShmGetImage itself waits for its reply and dispatches errors.
            fixture.display.sync()
            return 1
        fixture.ext.XShmGetImage = Function(capture)
        with self.assertRaisesRegex(RuntimeError, r'XShmGetImage rejected.*8, 130, 4'):
            snapshot.capture()
        self.assertIsNone(fixture.handler)
        snapshot.close()
        self.assert_released(fixture)

    def test_capture_uses_reply_without_extra_sync(self):
        fixture = Fixture()
        snapshot = fixture.create()
        old_sync = fixture.display.sync
        fixture.display.sync = lambda: (_ for _ in ()).throw(AssertionError('redundant XSync'))
        try:
            data, stride = snapshot.capture()
            self.assertEqual((len(data), stride), (64, 16))
            self.assertIsNone(fixture.handler)
        finally:
            fixture.display.sync = old_sync
            snapshot.close()
        self.assert_released(fixture)

    def test_close_sync_failure_still_releases_local_resources(self):
        fixture = Fixture()
        snapshot = fixture.create()
        fixture.display.sync = lambda: (_ for _ in ()).throw(RuntimeError('close sync failure'))
        with self.assertRaisesRegex(RuntimeError, 'close sync failure'):
            snapshot.close()
        for name in ('detach_server', 'destroy_image', 'shmdt', 'rmid'):
            self.assertIn(name, fixture.calls)
        self.assertIsNone(snapshot.image)
        self.assertEqual(snapshot.segment.shmid, -1)
        snapshot.close()

    def test_happy_close_does_not_remove_already_marked_segment(self):
        fixture = Fixture()
        snapshot = fixture.create()
        self.assertTrue(snapshot.segment_marked)
        self.assertEqual(fixture.calls.count('rmid'), 1)
        fixture.lib.shmctl = Function(lambda *args: self.fail('Redundant IPC_RMID'))
        snapshot.close()
        self.assertEqual(fixture.calls.count('rmid'), 1)
        self.assert_released(fixture)

    def test_guard_rejects_host_before_loading_libraries(self):
        fixture = Fixture()
        with patch.dict(m.os.environ, {'DISPLAY': ':1'}, clear=True), patch.object(m.c, 'CDLL') as library:
            with self.assertRaisesRegex(RuntimeError, 'isolated Alpine'):
                m.Snapshot(fixture.display, 4, 4)
            library.assert_not_called()


if __name__ == '__main__':
    unittest.main()
