#!/usr/bin/env python3
"""Launcher startup protocol in private subprocess fixtures, without GUI access."""
import os, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

class Launcher(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        binary = self.root/'bin'; binary.mkdir()
        self.helper = binary/'carpatic-calendar'
        source = (ROOT/'integration/carpatic/panel/bin/carpatic-calendar').read_text()
        source = source.replace("'/usr/local/lib/carpatic-panel'", repr(str(self.root/'absent')))
        self.helper.write_text(source)
        module = self.root/'lib/carpatic_panel'; module.mkdir(parents=True)
        (module/'__init__.py').write_text('')
        (module/'calendar_editor.py').write_text("from pathlib import Path\nPath(" + repr(str(self.root/'imported')) + ").write_text('yes')\ndef run(selection): return 0\n")
        notifier = binary/'notify-send'
        notifier.write_text('#!' + sys.executable + "\nfrom pathlib import Path\nimport sys\nPath(" + repr(str(self.root/'notification')) + ").write_text(' '.join(sys.argv[1:]))\n")
        notifier.chmod(0o700)
        self.env = dict(os.environ, PATH=str(binary)+':'+os.environ['PATH'])
        for key in ('DISPLAY','WAYLAND_DISPLAY','DBUS_SESSION_BUS_ADDRESS'): self.env.pop(key,None)
    def start(self):
        return subprocess.Popen([sys.executable,str(self.helper),'--event=/fixture.ics','--date=2026-10-11','--wait-for-launch'],env=self.env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    def test_permission_opens_helper(self):
        child = self.start()
        self.addCleanup(lambda: child.poll() is None and child.kill())
        stdout, stderr = child.communicate(b'1',timeout=5)
        self.assertEqual(child.returncode,0,stderr)
        self.assertTrue((self.root/'imported').exists())
    def test_eof_cancels_before_gui_import(self):
        child = self.start(); stdout,stderr=child.communicate(b'',timeout=5)
        self.assertEqual(child.returncode,1,stderr)
        self.assertFalse((self.root/'imported').exists())
    def test_startup_failure_requests_visible_notification(self):
        (self.root/'lib/carpatic_panel/calendar_editor.py').write_text("raise RuntimeError('private diagnostic must not be exposed')\n")
        child=self.start(); stdout,stderr=child.communicate(b'1',timeout=5)
        self.assertEqual(child.returncode,1)
        message=(self.root/'notification').read_text()
        self.assertIn('could not start',message)
        self.assertNotIn('private diagnostic',message)

if __name__ == '__main__': unittest.main()
