#!/usr/bin/env python3
"""Stage the real Notes installer without touching system or user data."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
class Installation(unittest.TestCase):
    def test_program_files_desktop_entry_and_data_preservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / 'home/user/.local/share/carpathian/notes'
            data.mkdir(parents=True)
            sentinel = data / 'notes.sqlite3'
            sentinel.write_bytes(b'unchanged user database')
            env = dict(os.environ, DESTDIR=str(root))
            subprocess.run(['sh', str(ROOT / 'integration/carpatic/notes/install.sh')],env=env,check=True,capture_output=True)
            self.assertEqual(sentinel.read_bytes(), b'unchanged user database')
            launcher = root / 'usr/local/bin/carpatic-notes'
            self.assertEqual(launcher.stat().st_mode & 0o777, 0o755)
            library = root / 'usr/local/lib/carpatic-notes/carpatic_notes'
            for name in ('__init__.py','store.py','app.py'):
                self.assertEqual((library/name).read_bytes(),(ROOT/'integration/carpatic/notes/lib/carpatic_notes'/name).read_bytes())
            entry=(root/'usr/local/share/applications/org.carpathian.Notes.desktop').read_text()
            self.assertIn('Exec=carpatic-notes\n', entry)
            self.assertIn('Terminal=false\n', entry)
            self.assertFalse((root/'etc/xdg/autostart').exists())
            self.assertFalse((root/'etc/runlevels').exists())
    def test_relative_staging_refused(self):
        env=dict(os.environ, DESTDIR='relative-notes-stage')
        result=subprocess.run(['sh',str(ROOT/'integration/carpatic/notes/install.sh')],env=env,capture_output=True)
        self.assertNotEqual(result.returncode,0)
        self.assertFalse((ROOT/'relative-notes-stage').exists())
if __name__=='__main__':unittest.main()
