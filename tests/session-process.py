#!/usr/bin/env python3
"""Real owned subprocesses verify helper signals never cross X displays."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'integration/carpatic/configurator/bin/carpatic-session-process'


class ProcessScope(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='carpatic-process-scope-')
        self.base = Path(self.tmp.name)
        self.script = self.base / 'carpatic-scope-proof'
        self.script.write_text('''import os, signal, time
from pathlib import Path
signal.signal(signal.SIGUSR1, lambda *_: Path(os.environ['MARK']).write_text('USR1'))
signal.signal(signal.SIGHUP, lambda *_: Path(os.environ['MARK']).write_text('HUP'))
Path(os.environ['READY']).write_text('ready')
while True: time.sleep(.1)
''')
        self.env = dict(os.environ, DISPLAY=':997', CARPATIC_SESSION='1')
        self.env.pop('WAYLAND_DISPLAY', None)
        self.children = []

    def tearDown(self):
        for child in self.children:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=3)
        self.tmp.cleanup()

    def spawn(self, display, suffix=''):
        index = len(self.children)
        ready = self.base / f'ready-{index}'
        mark = self.base / f'mark-{index}'
        script = self.script
        if suffix:
            script = self.base / (self.script.name + suffix)
            script.write_text(self.script.read_text())
        child = subprocess.Popen([sys.executable, str(script)],
                                 env=dict(self.env, DISPLAY=display, READY=str(ready), MARK=str(mark)))
        self.children.append(child)
        self.wait(lambda: ready.exists())
        return child, mark

    def wait(self, predicate):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.01)
        self.fail('bounded process condition timed out')

    def call(self, action, *args, env=None):
        return subprocess.run([sys.executable, str(CLI), action, '--script', self.script.name, *args],
                              env=env or self.env, capture_output=True, text=True, timeout=3)

    def test_pid_and_signal_are_display_scoped(self):
        own, own_mark = self.spawn(':997.0')
        other, other_mark = self.spawn(':998')
        prefix, _ = self.spawn(':997', '-different')
        result = self.call('pid')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(own.pid))
        self.assertEqual(self.call('stop', '--signal', 'USR1').returncode, 0)
        self.wait(own_mark.exists)
        self.assertEqual(own_mark.read_text(), 'USR1')
        self.assertFalse(other_mark.exists())
        self.assertIsNone(prefix.poll())
        self.assertEqual(self.call('stop').returncode, 0)
        self.wait(lambda: own.poll() is not None)
        self.assertIsNone(other.poll())
        self.assertIsNone(prefix.poll())

    def test_other_display_does_not_suppress_startup(self):
        self.spawn(':998')
        self.assertEqual(self.call('present').returncode, 1)

    def test_session_and_wayland_guards(self):
        own, _ = self.spawn(':997')
        for env in (dict(self.env, CARPATIC_SESSION='0'), dict(self.env, WAYLAND_DISPLAY='wayland-1')):
            self.assertEqual(self.call('stop', env=env).returncode, 2)
        self.assertIsNone(own.poll())


if __name__ == '__main__':
    unittest.main(verbosity=2)
