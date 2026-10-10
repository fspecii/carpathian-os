#!/usr/bin/env python3
"""Command/ownership checks only: never launch QEMU."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('vm_test', Path(__file__).resolve().parents[1] / 'scripts/vm-test.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class Commands(unittest.TestCase):
    def test_arm_command_and_variable_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vm = root / 'fixture'; vm.mkdir()
            binary = root / 'qemu-system-aarch64'; binary.write_text('unused'); binary.chmod(0o700)
            code = root / 'code.fd'; code.write_bytes(b'CODE')
            template = root / 'vars.fd'; template.write_bytes(b'VARS')
            a = SimpleNamespace(qemu=binary, firmware_code=code, firmware_vars=template, graphics='software', name='arm-test', ram=1536, display='headless')
            argv = m.arm_command(vm, {'port': 2274}, a, root / 'boot.iso')
            self.assertIn('tcg', argv); self.assertIn('cortex-a72', argv)
            self.assertIn('virtio-gpu-pci', argv)
            self.assertIn('scsi-cd,drive=cd,bootindex=1', argv)
            self.assertIn('virtio-blk-pci,drive=disk,bootindex=2', argv)
            self.assertTrue(any('read-only=true' in value and str(code) in value for value in argv))
            self.assertTrue(any('127.0.0.1:2274' in value for value in argv))
            variables = vm / 'uefi-vars.fd'
            variables.write_bytes(b'CHANGED')
            m.arm_command(vm, {'port': 2274}, a, None)
            self.assertEqual(variables.read_bytes(), b'CHANGED')
            self.assertEqual(template.read_bytes(), b'VARS')
            self.assertEqual(code.read_bytes(), b'CODE')
            variables.unlink(); variables.symlink_to(template)
            with self.assertRaises(RuntimeError): m.arm_command(vm, {'port': 2274}, a, None)
    def test_both_process_names(self):
        for name in ('qemu-system-aarch64', 'qemu-system-x86_64'):
            self.assertTrue(m.qemu_process([('/usr/bin/' + name).encode()]))
        self.assertFalse(m.qemu_process([b'/usr/bin/sh']))
    def test_explicit_firmware_required(self):
        with self.assertRaises(RuntimeError): m.firmware_path(None)

if __name__ == '__main__': unittest.main()
