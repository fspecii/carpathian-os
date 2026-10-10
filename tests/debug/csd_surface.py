#!/usr/bin/env python3
"""Actual GTK CSD surface correctness probe; owned isolated Alpine Xorg only.

Settled root pixels and real XTest clicks, not presentation/FPS evidence.
The explicit property cycle is a WM-contract diagnostic; it is not a claim that
GTK naturally changes its decoration implementation that way at runtime.
"""
import ctypes as C
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time

if (os.environ.get('CARPATIC_VM_TEST') != '1' or not Path('/etc/alpine-release').is_file()
        or os.environ.get('DISPLAY') != ':0' or 'WAYLAND_DISPLAY' in os.environ):
    raise SystemExit('Explicit isolated Alpine Xorg :0 only')
if subprocess.run(['pgrep', '-x', 'i3lock'], stdout=subprocess.DEVNULL).returncode == 0:
    raise SystemExit('Fixture locked')
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk
from rendering import Display, command

x = Display()
x.x.XQueryTree.argtypes = [C.c_void_p, C.c_ulong, C.POINTER(C.c_ulong), C.POINTER(C.c_ulong), C.POINTER(C.POINTER(C.c_ulong)), C.POINTER(C.c_uint)]
x.x.XQueryTree.restype = C.c_int
x.x.XFree.argtypes = [C.c_void_p]
records = []
windows = []
counts = {'backdrop': 0, 'body': 0}

def pump(seconds=.5):
    until = time.monotonic()+seconds
    while time.monotonic() < until:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(.005)

def children_of(wid):
    root, par, children, n = C.c_ulong(), C.c_ulong(), C.POINTER(C.c_ulong)(), C.c_uint()
    if not x.x.XQueryTree(x.handle, wid, C.byref(root), C.byref(par), C.byref(children), C.byref(n)):
        raise RuntimeError("Cannot query tree")
    try: return [children[i] for i in range(n.value)]
    finally:
        if children: x.x.XFree(children)

def numbers(text):
    return [int(v, 0) for v in re.findall(r"0x[0-9a-fA-F]+|[0-9]+", text.split("=", 1)[1])] if "=" in text else []

def assert_caption(expect_native):
    ids = children_of(x.root)
    par = parent(wid)
    if par != x.root: ids += children_of(par)
    visible = []
    for candidate in ids:
        association = prop(candidate, "_CARPATIC_CLIENT")
        target = re.search(r"window id # (0x[0-9a-fA-F]+)", association)
        if target and int(target.group(1), 16) == wid:
            if "Map State: IsViewable" in command("xwininfo", "-id", str(candidate)):
                visible.append(candidate)
    assert len(visible) == (1 if expect_native else 0), (expect_native, visible)
    assert header.get_mapped() and app.get_titlebar() == header, "GTK-owned header must survive"

def assert_csd_border(record):
    assert numbers(record["wm_extents"]) == [0, 0, 0, 0], ("CSD must not get native border extents", record)
    assert record["x_border_width"] == 0, ("CSD must not get opaque X border", record)
    assert record["outside_left_pixel"] == "0x7090d", ("CSD outside edge must expose backdrop", record)

def parent(wid):
    root, par, children, n = C.c_ulong(), C.c_ulong(), C.POINTER(C.c_ulong)(), C.c_uint()
    if not x.x.XQueryTree(x.handle, wid, C.byref(root), C.byref(par), C.byref(children), C.byref(n)):
        raise RuntimeError('Cannot query client parent')
    if children: x.x.XFree(children)
    return par.value

def prop(wid, name):
    return command('xprop', '-id', str(wid), name)

def pixels(points):
    result = []
    for px, py in points:
        image = x.x.XGetImage(x.handle, x.root, px, py, 1, 1, 0xFFFFFFFF, 2)
        if not image: raise RuntimeError('Root capture unavailable')
        try: result.append(x.x.XGetPixel(image, 0, 0) & 0xFFFFFF)
        finally: x.x.XDestroyImage(image)
    return result

def click(px, py, receiver):
    before = counts.copy()
    command('xdotool', 'mousemove', '--sync', str(px), str(py), 'click', '1')
    pump(.2)
    assert counts[receiver] > before[receiver], (receiver, before, counts)

