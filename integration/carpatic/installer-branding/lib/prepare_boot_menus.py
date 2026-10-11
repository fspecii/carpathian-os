#!/usr/bin/env python3
"""Brand extracted boot-menu text without altering boot identifiers or arguments."""
from pathlib import Path
import sys

FILES = {
    'grub.cfg': [('menuentry "Install Carpatic OS" {', 'menuentry "Install Carpathian OS" {')],
    'syslinux.cfg': [
        ('MENU TITLE Carpatic OS', 'MENU TITLE Carpathian OS'),
        ('MENU LABEL Install Carpatic OS', 'MENU LABEL Install Carpathian OS'),
        ('MENU AUTOBOOT Starting the Carpatic installer in # seconds',
         'MENU AUTOBOOT Starting the Carpathian OS installer in # seconds'),
    ],
    'theme.txt': [('  text = "Starting the Carpatic installer in %d seconds"',
                   '  text = "Starting the Carpathian OS installer in %d seconds"')],
}


def prepare(directory):
    directory = Path(directory)
    updates = {}
    for name, replacements in FILES.items():
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'Missing regular extracted boot-menu file: {name}')
        source = path.read_bytes().decode('utf-8')
        lines = source.splitlines(keepends=True)
        for old, new in replacements:
            old_indices = [i for i, line in enumerate(lines) if line.rstrip('\r\n') == old]
            new_indices = [i for i, line in enumerate(lines) if line.rstrip('\r\n') == new]
            if len(old_indices) + len(new_indices) != 1:
                raise ValueError(f'Unexpected boot-menu label in {name}: {old}')
            if old_indices:
                index = old_indices[0]
                lines[index] = new + lines[index][len(old):]
        updates[path] = ''.join(lines).encode('utf-8')
    # Validate every input before changing any staged file.
    for path, data in updates.items():
        path.write_bytes(data)


if __name__ == '__main__':
    try:
        if len(sys.argv) != 2:
            raise ValueError('Usage: prepare_boot_menus.py EXTRACTED_DIRECTORY')
        prepare(sys.argv[1])
    except (OSError, UnicodeError, ValueError) as error:
        raise SystemExit(f'Boot-menu branding failed: {error}')
