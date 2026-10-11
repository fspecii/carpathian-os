#!/usr/bin/env python3
"""Execute desktop preference/state handlers in temporary homes; no display."""
import ast
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import time
import unittest
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'integration/carpatic/settings/lib/cset/pages/desktop.py'
TREE = ast.parse(SOURCE.read_text())
HELPERS = {'desktop_files_marker', 'desktop_files_running', 'desktop_files_state', 'desktop_files_session', 'set_desktop_files'}

class DesktopFiles(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)
        self.folder = self.home / 'My Files'; self.folder.mkdir()
        self.directory = str(self.folder)
        self.running = False; self.commands = []
        self.environment = patch.dict(os.environ, {'HOME': str(self.home), 'DISPLAY': ':197',
            'CARPATIC_SESSION': '1', 'CARPATIC_SESSION_ID': 'owned-test-token'}, clear=True)
        self.environment.start()
        def out(*args):
            if args[0] == 'xdg-user-dir': return self.directory
            if '-root' in args: return '_NET_SUPPORTING_WM_CHECK(WINDOW): window id # 0x123'
            return '_NET_WM_NAME(UTF8_STRING) = "Carpathian OS"'
        def run(*args, **kwargs):
            self.commands.append(args)
            return (0 if self.running else 1, '') if 'present' in args else (0, '')
        self.ns = {'Path': Path, 'os': os, 'subprocess': subprocess, 'tempfile': tempfile, 'time': time,
                   'su': SimpleNamespace(which=lambda _: True, out=out, run_sync=run)}
        nodes = [node for node in TREE.body if isinstance(node, ast.FunctionDef) and node.name in HELPERS]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), self.ns)
    def tearDown(self):
        self.environment.stop(); self.temporary.cleanup()
    def marker(self): return self.ns['desktop_files_marker']()
    def disabled(self): self.marker().parent.mkdir(parents=True); self.marker().touch()
    def test_home_folder_preference_stays_disabled_without_creating_folder(self):
        self.directory = str(self.home)
        before = sorted(p.name for p in self.home.iterdir())
        state = self.ns['desktop_files_state']()
        self.assertTrue(state['home_disabled']); self.assertFalse(state['enabled'])
        with self.assertRaisesRegex(RuntimeError, 'dedicated Desktop folder'):
            self.ns['set_desktop_files'](True)
        self.assertEqual(sorted(p.name for p in self.home.iterdir()), before)
        self.assertFalse((self.home / 'Desktop').exists())
    def test_disable_uses_existing_marker_and_exact_owned_process_helper(self):
        self.ns['set_desktop_files'](False)
        self.assertTrue(self.marker().is_file())
        self.assertEqual(self.marker().stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.commands[0], ('carpatic-session-process', 'stop', '--name', 'xfdesktop'))
        self.assertEqual(self.commands[1], ('carpatic-session-process', 'present', '--name', 'xfdesktop'))
    def test_live_disabled_status_is_honest(self):
        self.disabled(); self.running = True
        state = self.ns['desktop_files_state']()
        self.assertTrue(state['running']); self.assertTrue(state['disabled'])
        self.assertIn('still running', state['status'])
    def test_disable_waits_for_exit_before_rapid_failed_enable(self):
        calls = iter([0, 0, 1])
        def stopping(*args, **kwargs):
            if args[1] == 'present': return next(calls), ''
            return 0, ''
        self.ns['su'].run_sync = stopping
        with patch.object(time, 'sleep') as pause:
            self.ns['set_desktop_files'](False)
        self.assertEqual(pause.call_count, 2)
        self.assertTrue(self.marker().exists())
        self.ns['su'].run_sync = lambda *args, **kwargs: (1, '')
        process = MagicMock(); process.poll.return_value = 1
        with patch.object(subprocess, 'Popen', return_value=process):
            with self.assertRaisesRegex(RuntimeError, 'could not start'):
                self.ns['set_desktop_files'](True)
        self.assertTrue(self.marker().exists())
    def test_inspection_timeout_does_not_claim_desktop_stopped(self):
        self.ns['su'].run_sync = lambda *args, **kwargs: (124, '') if args[1] == 'present' else (0, '')
        with self.assertRaisesRegex(RuntimeError, 'could not be checked'):
            self.ns['set_desktop_files'](False)
        self.assertTrue(self.marker().exists())

    def test_disable_timeout_keeps_marker_and_reports_running(self):
        self.running = True
        clock = iter([0, 0, 5])
        with patch.object(time, 'monotonic', side_effect=lambda: next(clock)), patch.object(time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'still running'):
                self.ns['set_desktop_files'](False)
        self.assertTrue(self.marker().exists())

    def test_enable_failure_preserves_marker_and_folder_preferences(self):
        self.disabled()
        process = MagicMock(); process.poll.return_value = 1
        with patch.object(subprocess, 'Popen', return_value=process):
            with self.assertRaisesRegex(RuntimeError, 'could not start'):
                self.ns['set_desktop_files'](True)
        self.assertTrue(self.marker().exists())
        self.assertEqual(self.directory, str(self.folder))
    def test_start_timeout_reaps_only_new_child_and_preserves_marker(self):
        self.disabled()
        process = MagicMock(); process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired('owned child', 2), 0]
        clock = iter([0, 0, 5])
        with patch.object(subprocess, 'Popen', return_value=process), \
                patch.object(time, 'monotonic', side_effect=lambda: next(clock)), patch.object(time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'did not become ready'):
                self.ns['set_desktop_files'](True)
        process.terminate.assert_called_once(); process.kill.assert_called_once()
        self.assertTrue(self.marker().exists())
    def test_successful_start_confirms_owned_helper_before_clearing_marker(self):
        self.disabled()
        responses = iter([1, 0])
        self.ns['su'].run_sync = lambda *args, **kwargs: (next(responses), '')
        process = MagicMock(); process.poll.return_value = None
        with patch.object(subprocess, 'Popen', return_value=process) as launch:
            self.ns['set_desktop_files'](True)
        self.assertEqual(launch.call_args.args[0], ['carpatic-desktop'])
        process.terminate.assert_not_called()
        self.assertFalse(self.marker().exists())

    def test_enable_existing_owned_desktop_clears_marker_without_duplicate(self):
        self.disabled(); self.running = True
        with patch.object(subprocess, 'Popen') as launch:
            self.ns['set_desktop_files'](True); launch.assert_not_called()
        self.assertFalse(self.marker().exists())
    def test_other_wm_or_missing_session_token_cannot_modify_preference(self):
        os.environ.pop('CARPATIC_SESSION_ID')
        with self.assertRaisesRegex(RuntimeError, 'Carpathian desktop'):
            self.ns['set_desktop_files'](False)
        self.assertFalse(self.marker().exists())
        os.environ['CARPATIC_SESSION_ID'] = 'owned-test-token'
        self.ns['su'].out = lambda *args: 'Other WM'
        with self.assertRaisesRegex(RuntimeError, 'not managed'):
            self.ns['set_desktop_files'](False)
        self.assertFalse(self.marker().exists())
    def test_symlink_preference_refused_without_modifying_target(self):
        target = self.home / 'preserve'; target.write_text('original')
        self.marker().parent.mkdir(parents=True); self.marker().symlink_to(target)
        with self.assertRaisesRegex(RuntimeError, 'symbolic link'):
            self.ns['set_desktop_files'](False)
        self.assertEqual(target.read_text(), 'original')

if __name__ == '__main__': unittest.main()
