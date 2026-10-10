#!/usr/bin/env python3
"""Wallpaper backend contracts; all command execution is an isolated fixture."""
import os
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integration/carpatic/wallpapers/lib"))
from carpatic_wallpapers import apply, cli


class DesktopWallpaper(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="carpatic-wallpaper-fixture-")
        self.addCleanup(tmp.cleanup)
        self.image = str(Path(tmp.name) / "chosen picture with spaces.jpg")
        self.other = str(Path(tmp.name) / "another monitor.jpg")
        Path(self.image).write_bytes(b"fixture image")
        Path(self.other).write_bytes(b"fixture image")
        self.calls = []
        self.owner = False
        self.fail_property = None
        self.tools = {"gdbus", "xfconf-query", "xrandr", "feh"}
        self.monitor_text = "Monitors: 2\n 0: +*eDP-1 1920/300x1080/170+0+0 eDP-1\n 1: +HDMI-1 1280/300x720/170-1280-50 HDMI-1\n"
        self.state = {"fill": "fill", "monitors": {"HDMI-1": self.other}}
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"DISPLAY": ":91", "DBUS_SESSION_BUS_ADDRESS": "fixture-bus", "CARPATIC_DESKTOP_SURFACE": "0"}).start()
        patch.object(apply.shutil, "which", side_effect=lambda n: "/fixture/" + n if n in self.tools else None).start()
        patch.object(apply.state, "load", return_value=self.state).start()

    def command(self, argv, **kwargs):
        # Never delegate fixture commands to subprocess or an actual session bus.
        self.calls.append((argv, kwargs))
        if argv[0] == "gdbus":
            return subprocess.CompletedProcess(argv, 0, "(true,)" if self.owner else "(false,)")
        if argv[0] == "xrandr":
            return subprocess.CompletedProcess(argv, 0, self.monitor_text)
        failed = self.fail_property and self.fail_property in argv
        return subprocess.CompletedProcess(argv, 1 if failed else 0, "")

    def properties(self):
        return {argv[argv.index("--property") + 1]: argv[argv.index("--set") + 1]
                for argv, _ in self.calls if argv[0] == "xfconf-query"}

    def test_prestart_sets_only_global_workspace_and_monitor_backdrops(self):
        os.environ["CARPATIC_DESKTOP_SURFACE"] = "1"
        self.assertTrue(apply.paint(self.image, run=self.command))
        props = self.properties()
        self.assertEqual(props, {
            "/backdrop/single-workspace-number": "0",
            "/backdrop/single-workspace-mode": "true",
            "/backdrop/screen0/monitoreDP-1/workspace0/last-image": self.image,
            "/backdrop/screen0/monitoreDP-1/workspace0/image-style": "5",
            "/backdrop/screen0/monitorHDMI-1/workspace0/last-image": self.other,
            "/backdrop/screen0/monitorHDMI-1/workspace0/image-style": "5"})
        self.assertFalse(any(c[0] in ("gdbus", "feh", "xwallpaper") for c, _ in self.calls))

    def test_live_owner_uses_verified_bus_name_and_bounded_query(self):
        self.owner = True
        self.assertTrue(apply.paint(self.image, run=self.command))
        argv, kwargs = self.calls[0]
        self.assertEqual(argv[-1], "org.xfce.xfdesktop")
        self.assertEqual(kwargs["timeout"], 3)
        self.assertTrue(self.properties())

    def test_no_owner_retains_root_backend_and_per_monitor_order(self):
        self.assertTrue(apply.paint(self.image, run=self.command))
        self.assertFalse(self.properties())
        self.assertEqual(self.calls[-1][0], ["feh", "--no-fehbg", "--bg-fill", self.image, self.other])

    def test_no_bus_does_not_autolaunch_bus(self):
        os.environ.pop("DBUS_SESSION_BUS_ADDRESS", None)
        self.assertTrue(apply.paint(self.image, run=self.command))
        self.assertFalse(any(c[0] == "gdbus" for c, _ in self.calls))

    def test_all_fill_modes_use_actual_tagged_enum_values(self):
        self.owner = True
        for fill, expected in (("fill", "5"), ("fit", "4"), ("stretch", "3"), ("center", "1"), ("tile", "2")):
            with self.subTest(fill=fill):
                self.calls.clear()
                self.assertTrue(apply.paint(self.image, fill, self.command))
                self.assertEqual(self.properties()["/backdrop/screen0/monitoreDP-1/workspace0/image-style"], expected)

    def test_property_failure_is_false_without_root_fallback(self):
        self.owner = True
        self.fail_property = "/backdrop/screen0/monitorHDMI-1/workspace0/last-image"
        self.assertFalse(apply.paint(self.image, run=self.command))
        self.assertFalse(any(c[0] in ("feh", "xwallpaper") for c, _ in self.calls))

    def test_missing_xfconf_or_monitors_is_false_not_hidden_root_success(self):
        self.owner = True
        self.tools.remove("xfconf-query")
        self.assertFalse(apply.paint(self.image, run=self.command))
        self.tools.add("xfconf-query")
        self.monitor_text = "Monitors: 0\n"
        self.assertFalse(apply.paint(self.image, run=self.command))
        self.assertFalse(any(c[0] in ("feh", "xwallpaper") for c, _ in self.calls))

    def test_command_timeout_is_reported_as_failure(self):
        os.environ["CARPATIC_DESKTOP_SURFACE"] = "1"
        def runner(argv, **kw):
            if argv[0] == "xfconf-query":
                raise subprocess.TimeoutExpired(argv, kw["timeout"])
            return self.command(argv, **kw)
        self.assertFalse(apply.paint(self.image, run=runner))

    def test_negative_monitor_offsets_are_preserved(self):
        self.assertEqual(apply.monitors(self.command), [("eDP-1", 1920, 1080, 0, 0), ("HDMI-1", 1280, 720, -1280, -50)])

    def test_missing_per_monitor_image_uses_default_and_xwallpaper_compatibility(self):
        self.state["monitors"]["HDMI-1"] = self.other + "missing"
        self.owner = True
        self.assertTrue(apply.paint(self.image, run=self.command))
        self.assertEqual(self.properties()["/backdrop/screen0/monitorHDMI-1/workspace0/last-image"], self.image)
        commands = apply.build_commands(self.image, "fit", {"HDMI-1": self.other},
                                         [("eDP-1",), ("HDMI-1",)], have=lambda n: n == "xwallpaper")
        self.assertEqual(commands, [["xwallpaper", "--output", "eDP-1", "--maximize", self.image,
                                     "--output", "HDMI-1", "--maximize", self.other]])


