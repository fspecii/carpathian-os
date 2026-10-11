#!/usr/bin/env python3
"""Actual mount parser against escaped temporary paths; no mounts or GTK."""
import ast
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'integration/carpatic/settings/lib/cset/pages/system.py'
tree = ast.parse(SOURCE.read_text())
nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'mounts'
         or isinstance(n, ast.Assign) and any(getattr(t, 'id', '') == 'REAL_FS' for t in n.targets)]
ns = {'os': os, 're': re}
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), ns)

def encode(path):
    return str(path).replace('\\', '\\134').replace(' ', '\\040').replace('\t', '\\011').replace('\n', '\\012')

class StorageMounts(unittest.TestCase):
    def test_real_filesystem_lookup_handles_escaped_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); table = root / 'mounts'
            for index, name in enumerate(('USB Drive', 'Școală\tDrive', 'slash\\drive', 'new\nline')):
                folder = root / name; folder.mkdir()
                table.write_text('/dev/disk\\040name ' + encode(folder) + ' ext4 rw 0 0\n')
                result = ns['mounts'](table)
                self.assertEqual(len(result), 1, name)
                device, mountpoint, filesystem, total, free = result[0]
                self.assertEqual((device, mountpoint, filesystem), ('/dev/disk name', str(folder), 'ext4'))
                stat = os.statvfs(folder)
                self.assertEqual((total, free), (stat.f_blocks * stat.f_frsize, stat.f_bavail * stat.f_frsize))

    def test_excluded_volumes_are_skipped_without_hiding_similar_names(self):
        with tempfile.TemporaryDirectory() as directory:
            table = Path(directory) / 'mounts'
            paths = ('/var/lib/docker', '/snap/app', '/boot/efi', '/snapshots', '/var/lib/docker-data')
            table.write_text(''.join(f'/dev/disk{i} {path} ext4 rw 0 0\n' for i, path in enumerate(paths)))
            stat = os.statvfs(directory)
            with patch.object(os, 'statvfs', return_value=stat) as lookup:
                result = ns['mounts'](table)
            self.assertEqual([r[1] for r in result], ['/snapshots', '/var/lib/docker-data'])
            self.assertEqual([call.args[0] for call in lookup.call_args_list], ['/snapshots', '/var/lib/docker-data'])

    def test_missing_paths_and_duplicate_devices_do_not_replace_valid_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            table = Path(directory) / 'mounts'
            table.write_text(f'/dev/same {directory}/missing ext4 rw 0 0\n/dev/same {directory} ext4 rw 0 0\n/dev/same / ext4 rw 0 0\n')
            result = ns['mounts'](table)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0][1], directory)

if __name__ == '__main__': unittest.main(verbosity=2)
