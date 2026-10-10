#!/usr/bin/env python3
"""Configuration, accessibility, process ownership and CLI persistence checks."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "integration/carpatic/motion/lib/window_animations.py"
spec = importlib.util.spec_from_file_location("window_animations", SOURCE)
motion = importlib.util.module_from_spec(spec); spec.loader.exec_module(motion)

class WindowAnimations(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cfg = Path(self.temp.name) / "config"
        self.env = patch.dict(os.environ, {"CARPATIC_CONFIG": str(self.cfg),
                                          "XDG_RUNTIME_DIR": self.temp.name,
                                          "CARPATIC_NO_ANIM": "0"})
        self.env.start()
    def tearDown(self): self.env.stop(); self.temp.cleanup()
    def test_validation_rejects_untrusted_values(self):
        for key, value in [("style", 'macos\";backend=\"bad'), ("speed", "9999"),
                           ("open", "perhaps"), ("unknown", "on")]:
            with self.assertRaises(ValueError): motion.validate(key, value)
    def test_off_and_reduce_motion_remove_every_transition(self):
        for key in ("enabled", "reduced"):
            state = dict(motion.DEFAULTS, reduced=False)
            state[key] = key == "reduced"
            self.assertNotIn("duration =", motion.render(state))
            self.assertNotIn('saved-image-blend =', motion.render(state))
    def test_bad_state_does_not_destroy_valid_preferences(self):
        self.cfg.mkdir()
        (self.cfg / "animations.json").write_text('{"speed":"fast","open":"garbage","style":"subtle"}')
        state = motion.load()
        self.assertEqual(state["speed"], "fast")
        self.assertTrue(state["open"])
        self.assertEqual(state["style"], "subtle")
    def test_reduce_motion_flag_overrides_preferences(self):
        self.cfg.mkdir(); (self.cfg / "reduced-motion").touch()
        state = motion.load()
        self.assertTrue(state["reduced"])
        self.assertNotIn("duration =", motion.render(state))
    def test_minimise_target_follows_dock_edge(self):
        self.cfg.mkdir(); state = dict(motion.DEFAULTS, reduced=False)
        (self.cfg / "panel.conf").write_text("design=ubuntu\nposition=auto\n")
        self.assertIn("window-monitor-x + 28 - window-x", motion.render(state))
        (self.cfg / "panel.conf").write_text("position=right\n")
        self.assertIn("window-monitor-width - 28 - window-x", motion.render(state))
    def test_subtle_uses_fades_and_can_keep_geometry(self):
        state = dict(motion.DEFAULTS, reduced=False, style="subtle")
        output = motion.render(state, "glx")
        self.assertNotIn("user-scale", output)
        self.assertIn('saved-image-blend =', output)
    def test_xrender_geometry_keeps_transform_without_saved_image_blending(self):
        state = dict(motion.DEFAULTS, reduced=False)
        output = motion.render(state, "xrender")
        self.assertIn('triggers = ["geometry"]', output)
        self.assertIn('window-width-before / window-width', output)
        self.assertNotIn('saved-image-blend', output)
    def test_xrender_repaints_exposed_windows_and_glx_keeps_damage_tracking(self):
        state = dict(motion.DEFAULTS, reduced=False)
        self.assertIn('use-damage = false;', motion.render(state, "xrender"))
        self.assertIn('use-damage = true;', motion.render(state, "glx"))
    def test_runtime_files_are_separate_for_private_displays(self):
        with patch.dict(os.environ, DISPLAY=":97"): first = motion.runtime_dir()
        with patch.dict(os.environ, DISPLAY=":98"): second = motion.runtime_dir()
        self.assertNotEqual(first, second)
    def test_signaling_tracks_real_owned_process_and_rejects_stale_pid(self):
        import signal
        env = dict(os.environ, DISPLAY=":97")
        child = subprocess.Popen(["picom", "-c", "import time; time.sleep(10)",
                                  str(self.cfg / "window-animations.conf")], executable=sys.executable, env=env)
        try:
            with patch.dict(os.environ, DISPLAY=":97"):
                runtime = motion.runtime_dir(); runtime.mkdir(parents=True, exist_ok=True)
                (runtime / "pid").write_text(str(child.pid))
                self.assertTrue(motion.signal_owned(child.pid, signal.SIGTERM))
                child.wait(timeout=3)
                self.assertFalse(motion.signal_owned(child.pid, signal.SIGTERM))
        finally:
            if child.poll() is None: child.terminate()
            child.wait(timeout=3)

    def test_unrelated_pid_is_not_owned(self):
        runtime = motion.runtime_dir(); runtime.mkdir(parents=True)
        (runtime / "pid").write_text(str(os.getpid()))
        self.assertIsNone(motion.owned_pid())
    def test_stale_record_cannot_claim_a_process_on_another_display(self):
        # Real procfs ownership, not a mock that repeats the implementation.
        env = dict(os.environ, DISPLAY=":97")
        child = subprocess.Popen(["picom", "-c", "import time; time.sleep(10)",
                                  str(self.cfg / "window-animations.conf")],
                                 executable=sys.executable, env=env)
        try:
            with patch.dict(os.environ, DISPLAY=":97"):
                runtime = motion.runtime_dir(); runtime.mkdir(parents=True)
                (runtime / "pid").write_text(str(child.pid))
                self.assertEqual(motion.owned_pid(), child.pid)
            with patch.dict(os.environ, DISPLAY=":98"):
                runtime = motion.runtime_dir(); runtime.mkdir(parents=True)
                (runtime / "pid").write_text(str(child.pid))
                self.assertIsNone(motion.owned_pid())
        finally:
            child.terminate(); child.wait(timeout=3)

    def test_backend_uses_glx_only_when_acceleration_is_confirmed(self):
        with patch.dict(os.environ, CARPATIC_ANIMATION_BACKEND="auto"), patch.object(motion, "session_guard", return_value=True):
            for output, expected in [("Accelerated: yes\n", "glx"),
                                     ("Accelerated: no\nOpenGL renderer string: llvmpipe", "xrender"),
                                     ("direct rendering: Yes", "xrender")]:
                with patch.object(motion.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, output)):
                    self.assertEqual(motion.select_backend(), expected)
            with patch.object(motion.subprocess, "run", side_effect=FileNotFoundError):
                self.assertEqual(motion.select_backend(), "xrender")
            with patch.object(motion.subprocess, "run", side_effect=subprocess.TimeoutExpired("glxinfo", 3)):
                self.assertEqual(motion.select_backend(), "xrender")
    def test_backend_override_and_offline_render_do_not_probe_display(self):
        with patch.object(motion.subprocess, "run") as probe:
            for backend in ("glx", "xrender"):
                with patch.dict(os.environ, CARPATIC_ANIMATION_BACKEND=backend):
                    self.assertEqual(motion.select_backend(), backend)
            with patch.dict(os.environ, CARPATIC_ANIMATION_BACKEND="auto"), patch.object(motion, "session_guard", return_value=False):
                self.assertEqual(motion.select_backend(), "xrender")
                self.assertIn('backend = "xrender"', motion.render(dict(motion.DEFAULTS, reduced=False)))
            probe.assert_not_called()
    def test_cli_persists_and_invalid_change_keeps_previous_value(self):
        env = dict(os.environ)
        result = subprocess.run(["python3", str(SOURCE), "set", "speed", "fast", "--no-apply"], env=env, capture_output=True)
        self.assertEqual(result.returncode, 0)
        previous = (self.cfg / "animations.json").read_bytes()
        invalid = subprocess.run(["python3", str(SOURCE), "set", "speed", "nonsense", "--no-apply"], env=env, capture_output=True)
        self.assertNotEqual(invalid.returncode, 0)
        self.assertEqual((self.cfg / "animations.json").read_bytes(), previous)
        state = json.loads(subprocess.check_output(["python3", str(SOURCE), "get", "--json"], env=env))
        self.assertEqual(state["speed"], "fast")

if __name__ == "__main__": unittest.main()
