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
        self.assertTrue({'elogind', 'elogind-openrc', 'polkit-elogind', 'polkit-gnome'} <= set(packages))

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
