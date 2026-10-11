#!/usr/bin/env python3
"""Focused staging checks: display text changes, boot configuration bytes do not."""
import importlib.util
import hashlib
import json
import struct
import xml.etree.ElementTree as ET
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('boot_branding', ROOT / 'integration/carpatic/installer-branding/lib/prepare_boot_menus.py')
branding = importlib.util.module_from_spec(spec)
spec.loader.exec_module(branding)


class BootBranding(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.original = {}
        for name, pairs in branding.FILES.items():
            text = '\n'.join(old for old, new in pairs) + '\n'
            text += 'linux /boot/vmlinuz-lts carpatic.test=1\ninitrd /boot/initramfs-lts\n'
            text += 'set theme=/boot/grub/themes/carpatic/theme.txt\n'
            text += 'LABEL carpatic\nDEFAULT carpatic\n'
            self.original[name] = text.encode()
            (self.directory / name).write_bytes(text.encode())

    def test_only_known_display_lines_change(self):
        branding.prepare(self.directory)
        for name, pairs in branding.FILES.items():
            expected = self.original[name]
            for old, new in pairs:
                expected = expected.replace(old.encode(), new.encode())
            self.assertEqual((self.directory / name).read_bytes(), expected)

    def test_idempotent(self):
        branding.prepare(self.directory)
        first = {p.name: p.read_bytes() for p in self.directory.iterdir()}
        branding.prepare(self.directory)
        self.assertEqual(first, {p.name: p.read_bytes() for p in self.directory.iterdir()})

    def test_unknown_label_fails_without_partial_write(self):
        path = self.directory / 'theme.txt'
        path.write_bytes(path.read_bytes().replace(b'Starting the Carpatic', b'Starting an unknown'))
        before = {p.name: p.read_bytes() for p in self.directory.iterdir()}
        with self.assertRaises(ValueError):
            branding.prepare(self.directory)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.directory.iterdir()})

    def test_duplicate_label_rejected(self):
        path = self.directory / 'grub.cfg'
        path.write_bytes(path.read_bytes() + (branding.FILES['grub.cfg'][0][0] + '\n').encode())
        with self.assertRaises(ValueError):
            branding.prepare(self.directory)

    def test_missing_file_rejected(self):
        (self.directory / 'syslinux.cfg').unlink()
        with self.assertRaises(ValueError):
            branding.prepare(self.directory)

    def test_symlink_rejected(self):
        path = self.directory / 'theme.txt'
        target = self.directory / 'external.txt'
        path.rename(target)
        path.symlink_to(target)
        with self.assertRaises(ValueError):
            branding.prepare(self.directory)
        self.assertEqual(target.read_bytes(), self.original['theme.txt'])

    def test_crlf_preserved(self):
        for path in self.directory.iterdir():
            path.write_bytes(path.read_bytes().replace(b'\n', b'\r\n'))
        branding.prepare(self.directory)
        for path in self.directory.iterdir():
            self.assertNotIn(b'\n', path.read_bytes().replace(b'\r\n', b''))


class BootAssets(unittest.TestCase):
    def test_recorded_sources_and_rasters_match(self):
        assets = ROOT / 'integration/carpatic/installer-branding/assets'
        metadata = json.loads((assets / 'boot-render-provenance.json').read_text())
        for name, expected in metadata['files'].items():
            self.assertEqual(hashlib.sha256((assets / name).read_bytes()).hexdigest(), expected)
        self.assertEqual(hashlib.sha256((ROOT / metadata['logo_source']).read_bytes()).hexdigest(), metadata['logo_sha256'])
        self.assertEqual(hashlib.sha256((assets / 'render-boot.py').read_bytes()).hexdigest(), metadata['renderer_sha256'])
        self.assertIn('Permission is hereby granted', (assets / 'BOOT-FONT-LICENSE.txt').read_text())

    def test_boot_png_format_and_vector_branding(self):
        assets = ROOT / 'integration/carpatic/installer-branding/assets'
        namespace = {'s': 'http://www.w3.org/2000/svg'}
        panel = ET.parse(ROOT / 'integration/carpatic/panel/assets/branding/carpathian-os.svg').getroot()
        expected_paths = [path.attrib['d'] for path in panel.findall('s:path', namespace)]
        for name, width, height in [('boot-background', 1280, 720), ('boot-splash', 640, 480)]:
            data = (assets / (name + '.png')).read_bytes()
            self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
            self.assertEqual(data[12:16], b'IHDR')
            self.assertEqual(struct.unpack('>IIBBBBB', data[16:29]), (width, height, 8, 2, 0, 0, 0))
            tree = ET.parse(assets / (name + '.svg')).getroot()
            self.assertEqual(tree.attrib['viewBox'], f'0 0 {width} {height}')
            logo = tree.find("s:g[@id='mountain']", namespace)
            self.assertEqual([path.attrib['d'] for path in logo], expected_paths)
            wordmark = tree.find("s:path[@id='wordmark']", namespace)
            self.assertEqual(wordmark.attrib['aria-label'], 'Carpathian OS')
            self.assertGreater(len(wordmark.attrib['d']), 5000)
            self.assertEqual(tree.findall('s:text', namespace), [])
            self.assertEqual(tree.find('s:rect', namespace).attrib['fill'], '#0b0e13')


if __name__ == '__main__':
    unittest.main()
