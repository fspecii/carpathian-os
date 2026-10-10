#!/usr/bin/env python3
"""Multiprocess probe-lease safety tests; never open X or touch host display."""
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent / 'debug'))
import rendering

CHILD = '''import sys
sys.path.insert(0, sys.argv[1])
from rendering import ProbeLease
lease = ProbeLease(sys.argv[2])
print('LEASED', flush=True)
sys.stdin.readline()
lease.close()
'''


class Tests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'display.lock'

    def child(self):
        process = subprocess.Popen([sys.executable, '-u', '-c', CHILD,
                                    str(Path(rendering.__file__).parent), str(self.path)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def cleanup():
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)
        self.addCleanup(cleanup)
        ready, _, _ = select.select([process.stdout], [], [], 5)
        self.assertTrue(ready, 'Child did not report a held lease')
        self.assertEqual(process.stdout.readline().strip(), 'LEASED')
        return process

    def test_multiprocess_nonblocking_contention_and_reacquire(self):
        child = self.child()
        inode = self.path.stat().st_ino
        start = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, 'Another probe owns'):
            rendering.ProbeLease(self.path)
        self.assertLess(time.monotonic() - start, .5)
        _, stderr = child.communicate('\n', timeout=5)
        self.assertEqual(child.returncode, 0, stderr)
        lease = rendering.ProbeLease(self.path)
        lease.close()
        self.assertEqual(self.path.stat().st_ino, inode, 'Lease inode must persist')

    def test_abrupt_owner_exit_releases_kernel_lease(self):
        child = self.child()
        inode = self.path.stat().st_ino
        child.kill()
        child.communicate(timeout=5)
        lease = rendering.ProbeLease(self.path)
        lease.close()
        self.assertEqual(self.path.stat().st_ino, inode)

    def test_symlink_refused_without_target_change(self):
        target = Path(self.temporary.name) / 'target'
        target.write_text('untouched')
        target.chmod(0o600)
        self.path.symlink_to(target)
        with self.assertRaises(OSError):
            rendering.ProbeLease(self.path)
        self.assertEqual(target.read_text(), 'untouched')
        self.assertTrue(self.path.is_symlink())

    def test_existing_insecure_permissions_refused(self):
        self.path.write_text('')
        self.path.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, 'Unsafe probe lease'):
            rendering.ProbeLease(self.path)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o644)

    def test_hardlink_refused(self):
        self.path.write_text('')
        self.path.chmod(0o600)
        os.link(self.path, Path(self.temporary.name) / 'second-link')
        with self.assertRaisesRegex(RuntimeError, 'Unsafe probe lease'):
            rendering.ProbeLease(self.path)

    def test_contention_precedes_loading_xlib(self):
        lease = rendering.ProbeLease(self.path)
        self.addCleanup(lease.close)
        original = rendering.ProbeLease
        with patch.object(rendering, 'fixture_lease_required', return_value=True), \
                patch.object(rendering, 'ProbeLease', side_effect=lambda: original(self.path)), \
                patch.object(rendering.c, 'CDLL') as library:
            with self.assertRaisesRegex(RuntimeError, 'Another probe owns'):
                rendering.Display()
            library.assert_not_called()

    def test_constructor_failure_releases_lease(self):
        original = rendering.ProbeLease
        with patch.object(rendering, 'fixture_lease_required', return_value=True), \
                patch.object(rendering, 'ProbeLease', side_effect=lambda: original(self.path)), \
                patch.object(rendering.c, 'CDLL', side_effect=RuntimeError('Xlib unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'Xlib unavailable'):
                rendering.Display()
        lease = original(self.path)
        lease.close()

    def test_post_open_constructor_failure_preserves_original_and_releases(self):
        original = rendering.ProbeLease
        library = MagicMock()
        library.XOpenDisplay.return_value = 1
        library.XDefaultRootWindow.side_effect = RuntimeError('root unavailable')
        library.XCloseDisplay.side_effect = RuntimeError('close unavailable')
        with patch.object(rendering, 'fixture_lease_required', return_value=True), \
                patch.object(rendering, 'ProbeLease', side_effect=lambda: original(self.path)), \
                patch.object(rendering.c, 'CDLL', return_value=library):
            with self.assertRaisesRegex(RuntimeError, 'root unavailable') as failure:
                rendering.Display()
        self.assertTrue(any('close unavailable' in note for note in failure.exception.__notes__))
        library.XCloseDisplay.assert_called_once_with(1)
        lease = original(self.path)
        lease.close()

    def test_close_failures_still_close_connection_and_release_lease(self):
        calls = []
        def destroy(handle, window):
            calls.append(window)
            raise RuntimeError('destroy failure')
        display = rendering.Display.__new__(rendering.Display)
        display.handle, display.windows = 1, [10, 11]
        display.lease = rendering.ProbeLease(self.path)
        display.x = SimpleNamespace(XDestroyWindow=destroy,
                                    XSync=lambda *args: calls.append('sync'),
                                    XCloseDisplay=lambda *args: calls.append('close'))
        with self.assertRaisesRegex(RuntimeError, 'destroy failure'):
            display.close()
        self.assertEqual(calls, [11, 10, 'sync', 'close'])
        self.assertIsNone(display.handle)
        display.close()
        lease = rendering.ProbeLease(self.path)
        lease.close()

    def test_only_explicit_isolated_alpine_zero_display_requires_lease(self):
        valid = dict(DISPLAY=':0', CARPATIC_VM_TEST='1')
        with patch.object(rendering.Path, 'is_file', return_value=True):
            for environment, expected in [(valid, True), ({'DISPLAY': ':0'}, False),
                                          ({**valid, 'DISPLAY': ':193'}, False),
                                          ({**valid, 'WAYLAND_DISPLAY': ''}, False)]:
                with patch.dict(os.environ, environment, clear=True):
                    self.assertEqual(rendering.fixture_lease_required(), expected)
        with patch.dict(os.environ, valid, clear=True), patch.object(rendering.Path, 'is_file', return_value=False):
            self.assertFalse(rendering.fixture_lease_required())


if __name__ == '__main__':
    unittest.main()
