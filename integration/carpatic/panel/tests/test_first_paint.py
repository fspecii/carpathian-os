#!/usr/bin/env python3
"""Actual GTK draw/first-paint regression on an explicitly private Xvfb.

The synthetic compositor selection exercises GTK's composited branch; X11
opacity is recorded as metadata. It performs no redirection or composition. Real
Xorg/GLX/XRender presentation remains a separate acceptance gate.
"""
import contextlib
import ctypes as c
import datetime as dt
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

if (os.environ.get('CARPATIC_WM_TEST_DISPLAY') != '1'
        or os.environ.get('WAYLAND_DISPLAY')
        or os.environ.get('DISPLAY') in (None, ':0', ':1', ':0.0', ':1.0')):
    raise SystemExit('Explicit private Xvfb display required')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk
from carpatic_panel.kit import Canvas, View, Node, Group, render_surface
from carpatic_panel.flyout_cal import CalView, CalModel
from carpatic_panel.notes import FakeNotes
from carpatic_panel.popup import Popup
from carpatic_panel.theme import Theme


class OpacitySelection:
    def __init__(self):
        self.x = c.CDLL('libX11.so.6')
        declarations = {
            'XOpenDisplay': (c.c_void_p, [c.c_char_p]),
            'XDefaultRootWindow': (c.c_ulong, [c.c_void_p]),
            'XDefaultScreen': (c.c_int, [c.c_void_p]),
            'XInternAtom': (c.c_ulong, [c.c_void_p, c.c_char_p, c.c_int]),
            'XCreateSimpleWindow': (c.c_ulong, [c.c_void_p, c.c_ulong, c.c_int, c.c_int, c.c_uint, c.c_uint, c.c_uint, c.c_ulong, c.c_ulong]),
            'XSetSelectionOwner': (c.c_int, [c.c_void_p, c.c_ulong, c.c_ulong, c.c_ulong]),
            'XGetSelectionOwner': (c.c_ulong, [c.c_void_p, c.c_ulong]),
            'XSync': (c.c_int, [c.c_void_p, c.c_int]),
            'XDestroyWindow': (c.c_int, [c.c_void_p, c.c_ulong]),
            'XCloseDisplay': (c.c_int, [c.c_void_p]),
            'XFree': (c.c_int, [c.c_void_p]),
            'XGetWindowProperty': (c.c_int, [c.c_void_p, c.c_ulong, c.c_ulong, c.c_long, c.c_long, c.c_int, c.c_ulong, c.POINTER(c.c_ulong), c.POINTER(c.c_int), c.POINTER(c.c_ulong), c.POINTER(c.c_ulong), c.POINTER(c.c_void_p)]),
        }
        for name, (result, args) in declarations.items():
            fn = getattr(self.x, name); fn.restype, fn.argtypes = result, args
        self.display = self.x.XOpenDisplay(None)
        assert self.display
        self.root = self.x.XDefaultRootWindow(self.display)
        self.atom = self.x.XInternAtom(self.display, f'_NET_WM_CM_S{self.x.XDefaultScreen(self.display)}'.encode(), 0)
        assert self.x.XGetSelectionOwner(self.display, self.atom) == 0, 'Private fixture already has a compositor'
        self.owner = self.x.XCreateSimpleWindow(self.display, self.root, 0, 0, 1, 1, 0, 0, 0)
        self.x.XSetSelectionOwner(self.display, self.atom, self.owner, 0)
        self.x.XSync(self.display, 0)

    def opacity(self, xid):
        Gdk.Display.get_default().sync()
        atom = self.x.XInternAtom(self.display, b'_NET_WM_WINDOW_OPACITY', 0)
        kind, fmt, count, after, data = c.c_ulong(), c.c_int(), c.c_ulong(), c.c_ulong(), c.c_void_p()
        rc = self.x.XGetWindowProperty(self.display, xid, atom, 0, 1, 0, 6, c.byref(kind), c.byref(fmt), c.byref(count), c.byref(after), c.byref(data))
        assert rc == 0
        try:
            if not count.value: return 0xFFFFFFFF  # absent means fully opaque
            assert fmt.value == 32 and count.value == 1
            return c.cast(data, c.POINTER(c.c_ulong))[0] & 0xFFFFFFFF
        finally:
            if data: self.x.XFree(data)

    def close(self):
        self.x.XSetSelectionOwner(self.display, self.atom, 0, 0)
        self.x.XDestroyWindow(self.display, self.owner)
        self.x.XSync(self.display, 0)
        self.x.XCloseDisplay(self.display)


