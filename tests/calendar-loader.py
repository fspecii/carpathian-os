#!/usr/bin/env python3
"""Real-thread tests; no GTK, display, or user's calendar required."""
import importlib.util
import pathlib
import queue
import threading
import unittest

PATH = pathlib.Path(__file__).resolve().parents[1] / 'integration/carpatic/panel/lib/carpatic_panel/event_loader.py'
spec = importlib.util.spec_from_file_location('event_loader', PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.callbacks = queue.Queue()
        self.started = queue.Queue()
        self.release = threading.Event()
        self.calls = []
        self.results = []
        self.main = threading.get_ident()
        self.fail = False

        def load(lo, hi, data, issues):
            self.calls.append((lo, hi, data, threading.current_thread().daemon))
            self.started.put(data)
            if not self.release.wait(3):
                raise RuntimeError('test handshake timeout')
            if self.fail:
                raise ValueError('broken import')
            issues.append('import warning')
            return [data]

        def result(*args):
            self.assertEqual(threading.get_ident(), self.main)
            self.results.append(args)

        self.loader = module.EventLoader(load, self.callbacks.put, result)
        self.addCleanup(self.release.set)
        self.addCleanup(self.loader.close)

    def pump(self):
        self.callbacks.get(timeout=3)()

    def test_result_and_no_idle_worker(self):
        self.loader.request('a', 1, 2, 'first')
        self.assertEqual(self.started.get(timeout=3), 'first')
        worker = self.loader._active[1]
        self.release.set()
        self.pump()
        self.assertEqual(self.results, [('a', ['first'], ['import warning'])])
        self.assertFalse(worker.is_alive())
        self.assertIsNone(self.loader._active)
        self.assertEqual(self.calls[0], (1, 2, 'first', True))

    def test_latest_pending_coalesces_and_suppresses_stale(self):
        self.loader.request('a', 1, 2, 'first')
        self.started.get(timeout=3)
        self.loader.request('b', 3, 4, 'discarded')
        self.loader.request('c', 5, 6, 'last')
        self.release.set()
        self.pump()
        self.assertEqual(self.results, [])
        self.assertEqual(self.started.get(timeout=3), 'last')
        self.pump()
        self.assertEqual([c[2] for c in self.calls], ['first', 'last'])
        self.assertEqual(self.results, [('c', ['last'], ['import warning'])])

    def test_same_active_key_does_not_reload(self):
        self.loader.request('a', 1, 2, 'first')
        self.started.get(timeout=3)
        self.loader.request('b', 1, 2, 'pending')
        self.loader.request('a', 1, 2, 'duplicate')
        self.release.set()
        self.pump()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.results[0][0], 'a')

    def test_close_discards_pending_and_future_requests(self):
        self.loader.request('a', 1, 2, 'first')
        self.started.get(timeout=3)
        self.loader.request('b', 1, 2, 'pending')
        self.loader.close()
        self.loader.request('c', 1, 2, 'future')
        self.release.set()
        self.pump()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.results, [])

    def test_close_after_completion_queued(self):
        self.release.set()
        self.loader.request('a', 1, 2, 'first')
        callback = self.callbacks.get(timeout=3)
        self.loader.close()
        callback()
        self.assertEqual(self.results, [])

    def test_failure_then_retry(self):
        self.fail = True
        self.release.set()
        self.loader.request('a', 1, 2, 'first')
        self.pump()
        self.assertEqual(self.results[0][1], [])
        self.assertIn('broken import', self.results[0][2][0])
        self.fail = False
        self.loader.request('b', 1, 2, 'retry')
        self.pump()
        self.assertEqual(self.results[-1][1], ['retry'])

    def test_result_callback_can_request(self):
        self.release.set()
        def received(key, events, issues):
            self.results.append(key)
            if key == 'a':
                self.loader.request('b', 1, 2, 'second')
        self.loader._on_result = received
        self.loader.request('a', 1, 2, 'first')
        self.pump()
        self.pump()
        self.assertEqual(self.results, ['a', 'b'])

    def test_result_callback_can_close(self):
        self.release.set()
        self.loader._on_result = lambda *args: self.loader.close()
        self.loader.request('a', 1, 2, 'first')
        self.pump()
        self.assertTrue(self.loader._closed)
        self.assertIsNone(self.loader._active)


if __name__ == '__main__':
    unittest.main()
