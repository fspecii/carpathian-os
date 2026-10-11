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
        self.mounts = self.root / 'mounts'; self.mounts.write_text('/dev/test / btrfs rw 0 0\n')
        self.script.write_text(SOURCE.read_text().replace('/run/', str(self.root / 'run') + '/').replace('/proc/mounts', str(self.mounts)).replace('/var/lib/carpathian-blueman-compatibility-error', str(self.root / 'run/carpathian-blueman-compatibility-error')))
        runtime = self.root / 'run/carpatic'; runtime.mkdir(parents=True)
        (runtime / 'boot-versions').write_text('')
        self.counter = runtime / 'updates-available'; self.counter.write_text('7\n')
        self.env = dict(os.environ, PATH=str(self.bin)+':/usr/bin:/bin', TMPDIR=str(self.root),
                        STUB_LOG=str(self.root / 'commands.log'), CASE='success', CARPATIC_RUNNING_KERNEL='test')
        self.stub('id', 'printf "0\\n"')
        self.stub('ls', 'printf "test\\n"')
        self.stub('carpatic-rollback', 'printf \"%s\\n\" \"rollback $*\" >> \"$STUB_LOG\"; [ \"$CASE\" != snapshot-failure ]')
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
    def test_bluetooth_compatibility_failure_does_not_report_update_complete(self):
        marker = self.root / 'run/carpathian-blueman-compatibility-error'
        marker.write_text('Compatibility update required')
        result = self.invoke()
        self.assert_no_success(result)
        self.assertIn('Bluetooth pairing requires a compatibility update', result.stderr)
        self.assertIn('apk upgrade', (self.root / 'commands.log').read_text())

    def test_bluetooth_repair_marker_is_not_hidden_by_empty_update_list(self):
        (self.root / 'run/carpathian-blueman-compatibility-error').write_text('repair needed')
        result = self.invoke(case='no-updates')
        self.assert_no_success(result)
        self.assertNotIn('Your system is up to date', result.stdout)
        self.assertIn('Bluetooth pairing requires a compatibility update', result.stderr)

    def test_upgrade_failure_retains_bluetooth_repair_reason(self):
        (self.root / 'run/carpathian-blueman-compatibility-error').write_text('repair needed')
        result = self.invoke(case='upgrade-failure')
        self.assert_no_success(result)
        self.assertIn('Bluetooth pairing requires a compatibility update', result.stderr)

    def test_btrfs_snapshot_failure_stops_before_upgrade(self):
        result = self.invoke(case='snapshot-failure')
        self.assert_no_success(result)
        self.assertNotIn('apk upgrade', (self.root / 'commands.log').read_text())
        self.assertIn('safety restore point could not be saved', result.stderr)
    def test_real_rollback_boot_copy_failure_blocks_upgrade(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('actual_rollback_failure_fixture', ROOT / 'tests/rollback-commands.py')
        recovery_module = importlib.util.module_from_spec(spec); spec.loader.exec_module(recovery_module)
        recovery = recovery_module.Recovery('test_successful_restore_keeps_nested_and_home')
        recovery.setUp()
        try:
            self.stub('carpatic-rollback', 'exec /bin/sh "$REAL_ROLLBACK" "$@"')
            for name in ('CARPATIC_TOP','CARPATIC_BOOT','CARPATIC_INDEX','TEST_ROOT','TEST_TOP','TEST_BOOT','TEST_ID','NESTED'):
                self.env[name] = recovery.env[name]
            self.env.update(REAL_ROLLBACK=str(recovery_module.SCRIPT), FAILURE='snapshot-copy',
                            PATH=str(self.bin)+':'+str(recovery.bin)+':/usr/bin:/bin')
            self.script.write_text(self.script.read_text().replace(str(self.root/'run/carpatic/.carpathian-rollback.lock'),str(recovery.top/'.carpathian-rollback.lock')))
            result = self.invoke()
            self.assert_no_success(result)
            self.assertNotIn('apk upgrade', (self.root/'commands.log').read_text())
            self.assertIn('restore point was not published',result.stderr)
            recovery.original_boot(); recovery.preserved_root(); recovery.clean_staging()
        finally:
            recovery.doCleanups()

    def test_update_holds_restore_lock_during_package_upgrade(self):
        import fcntl, time
        started=self.root/'upgrade-started'; release=self.root/'upgrade-release'
        self.stub('apk', '\n'.join([
            'case "$1" in',
            'update) exit 0;;',
            'list) echo example; exit 0;;',
            'upgrade) touch "'+str(started)+'"; while [ ! -f "'+str(release)+'" ]; do sleep 0.05; done;;',
            'info) exit 1;;', 'esac']))
        process=subprocess.Popen(['sh',str(self.script),'apply'],env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            deadline=time.monotonic()+3
            while not started.exists() and time.monotonic()<deadline: time.sleep(.02)
            self.assertTrue(started.exists())
            with (self.root/'run/carpatic/.carpathian-rollback.lock').open('w') as lock:
                with self.assertRaises(BlockingIOError): fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            restore_env=dict(self.env, CARPATIC_TOP=str(self.root/'run/carpatic'))
            denied=subprocess.run(['sh',str(ROOT/'integration/carpatic/compat/bin/carpatic-rollback'),'snapshot','during-update'],env=restore_env,capture_output=True,text=True,timeout=3)
            self.assertNotEqual(denied.returncode,0)
            self.assertIn('another restore-point operation',denied.stderr)
            release.touch(); output,error=process.communicate(timeout=5)
            self.assertEqual(process.returncode,0,error)
        finally:
            release.touch()
            if process.poll() is None: process.kill(); process.communicate()

    def test_btrfs_missing_restore_helper_stops_upgrade(self):
        (self.bin / 'carpatic-rollback').unlink()
        result = self.invoke()
        self.assert_no_success(result)
        self.assertNotIn('apk upgrade', (self.root / 'commands.log').read_text())
    def test_ext4_update_remains_usable_without_claiming_snapshot(self):
        self.mounts.write_text('/dev/test / ext4 rw 0 0\n')
        result = self.invoke(case='snapshot-failure')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('No system restore point is available on ext4', result.stdout)
        self.assertNotIn('Safety snapshot taken', result.stdout)
        self.assertNotIn('rollback snapshot', (self.root / 'commands.log').read_text())
        self.assertIn('apk upgrade', (self.root / 'commands.log').read_text())

    def test_periodic_caller_off_success_and_failure_status(self):
        source = ROOT/'integration/carpatic/compat/system/periodic-auto-update'
        caller = self.root/'periodic-auto-update'
        flag = self.root/'auto-updates'; log = self.root/'auto-update.log'
        caller.write_text(source.read_text().replace('/etc/carpatic/auto-updates',str(flag)).replace('/var/log/carpatic-auto-update.log',str(log)))
        self.stub('carpatic-update', 'echo "automatic apply requested"; [ "$CASE" != periodic-failure ] || exit 9')
        def run(): return subprocess.run(['sh',str(caller)],env=self.env,capture_output=True,text=True,timeout=5)
        self.assertEqual(run().returncode,0); self.assertFalse(log.exists())
        flag.touch(); self.assertEqual(run().returncode,0)
        self.assertIn('automatic apply requested',log.read_text())
        self.env['CASE']='periodic-failure'; self.assertEqual(run().returncode,9)
        (self.bin/'carpatic-update').unlink(); self.assertEqual(run().returncode,127)
        self.stub('carpatic-update', 'exit 0')
        log.unlink(); log.mkdir()
        self.assertNotEqual(run().returncode,0)

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
