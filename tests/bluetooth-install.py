#!/usr/bin/env python3
"""Actual package/runtime shell stanzas in temporary roots, no network changes."""
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
DESKTOP=ROOT/'alpine/desktop-tools.sh'
REQUIRED={'bluez','bluez-openrc'}

class BluetoothInstallation(unittest.TestCase):
    def stage(self,skip,missing=None):
        with tempfile.TemporaryDirectory(prefix='Bluetooth contract ') as directory:
            root=Path(directory);bin=root/'bin';bin.mkdir();calls=root/'calls'
            (bin/'apk').write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$APK_CALLS"\n');(bin/'apk').chmod(0o755)
            if missing!='bluetoothctl':(bin/'bluetoothctl').write_text('#!/bin/sh\nexit 0\n');(bin/'bluetoothctl').chmod(0o755)
            text=DESKTOP.read_text();start=text.index('if [ "${CARPATIC_SKIP_PACKAGES:-0}" != 1 ]; then')
            package_end=text.index('\nfi',start)+3
            bluetooth_start=text.index('# GUI Bluetooth runtime contract;',package_end)
            end=text.index('# End GUI Bluetooth runtime contract.',bluetooth_start)
            block=text[start:package_end]+"\n"+text[bluetooth_start:end]
            for name in ('/usr/lib/bluetooth/bluetoothd','/etc/init.d/bluetooth'):
                target=root/name.lstrip('/');target.parent.mkdir(parents=True,exist_ok=True)
                if missing!=name:target.write_text('fixture');target.chmod(0o755)
                block=block.replace(name,shlex.quote(str(target)))
            result=subprocess.run(['/bin/sh','-eu','-c',block],env={'PATH':str(bin),'CARPATIC_SKIP_PACKAGES':str(skip),'APK_CALLS':str(calls)},capture_output=True,text=True)
            return result,calls.read_text().splitlines() if calls.exists() else []
    def test_online_installer_explicit_bluetooth_packages(self):
        result,packages=self.stage(0)
        self.assertEqual(result.returncode,0,result.stderr);self.assertTrue(REQUIRED<=set(packages))
    def test_prebuilt_skip_still_checks_complete_runtime(self):
        result,packages=self.stage(1)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(packages,[])
    def test_each_missing_runtime_fails_even_when_packages_skipped(self):
        for missing in ('bluetoothctl','/usr/lib/bluetooth/bluetoothd','/etc/init.d/bluetooth'):
            for skip in (0,1):
                with self.subTest(missing=missing,skip=skip):
                    result,packages=self.stage(skip,missing)
                    self.assertNotEqual(result.returncode,0)
                    self.assertIn('Required desktop Bluetooth runtime is missing:',result.stderr)
                    if skip:self.assertEqual(packages,[])
    def test_offline_guard_requires_each_exact_package(self):
        text=(ROOT/'scripts/build-dev-iso.sh').read_text();start=text.index('for required in xterm ')
        block=text[start:text.index('\ndone',start)+len('\ndone')]
        names=shlex.split(block.split('for required in ',1)[1].split('; do',1)[0])
        self.assertTrue(REQUIRED<=set(names))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in names:(root/(name+'-1.0-r0.apk')).touch()
            def check():return subprocess.run(['/bin/sh','-eu','-c',block],env={'PATH':'/usr/bin:/bin','apks':directory},capture_output=True,text=True)
            self.assertEqual(check().returncode,0)
            for name in sorted(REQUIRED):
                path=root/(name+'-1.0-r0.apk');path.unlink();decoy=root/(name+'-extra-1.0-r0.apk');decoy.touch()
                result=check();self.assertNotEqual(result.returncode,0)
                self.assertIn('Missing required offline package: '+name,result.stderr)
                decoy.unlink();path.touch();self.assertEqual(check().returncode,0)

if __name__=='__main__':unittest.main(verbosity=2)
