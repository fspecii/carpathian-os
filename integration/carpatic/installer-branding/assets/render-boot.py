#!/usr/bin/python3
"""Developer-only renderer. ISO assembly consumes the committed PNG files."""
import hashlib
import json
from pathlib import Path
import subprocess
import cairo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
FONT = Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
LOGO = ROOT / 'integration/carpatic/panel/assets/branding/carpathian-os.svg'

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def wordmark(size, center, baseline):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1280, 720)
    context = cairo.Context(surface)
    context.select_font_face('DejaVu Sans', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    context.set_font_size(size)
    text = 'Carpathian OS'
    extents = context.text_extents(text)
    cursor = center - extents.width / 2 - extents.x_bearing
    for character in text:
        context.move_to(cursor, baseline)
        context.text_path(character)
        cursor += context.text_extents(character).x_advance
    commands = []
    for kind, points in context.copy_path():
        letter = {cairo.PATH_MOVE_TO: 'M', cairo.PATH_LINE_TO: 'L',
                  cairo.PATH_CURVE_TO: 'C', cairo.PATH_CLOSE_PATH: 'Z'}[kind]
        commands.append(letter + ' '.join(format(value, '.5f').rstrip('0').rstrip('.') for value in points))
    return ' '.join(commands)

matched = subprocess.check_output(['fc-match', '-f', '%{file}', 'DejaVu Sans']).decode()
if matched != str(FONT):
    raise SystemExit('Expected fixed DejaVu Sans regular font')
# These exact vector paths come from the public panel logo; only palette changes.
mountain = 'M2 26 15 4l6 10 4-6 9 18H2Z'
snow = 'm10 15 5-8 5 8-5-3Z'
if mountain not in LOGO.read_text() or snow not in LOGO.read_text():
    raise SystemExit('Panel logo changed; review boot logo provenance')
assets = {}
for name, width, height, scale, y, font_size, baseline in (
    ('boot-background', 1280, 720, 3, 104, 34, 236),
    ('boot-splash', 640, 480, 2, 60, 24, 156),
):
    x = (width - 36 * scale) / 2
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<title>Carpathian OS installer boot background</title>
<rect width="{width}" height="{height}" fill="#0b0e13"/>
<g id="mountain" transform="translate({x:g} {y}) scale({scale})">
<path d="{mountain}" fill="#5cc8a8"/>
<path d="{snow}" fill="#f5f7f2"/>
</g>
<path id="wordmark" aria-label="Carpathian OS" d="{wordmark(font_size, width / 2, baseline)}" fill="#e7ecf3"/>
</svg>
'''
    source = HERE / (name + '.svg')
    output = HERE / (name + '.png')
    source.write_text(svg)
    subprocess.run(['convert', str(source), '-background', '#0b0e13', '-alpha', 'off', '-strip',
                    '-depth', '8', '-interlace', 'none', 'PNG24:' + str(output)], check=True)
    assets[source.name] = digest(source)
    assets[output.name] = digest(output)
metadata = {
    'logo_source': str(LOGO.relative_to(ROOT)), 'logo_sha256': digest(LOGO),
    'font': 'DejaVu Sans regular', 'font_file': str(FONT), 'font_sha256': digest(FONT),
    'font_license': 'Bitstream Vera; DejaVu changes public domain; see BOOT-FONT-LICENSE.txt',
    'cairo_version': cairo.cairo_version_string(),
    'imagemagick_version': subprocess.check_output(['convert', '-version']).decode().splitlines()[0],
    'renderer_sha256': digest(Path(__file__)), 'files': assets,
}
(HERE / 'boot-render-provenance.json').write_text(json.dumps(metadata, indent=2) + '\n')
