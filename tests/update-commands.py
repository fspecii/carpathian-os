#!/usr/bin/env python3
"""Update status regressions with stub tools; never mutate real system packages."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / 'integration/carpatic/compat/bin/carpatic-update'

class UpdateCommands(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'; self.bin.mkdir()
        # A fixture copy redirects every /run write. Production has no runtime
        # directory override that could be abused by a privileged caller.
        self.script = self.root / 'carpatic-update'
        self.script.write_text(SOURCE.read_text().replace('/run/', str(self.root / 'run') + '/'))
        runtime = self.root / 'run/carpatic'; runtime.mkdir(parents=True)
        (runtime / 'boot-versions').write_text('')
        self.counter = runtime / 'updates-available'; self.counter.write_text('7\n')
        self.env = dict(os.environ, PATH=str(self.bin)+':/usr/bin:/bin', TMPDIR=str(self.root),
                        STUB_LOG=str(self.root / 'commands.log'), CASE='success', CARPATIC_RUNNING_KERNEL='test')
        self.stub('id', 'printf "0\\n"')
        self.stub('ls', 'printf "test\\n"')
        self.stub('carpatic-rollback', 'exit 0')
        self.stub('apk', '''printf '%s\\n' "apk $*" >> "$STUB_LOG"
case "$1" in
 update) [ "$CASE" != offline ];;
 list) [ "$CASE" != list-failure ] || exit 1
       [ "$CASE" = no-updates ] || echo 'example-2 x86_64 [upgradable from: example-1]' ; exit 0;;
 upgrade) echo 'starting upgrade'; echo 'package operation detail'; echo 'final package result'
          [ "$CASE" != upgrade-failure ];;
 info) exit 1;;
 *) exit 1;;
esac''')
        self.stub('fwupdmgr', '''printf '%s\\n' "firmware $*" >> "$STUB_LOG"
echo 'firmware tool output'
[ "$CASE" != firmware-failure ]''')
    def tearDown(self): self.temp.cleanup()
    def stub(self, name, body):
        p = self.bin / name; p.write_text('#!/bin/sh\n'+body+'\n'); p.chmod(0o755)
    def invoke(self, mode='apply', case='success'):
        self.env['CASE'] = case
        return subprocess.run(['sh', str(self.script), *mode.split()], env=self.env,
                              capture_output=True, text=True, timeout=5)
    def assert_no_success(self, result):
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('Done.', result.stdout)
        self.assertEqual(self.counter.read_text(), '7\n')
    def test_upgrade_failure_is_not_tail_success(self):
        result = self.invoke(case='upgrade-failure')
        self.assert_no_success(result)
        self.assertIn('final package result', result.stdout)
        self.assertIn('did not finish', result.stderr)
        self.assertFalse(list(self.root.glob('carpatic-update-*')))
    def test_success_clears_count_only_after_upgrade(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Done.', result.stdout)
        self.assertEqual(self.counter.read_text(), '0\n')
    def test_offline_refresh_never_starts_upgrade(self):
        result = self.invoke(case='offline'); self.assert_no_success(result)
        self.assertNotIn('apk upgrade', (self.root / 'commands.log').read_text())
    def test_failed_list_is_not_up_to_date(self):
        for mode in ('apply', 'check', 'list'):
            result = self.invoke(mode, 'list-failure')
            self.assert_no_success(result)
            self.assertNotIn('up to date', result.stdout)
    def test_empty_list_is_successful_noop(self):
        result = self.invoke(case='no-updates')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('up to date', result.stdout)
        self.assertNotIn('apk upgrade', (self.root / 'commands.log').read_text())
    def test_failed_firmware_does_not_announce_completion(self):
        result = self.invoke('firmware apply', 'firmware-failure')
        self.assert_no_success(result)
        self.assertNotIn('restart to finish', result.stdout)
    def test_successful_firmware_preserves_tool_output(self):
        result = self.invoke('firmware apply')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('firmware tool output', result.stdout)

if __name__ == '__main__': unittest.main(verbosity=2)
