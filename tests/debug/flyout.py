#!/usr/bin/env python3
"""Real GTK first-paint/opaque-slide regression. Isolated Alpine Xorg only."""
import datetime as dt
import hashlib
import json
import struct
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
from gi.repository import Gtk, GLib, Gdk
from carpatic_panel.popup import Popup
from carpatic_panel.kit import View, Canvas, render_surface
from carpatic_panel import uiscale
from carpatic_panel.flyout_cal import CalView, CalModel
from carpatic_panel.notes import FakeNotes
from flyout_oracle import classify
from carpatic_panel.theme import Theme
from rendering import Display, COLOR, command

if os.system('pgrep -x i3lock >/dev/null 2>&1') == 0:
    raise SystemExit('Screen-locked fixture cannot test pixels')

config = Path(os.environ['CARPATIC_CONFIG'])
config.mkdir(parents=True, exist_ok=True)
x = Display()
base = x.create('Flyout opaque backdrop', COLOR, 1100, 780)
x.x.XMapWindow(x.handle, base)
x.sync()
command('xdotool', 'windowmove', str(base), '100', '0')
time.sleep(.4)
# The actual calendar view gets owned empty data; no reminder/calendar writes
# or reads from the fixture user's personal data are needed for this oracle.
os.environ['XDG_DATA_HOME'] = str(config / 'probe-data')
Path(os.environ['XDG_DATA_HOME']).mkdir(exist_ok=True)

def pixels_at(points):
    left, top = min(p[0] for p in points), min(p[1] for p in points)
    width, height = max(p[0] for p in points)-left+1, max(p[1] for p in points)-top+1
    image = x.x.XGetImage(x.handle, x.root, left, top, width, height, 0xFFFFFFFF, 2)
    assert image, 'Cannot capture presented popup/backdrop'
    try:
        return [x.x.XGetPixel(image, px-left, py-top) & 0xFFFFFF for px, py in points]
    finally:
        x.x.XDestroyImage(image)

