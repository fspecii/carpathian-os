#!/usr/bin/env python3
"""Isolate software virtio configuration from physical and accelerated GPUs."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('arm_graphics', ROOT / 'alpine/arm64-graphics.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Graphics(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.sysfs = self.root / 'sysfs'
        self.sysfs.mkdir()
        self.target = self.root / 'etc/X11/xorg.conf.d/21-carpathian-virtio-software.conf'

    def tearDown(self):
        self.temporary.cleanup()

    def device(self, name, identifier, features):
        device = self.sysfs / name
        device.mkdir()
        (device / 'device').write_text(identifier)
        (device / 'features').write_text(features)
        return device

    def test_software_gpu_gets_visible_scanout(self):
        self.device('virtio0', '0x0010\n', '010000\n')
        self.assertTrue(module.configure(self.sysfs, self.root))
        self.assertIn('Option "ShadowFB" "true"', self.target.read_text())
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o644)

    def test_acceleration_removes_only_owned_software_override(self):
        device = self.device('virtio0', '0x0010', '010000')
        module.configure(self.sysfs, self.root)
        (device / 'features').write_text('110000')
        self.assertFalse(module.configure(self.sysfs, self.root))
        self.assertFalse(self.target.exists())

    def test_non_gpu_unknown_and_mixed_devices_keep_defaults(self):
        self.device('virtio0', '0x0001', '000000')
        self.device('virtio1', '0x0010', 'unknown')
        self.assertFalse(module.configure(self.sysfs, self.root))
        self.device('virtio2', '0x0010', '010000')
        self.device('virtio3', '0x0010', '110000')
        self.assertFalse(module.configure(self.sysfs, self.root))
        self.assertFalse(self.target.exists())

    def test_independent_configuration_and_symlink_are_preserved(self):
        self.device('virtio0', '0x0010', '010000')
        self.target.parent.mkdir(parents=True)
        self.target.write_text('user configuration')
        with self.assertRaises(ValueError):
            module.configure(self.sysfs, self.root)
        self.assertEqual(self.target.read_text(), 'user configuration')
        self.target.unlink()
        other = self.root / 'other'
        other.write_text('unchanged')
        self.target.symlink_to(other)
        with self.assertRaises(ValueError):
            module.configure(self.sysfs, self.root)
        self.assertEqual(other.read_text(), 'unchanged')


if __name__ == '__main__':
    unittest.main()
