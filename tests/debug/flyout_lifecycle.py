#!/usr/bin/env python3
"""Keep an actual GTK popup alive through compositor stop/start transitions."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

if (os.environ.get('CARPATIC_VM_TEST') != '1' or not Path('/etc/alpine-release').exists()
        or os.environ.get('DISPLAY') != ':0' or os.environ.get('WAYLAND_DISPLAY')):
    raise SystemExit('Isolated Alpine Xorg :0 only')
if subprocess.run(['pgrep', '-x', 'i3lock'], stdout=subprocess.DEVNULL).returncode == 0:
    raise SystemExit('Fixture is locked')
sys.path.insert(0, '/usr/local/lib/carpatic-panel')
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Gdk
from carpatic_panel.popup import Popup
from carpatic_panel.kit import View
from carpatic_panel.theme import Theme
from rendering import Display, COLOR, command

cfg = Path(os.environ.get('CARPATIC_CONFIG') or str(Path.home() / '.config/carpatic'))
path = cfg / 'animations.json'
saved = path.read_bytes() if path.exists() else None
original = json.loads(command('carpatic-animations', 'get', '--json'))
assert original['enabled'] and original['running'], 'Start the fixture compositor first'
x = Display()
base = x.create('Live flyout backdrop', COLOR, 700, 550)
x.x.XMapWindow(x.handle, base); x.sync()
command('xdotool', 'windowmove', str(base), '80', '60')
time.sleep(.5)
_, geometry = x.pixels(base)
assert int(geometry['X']) <= 150 and int(geometry['Y']) <= 130, geometry
assert int(geometry['X']) + int(geometry['WIDTH']) > 509, geometry
assert int(geometry['Y']) + int(geometry['HEIGHT']) > 529, geometry
print(json.dumps(dict(backdrop_geometry=geometry)), flush=True)
records = []
popup = None
child = None
try:
    for start in (True, False):
        command('carpatic-animations', 'set', 'enabled', 'on' if start else 'off')
        theme = Theme.from_palette(dict(dark_background='#173f66'))
        view = View(theme); view.W, view.H = 360, 400
        popup = Popup(view, theme, (150, 130), slide=False)
        states = [start, not start, start, not start, start]
        phase = [0, time.monotonic() + .4]
        errors = []
        deadline = time.monotonic() + 15
        def sample():
            global child
            try:
                if time.monotonic() > deadline: raise AssertionError('Compositor transition timed out')
                if child is not None:
                    rc = child.poll()
                    if rc is None: return True
                    assert rc == 0, child.communicate()[1].decode()
                    child = None; phase[1] = time.monotonic() + .25
                if time.monotonic() < phase[1]: return True
                expected = states[phase[0]]
                assert popup.composited == expected, 'Popup retained the previous compositor state'
                points = [(200, 200, 0x173F66), (150, 130, COLOR),
                          (509, 130, COLOR), (150, 529, COLOR), (509, 529, COLOR)]
                pixels = []
                for px, py, color in points:
                    image = x.x.XGetImage(x.handle, x.root, px, py, 1, 1, 0xFFFFFFFF, 2)
                    assert image, 'Root pixel unavailable'
                    pixel = x.x.XGetPixel(image, 0, 0) & 0xFFFFFF
                    x.x.XDestroyImage(image)
                    assert pixel == color, f'{px},{py}: {pixel:06x}, expected {color:06x}'
                    pixels.append(f'{pixel:06x}')
                print(json.dumps(dict(start_composited=start, phase=phase[0],
                                      composited=expected, pixels=pixels, ok=True)), flush=True)
                records.append(pixels)
                phase[0] += 1
                if phase[0] == len(states): Gtk.main_quit(); return False
                popup.poke()
                child = subprocess.Popen(['carpatic-animations', 'set', 'enabled',
                                          'on' if states[phase[0]] else 'off'],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                return True
            except Exception as error:
                errors.append(str(error)); Gtk.main_quit(); return False
        GLib.timeout_add(30, sample)
        Gtk.main()
        if errors:
            root = Gdk.get_default_root_window()
            Gdk.pixbuf_get_from_window(root, 0, 0, root.get_width(), root.get_height()).savev('/var/tmp/flyout-lifecycle-failure.png', 'png', [], [])
        assert not errors, errors
        Gdk.Display.get_default().get_default_seat().ungrab()
        popup.destroy(); popup = None
        while Gtk.events_pending(): Gtk.main_iteration_do(False)
    print(json.dumps(dict(summary=True, phases=len(records), pixels=len(records)*5, failed=0)), flush=True)
finally:
    if child is not None:
        child.wait(timeout=20)
    if popup is not None:
        Gdk.Display.get_default().get_default_seat().ungrab(); popup.destroy()
    if saved is None: path.unlink(missing_ok=True)
    else: path.write_bytes(saved)
    command('carpatic-animations', 'apply')
    x.close()
