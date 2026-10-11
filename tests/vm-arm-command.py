#!/usr/bin/env python3
"""Command/ownership checks only: never launch QEMU."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import json

spec = importlib.util.spec_from_file_location('vm_test', Path(__file__).resolve().parents[1] / 'scripts/vm-test.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class Commands(unittest.TestCase):
    def test_space_threshold_boundaries(self):
        for installation, gib in ((False, 1), (True, 6)):
            required = gib * 1024 ** 3
            with patch.object(m.shutil, 'disk_usage', return_value=SimpleNamespace(free=required - 1)):
                with self.assertRaisesRegex(RuntimeError, 'available .*required'):
                    m.require_host_space(Path('/unused'), installation)
            with patch.object(m.shutil, 'disk_usage', return_value=SimpleNamespace(free=required)):
                m.require_host_space(Path('/unused'), installation)
    def test_insufficient_space_start_has_no_mutations(self):
        for arch in ('x86_64', 'aarch64'):
            for cdrom in (False, True):
                with self.subTest(arch=arch, cdrom=cdrom), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory); vm = root / 'vm/test-space'; vm.mkdir(parents=True)
                    metadata = json.dumps({'arch': arch, 'port': 2279})
                    (vm / 'fixture.json').write_text(metadata)
                    (vm / 'overlay.qcow2').write_bytes(b'UNCHANGED')
                    iso = root / 'test.iso'; iso.write_bytes(b'ISO')
                    argv = ['vm-test', '--name', 'space', 'start'] + (['--cdrom', str(iso)] if cdrom else [])
                    with patch.object(m, 'ROOT', root), patch('sys.argv', argv), \
                            patch.object(m, 'live', return_value=None), \
                            patch.object(m.shutil, 'disk_usage', return_value=SimpleNamespace(free=0)), \
                            patch.object(m, 'call') as call, patch.object(m, 'arm_command') as arm:
                        with self.assertRaisesRegex(RuntimeError, 'Insufficient host disk space'):
                            m.main()
                        call.assert_not_called(); arm.assert_not_called()
                    self.assertEqual((vm / 'fixture.json').read_text(), metadata)
                    self.assertEqual((vm / 'overlay.qcow2').read_bytes(), b'UNCHANGED')
                    self.assertEqual(sorted(p.name for p in vm.iterdir()), ['fixture.json', 'overlay.qcow2'])
                    self.assertFalse((root / 'vm/.test-start.lock').exists())
    def test_insufficient_space_clone_does_not_create_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / 'base.qcow2'; base.write_bytes(b'BASE')
            key = root / 'key'; key.write_text('unused test key')
            argv = ['vm-test', '--name', 'space', 'clone', '--base', str(base), '--key', str(key), '--port', '2279']
            with patch.object(m, 'ROOT', root), patch('sys.argv', argv), \
                    patch.object(m.shutil, 'disk_usage', return_value=SimpleNamespace(free=0)), \
                    patch.object(m, 'call') as call:
                with self.assertRaisesRegex(RuntimeError, 'Insufficient host disk space'):
                    m.main()
                call.assert_not_called()
            self.assertFalse((root / 'vm').exists())
            self.assertEqual(base.read_bytes(), b'BASE')

    def test_already_running_bypasses_space_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); vm = root / 'vm/test-running'; vm.mkdir(parents=True)
            (vm / 'fixture.json').write_text('{}')
            with patch.object(m, 'ROOT', root), patch('sys.argv', ['vm-test', '--name', 'running', 'start']), \
                    patch.object(m, 'live', return_value=123), patch.object(m, 'require_host_space') as guard, \
                    patch.object(m, 'call') as call:
                m.main(); guard.assert_not_called(); call.assert_not_called()
            self.assertFalse((root / 'vm/.test-start.lock').exists())

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
    def test_protected_preview_refuses_destroy_before_process_action(self):
        for metadata, marker in (({'protected': True}, False), ({}, True)):
            with self.subTest(metadata=metadata, marker=marker), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                vm = root / 'vm/test-preview'; vm.mkdir(parents=True)
                (vm / 'fixture.json').write_text(json.dumps(metadata))
                disk = vm / 'overlay.qcow2'; disk.write_bytes(b'USER DISK')
                if marker: (vm / 'USER-PREVIEW-DO-NOT-DESTROY').touch()
                with patch.object(m, 'ROOT', root), patch('sys.argv', ['vm-test', '--name', 'preview', 'destroy']), patch.object(m, 'live') as live:
                    with self.assertRaisesRegex(RuntimeError, 'protected user preview'):
                        m.main()
                    live.assert_not_called()
                self.assertEqual(disk.read_bytes(), b'USER DISK')
    def test_disposable_stopped_fixture_can_be_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vm = root / 'vm/test-disposable'; vm.mkdir(parents=True)
            (vm / 'fixture.json').write_text('{}')
            base = root / 'base.qcow2'; base.write_bytes(b'GOLDEN BASE')
            with patch.object(m, 'ROOT', root), patch('sys.argv', ['vm-test', '--name', 'disposable', 'destroy']), patch.object(m, 'live', return_value=None):
                m.main()
            self.assertFalse(vm.exists())
            self.assertEqual(base.read_bytes(), b'GOLDEN BASE')

if __name__ == '__main__': unittest.main()
