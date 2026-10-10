#!/usr/bin/env python3
"""Pure geometry, palette contrast and staged asset checks; no GTK/X server."""
import importlib.util
import re
from pathlib import Path
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

PANEL = Path(__file__).resolve().parents[1]
ROOT = PANEL.parents[2]


def module(name):
    spec = importlib.util.spec_from_file_location(name, PANEL / 'lib/carpatic_panel' / f'{name}.py')
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


branding, theme, designs = (module(name) for name in ('branding', 'theme', 'designs'))


def vertices(source):
    """Resolve the line-only SVG contours used by the shared mountain mark."""
    tokens = re.findall(r'[MmLlHhZz]|-?\d+(?:\.\d+)?', source)
    paths, path = [], []
    x = y = 0.0
    command = None
    index = 0
    while index < len(tokens):
        if tokens[index].isalpha():
            command = tokens[index]; index += 1
            if command in 'Zz':
                if path[-1] != path[0]: path.append(path[0])
                x, y = path[0]
                paths.append(path); path = []; command = None
                continue
        if command is None: raise ValueError('Missing path command')
        if command in 'Hh':
            value = float(tokens[index]); index += 1
            x = x + value if command == 'h' else value
        else:
            a, b = map(float, tokens[index:index+2]); index += 2
            x, y = (x+a, y+b) if command.islower() else (a, b)
        path.append((x, y))
        if command == 'M': command = 'L'
        elif command == 'm': command = 'l'
    if path: paths.append(path)
    return paths


class Context:
    def __init__(self, fail=False): self.calls, self.fail = [], fail
    def __getattr__(self, name):
        def call(*arguments):
            self.calls.append((name, arguments))
            if self.fail and name == 'fill': raise RuntimeError('injected paint failure')
        return call


class Branding(unittest.TestCase):
    def test_canonical_and_symbolic_assets_preserve_brand_geometry(self):
        canonical = PANEL / 'assets/branding/carpathian-os.svg'
        original = ET.fromstring(canonical.read_text())
        self.assertEqual(original.attrib['viewBox'], '0 0 36 30')
        symbolic = ET.parse(PANEL / 'assets/branding/carpathian-os-symbolic.svg').getroot()
        self.assertEqual(symbolic.attrib['viewBox'], original.attrib['viewBox'])
        paths = original.findall('{http://www.w3.org/2000/svg}path')
        path = symbolic.find('{http://www.w3.org/2000/svg}path')
        expected = [contour for p in paths for contour in vertices(p.attrib['d'])]
        self.assertEqual(expected, [
            [(2, 26), (15, 4), (21, 14), (25, 8), (34, 26), (2, 26)],
            [(10, 15), (15, 7), (20, 15), (15, 12), (10, 15)],
        ])
        self.assertEqual(vertices(path.attrib['d']), expected)
        # Changing m to M also changes implicit subsequent lines to absolute.
        # Both that error and a relative appended move displace the notch.
        wrong_absolute = paths[0].attrib['d'] + ' M' + paths[1].attrib['d'][1:]
        wrong_relative = paths[0].attrib['d'] + ' ' + paths[1].attrib['d']
        self.assertNotEqual(vertices(wrong_absolute), expected)
        self.assertNotEqual(vertices(wrong_relative), expected)
        self.assertEqual(path.attrib['fill-rule'], 'evenodd')

    def test_mark_preserves_aspect_ratio_and_palette_colour(self):
        context = Context()
        foreground = (.9, .8, .7, 1)
        branding.draw_mark(context, 40, 30, 18, foreground)
        self.assertEqual(context.calls[0], ('save', ()))
        self.assertIn(('translate', (31, 22.5)), context.calls)
        self.assertIn(('scale', (.5, .5)), context.calls)
        self.assertIn(('set_source_rgba', foreground), context.calls)
        self.assertIn(('set_fill_rule', (1,)), context.calls)
        self.assertEqual(context.calls.count(('close_path', ())), 2)
        self.assertEqual(context.calls[-1], ('restore', ()))

    def test_failed_paint_restores_context(self):
        context = Context(fail=True)
        with self.assertRaisesRegex(RuntimeError, 'injected paint'):
            branding.draw_mark(context, 0, 0, 36, (0, 0, 0, 1))
        self.assertEqual(context.calls[-1], ('restore', ()))

    def test_all_shipped_palette_marks_have_nontext_icon_contrast(self):
        palettes = sorted((PANEL.parent / 'configurator/themes').glob('*/colors.toml'))
        self.assertGreaterEqual(len(palettes), 29)
        for path in palettes:
            colors = theme.parse_toml_colors(path)
            palette = theme.Theme.from_palette(colors)
            with self.subTest(palette=path.parent.name):
                for background in (palette.bg, palette.deep, palette.surface):
                    light, dark = sorted((theme.luminance(palette.fg), theme.luminance(background)), reverse=True)
                    self.assertGreaterEqual((light + .05) / (dark + .05), 3)

    def test_every_design_retains_a_branded_launcher_surface(self):
        for name in designs.DESIGNS:
            surfaces = designs.surfaces({'design': name})
            with self.subTest(design=name):
                self.assertTrue(any(set(surface.left + surface.center + surface.right) & {'start', 'logo', 'activities'} for surface in surfaces))

    def test_destdir_install_retains_assets_and_command_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(['sh', str(PANEL / 'install.sh')],
                                    env={'PATH': '/usr/bin:/bin', 'DESTDIR': temporary, 'PREFIX': '/usr'},
                                    text=True, capture_output=True, check=True)
            target = Path(temporary)
            for name in ('carpathian-os.svg', 'carpathian-os-symbolic.svg'):
                asset = target / 'usr/share/carpatic/panel/branding' / name
                self.assertEqual(asset.read_bytes(), (PANEL / 'assets/branding' / name).read_bytes())
                self.assertEqual(asset.stat().st_mode & 0o777, 0o644)
            for name in ('carpatic-panel', 'carpatic-flyout', 'carpatic-overview'):
                self.assertTrue((target / 'usr/bin' / name).is_file())
            self.assertTrue((target / 'usr/lib/carpatic-panel/carpatic_panel/branding.py').is_file())


if __name__ == '__main__':
    unittest.main()
