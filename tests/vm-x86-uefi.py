#!/usr/bin/env python3
"""Disposable command/firmware checks; QEMU is never launched."""
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('vm_test', Path(__file__).resolve().parents[1] / 'scripts/vm-test.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class Firmware(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vm = self.root / 'vm/test-uefi'
        (self.vm / 'run').mkdir(parents=True)
        (self.vm / 'fixture.json').write_text(json.dumps({'port': 2286, 'arch': 'x86_64'}))
        (self.vm / 'overlay.qcow2').write_bytes(b'OWNED DISK')
        self.code = self.root / 'code.fd'; self.code.write_bytes(b'CODE')
        self.template = self.root / 'vars.fd'; self.template.write_bytes(b'TEMPLATE')
        self.a = SimpleNamespace(firmware_code=self.code, firmware_vars=self.template)

    def start(self, *arguments):
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(m, 'ROOT', self.root))
            stack.enter_context(patch('sys.argv', ['vm-test', '--name', 'uefi', 'start', *arguments]))
            stack.enter_context(patch.object(m, 'live', return_value=None))
            stack.enter_context(patch.object(m, 'require_host_space'))
            stack.enter_context(patch.object(m.os, 'access', return_value=True))
            original_read = Path.read_text
            def read(path, *args, **kwargs):
                if str(path) == '/proc/meminfo': return 'MemAvailable: 999999999 kB\n'
                return original_read(path, *args, **kwargs)
            stack.enter_context(patch.object(Path, 'read_text', read))
            original_glob = Path.glob
            stack.enter_context(patch.object(Path, 'glob', lambda path, pattern: iter(()) if str(path) == '/proc' else original_glob(path, pattern)))
            call = stack.enter_context(patch.object(m, 'call'))
            m.main()
            return call.call_args.args[0]

    def test_bios_default_no_variable_mutation(self):
        command = self.start()
        self.assertFalse(any('pflash' in part for part in command))
        self.assertFalse((self.vm / 'uefi-vars.fd').exists())
        self.assertNotIn('boot_firmware', json.loads((self.vm / 'fixture.json').read_text()))

    def test_uefi_cd_then_disk_restart_persists_nvram_and_firmware(self):
        iso = self.root / 'candidate.iso'; iso.write_bytes(b'IMMUTABLE ISO')
        command = self.start('--uefi', '--firmware-code', str(self.code), '--firmware-vars', str(self.template), '--cdrom', str(iso))
        self.assertIn(f'if=pflash,format=raw,unit=0,file={self.code},readonly=on', command)
        variables = self.vm / 'uefi-vars.fd'
        self.assertIn(f'if=pflash,format=raw,unit=1,file={variables}', command)
        self.assertEqual(variables.read_bytes(), b'TEMPLATE')
        self.assertEqual(variables.stat().st_mode & 0o777, 0o600)
        variables.write_bytes(b'BOOT ENTRY')
        restarted = self.start()
        self.assertIn(f'if=pflash,format=raw,unit=1,file={variables}', restarted)
        self.assertFalse(any('media=cdrom' in part for part in restarted))
        self.assertEqual(variables.read_bytes(), b'BOOT ENTRY')
        self.assertEqual(self.code.read_bytes(), b'CODE')
        self.assertEqual(self.template.read_bytes(), b'TEMPLATE')
        self.assertEqual(iso.read_bytes(), b'IMMUTABLE ISO')
        self.assertEqual(json.loads((self.vm / 'fixture.json').read_text())['boot_firmware'], 'uefi')

    def test_isolated_variables_per_fixture(self):
        other = self.root / 'other'; other.mkdir()
        m.x86_uefi(self.vm, {}, self.a)
        m.x86_uefi(other, {}, self.a)
        (self.vm / 'uefi-vars.fd').write_bytes(b'CHANGED')
        self.assertEqual((other / 'uefi-vars.fd').read_bytes(), b'TEMPLATE')
        self.assertFalse(os.path.samefile(self.vm / 'uefi-vars.fd', other / 'uefi-vars.fd'))

    def test_missing_empty_same_and_unsafe_path_rejected_before_copy(self):
        cases = [(self.root / 'missing', self.template), (self.code, self.code)]
        empty = self.root / 'empty.fd'; empty.touch(); cases.append((empty, self.template))
        bad = self.root / 'bad,code.fd'; bad.write_bytes(b'CODE'); cases.append((bad, self.template))
        alias = self.root / 'alias.fd'; os.link(self.code, alias); cases.append((self.code, alias))
        for code, template in cases:
            with self.subTest(code=code, template=template), self.assertRaises(RuntimeError):
                m.x86_uefi(self.vm, {}, SimpleNamespace(firmware_code=code, firmware_vars=template))
            self.assertFalse((self.vm / 'uefi-vars.fd').exists())

    def test_shared_or_symlink_variables_rejected(self):
        variables = self.vm / 'uefi-vars.fd'
        variables.symlink_to(self.template)
        with self.assertRaisesRegex(RuntimeError, 'unshared'): m.x86_uefi(self.vm, {}, self.a)
        variables.unlink(); os.link(self.template, variables)
        with self.assertRaisesRegex(RuntimeError, 'unshared'): m.x86_uefi(self.vm, {}, self.a)
        self.assertEqual(self.template.read_bytes(), b'TEMPLATE')

    def test_existing_firmware_cannot_be_replaced(self):
        _, meta = m.x86_uefi(self.vm, {}, self.a)
        replacement = self.root / 'new-code.fd'; replacement.write_bytes(b'OTHER')
        with self.assertRaisesRegex(RuntimeError, 'original firmware'):
            m.x86_uefi(self.vm, meta, SimpleNamespace(firmware_code=replacement, firmware_vars=self.template))
        self.assertEqual((self.vm / 'uefi-vars.fd').read_bytes(), b'TEMPLATE')

    def test_variable_file_cannot_be_its_own_template(self):
        variables = self.vm / 'uefi-vars.fd'; variables.write_bytes(b'PRIVATE TEMPLATE')
        with self.assertRaisesRegex(RuntimeError, 'firmware template'):
            m.x86_uefi(self.vm, {}, SimpleNamespace(firmware_code=self.code, firmware_vars=variables))
        self.assertEqual(variables.read_bytes(), b'PRIVATE TEMPLATE')

    def test_default_ovmf_paths_and_missing_default_diagnostic(self):
        original = m.firmware_path
        seen = []
        def resolve(path):
            seen.append(str(path))
            return original(self.code if path.name == 'OVMF_CODE_4M.fd' else self.template)
        default = SimpleNamespace(firmware_code=None, firmware_vars=None)
        with patch.object(m, 'firmware_path', side_effect=resolve):
            m.x86_uefi(self.vm, {}, default)
        self.assertEqual(seen, ['/usr/share/OVMF/OVMF_CODE_4M.fd', '/usr/share/OVMF/OVMF_VARS_4M.fd'])
        with patch.object(m, 'firmware_path', side_effect=FileNotFoundError):
            with self.assertRaisesRegex(RuntimeError, 'Missing x86 UEFI firmware.*supply'):
                m.x86_uefi(self.vm, {}, default)

    def test_firmware_paths_require_explicit_uefi_for_bios_fixture(self):
        with self.assertRaises(SystemExit): self.start('--firmware-code', str(self.code))
        self.assertFalse((self.vm / 'uefi-vars.fd').exists())

if __name__ == '__main__': unittest.main()
