#!/usr/bin/env python3
"""Payload identity negative controls; synthetic ELF is not ARM execution proof."""
import importlib.util
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

VERIFIER = Path(__file__).resolve().parent.parent / 'alpine/verify-prebuilt.py'
spec = importlib.util.spec_from_file_location('verify_prebuilt', VERIFIER)
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


def elf(arch, shared=False, loader=None):
    interp = (loader or f'/lib/ld-musl-{arch}.so.1').encode() + b'\0'
    count = 1 if shared else 2
    offset = 64 + count * 56
    data = bytearray(offset + (0 if shared else len(interp)))
    data[:16] = b'\x7fELF\x02\x01\x01' + bytes(9)
    struct.pack_into('<HHIQQQIHHHHHH', data, 16, 3, module.MACHINES[arch],
                     1, 0, 64, 0, 0, 64, 56, count, 0, 0, 0)
    struct.pack_into('<IIQQQQQQ', data, 64, 1, 5, 0, 0, 0, len(data), len(data), 4096)
    if not shared:
        struct.pack_into('<IIQQQQQQ', data, 120, 3, 4, offset, 0, 0, len(interp), len(interp), 1)
        data[offset:] = interp
    return data


class ArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='carpatic-elf-test-')
        self.root = Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def payload(self, arch):
        for name in module.FILES:
            (self.root/name).write_bytes(elf(arch, name.endswith('.so')))
    def test_both_architectures_accept_complete_payload(self):
        for arch in module.MACHINES:
            self.payload(arch); module.verify(self.root, arch)
    def test_every_mixed_architecture_member_rejected(self):
        for target in module.MACHINES:
            other = 'aarch64' if target == 'x86_64' else 'x86_64'
            for name in module.FILES:
                self.payload(target)
                (self.root/name).write_bytes(elf(other,name.endswith('.so')))
                with self.assertRaisesRegex(ValueError, 'wrong ELF machine'):
                    module.verify(self.root,target)
    def test_loader_and_shared_object_contract(self):
        for arch in module.MACHINES:
            for name in module.FILES[:-1]:
                self.payload(arch)
                (self.root/name).write_bytes(elf(arch,loader='/lib64/ld-linux-x86-64.so.2'))
                with self.assertRaisesRegex(ValueError,'interpreter'): module.verify(self.root,arch)
            self.payload(arch)
            (self.root/module.FILES[-1]).write_bytes(elf(arch))
            with self.assertRaisesRegex(ValueError,'interpreter'): module.verify(self.root,arch)
    def test_missing_symlink_nonelf_truncated_and_wrong_class_rejected(self):
        for mutation in ('missing','symlink','nonelf','truncated','class','table'):
            self.payload('aarch64'); path=self.root/module.FILES[0]
            if mutation=='missing':path.unlink()
            elif mutation=='symlink':path.unlink();path.symlink_to(module.FILES[1])
            elif mutation=='nonelf':path.write_bytes(b'#!/bin/sh\nexit 0\n')
            else:
                data=elf('aarch64')
                if mutation=='truncated':data=data[:70]
                elif mutation=='class':data[4]=1
                else:struct.pack_into('<Q',data,32,2**63)
                path.write_bytes(data)
            with self.assertRaises(ValueError,msg=mutation):module.verify(self.root,'aarch64')
    def test_cli_fails_closed(self):
        self.payload('x86_64')
        result=subprocess.run([sys.executable,str(VERIFIER),str(self.root),'--arch','aarch64'],capture_output=True,text=True)
        self.assertEqual(result.returncode,1);self.assertIn('rejected',result.stderr)
        result=subprocess.run([sys.executable,str(VERIFIER),str(self.root),'--arch','armv7'],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)

if __name__=='__main__':unittest.main()
