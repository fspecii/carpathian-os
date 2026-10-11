#!/usr/bin/env python3
"""Isolated POSIX-shell package/config composition; no mounts, apk or system writes."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = Path(os.environ.get('CARPATIC_DESKTOP_TOOLS_TEST_SOURCE', ROOT / 'alpine/desktop-tools.sh'))
SOURCE = ROOT / 'integration/carpatic'
REQUIRED = {'thunar', 'gvfs', 'gvfs-fuse', 'udisks2', 'udiskie'}
RECOVERY_REQUIRED = {'btrfs-progs', 'flock'}


def installer_parts():
    text = DESKTOP.read_text()
    begin = text.index('if [ "${CARPATIC_SKIP_PACKAGES:-0}" != 1 ]; then')
    end = text.index('\nfi', begin) + 3
    block = text[begin:end]
    command = next(line for line in text.splitlines()
                   if line.startswith('install ') and '/etc/carpatic/udiskie.yml' in line)
    if text.index(command) < end:
        raise AssertionError('Required desktop config must install even when packages are supplied offline')
    return block, command


class RemovableMediaInstallation(unittest.TestCase):
    def stage(self, skip, source=SOURCE, existing=None):
        with tempfile.TemporaryDirectory(prefix='removable-media staging ') as directory:
            root = Path(directory)
            bindir = root / 'bin'; bindir.mkdir()
            calls = root / 'apk-calls.json'
            apk = bindir / 'apk'
            apk.write_text('#!/usr/bin/python3\nimport json,os,sys\nfrom pathlib import Path\nPath(os.environ["APK_CALLS"]).write_text(json.dumps(sys.argv[1:]))\n')
            apk.chmod(0o755)
            target = root / 'etc/carpatic/udiskie.yml'
            if existing is not None:
                target.parent.mkdir(parents=True); target.write_bytes(existing)
            block, command = installer_parts()
            # Execute the actual installer stanza. Only its absolute destination
            # is scoped to staging; shell quoting and install modes stay intact.
            command = command.replace('/etc/carpatic/udiskie.yml', str(target))
            # Original destination is unquoted; quote the staging path (which
            # intentionally contains spaces) without changing the source argv.
            command = command.replace(str(target), shlex.quote(str(target)))
            result = subprocess.run(['/bin/sh', '-eu', '-c', block+'\n'+command],
                                    capture_output=True, text=True,
                                    env={'PATH': str(bindir)+':/usr/bin:/bin', 'SRC': str(source),
                                         'CARPATIC_SKIP_PACKAGES': str(skip), 'APK_CALLS': str(calls)})
            packages = json.loads(calls.read_text()) if calls.exists() else None
            contents = target.read_bytes() if target.exists() else None
            mode = target.stat().st_mode & 0o777 if target.exists() else None
            return result, packages, contents, mode

    def test_online_packages_and_actual_policy_install(self):
        result, packages, contents, mode = self.stage(0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(packages[0], 'add')
        self.assertTrue(REQUIRED <= set(packages))
        self.assertTrue({'dbus-openrc', 'elogind', 'polkit-elogind', 'polkit-gnome'} <= set(packages))
        self.assertEqual(contents, (SOURCE / 'compat/share/udiskie.yml').read_bytes())
        self.assertEqual(mode, 0o644)

    def test_online_recovery_tools_are_explicit_dependencies(self):
        result, packages, _, _ = self.stage(0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(RECOVERY_REQUIRED <= set(packages))

    def test_offline_iso_requires_each_recovery_tool(self):
        text = (ROOT / 'scripts/build-dev-iso.sh').read_text()
        start = text.index('for required in xterm ')
        block = text[start:text.index('\ndone', start)+len('\ndone')]
        names = shlex.split(block.split('for required in ',1)[1].split('; do',1)[0])
        self.assertTrue(RECOVERY_REQUIRED <= set(names))
        with tempfile.TemporaryDirectory() as directory:
            apks=Path(directory)
            for name in names: (apks/(name+'-1.0-r0.apk')).touch()
            def check():
                return subprocess.run(['/bin/sh','-eu','-c',block],capture_output=True,text=True,
                                      env={'PATH':'/usr/bin:/bin','apks':directory})
            self.assertEqual(check().returncode,0)
            for name in sorted(RECOVERY_REQUIRED):
                path=apks/(name+'-1.0-r0.apk');path.unlink()
                # A similarly named package must not satisfy the exact root.
                decoy=apks/(name+'-extra-1.0-r0.apk');decoy.touch()
                result=check()
                self.assertNotEqual(result.returncode,0,name)
                self.assertIn('Missing required offline package: '+name,result.stderr)
                decoy.unlink();path.touch()
                self.assertEqual(check().returncode,0)

    def test_offline_skip_still_installs_and_refreshes_policy(self):
        result, packages, contents, mode = self.stage(1, existing=b'obsolete policy\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(packages, 'Offline install must not fetch packages')
        self.assertEqual(contents, (SOURCE / 'compat/share/udiskie.yml').read_bytes())
        self.assertEqual(mode, 0o644)

    def test_missing_policy_source_fails_staging(self):
        with tempfile.TemporaryDirectory() as missing:
            result, packages, contents, _ = self.stage(1, source=Path(missing))
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(contents)
        self.assertIsNone(packages)

    def test_offline_iso_requires_complete_media_package_inputs(self):
        text = (ROOT / 'scripts/build-dev-iso.sh').read_text()
        start = text.index('for required in xterm ')
        block = text[start:text.index('\ndone', start)+len('\ndone')]
        names = shlex.split(block.split('for required in ',1)[1].split('; do',1)[0])
        self.assertTrue(REQUIRED <= set(names))
        with tempfile.TemporaryDirectory() as directory:
            apks=Path(directory)
            for name in names: (apks/(name+'-1.0-r0.apk')).touch()
            def check():
                return subprocess.run(['/bin/sh','-eu','-c',block],capture_output=True,text=True,
                                      env={'PATH':'/usr/bin:/bin','apks':directory})
            self.assertEqual(check().returncode,0)
            for name in sorted(REQUIRED):
                path=apks/(name+'-1.0-r0.apk');path.unlink()
                result=check()
                self.assertNotEqual(result.returncode,0,name)
                self.assertIn('Missing required offline package: '+name,result.stderr)
                path.touch()
            # A similarly prefixed optional backend cannot satisfy the gvfs core.
            (apks/'gvfs-1.0-r0.apk').unlink()
            (apks/'gvfs-mtp-1.0-r0.apk').touch()
            self.assertNotEqual(check().returncode,0)
        runtime = (ROOT / 'alpine/install-prebuilt.sh').read_text()
        self.assertIn('apk add --no-network --no-progress "$project"/packages/*.apk', runtime)
        self.assertIn('CARPATIC_SKIP_PACKAGES=1', runtime)

    def test_session_consumes_same_config_and_file_manager(self):
        startup = (SOURCE / 'desktop/session/autostart.sh').read_text()
        line = next(line for line in startup.splitlines() if 'udiskie --automount' in line)
        self.assertIn('--notify --smart-tray --file-manager thunar', line)
        self.assertIn('--config /etc/carpatic/udiskie.yml', line)
        self.assertIn('/etc/carpatic/udiskie.yml', (SOURCE / 'compat/install.sh').read_text())
        world = set((ROOT / 'alpine/arm64-runtime-world.txt').read_text().splitlines())
        self.assertTrue(REQUIRED <= world)
        # Policy is preserved exactly, including the permitted udisks-created
        # LUKS exception before manually opened mapper devices are ignored.
        policy = (SOURCE / 'compat/share/udiskie.yml').read_text()
        self.assertLess(policy.index("'/dev/mapper/luks-*'"), policy.index("'/dev/mapper/*'"))


if __name__ == '__main__':
    unittest.main()
