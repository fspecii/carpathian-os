#!/usr/bin/env python3
"""Host-only policy assertions and restoration failures; no X display opened."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import contextlib
import io
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('animation_matrix', Path(__file__).parent/'debug/animation_matrix.py')
matrix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(matrix)


class Policy(unittest.TestCase):
    def test_active_backend_rejects_silent_fallback_or_missing_selection(self):
        self.assertEqual(matrix.validate_backend('backend = "glx";', 'glx', 'glx-macos-normal'), 'glx')
        self.assertEqual(matrix.validate_backend('backend = "xrender";', 'xrender', 'xrender-subtle-fast'), 'xrender')
        for configuration in ['backend = "xrender";', 'backend = "invalid";', '# no backend']:
            with self.assertRaisesRegex(RuntimeError, 'generated backend'):
                matrix.validate_backend(configuration, 'glx', 'glx-macos-normal')

    def test_cli_selects_four_policy_cases_or_full_sixteen(self):
        for policy_only in (True, False):
            with self.subTest(policy_only=policy_only), tempfile.TemporaryDirectory() as directory:
                home = Path(directory); cfg = home/'.config/carpatic'; cfg.mkdir(parents=True)
                defaults = dict(enabled=True, style='macos', speed='normal', open=True, close=True,
                                minimize=True, geometry=True, workspaces=True, menus=True)
                original = json.dumps(defaults).encode()
                (cfg/'animations.json').write_bytes(original)
                def run(*args):
                    settings = json.loads((cfg/'animations.json').read_text())
                    if args[0] == 'xprop': return '_CARPATIC_ANIMATION_PREPARE(CARDINAL) = 0'
                    if args[1] == 'get':
                        return json.dumps(dict(settings, reduced=(cfg/'reduced-motion').exists(), running=settings['enabled']))
                    backend = os.environ['CARPATIC_ANIMATION_BACKEND'] if settings['enabled'] else 'xrender'
                    (cfg/'window-animations.conf').write_text(f'backend = "{backend}";')
                    return ''
                def child(*args, **kwargs):
                    self.assertIn('--actions', args[0])
                    kwargs['stdout'].write('{"summary":true,"samples":3,"failed":0}\n')
                    return SimpleNamespace(returncode=0)
                def policy(_):
                    enabled = json.loads((cfg/'animations.json').read_text())['enabled']
                    return dict(samples=4, failed=0, compositor_owner=int(enabled))
                exists = Path.exists
                argv = ['matrix','--results',str(home/'results'),'--iterations','3'] + (['--policy-only'] if policy_only else [])
                output = io.StringIO()
                with patch.dict(os.environ, {'CARPATIC_VM_TEST':'1','DISPLAY':':0','CARPATIC_ANIMATION_BACKEND':'glx'}), \
                        patch.object(Path, 'home', return_value=home), \
                        patch.object(Path, 'exists', lambda path: True if str(path) == '/etc/alpine-release' else exists(path)), \
                        patch.object(matrix, 'run', side_effect=run), \
                        patch.object(matrix.subprocess, 'run', side_effect=child) as children, \
                        patch.object(matrix, 'policy_actions', side_effect=policy) as policies, \
                        patch.object(sys, 'argv', argv), contextlib.redirect_stdout(output):
                    os.environ.pop('WAYLAND_DISPLAY', None)
                    self.assertEqual(matrix.main(), 0)
                summary = json.loads(output.getvalue().splitlines()[-1])
                self.assertEqual(summary['cases'], 4 if policy_only else 16)
                self.assertEqual(summary['active_cases'], 0 if policy_only else 12)
                self.assertEqual(summary['policy_cases'], 4)
                self.assertEqual(children.call_count, 0 if policy_only else 12)
                self.assertEqual(policies.call_count, 4)
                self.assertEqual((cfg/'animations.json').read_bytes(), original)
                self.assertFalse((cfg/'reduced-motion').exists())

    def test_disabled_and_reduced_have_distinct_compositor_contracts(self):
        matrix.validate_policy('disabled', dict(enabled=False, running=False, reduced=False), 'backend="xrender";', 0)
        matrix.validate_policy('reduced', dict(enabled=True, running=True, reduced=True), 'backend="glx";', 0)
        for mode, state in [('disabled', dict(enabled=False, running=True, reduced=False)),
                            ('reduced', dict(enabled=True, running=False, reduced=True))]:
            with self.assertRaises(RuntimeError): matrix.validate_policy(mode, state, '', 0)

    def test_timed_effects_and_staged_unmap_fail_policy(self):
        state = dict(enabled=True, running=True, reduced=True)
        for text, delay in [('duration = .2;', 0), ('saved-image-blend = 1;', 0), ('', 50), ('', None)]:
            with self.assertRaises(RuntimeError): matrix.validate_policy('reduced', state, text, delay)

    def test_preferences_and_backend_restored_when_first_apply_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory); cfg = home/'.config/carpatic'; cfg.mkdir(parents=True)
            original = b'{"enabled":false,"speed":"fast"}\n'
            (cfg/'animations.json').write_bytes(original)
            (cfg/'reduced-motion').write_bytes(b'original flag\n')
            defaults = dict(enabled=True, style='macos', speed='normal', open=True, close=True,
                            minimize=True, geometry=True, workspaces=True, menus=True)
            applies = []
            def run(*args):
                if args[1] == 'get': return json.dumps(defaults)
                applies.append(args)
                if len(applies) == 1: raise RuntimeError('controlled apply failure')
                return ''
            exists = Path.exists
            with patch.dict(os.environ, {'CARPATIC_VM_TEST':'1', 'DISPLAY':':0', 'CARPATIC_ANIMATION_BACKEND':'xrender'}), \
                    patch.object(Path, 'home', return_value=home), \
                    patch.object(Path, 'exists', lambda path: True if str(path) == '/etc/alpine-release' else exists(path)), \
                    patch.object(matrix, 'run', side_effect=run), \
                    patch.object(sys, 'argv', ['matrix', '--results', str(home/'results'), '--iterations','3']):
                os.environ.pop('WAYLAND_DISPLAY', None)
                with self.assertRaisesRegex(RuntimeError, 'controlled apply failure'): matrix.main()
                self.assertEqual(os.environ['CARPATIC_ANIMATION_BACKEND'], 'xrender')
            self.assertEqual((cfg/'animations.json').read_bytes(), original)
            self.assertEqual((cfg/'reduced-motion').read_bytes(), b'original flag\n')
            self.assertEqual(len(applies), 2)


if __name__ == '__main__': unittest.main()
