#!/usr/bin/env python3
"""Read-only status failure regressions; no GTK, package or system mutation."""
import ast
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

SOURCE = Path(__file__).resolve().parents[1] / 'integration/carpatic/settings/lib/cset/pages/system.py'
tree = ast.parse(SOURCE.read_text())
nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in
         {'parse_update_status', 'read_update_status'}]
page = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'UpdatesPage')
fill = next(n for n in page.body if isinstance(n, ast.FunctionDef) and n.name == 'fill')
namespace = {'subprocess': subprocess}
exec(compile(ast.Module(body=nodes + [fill], type_ignores=[]), str(SOURCE), 'exec'), namespace)

class UpdateStatus(unittest.TestCase):
    def test_failed_command_cannot_publish_success_text(self):
        with patch.object(subprocess, 'run', side_effect=subprocess.CalledProcessError(
                1, ['carpatic-update', 'status'], output='updates: 0, restart needed: no')):
            with self.assertRaises(subprocess.CalledProcessError): namespace['read_update_status']()

    def test_missing_timeout_and_invalid_output_are_errors(self):
        for failure in (FileNotFoundError(), subprocess.TimeoutExpired('status', 15)):
            with patch.object(subprocess, 'run', side_effect=failure):
                with self.assertRaises(type(failure)): namespace['read_update_status']()
        with patch.object(subprocess, 'run', return_value=SimpleNamespace(stdout='')):
            with self.assertRaises(RuntimeError): namespace['read_update_status']()

    def test_valid_status_and_untrusted_count(self):
        with patch.object(subprocess, 'run', return_value=SimpleNamespace(
                stdout='updates: 2, restart needed: yes\n')):
            value = namespace['read_update_status']()
        self.assertEqual(namespace['parse_update_status'](value), ('2', True))
        self.assertEqual(namespace['parse_update_status']('updates: failed, restart needed: no'), ('unknown', False))

    def test_failure_replaces_stale_success_and_disables_actions(self):
        page = SimpleNamespace(status=MagicMock(), btn_apply=MagicMock(), btn_restart=MagicMock())
        namespace['fill'](page, RuntimeError('status failed'))
        page.status.set_value.assert_called_once_with('Status unavailable')
        page.status.set_state.assert_called_once_with('warn')
        page.btn_apply.set_sensitive.assert_called_once_with(False)
        page.btn_restart.set_visible.assert_called_once_with(False)

if __name__ == '__main__': unittest.main(verbosity=2)