def sample_points(view):
    # Select real surface-colour patches from the rendered view, not arbitrary
    # positions that might contain calendar text. Require a 25px vertical margin
    # around each patch to cover the complete local 12px opening slide.
    surf, _ = render_surface(view, scale=uiscale.factor())
    surf.flush()
    data, stride = surf.get_data(), surf.get_stride()
    def rgb(px, py):
        return struct.unpack_from('=I', data, py*stride+px*4)[0] & 0xFFFFFF
    selected = []
    margin = max(25, uiscale.devr(16))
    for py in range(margin+16, surf.get_height()-margin-16, 35):
        for px in range(30, surf.get_width()-30, 45):
            if all(rgb(px+dx, py+dy) == 0x173F66
                   for dx in range(-8, 9, 4) for dy in range(-margin, margin+1, 4)):
                selected.append((150+px, 30+py))
    assert len(selected) >= 4, f'Insufficient opaque patches in {type(view).__name__}: {selected}'
    # Distribute samples over the actual content rather than one corner.
    return [selected[i*(len(selected)-1)//3] for i in range(4)]

def context(popup):
    xid = popup.get_window().get_xid()
    info = dict(xid=xid, gtk_opacity=popup.get_opacity(), paint_ready=popup._paint_ready,
                x11=command('xprop', '-id', str(xid), '_NET_WM_WINDOW_TYPE',
                            '_NET_WM_WINDOW_OPACITY', 'WM_CLASS'),
                map=command('xwininfo', '-id', str(xid)), compositor_configs=[])
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit(): continue
        try:
            args = proc.joinpath('cmdline').read_bytes().split(b'\0')
            if not args or Path(os.fsdecode(args[0])).name != 'picom': continue
            if proc.stat().st_uid != os.getuid() or b'--config' not in args: continue
            env = proc.joinpath('environ').read_bytes().split(b'\0')
            display = next((item[8:].decode() for item in env if item.startswith(b'DISPLAY=')), None)
            if display not in (os.environ['DISPLAY'], os.environ['DISPLAY']+'.0'): continue
            path = Path(os.fsdecode(args[args.index(b'--config')+1]))
            raw = path.read_bytes()
            info['compositor_configs'].append(dict(pid=int(proc.name), path=str(path),
                sha256=hashlib.sha256(raw).hexdigest(), config=raw.decode()))
        except (OSError, IndexError): continue
    return info

# GTK logs Python draw exceptions without raising them out of Gtk.main().
# A draw-after callback may still fire, so paint_ready alone is not proof that
# the content painter completed successfully.
draw_errors = []
original_draw = Canvas.on_draw
def checked_draw(canvas, *args):
    try:
        return original_draw(canvas, *args)
    except Exception as error:
        draw_errors.append(type(error).__name__+': '+str(error))
        raise
Canvas.on_draw = checked_draw

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
            for kind in ('generic', 'calendar'):
                theme = Theme.from_palette(dict(dark_background='#173f66'))
                if kind == 'calendar':
                    view = CalView(theme, CalModel(today=dt.date(2030, 2, 17), data=os.environ['XDG_DATA_HOME']),
                                   FakeNotes([]), look='win', max_h=min(760, uiscale.logical(Gdk.get_default_root_window().get_height())-80))
                else:
                    view = View(theme)
                    view.W, view.H = 360, 400
                points = sample_points(view)
                backdrop_deadline = time.monotonic()+2
                while pixels_at(points) != [COLOR]*len(points):
                    assert time.monotonic() < backdrop_deadline, 'Backdrop is occluded or does not cover sample points before new popup mapping'
                    time.sleep(.016)
                draw_errors.clear()
                popup = Popup(view, theme, (150, 30))
                assert popup.composited, 'Fixture must exercise a composited RGBA window'
                assert popup.get_opacity() == 0, 'Newly mapped, unpainted popup is visible'
                assert popup.slide == (mode not in ('menus-off', 'disabled', 'reduced'))
                time.sleep(.05)  # let the compositor observe the mapped hidden window
                print(json.dumps(dict(context=True, kind=kind, mode=mode, iteration=iteration,
                                      points=points, metadata=context(popup))), flush=True)
                classify(0, pixels_at(points), COLOR, 0x173F66, False)
                frames = []
                opacities = []
                deadline = time.monotonic() + 3
                errors = []
                records = []
                started = time.monotonic()
                def sample():
                    if draw_errors:
                        errors.extend(draw_errors); Gtk.main_quit(); return False
                    opacity = popup.get_opacity()
                    opacities.append(opacity)
                    observed = pixels_at(points)
                    record = dict(elapsed=time.monotonic()-started, opacity=opacity,
                                  paint_ready=popup._paint_ready, gtk_mapped=popup.get_mapped(), position=popup.get_position(), pixels=observed)
                    records.append(record)
                    try:
                        status = classify(opacity, observed, COLOR, 0x173F66, bool(frames))
                    except AssertionError as error:
                        errors.append(str(error)); Gtk.main_quit(); return False
                    record['classification'] = status
                    if status == 'visible': frames.append(observed)
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
                    print(json.dumps(dict(failure=True, kind=kind, mode=mode, iteration=iteration, records=records, screenshot_is_later=True, metadata=context(popup))), flush=True)
                assert not errors, errors
                assert frames and all(value in (0, 1) for value in opacities), opacities
                assert popup.get_position() == (150, 30), popup.get_position()
                print(json.dumps(dict(kind=kind, mode=mode, iteration=iteration, samples=len(frames), records=records, final_metadata=context(popup), ok=True)), flush=True)
                results.append(len(frames))
                # Release the same pointer grab used by the actual calendar.
                from gi.repository import Gdk
                Gdk.Display.get_default().get_default_seat().ungrab()
                popup.destroy()
                while Gtk.events_pending(): Gtk.main_iteration_do(False)
    print(json.dumps(dict(summary=True, cases=len(results), samples=sum(results), failed=0)), flush=True)
finally:
    x.close()
