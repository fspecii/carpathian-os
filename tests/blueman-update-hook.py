#!/usr/bin/env python3
"""APK lifecycle fixtures for Blueman compatibility; no host paths mutated."""
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / 'integration/carpatic/compat/system/apk-commit-hook'


class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='blueman apk lifecycle ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manager = self.root / 'usr/bin/blueman-manager'
        self.patch = self.root / 'usr/libexec/carpatic/blueman-passkey.py'
        self.marker = self.root / 'run/carpathian-blueman-compatibility-error'
        self.calls = self.root / 'patch-calls'
        self.source = self.root / 'agent-source'
        self.fail = self.root / 'fail-patch'
        for path in (self.manager, self.patch, self.marker): path.parent.mkdir(parents=True, exist_ok=True)
        self.manager.write_text('fixture manager'); self.manager.chmod(0o700)
        self.source.write_text('upstream')
        self.patch.write_text('from pathlib import Path\n' +
            'calls=Path(' + repr(str(self.calls)) + ')\n' +
            "with calls.open('a') as stream: stream.write('applied\\n')\n" +
            'if Path(' + repr(str(self.fail)) + ').exists(): raise SystemExit(1)\n' +
            'Path(' + repr(str(self.source)) + ").write_text('patched')\n")
        source = HOOK.read_text()
        replacements = {
            '/usr/bin/blueman-manager': self.manager,
            '/usr/libexec/carpatic/blueman-passkey.py': self.patch,
            '/var/lib/carpathian-blueman-compatibility-error': self.marker,
            '/usr/bin/python3': Path(sys.executable),
            '/usr/local/bin/carpatic-update': self.root / 'absent-update',
            '/usr/lib/cups/backend/cups-pdf': self.root / 'absent-cups',
            '/usr/libexec/carpatic/brand-os': self.root / 'absent-brand',
        }
        for old, new in replacements.items(): source = source.replace(old, shlex.quote(str(new)))
        self.hook = self.root / 'hook'; self.hook.write_text(source)
        self.env = dict(os.environ, CARPATIC_APPS_DIR=str(self.root / 'apps'), CARPATIC_ICON_DIR=str(self.root / 'icons'))

    def run_hook(self, phase='post-commit'):
        return subprocess.run(['/bin/sh', str(self.hook), phase], env=self.env, capture_output=True, text=True, timeout=5)

    def test_success_and_repeat_are_idempotent(self):
        self.marker.write_text('old failure')
        for _ in range(2):
            result = self.run_hook(); self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.source.read_text(), 'patched'); self.assertFalse(self.marker.exists())
        self.assertEqual(self.calls.read_text().splitlines(), ['applied', 'applied'])

    def test_package_overwrite_reapplies_compatibility(self):
        self.assertEqual(self.run_hook().returncode, 0)
        self.source.write_text('upstream')
        self.assertEqual(self.run_hook().returncode, 0)
        self.assertEqual(self.source.read_text(), 'patched')
        self.assertEqual(len(self.calls.read_text().splitlines()), 2)

    def test_patch_failure_leaves_generic_marker_and_nonzero(self):
        self.fail.touch()
        result = self.run_hook()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.marker.is_file())
        self.assertNotIn(str(self.root), self.marker.read_text())
        self.assertEqual(self.source.read_text(), 'upstream')

    def test_package_removal_clears_old_failure_without_patch(self):
        self.manager.unlink(); self.marker.write_text('old failure')
        result = self.run_hook(); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.marker.exists()); self.assertFalse(self.calls.exists())

    def test_precommit_does_not_execute_patch_or_change_marker(self):
        self.marker.write_text('old failure')
        result = self.run_hook('pre-commit'); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.calls.exists()); self.assertEqual(self.marker.read_text(), 'old failure')
        self.assertEqual(self.source.read_text(), 'upstream')


class DesktopInstallation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='blueman desktop install ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.integration = self.root / 'integration'
        self.helper_source = self.integration / 'compatibility/blueman-passkey.py'
        self.hook_source = self.integration / 'compat/system/apk-commit-hook'
        for path in (self.helper_source, self.hook_source): path.parent.mkdir(parents=True, exist_ok=True)
        self.helper_source.write_bytes((ROOT / 'integration/carpatic/compatibility/blueman-passkey.py').read_bytes())
        self.hook_source.write_bytes(HOOK.read_bytes())
        self.helper = self.root / 'installed/helper.py'
        self.hook = self.root / 'installed/hooks/carpatic-fixups'
        self.marker = self.root / 'state/repair'
        self.marker.parent.mkdir(); self.marker.write_text('retained failure')
        binary = self.root / 'bin'; binary.mkdir()
        self.calls = self.root / 'python-calls'
        stub = binary / 'python3'
        stub.write_text('#!/bin/sh\nprintf \'%s\\n\' "$@" > "$FIXTURE_CALLS"\nexit "$FIXTURE_PATCH_RC"\n')
        stub.chmod(0o700)
        self.env = dict(os.environ, PATH=str(binary) + ':/usr/bin:/bin', SRC=str(self.integration),
                        FIXTURE_CALLS=str(self.calls), FIXTURE_PATCH_RC='0')
        text = (ROOT / 'alpine/desktop-tools.sh').read_text()
        start = text.index('# Install pairing compatibility and its APK lifecycle in every desktop.')
        end = text.index('# End Bluetooth compatibility lifecycle.', start)
        self.block = text[start:end]
        for old, new in (('/usr/libexec/carpatic/blueman-passkey.py', self.helper),
                         ('/var/lib/carpathian-blueman-compatibility-error', self.marker),
                         ('/etc/apk/commit_hooks.d/carpatic-fixups', self.hook)):
            self.block = self.block.replace(old, shlex.quote(str(new)))

    def run_install(self):
        return subprocess.run(['/bin/sh', '-eu', '-c', self.block], env=self.env,
                              capture_output=True, text=True, timeout=5)

    def test_normal_desktop_installs_exact_helper_and_hook_and_clears_marker(self):
        result = self.run_install(); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.helper.read_bytes(), self.helper_source.read_bytes())
        self.assertEqual(self.hook.read_bytes(), self.hook_source.read_bytes())
        self.assertEqual(self.helper.stat().st_mode & 0o777, 0o644)
        self.assertEqual(self.hook.stat().st_mode & 0o777, 0o755)
        self.assertEqual(self.calls.read_text().splitlines(), ['-I', str(self.helper)])
        self.assertFalse(self.marker.exists())

    def test_failed_initial_patch_aborts_without_hook_or_marker_clear(self):
        self.env['FIXTURE_PATCH_RC'] = '1'
        result = self.run_install(); self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.helper.read_bytes(), self.helper_source.read_bytes())
        self.assertFalse(self.hook.exists())
        self.assertEqual(self.marker.read_text(), 'retained failure')
        self.assertEqual(self.calls.read_text().splitlines(), ['-I', str(self.helper)])


if __name__ == '__main__': unittest.main()