def pump_until(predicate, seconds=2):
    deadline = time.monotonic()+seconds
    while time.monotonic() < deadline:
        while Gtk.events_pending(): Gtk.main_iteration_do(False)
        if predicate(): return
        time.sleep(.005)
    raise AssertionError('GTK condition did not settle')


def pump_for(seconds):
    deadline = time.monotonic()+seconds
    while time.monotonic() < deadline:
        while Gtk.events_pending(): Gtk.main_iteration_do(False)
        time.sleep(.005)


class FirstPaint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(prefix='carpathian-first-paint-')
        os.environ['XDG_DATA_HOME'] = cls.work.name+'/data'
        os.environ['CARPATIC_CONFIG'] = cls.work.name+'/config'
        Path(os.environ['XDG_DATA_HOME']).mkdir()
        Path(os.environ['CARPATIC_CONFIG']).mkdir()
        cls.selection = OpacitySelection()
        pump_until(lambda: Gdk.Screen.get_default().is_composited())
        cls.errors = []
        cls.original_draw = staticmethod(Canvas.on_draw)
        def observed(canvas, *args):
            try: return cls.original_draw(canvas, *args)
            except Exception as error:
                cls.errors.append(type(error).__name__+': '+str(error))
                raise
        Canvas.on_draw = observed

    @classmethod
    def tearDownClass(cls):
        Canvas.on_draw = cls.original_draw
        cls.selection.close()
        cls.work.cleanup()

    def make_popup(self, view):
        popup = Popup(view, view.theme, (150, 30), slide=False)
        self.addCleanup(popup.destroy)
        self.assertTrue(popup.composited)
        self.assertEqual(popup.get_opacity(), 0)
        return popup

    def test_real_empty_calendar_reference_and_actual_draw(self):
        for height in (520, 720):
            with self.subTest(max_h=height):
                self.errors.clear()
                view = CalView(Theme.from_palette(dict(dark_background='#173f66')),
                               CalModel(today=dt.date(2030, 2, 17), data=os.environ['XDG_DATA_HOME']),
                               FakeNotes([]), look='win', max_h=height)
                surface, _ = render_surface(view)
                self.assertEqual(surface.get_height(), view.size()[1])
                groups = {name: dict(height=g.h, content=g.content_h, max_offset=g.max_offset) for name, g in view.groups.items()}
                self.assertTrue(all(g.max_offset == 0 for g in view.groups.values()))
                popup = self.make_popup(view)
                pump_until(lambda: popup._paint_ready and popup.get_opacity() == 1)
                self.assertTrue(popup.canvas.paint_complete)
                self.assertEqual(self.errors, [])
                self.assertEqual(self.selection.opacity(popup.get_window().get_xid()), 0xFFFFFFFF)
                print(json.dumps(dict(max_h=height, size=view.size(), groups=groups, actual_draw=True,
                                      paint_ready=popup._paint_ready, opacity=popup.get_opacity(),
                                      x11_opacity_property=self.selection.opacity(popup.get_window().get_xid()),
                                      scope='GTK and X11 opacity property; synthetic compositor selection')), flush=True)
                popup.destroy()
                pump_for(.03)

    def test_collapsed_group_preserves_adjacent_and_valid_paint(self):
        import cairo
        class GroupView(View):
            def build(self):
                self.groups={'collapsed':Group(10,10,30,-5,100),
                             'zero-width':Group(10,10,0,30,100),
                             'valid':Group(60,10,30,30,100)}
                def rejected(cr,n,st): raise AssertionError('Collapsed painter was executed')
                def colored(color):
                    def paint(cr,n,st):
                        cr.set_source_rgb(*color);cr.rectangle(n.x,n.y,n.w,n.h);cr.fill()
                    return paint
                return [Node(x=10,y=10,w=30,h=30,group='collapsed',paint=rejected),
                        Node(x=10,y=10,w=30,h=30,group='zero-width',paint=rejected),
                        Node(x=60,y=10,w=30,h=30,group='valid',paint=colored((0,1,0))),
                        Node(x=110,y=10,w=30,h=30,paint=colored((1,0,0)))]
        view=GroupView(Theme.from_palette(dict(dark_background='#173f66')))
        view.W,view.H=180,100
        surface,_=render_surface(view)
        surface.flush()
        import struct
        data=surface.get_data();stride=surface.get_stride()
        def rgb(x,y): return struct.unpack_from('=I',data,y*stride+x*4)[0]&0xFFFFFF
        self.assertEqual(rgb(70,20),0x00FF00,'Valid clipped node still paints')
        self.assertEqual(rgb(120,20),0xFF0000,'Collapsed group must restore Cairo state before adjacent node')
        self.assertEqual(rgb(20,20),0x173F66,'Collapsed groups leave the frame untouched')
        self.assertEqual(view.groups['collapsed'].max_offset,0)
        self.assertEqual(view.groups['zero-width'].max_offset,0)
        self.assertEqual(view.groups['valid'].max_offset,70)

    def test_failed_actual_draw_never_reveals(self):
        class BrokenView(View):
            def paint_frame(self, cr, width, height, alpha=1):
                raise RuntimeError('intentional first-paint negative control')
        self.errors.clear()
        view = BrokenView(Theme.from_palette(dict(dark_background='#173f66')))
        view.W, view.H = 360, 400
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            popup = self.make_popup(view)
            after_draw = []
            popup.canvas.connect_after('draw', lambda *_: (after_draw.append(True), False)[1])
            pump_until(lambda: bool(after_draw))
            pump_for(.12)
        self.assertTrue(self.errors, 'Negative must actually execute the failing content painter')
        self.assertTrue(all('intentional first-paint negative control' in error for error in self.errors))
        self.assertFalse(popup.canvas.paint_complete)
        self.assertFalse(popup._paint_ready, 'draw-after must not certify failed content')
        self.assertEqual(popup.get_opacity(), 0)
        print(json.dumps(dict(negative=True, actual_draw_errors=self.errors, after_draw_calls=len(after_draw),
                              paint_ready=popup._paint_ready, opacity=popup.get_opacity(),
                              x11_opacity_property=self.selection.opacity(popup.get_window().get_xid()),
                              traceback_captured='intentional first-paint negative control' in stderr.getvalue())), flush=True)
        reveals=[]
        original_reveal=popup._reveal
        def revealed():
            reveals.append(True)
            return original_reveal()
        popup._reveal=revealed
        view.paint_frame=View.paint_frame.__get__(view,type(view))
        self.errors.clear()
        popup.canvas.queue_draw()
        pump_until(lambda: popup._paint_ready and popup.get_opacity()==1)
        popup.canvas.queue_draw()
        pump_for(.08)
        self.assertTrue(popup.canvas.paint_complete)
        self.assertEqual(self.errors,[])
        self.assertEqual(len(reveals),1,'Repair must reveal once, without remaining hidden or rescheduling on each redraw')
        print(json.dumps(dict(repaired=True,reveals=len(reveals),paint_ready=popup._paint_ready,opacity=popup.get_opacity())),flush=True)



if __name__ == '__main__':
    unittest.main()
