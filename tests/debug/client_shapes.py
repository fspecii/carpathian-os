#!/usr/bin/env python3
"""Owned real-Xorg client shape pixel/input regression; no performance claim.

Run only on the explicitly marked isolated Alpine :0 fixture. Exercises pre-map
bounding/input holes, dynamic input-only and visual holes, shape removal and
native-caption drag. Uses actual XTest input and records the receiving window.
Preferences are untouched; owned windows are destroyed and pointer restored.
"""
import argparse
import ctypes as c
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rendering import Display, COLOR
from frame_surface import guard, bind, wait_for_frame, require_viewable, geometry, drawable_geometry, Handler, XErrorEvent

BACKDROP = 0xdd22cc
BOUNDING, INPUT = 0, 2  # X11/extensions/shapeconst.h


class Rectangle(c.Structure):
    _fields_ = [('x', c.c_short), ('y', c.c_short), ('width', c.c_ushort), ('height', c.c_ushort)]


class WindowChanges(c.Structure):
    _fields_ = [('x', c.c_int), ('y', c.c_int), ('width', c.c_int), ('height', c.c_int),
                ('border_width', c.c_int), ('sibling', c.c_ulong), ('stack_mode', c.c_int)]


class ButtonEvent(c.Structure):
    _fields_ = [('type', c.c_int), ('serial', c.c_ulong), ('send_event', c.c_int),
                ('display', c.c_void_p), ('window', c.c_ulong), ('root', c.c_ulong),
                ('subwindow', c.c_ulong), ('time', c.c_ulong), ('x', c.c_int),
                ('y', c.c_int), ('x_root', c.c_int), ('y_root', c.c_int),
                ('state', c.c_uint), ('button', c.c_uint), ('same_screen', c.c_int)]


class Event(c.Union):
    _fields_ = [('type', c.c_int), ('button', ButtonEvent), ('pad', c.c_long * 24)]


