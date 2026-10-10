#!/usr/bin/env python3
"""Isolated CLI contracts only: no X server, desktop or file manager is started."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "integration/carpatic/desktop/bin/carpatic-desktop"


class DesktopCommands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="carpatic-desktop-commands-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.record = self.root / "launch.json"
        self.desktop = self.root / "Bureau with spaces"
        self.env = dict(os.environ, CARPATIC_SESSION="1", DISPLAY=":91",
                        XDG_CONFIG_HOME=str(self.root / "config"),
                        PATH=str(self.bin), FIXTURE_RECORD=str(self.record),
                        FIXTURE_DESKTOP=str(self.desktop), FIXTURE_WM="Carpathian OS")
        self.env.pop("WAYLAND_DISPLAY", None)
        for tool in ("sed", "grep", "mkdir"):
            (self.bin / tool).symlink_to(shutil.which(tool))
        self.command("xprop", '#!/bin/sh\nif [ "$1" = -root ]; then echo "_NET_SUPPORTING_WM_CHECK(WINDOW): window id # 0x123"; else printf \'_NET_WM_NAME(UTF8_STRING) = "%s"\\n\' "$FIXTURE_WM"; fi\n')
        self.command("xdg-user-dir", '#!/bin/sh\n[ "$1" = DESKTOP ] || exit 9\nprintf "%s\\n" "$FIXTURE_DESKTOP"\n')
        self.command("xfdesktop", f'#!{shutil.which("python3")}\nimport os,sys,json\nwith open(os.environ["FIXTURE_RECORD"], "w") as f: json.dump({{"argv":sys.argv[1:],"backend":os.environ.get("GDK_BACKEND"),"home":os.environ.get("HOME")}}, f)\nsys.exit(int(os.environ.get("FIXTURE_EXIT", "0")))\n')

    def command(self, name, text):
        path = self.bin / name
        path.write_text(text)
        path.chmod(0o755)

    def run_helper(self, *args):
        return subprocess.run(["/bin/sh", str(HELPER), *args], env=self.env,
                              text=True, capture_output=True, timeout=5)

    def assert_refused(self, phrase):
        result = self.run_helper("start")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(phrase, result.stderr)
        self.assertFalse(self.record.exists())
        self.assertFalse(self.desktop.exists())

    def test_start_preserves_home_preferences_and_xdg_directory(self):
        config = Path(self.env["XDG_CONFIG_HOME"])
        config.mkdir()
        wallpaper = config / "wallpaper"
        wallpaper.write_text("existing wallpaper\n")
        result = self.run_helper("start")
        self.assertEqual(result.returncode, 0, result.stderr)
        launch = json.loads(self.record.read_text())
        self.assertEqual(launch["argv"], ["--disable-wm-check"])
        self.assertEqual(launch["backend"], "x11")
        self.assertEqual(launch["home"], os.environ.get("HOME"))
        self.assertTrue(self.desktop.is_dir())
        self.assertEqual(wallpaper.read_text(), "existing wallpaper\n")
        self.assertEqual(list(config.iterdir()), [wallpaper])

    def test_rejects_non_carpatic_session(self):
        self.env["CARPATIC_SESSION"] = "0"
        self.assert_refused("Carpathian session")

    def test_rejects_wayland_and_missing_display(self):
        self.env["WAYLAND_DISPLAY"] = "wayland-fixture"
        self.assert_refused("X11 display")
        self.env.pop("WAYLAND_DISPLAY")
        self.env.pop("DISPLAY")
        self.assert_refused("X11 display")

    def test_rejects_other_window_manager_even_with_session_label(self):
        self.env["FIXTURE_WM"] = "COSMIC"
        self.assert_refused("not managed by Carpathian OS")

    def test_missing_dependency_is_actionable(self):
        (self.bin / "xfdesktop").unlink()
        self.assert_refused("doas apk add xfdesktop xdg-user-dirs xprop")

    def test_disabled_and_relative_desktop_directories_are_not_created(self):
        self.env["FIXTURE_DESKTOP"] = os.environ["HOME"]
        self.assert_refused("Desktop icons are disabled")
        self.env["FIXTURE_DESKTOP"] = "relative-directory"
        self.assert_refused("absolute path")

    def test_launcher_failure_is_not_masked(self):
        self.env["FIXTURE_EXIT"] = "7"
        self.assertEqual(self.run_helper("start").returncode, 7)

    def test_unknown_actions_and_help_do_not_launch(self):
        for args in (("stop",), ("start", "extra")):
            self.assertNotEqual(self.run_helper(*args).returncode, 0)
        self.assertEqual(self.run_helper("--help").returncode, 0)
        self.assertFalse(self.record.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
