#!/usr/bin/env python3
"""Recovery warnings through actual progress handlers; no GTK or commands."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'integration/carpatic/settings/lib/cset'
namespace = {}
tree = ast.parse((ROOT / 'runner.py').read_text())
friendly = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'friendly_error')
tree = ast.parse((ROOT / 'ui.py').read_text())
sheet = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ProgressSheet')
step = next(n for n in sheet.body if isinstance(n, ast.FunctionDef) and n.name == 'step_done')
exec(compile(ast.Module(body=[friendly, step], type_ignores=[]), 'actual progress handlers', 'exec'), namespace)

class ProgressErrors(unittest.TestCase):
    def result(self, cancelled, text, rc=1, auth_failed=False):
        result = []
        page = SimpleNamespace(job=SimpleNamespace(cancelled=cancelled, auth_failed=auth_failed, tail=text.splitlines()),
                               runner=SimpleNamespace(friendly_error=namespace['friendly_error']),
                               finish=lambda ok, message: result.append((ok, message)))
        namespace['step_done'](page, rc)
        return result[0]

    def test_partial_recovery_warning_survives_error_and_cancellation(self):
        warning = 'carpatic-rollback: partial restore failure; do not restart. Recovery data retained at /boot/.backup'
        for cancelled in (False, True):
            for auth_failed in (False, True):
                ok, message = self.result(cancelled, 'no space left\n' + warning, auth_failed=auth_failed)
                self.assertFalse(ok)
                self.assertEqual(message, warning)

    def test_cancelled_committed_operation_does_not_claim_unchanged(self):
        ok, message = self.result(True, 'Snapshot saved: complete-point', 130)
        self.assertFalse(ok)
        self.assertIn('Some changes may have completed', message)
        self.assertNotIn('Nothing was changed', message)

    def test_unknown_failure_does_not_claim_system_is_intact(self):
        ok, message = self.result(False, 'unrecognized failure')
        self.assertFalse(ok)
        self.assertIn('Review the details', message)
        self.assertNotIn('Nothing broken', message)

if __name__ == '__main__': unittest.main(verbosity=2)
