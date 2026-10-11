#!/usr/bin/env python3
"""Host-only authentication installation composition; no system files touched."""
import pathlib
import shlex
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
DESKTOP = ROOT / 'alpine/desktop-tools.sh'
SETTINGS = ROOT / 'integration/carpatic/settings/install.sh'


class AuthenticationInstallation(unittest.TestCase):
    def test_online_installer_requests_session_and_agent(self):
        text = DESKTOP.read_text()
        block = text.split('apk add ', 1)[1].split('\nfi', 1)[0]
        packages = shlex.split(block.replace('\\\n', ' '))
        self.assertTrue({'elogind', 'elogind-openrc', 'polkit-elogind', 'polkit-gnome', 'dbus-openrc', 'polkit-openrc'} <= set(packages))

    def test_offline_package_guard_missing_and_present(self):
        text = (ROOT / 'scripts/build-dev-iso.sh').read_text()
        begin = text.index('for required in xterm ')
        block = text[begin:text.index('\ndone', begin) + len('\ndone')]
        required = shlex.split(block.split('for required in ', 1)[1].split('; do', 1)[0])
        self.assertTrue({'elogind', 'polkit-elogind', 'polkit-gnome', 'elogind-openrc', 'dbus-openrc', 'polkit-openrc'} <= set(required))
        with tempfile.TemporaryDirectory() as directory:
            apks = pathlib.Path(directory)
            for package in required:
                (apks / (package + '-1.0-r0.apk')).touch()
            def check():
                return subprocess.run(['sh', '-eu', '-c', block], capture_output=True, text=True,
                                      env={'PATH': '/usr/bin:/bin', 'apks': directory})
            self.assertEqual(check().returncode, 0)
            for package in ('elogind', 'polkit-elogind', 'polkit-gnome', 'elogind-openrc', 'dbus-openrc', 'polkit-openrc'):
                path = apks / (package + '-1.0-r0.apk')
                path.unlink()
                result = check()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Missing required offline package: ' + package, result.stderr)
                path.touch()

    def test_prebuilt_runtime_requires_pkexec(self):
        text = (ROOT / 'alpine/install-prebuilt.sh').read_text()
        begin = text.index('for required in xfdesktop ')
        block = text[begin:text.index('\ndone', begin) + len('\ndone')]
        required = shlex.split(block.split('for required in ', 1)[1].split('; do', 1)[0])
        self.assertIn('pkexec', required)
        with tempfile.TemporaryDirectory() as directory:
            for command in required:
                path = pathlib.Path(directory) / command
                path.write_text('#!/bin/sh\nexit 0\n')
                path.chmod(0o755)
            def check():
                return subprocess.run(['/bin/sh', '-eu', '-c', block], capture_output=True,
                                      text=True, env={'PATH': directory})
            self.assertEqual(check().returncode, 0)
            (pathlib.Path(directory) / 'pkexec').unlink()
            result = check()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Required desktop runtime is missing: pkexec', result.stderr)

    def test_prebuilt_agent_missing_nonexecutable_and_present(self):
        text = (ROOT / 'alpine/install-prebuilt.sh').read_text()
        begin = text.index('auth_agent=\n')
        block = text[begin:text.index("\npython3 -c 'import gi;", begin)]
        candidates = shlex.split(block.split('for candidate in ', 1)[1].split('; do', 1)[0])
        with tempfile.TemporaryDirectory() as directory:
            scoped = block
            for candidate in candidates:
                scoped = scoped.replace(candidate, directory + candidate)
            def check():
                return subprocess.run(['sh', '-eu', '-c', scoped], capture_output=True, text=True)
            self.assertNotEqual(check().returncode, 0)
            for candidate in candidates:
                path = pathlib.Path(directory + candidate)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('#!/bin/sh\nexit 0\n')
                path.chmod(0o644)
                self.assertNotEqual(check().returncode, 0)
                path.chmod(0o755)
                self.assertEqual(check().returncode, 0)
                path.unlink()

    def test_services_validate_all_before_enabling_runlevels(self):
        text = (ROOT / 'alpine/desktop-services.sh').read_text()
        block = text[text.index('for service in cgroups '):]
        self.assertNotIn('rc-service', block)
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            init = root / 'etc/init.d'
            init.mkdir(parents=True)
            bindir = root / 'bin'
            bindir.mkdir()
            log = root / 'calls'
            updater = bindir / 'rc-update'
            updater.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALL_LOG"\n')
            updater.chmod(0o755)
            daemon = root / 'usr/libexec/elogind/elogind'
            daemon.parent.mkdir(parents=True)
            daemon.write_text('#!/bin/sh\nexit 0\n')
            daemon.chmod(0o755)
            scoped = block.replace('/etc/init.d/', str(init) + '/')
            scoped = scoped.replace('/usr/libexec/elogind/elogind', str(daemon))
            def check():
                if log.exists():
                    log.unlink()
                return subprocess.run(['/bin/sh', '-eu', '-c', scoped], capture_output=True,
                                      text=True, env={'PATH': str(bindir), 'CALL_LOG': str(log)})
            services = ('cgroups', 'dbus', 'elogind', 'polkit')
            for service in services:
                path = init / service
                path.write_text('#!/bin/sh\nexit 0\n')
                path.chmod(0o755)
            self.assertEqual(check().returncode, 0)
            self.assertEqual(log.read_text().splitlines(), ['add cgroups boot', 'add dbus default',
                                                          'add elogind default', 'add polkit default'])
            for service in services:
                path = init / service
                path.chmod(0o644)
                result = check()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Required desktop service is missing: ' + service, result.stderr)
                self.assertFalse(log.exists(), 'all services must be validated before changing runlevels')
                path.chmod(0o755)
            daemon.unlink()
            result = check()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Required desktop daemon is missing: elogind', result.stderr)
            self.assertFalse(log.exists())
            daemon.write_text('#!/bin/sh\nexit 0\n')
            daemon.chmod(0o755)
            updater.write_text('#!/bin/sh\nexit 1\n')
            self.assertNotEqual(check().returncode, 0, 'runlevel activation failure must propagate')

    def test_service_helper_is_called_after_dependency_install(self):
        text = DESKTOP.read_text()
        invocation = text.index('sh alpine/desktop-services.sh')
        self.assertGreater(invocation, text.index('apk add '))
        self.assertLess(invocation, text.index('sh "$SRC/settings/install.sh"'))

    def test_settings_policy_creates_missing_directory(self):
        command = next(line for line in SETTINGS.read_text().splitlines()
                       if 'org.carpatic.settings.policy' in line and 'install ' in line)
        self.assertTrue(command.startswith('install -Dm644 '))
        with tempfile.TemporaryDirectory() as directory:
            destination = pathlib.Path(directory) / 'usr/share/polkit-1/actions'
            scoped = command.replace('/usr/share/polkit-1/actions', str(destination))
            subprocess.run(['sh', '-eu', '-c', scoped], check=True,
                           env={'PATH': '/usr/bin:/bin', 'SRC': str(ROOT / 'integration/carpatic/settings')})
            installed = destination / 'org.carpatic.settings.policy'
            self.assertEqual(installed.read_bytes(), (ROOT / 'integration/carpatic/settings/share' / installed.name).read_bytes())
            self.assertEqual(installed.stat().st_mode & 0o777, 0o644)

    def test_settings_system_helpers_have_installed_policies(self):
        text = DESKTOP.read_text()
        begin = text.index('for policy in "$SRC"/compat/share/*.policy; do')
        block = text[begin:text.index('\ndone', begin) + len('\ndone')]
        with tempfile.TemporaryDirectory() as directory:
            destination = pathlib.Path(directory) / 'usr/share/polkit-1/actions'
            scoped = block.replace('/usr/share/polkit-1/actions', str(destination))
            subprocess.run(['sh', '-eu', '-c', scoped], check=True,
                           env={'PATH': '/usr/bin:/bin', 'SRC': str(ROOT / 'integration/carpatic')})
            installed = sorted(destination.glob('*.policy'))
            source = sorted((ROOT / 'integration/carpatic/compat/share').glob('*.policy'))
            self.assertEqual([p.name for p in installed], [p.name for p in source])
            paths = set()
            for original, copied in zip(source, installed):
                self.assertEqual(original.read_bytes(), copied.read_bytes())
                for annotation in ET.parse(copied).iter('annotate'):
                    if annotation.get('key') == 'org.freedesktop.policykit.exec.path':
                        paths.add(annotation.text)
            self.assertTrue({'/usr/local/bin/carpatic-update', '/usr/local/bin/carpatic-security',
                             '/usr/local/bin/carpatic-rollback'} <= paths)


if __name__ == '__main__':
    unittest.main()