class Probe:
    def __init__(self, x):
        self.x = x
        self.errors = []
        self.pressed = False
        self.pointer = None
        self.content_size = (420, 280)
        self.shape = c.CDLL('libXext.so.6')
        self.xtest = c.CDLL('libXtst.so.6')
        ptr, win, integer = c.c_void_p, c.c_ulong, c.c_int
        entries = (
            (x.x, 'XSelectInput', integer, [ptr, win, c.c_long]),
            (x.x, 'XConfigureWindow', integer, [ptr, win, c.c_uint, c.POINTER(WindowChanges)]),
            (x.x, 'XPending', integer, [ptr]),
            (x.x, 'XNextEvent', integer, [ptr, c.POINTER(Event)]),
            (x.x, 'XTranslateCoordinates', integer, [ptr, win, win, integer, integer,
                                                     c.POINTER(integer), c.POINTER(integer), c.POINTER(win)]),
            (x.x, 'XQueryPointer', integer, [ptr, win, c.POINTER(win), c.POINTER(win),
                                            c.POINTER(integer), c.POINTER(integer), c.POINTER(integer),
                                            c.POINTER(integer), c.POINTER(c.c_uint)]),
            (self.shape, 'XShapeQueryVersion', integer, [ptr, c.POINTER(integer), c.POINTER(integer)]),
            (self.shape, 'XShapeCombineRectangles', None, [ptr, win, integer, integer, integer,
                                                         c.POINTER(Rectangle), integer, integer, integer]),
            (self.shape, 'XShapeCombineMask', None, [ptr, win, integer, integer, integer, win, integer]),
            (self.xtest, 'XTestQueryExtension', integer, [ptr, c.POINTER(integer), c.POINTER(integer),
                                                         c.POINTER(integer), c.POINTER(integer)]),
            (self.xtest, 'XTestFakeMotionEvent', integer, [ptr, integer, integer, integer, c.c_ulong]),
            (self.xtest, 'XTestFakeButtonEvent', integer, [ptr, c.c_uint, integer, c.c_ulong]))
        for lib, name, result, arguments in entries:
            fn = getattr(lib, name)
            fn.restype, fn.argtypes = result, arguments
        def error(_display, event):
            value = c.cast(event, c.POINTER(XErrorEvent)).contents
            self.errors.append(dict(code=value.error_code, request=value.request_code,
                                    minor=value.minor_code, resource=f'{value.resourceid:#x}'))
            return 0
        self.handler = Handler(error)
        self.previous = x.x.XSetErrorHandler(self.handler)
        try:
            major, minor, event, error_base = integer(), integer(), integer(), integer()
            if not self.shape.XShapeQueryVersion(x.handle, c.byref(major), c.byref(minor)):
                raise RuntimeError('XShape extension unavailable')
            if (major.value, minor.value) < (1, 1):
                raise RuntimeError('Shape 1.1 input regions required')
            if not self.xtest.XTestQueryExtension(x.handle, c.byref(event), c.byref(error_base),
                                                c.byref(major), c.byref(minor)):
                raise RuntimeError('XTest extension unavailable')
            root, child, rx, ry, wx, wy, mask = win(), win(), integer(), integer(), integer(), integer(), c.c_uint()
            if not x.x.XQueryPointer(x.handle, x.root, c.byref(root), c.byref(child),
                                     c.byref(rx), c.byref(ry), c.byref(wx), c.byref(wy), c.byref(mask)):
                raise RuntimeError('Cannot save isolated pointer position')
            if mask.value & (0x100 | 0x200 | 0x400 | 0x800 | 0x1000):
                raise RuntimeError('Pointer button already held; refuse synthesized input')
            self.pointer = (rx.value, ry.value)
            self.check_errors()
        except BaseException:
            x.x.XSetErrorHandler(c.cast(self.previous, Handler))
            raise

    def check_errors(self):
        self.x.sync()
        if self.errors:
            raise RuntimeError(f'X11 errors: {self.errors}')

    def shape_ring(self, client, kind, hole_x):
        width, height = self.content_size
        if not 0 < hole_x < width - 40 or height <= 100:
            raise RuntimeError(f'Hole does not fit current client content {width}x{height}')
        rectangles = (Rectangle * 4)(Rectangle(0, 0, width, 60), Rectangle(0, 60, hole_x, 40),
                                      Rectangle(hole_x + 40, 60, width - hole_x - 40, 40),
                                      Rectangle(0, 100, width, height - 100))
        self.shape.XShapeCombineRectangles(self.x.handle, client, kind, 0, 0, rectangles, 4, 0, 0)
        self.check_errors()

    def remove_shape(self, client, kind):
        self.shape.XShapeCombineMask(self.x.handle, client, kind, 0, 0, 0, 0)
        self.check_errors()

    def position(self, window, px, py):
        rx, ry, child = c.c_int(), c.c_int(), c.c_ulong()
        if not self.x.x.XTranslateCoordinates(self.x.handle, window, self.x.root, px, py,
                                              c.byref(rx), c.byref(ry), c.byref(child)):
            raise RuntimeError('Cannot translate fixture point to root')
        return rx.value, ry.value

    def motion(self, px, py):
        if not self.xtest.XTestFakeMotionEvent(self.x.handle, 0, px, py, 0):
            raise RuntimeError('XTest pointer motion rejected')
        self.check_errors()

    def button(self, pressed):
        if not self.xtest.XTestFakeButtonEvent(self.x.handle, 1, int(pressed), 0):
            raise RuntimeError('XTest button event rejected')
        self.pressed = pressed
        self.check_errors()

    def events(self):
        received = []
        while self.x.x.XPending(self.x.handle):
            event = Event()
            self.x.x.XNextEvent(self.x.handle, c.byref(event))
            if event.type == 4:
                received.append(event.button.window)
        return received

    def click(self, client, receiver, px, py):
        self.events()
        self.motion(*self.position(client, px, py))
        self.button(True)
        self.button(False)
        until = time.monotonic() + .25
        received = []
        while time.monotonic() < until:
            received.extend(self.events())
            time.sleep(.005)
        return dict(client=received.count(client), receiver=received.count(receiver),
                    other=[f'{window:#x}' for window in received if window not in (client, receiver)])

    def pixel(self, client, px, py):
        rx, ry = self.position(client, px, py)
        image = self.x.x.XGetImage(self.x.handle, self.x.root, rx, ry, 1, 1, 0xffffffff, 2)
        if not image:
            self.check_errors()
            raise RuntimeError('Root pixel capture failed')
        try:
            self.check_errors()
            return self.x.x.XGetPixel(image, 0, 0) & 0xffffff
        finally:
            self.x.x.XDestroyImage(image)

    def cleanup_input(self):
        if self.pressed:
            self.xtest.XTestFakeButtonEvent(self.x.handle, 1, 0, 0)
            self.pressed = False
        if self.pointer is not None:
            self.xtest.XTestFakeMotionEvent(self.x.handle, 0, *self.pointer, 0)
        self.x.sync()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Optional JSON evidence file')
    args = parser.parse_args()
    guard()  # before opening display or loading XTest
    x = Display()
    bind(x)
    probe = None
    checks = []
    def record(label, yes, **evidence):
        result = dict(check=label, passed=bool(yes), **evidence)
        checks.append(result)
        print(json.dumps(result), flush=True)
    try:
        probe = Probe(x)
        width, height, _ = drawable_geometry(x, x.root)
        receiver = x.create('Owned shape-hole receiver', BACKDROP, width, height, override=True)
        # Override-redirect backdrop must cover root, not the create helper's (100,100).
        x.x.XMoveWindow.restype, x.x.XMoveWindow.argtypes = c.c_int, [c.c_void_p, c.c_ulong, c.c_int, c.c_int]
        x.x.XMoveWindow(x.handle, receiver, 0, 0)
        x.x.XSelectInput(x.handle, receiver, (1 << 2) | (1 << 3))
        x.x.XMapWindow(x.handle, receiver)
        client = x.create('Owned native shaped dialog', COLOR, 420, 280)
        x.x.XSelectInput(x.handle, client, (1 << 2) | (1 << 3))
        for kind in (BOUNDING, INPUT):
            probe.shape_ring(client, kind, 60)
        x.x.XMapWindow(x.handle, client)
        x.message(client, '_NET_ACTIVE_WINDOW', [1, 0, 0, 0, 0])
        frame, caption = wait_for_frame(x, client)
        # Put our backdrop below the frame but ABOVE a real desktop window;
        # lowering to root bottom would let xfdesktop hide the receiver.
        changes = WindowChanges(sibling=frame, stack_mode=1)
        x.x.XConfigureWindow(x.handle, receiver, (1 << 5) | (1 << 6), c.byref(changes))
        probe.check_errors()
        time.sleep(.5)
        require_viewable(client, frame, caption, receiver)
        cg = geometry(client)
        # Requested dimensions are the initial outer allocation; the WM may
        # reserve native caption height within it (420x248 content is valid).
        # Keep the pre-map shapes untouched for the first checks. Future shape
        # updates use the measured content extent instead of the outer request.
        if cg['WIDTH'] <= 240 or cg['HEIGHT'] <= 180:
            raise RuntimeError(f'Client content cannot cover hole/control points: {cg}')
        probe.content_size = (cg['WIDTH'], cg['HEIGHT'])
        def click(label, px, py, target):
            received = probe.click(client, receiver, px, py)
            record(label, received[target] == 1 and received['receiver' if target == 'client' else 'client'] == 0
                   and not received['other'], received=received, point=[px, py])
        def pixel(label, px, py, expected):
            actual = probe.pixel(client, px, py)
            record(label, actual == expected, actual=f'{actual:06x}', expected=f'{expected:06x}', point=[px, py])
        pixel('pre-map visual hole exposes owned receiver', 80, 80, BACKDROP)
        click('pre-map input hole click-through', 80, 80, 'receiver')
        pixel('solid body visual positive control', 200, 150, COLOR)
        click('solid body input positive control', 200, 150, 'client')
        probe.remove_shape(client, BOUNDING)
        probe.shape_ring(client, INPUT, 140)
        time.sleep(.4)
        pixel('input-only hole retains visible body', 160, 80, COLOR)
        click('dynamic input-only hole click-through', 160, 80, 'receiver')
        click('old hole input restored', 80, 80, 'client')
        probe.shape_ring(client, BOUNDING, 140)
        time.sleep(.4)
        pixel('dynamic visual hole exposes owned receiver', 160, 80, BACKDROP)
        click('dynamic visual hole click-through', 160, 80, 'receiver')
        for kind in (BOUNDING, INPUT):
            probe.remove_shape(client, kind)
        time.sleep(.4)
        pixel('removed visual hole restores body', 160, 80, COLOR)
        click('removed input hole restores client receiver', 160, 80, 'client')
        before = geometry(frame)
        title = geometry(caption)
        start = probe.position(caption, title['WIDTH'] // 2, title['HEIGHT'] // 2)
        probe.motion(*start)
        probe.button(True)
        time.sleep(.1)
        probe.motion(start[0] + 30, start[1] + 20)
        time.sleep(.1)
        probe.button(False)
        time.sleep(.4)
        after = geometry(frame)
        record('native caption drag remains functional',
               (before['X'], before['Y']) != (after['X'], after['Y']), before=before, after=after)
        probe.check_errors()
        result = dict(guarded=True, correctness_only=True, content_geometry=cg, checks=checks,
                      summary=dict(passed=all(item['passed'] for item in checks), cases=len(checks)))
        if args.output:
            args.output.write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result['summary']), flush=True)
        return 0 if result['summary']['passed'] else 1
    finally:
        if probe is not None:
            try:
                probe.cleanup_input()
            finally:
                try:
                    x.close()
                finally:
                    x.x.XSetErrorHandler(c.cast(probe.previous, Handler))
        else:
            x.close()


if __name__ == '__main__':
    raise SystemExit(main())