def snapshot(phase):
    origin = app.get_window().get_origin()
    # PyGObject returns (success, x, y) on GTK3.
    ox, oy = origin[-2:]
    width, height = app.get_window().get_width(), app.get_window().get_height()
    corner_points = [(ox+1, oy+1), (ox+width-2, oy+1), (ox+1, oy+height-2), (ox+width-2, oy+height-2)]
    body_x, body_y = body.translate_coordinates(app, body.get_allocated_width()//2, body.get_allocated_height()//2)
    body_pixel = pixels([(ox+body_x, oy+body_y)])[0]
    assert body_pixel == 0x25A9DF, (phase, hex(body_pixel))
    click(ox+body_x, oy+body_y, 'body')
    record = {'phase': phase, 'client': hex(wid), 'parent': hex(parent(wid)), 'origin': [ox, oy], 'size': [width, height],
              'gtk_extents': prop(wid, '_GTK_FRAME_EXTENTS'), 'wm_extents': prop(wid, '_NET_FRAME_EXTENTS'),
              'body_pixel': hex(body_pixel), 'corner_pixels': [hex(p) for p in pixels(corner_points)],
              'outside_left_pixel': hex(pixels([(ox-1, oy+height//2)])[0]),
              'x_border_width': int(re.search(r'Border width:\s*(\d+)', command('xwininfo', '-id', str(wid))).group(1)),
              'click_counts': counts.copy()}
    records.append(record)
    print(json.dumps(record), flush=True)
    return record

try:
    backdrop = Gtk.Window(type=Gtk.WindowType.POPUP)
    windows.append(backdrop)
    backdrop.set_default_size(1100, 650)
    backdrop.move(100, 70)
    receiver = Gtk.DrawingArea()
    receiver.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
    receiver.connect('draw', lambda widget, cr: (cr.set_source_rgb(7/255, 9/255, 13/255), cr.paint(), False)[-1])
    receiver.connect('button-press-event', lambda *_: counts.__setitem__('backdrop', counts['backdrop']+1) or False)
    backdrop.add(receiver)
    backdrop.show_all()
    pump()
    app = Gtk.Window()
    windows.append(app)
    visual = app.get_screen().get_rgba_visual()
    assert visual is not None and app.get_screen().is_composited(), 'Real RGBA compositor required'
    app.set_visual(visual)
    app.set_type_hint(Gdk.WindowTypeHint.DIALOG)
    app.set_title('Owned GTK CSD surface')
    app.set_default_size(420, 280)
    app.get_style_context().add_class('csd-surface-fixture')
    header = Gtk.HeaderBar(title='CSD owns this caption', show_close_button=True)
    app.set_titlebar(header)
    css = Gtk.CssProvider()
    css.load_from_data(b'window.csd-surface-fixture {background-color:transparent;} window.csd-surface-fixture decoration {border-radius:12px;box-shadow:0 5px 10px rgba(0,0,0,.3);} headerbar {background-image:none;background-color:#203040;border-radius:12px 12px 0 0;}')
    Gtk.StyleContext.add_provider_for_screen(app.get_screen(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    body = Gtk.DrawingArea()
    body.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
    body.connect('draw', lambda widget, cr: (cr.set_source_rgb(37/255, 169/255, 223/255), cr.paint(), False)[-1])
    body.connect('button-press-event', lambda *_: counts.__setitem__('body', counts['body']+1) or False)
    app.add(body)
    app.show_all()
    pump(.8)
    wid = app.get_window().get_xid()
    command('xdotool', 'windowmove', str(wid), '330', '220')
    pump(.6)
    initial = snapshot('initial-real-gtk-csd')
    assert parent(wid) == x.root, 'Initial CSD should retain its own root surface'
    assert_caption(False)
    gtk_extents = numbers(initial['gtk_extents'])
    real_shadow_extents = len(gtk_extents) == 4 and any(value > 0 for value in gtk_extents)
    mode = 'shadow-csd' if real_shadow_extents else 'solid-csd'
    print(json.dumps({'gtk_mode': mode, 'transparent_corners_qualified': bool(real_shadow_extents)}), flush=True)
    assert_csd_border(initial)
    if real_shadow_extents:
        assert initial['corner_pixels'][0] == '0x7090d', initial
        ox, oy = initial['origin']
        click(ox+1, oy+1, 'backdrop')
    original_extents = initial['gtk_extents'].split('=', 1)[1].strip() if gtk_extents else None
    original_motif = prop(wid, '_MOTIF_WM_HINTS')
    assert numbers(original_motif), 'Actual GTK solid-CSD must provide Motif decoration hints'
    command('xprop', '-id', str(wid), '-remove', '_GTK_FRAME_EXTENTS', '-remove', '_MOTIF_WM_HINTS')
    pump(.6)
    assert parent(wid) != x.root, 'Forced native contract should create one common frame'
    assert_caption(True)
    snapshot('forced-property-native-contract')
    if original_extents is not None:
        command('xprop', '-id', str(wid), '-f', '_GTK_FRAME_EXTENTS', '32c', '-set', '_GTK_FRAME_EXTENTS', original_extents)
    command('xprop', '-id', str(wid), '-f', '_MOTIF_WM_HINTS', '32c', '-set', '_MOTIF_WM_HINTS', original_motif.split('=', 1)[1].strip())
    pump(.6)
    restored = snapshot('restored-gtk-csd-property')
    assert restored['parent'] != hex(x.root), 'Existing frame identity must survive CSD restoration'
    # GTK remains responsible for its own client mask throughout the diagnostic.
    assert_caption(False)
    assert_csd_border(restored)
    if real_shadow_extents:
        assert restored['corner_pixels'][0] == '0x7090d', restored
    print(json.dumps({'summary': True, 'phases': len(records), 'passed': True,
                      'gtk_mode': mode, 'transparent_corners_qualified': bool(real_shadow_extents),
                      'scope': 'settled real GTK pixels/input, zero native CSD border, preserved app header; explicit property cycle, shadow checks only with actual GTK extents'}), flush=True)
finally:
    for window in reversed(windows):
        window.destroy()
    pump(.1)
    if 'css' in globals(): Gtk.StyleContext.remove_provider_for_screen(Gdk.Screen.get_default(), css)
    x.close()
