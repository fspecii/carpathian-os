#!/usr/bin/env python3
"""Validate native payload architecture and musl loader without executing files."""
import argparse
from pathlib import Path
import struct
import sys

FILES = ('carpatic-wm', 'carpatic-intro-play', 'carpatic-clipwatch',
         'carpatic-supertap', 'libcarpatic-livecss.so')
MACHINES = {'x86_64': 62, 'aarch64': 183}


def verify_file(path, arch, shared=False):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'{path.name}: required regular file missing')
    data = path.read_bytes()
    if len(data) < 64 or data[:7] != b'\x7fELF\x02\x01\x01':
        raise ValueError(f'{path.name}: expected ELF64 little-endian version1')
    kind, machine, version = struct.unpack_from('<HHI', data, 16)
    phoff = struct.unpack_from('<Q', data, 32)[0]
    ehsize, phsize, phcount = struct.unpack_from('<HHH', data, 52)
    if machine != MACHINES[arch] or version != 1:
        raise ValueError(f'{path.name}: wrong ELF machine/version for {arch}: {machine}/{version}')
    if ehsize != 64 or phsize != 56 or not phcount or phcount == 65535:
        raise ValueError(f'{path.name}: invalid or unsupported ELF program table')
    if phoff < 64 or phoff + phcount * phsize > len(data):
        raise ValueError(f'{path.name}: truncated ELF program table')
    if kind not in ((3,) if shared else (2, 3)):
        raise ValueError(f'{path.name}: invalid ELF file type {kind}')
    interpreters = []
    load = False
    for index in range(phcount):
        header = struct.unpack_from('<IIQQQQQQ', data, phoff + index * phsize)
        segment, _, offset, _, _, size, memory, _ = header
        if offset + size > len(data):
            raise ValueError(f'{path.name}: truncated ELF segment')
        if segment == 1:
            load = True
            if memory < size:
                raise ValueError(f'{path.name}: invalid load segment size')
        if segment == 3:
            interpreters.append(data[offset:offset + size])
    if not load:
        raise ValueError(f'{path.name}: no loadable segment')
    expected = f'/lib/ld-musl-{arch}.so.1'.encode() + b'\0'
    if interpreters != ([] if shared else [expected]):
        raise ValueError(f'{path.name}: incompatible ELF interpreter for {arch}')


def verify(root, arch):
    if arch not in MACHINES:
        raise ValueError(f'Unsupported native payload architecture: {arch}')
    for name in FILES:
        verify_file(root / name, arch, name.endswith('.so'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--arch', required=True, choices=MACHINES)
    args = parser.parse_args()
    try:
        verify(args.directory, args.arch)
    except (OSError, ValueError, struct.error) as error:
        print(f'Native payload rejected: {error}', file=sys.stderr)
        return 1
    print(f'Native payload ELF/musl verification passed: {args.arch} (5 files)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
