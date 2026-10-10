#!/usr/bin/env python3
"""Real GTK first-paint/opaque-slide regression. Isolated Alpine Xorg only."""
import json
import os
from pathlib import Path
import sys
import time

if (os.environ.get('CARPATIC_VM_TEST') != '1' or not Path('/etc/alpine-release').exists()
        or os.environ.get('DISPLAY') != ':0' or os.environ.get('WAYLAND_DISPLAY')):
    raise SystemExit('Run only in an explicitly marked isolated Alpine Xorg VM')

sys.path.insert(0, '/usr/local/lib/carpatic-panel')
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib
from carpatic_panel.popup import Popup
from carpatic_panel.kit import View
from carpatic_panel.theme import Theme
from rendering import Display, COLOR, command

if os.system('pgrep -x i3lock >/dev/null 2>&1') == 0:
    raise SystemExit('Screen-locked fixture cannot test pixels')

config = Path(os.environ['CARPATIC_CONFIG'])
config.mkdir(parents=True, exist_ok=True)
x = Display()
base = x.create('Flyout opaque backdrop', COLOR, 700, 550)
x.x.XMapWindow(x.handle, base)
x.sync()
command('xdotool', 'windowmove', str(base), '100', '100')
time.sleep(.4)
results = []
try:
    for mode in ('normal', 'slow', 'fast', 'menus-off', 'disabled', 'reduced'):
        (config / 'animations.json').write_text(json.dumps(dict(enabled=mode != 'disabled',
                                                              menus=mode != 'menus-off',
                                                              speed=mode if mode in ('slow', 'fast') else 'normal')))
        reduced = config / 'reduced-motion'
        if mode == 'reduced': reduced.touch()
        else: reduced.unlink(missing_ok=True)
        for iteration in range(3):
            theme = Theme.from_palette(dict(dark_background='#173f66'))
            view = View(theme)
            view.W, view.H = 360, 400
            popup = Popup(view, theme, (150, 130))
            assert popup.composited, 'Fixture must exercise a composited RGBA window'
            assert popup.get_opacity() == 0, 'Newly mapped, unpainted popup is visible'
            assert popup.slide == (mode not in ('menus-off', 'disabled', 'reduced'))
            time.sleep(.05)  # let the compositor observe the mapped hidden window
            image = x.x.XGetImage(x.handle, x.root, 200, 200, 1, 1, 0xFFFFFFFF, 2)
            assert image, 'Cannot capture pre-paint backdrop'
            pixel = x.x.XGetPixel(image, 0, 0) & 0xFFFFFF
            x.x.XDestroyImage(image)
            assert pixel == COLOR, f'Unpainted popup changed the backdrop: {pixel:06x}'
            frames = []
            opacities = []
            deadline = time.monotonic() + 3
            errors = []
            def sample():
                opacity = popup.get_opacity()
                opacities.append(opacity)
                if opacity == 1:
                    image = x.x.XGetImage(x.handle, x.root, 200, 200, 1, 1, 0xFFFFFFFF, 2)
                    if not image:
                        errors.append('Cannot capture visible popup'); Gtk.main_quit(); return False
                    pixel = x.x.XGetPixel(image, 0, 0) & 0xFFFFFF
                    x.x.XDestroyImage(image)
                    # Gtk's opacity property changes before the compositor
                    # presents the first frame. Start the content oracle only
                    # when that painted frame is actually visible.
                    if pixel == 0x173F66: frames.append(pixel)
                    if frames and pixel != 0x173F66:
                        errors.append(f'Opaque popup contains {pixel:06x}'); Gtk.main_quit(); return False
                if popup._anim_done() and len(frames) >= 8:
                    Gtk.main_quit(); return False
                if time.monotonic() > deadline:
                    errors.append('Opening transition did not finish'); Gtk.main_quit(); return False
                return True
            GLib.timeout_add(16, sample)
            Gtk.main()
            if errors:
                from gi.repository import Gdk
                root = Gdk.get_default_root_window()
                Gdk.pixbuf_get_from_window(root, 0, 0, root.get_width(), root.get_height()).savev('/var/tmp/flyout-failure.png', 'png', [], [])
                print('Failure geometry', popup.get_position(), popup.get_size(), flush=True)
            assert not errors, errors
            assert frames and all(value in (0, 1) for value in opacities), opacities
            assert popup.get_position() == (150, 130), popup.get_position()
            print(json.dumps(dict(mode=mode, iteration=iteration, samples=len(frames), ok=True)), flush=True)
            results.append(len(frames))
            # Release the same pointer grab used by the actual calendar.
            from gi.repository import Gdk
            Gdk.Display.get_default().get_default_seat().ungrab()
            popup.destroy()
            while Gtk.events_pending(): Gtk.main_iteration_do(False)
    print(json.dumps(dict(summary=True, cases=len(results), samples=sum(results), failed=0)), flush=True)
finally:
    x.close()