class ExplicitPaintCLI(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="carpatic-explicit-paint-")
        self.addCleanup(tmp.cleanup)
        self.picture = str(Path(tmp.name) / "actual image with spaces.jpg")
        Path(self.picture).write_bytes(b"\xff\xd8\xff" + b"\0" * 29)
        self.addCleanup(patch.stopall)
        self.paint = patch.object(apply, "paint", return_value=True).start()
        self.current = patch.object(apply, "current_wallpaper", return_value="").start()
        self.save = patch.object(apply.state, "save").start()
        self.setting = patch.object(apply, "set_setting").start()

    def invoke(self, args):
        with contextlib.redirect_stderr(io.StringIO()) as error:
            status = cli.main(args)
        return status, error.getvalue()

    def test_explicit_image_and_fill_do_not_depend_on_current_or_mutate_preferences(self):
        status, error = self.invoke(["paint", self.picture, "--fill", "fit"])
        self.assertEqual(status, 0, error)
        self.paint.assert_called_once_with(self.picture, "fit")
        self.current.assert_not_called()
        self.save.assert_not_called()
        self.setting.assert_not_called()

    def test_noargs_preserves_current_and_saved_fill_resolution(self):
        self.current.return_value = self.picture
        status, error = self.invoke(["paint"])
        self.assertEqual(status, 0, error)
        self.paint.assert_called_once_with(self.picture, None)

    def test_unresolved_current_and_bad_explicit_image_are_errors(self):
        for args in (["paint"], ["paint", self.picture + "missing"]):
            with self.subTest(args=args):
                self.assertEqual(self.invoke(args)[0], 1)
        self.paint.assert_not_called()

    def test_failed_backend_stays_failed_even_without_display(self):
        self.paint.return_value = False
        with patch.dict(os.environ, {}, clear=True):
            status, error = self.invoke(["paint", self.picture])
        self.assertEqual(status, 1)
        self.assertIn("Could not paint", error)

    def test_bad_fill_missing_fill_and_extra_arguments_do_not_paint(self):
        for tail in (["--fill"], ["--fill", "nonsense"], ["--unknown"], [self.picture, self.picture]):
            with self.subTest(tail=tail):
                self.assertEqual(self.invoke(["paint"] + tail)[0], 1)
        self.paint.assert_not_called()


class ConfiguratorPaint(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="carpatic-configurator-paint-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.record = self.root / "argv.json"
        self.env = dict(os.environ, PATH=str(self.bin), FIXTURE_RECORD=str(self.record), FIXTURE_EXIT="0")
        # Execute only the actual wp_paint function, never full configurator logic.
        source = (ROOT / "integration/carpatic/configurator/bin/carpatic-apply").read_text()
        start = source.index("wp_paint() {")
        self.function = source[start:source.index("\n}\n", start) + 3]
        script = "#!" + sys.executable + "\nimport json,os,sys\nwith open(os.environ['FIXTURE_RECORD'], 'w') as f: json.dump(sys.argv[1:],f)\nsys.exit(int(os.environ['FIXTURE_EXIT']))\n"
        for name in ("carpatic-wallpaper", "feh"):
            path = self.bin / name
            path.write_text(script)
            path.chmod(0o755)

    def invoke(self, mode):
        source = "get_setting() { printf '%s\\n' " + mode + "; }\n" + self.function + '\nwp_paint "$1"\n'
        return subprocess.run(["/bin/sh", "-c", source, "fixture", "/fixture/picture with spaces.jpg"],
                              env=self.env, capture_output=True, text=True, timeout=5)

    def test_configurator_passes_resolved_picture_and_mode(self):
        result = self.invoke("center")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.record.read_text()), ["paint", "/fixture/picture with spaces.jpg", "--fill", "center"])

    def test_helper_failure_is_not_hidden_by_feh(self):
        self.env["FIXTURE_EXIT"] = "9"
        result = self.invoke("fit")
        self.assertEqual(result.returncode, 9)
        self.assertEqual(json.loads(self.record.read_text())[0], "paint")

    def test_missing_helper_retains_feh_fallback(self):
        (self.bin / "carpatic-wallpaper").unlink()
        result = self.invoke("tile")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.record.read_text()), ["--no-fehbg", "--bg-tile", "/fixture/picture with spaces.jpg"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
