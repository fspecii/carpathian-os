#!/usr/bin/env python3
"""Named-frame surface probe for the native reparenting frame on the Alpine Xorg fixture.

Creates an owned cyan dialog, waits for the native frame to reparent it, then names
the FRAME pixmap via XComposite (never redirecting any window) and proves the
composited surface holds the cyan body plus a distinct titlebar that matches the
title child's own pixels. Pixel correctness only; no presentation timing/FPS claims.
No preference, userpref or compositor changes; fixture windows are owned and closed.
"""
import argparse
import ctypes as c
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rendering import Display, COLOR, WindowAttributes, command

BAD_MATCH = 8
CM_ATOM = '_NET_WM_CM_S0'  # compositor manager selection for screen 0


class VisualInfo(c.Structure):
    _fields_ = [('visual', c.c_void_p), ('visualid', c.c_ulong),
                ('screen', c.c_int), ('depth', c.c_int), ('visual_class', c.c_int),
                ('red_mask', c.c_ulong), ('green_mask', c.c_ulong),
                ('blue_mask', c.c_ulong), ('colormap_size', c.c_int),
                ('bits_per_rgb', c.c_int)]


class DirectFormat(c.Structure):
    _fields_ = [(name, c.c_short) for name in
                ('red', 'redMask', 'green', 'greenMask', 'blue', 'blueMask', 'alpha', 'alphaMask')]


class PictureFormat(c.Structure):
    _fields_ = [('id', c.c_ulong), ('type', c.c_int), ('depth', c.c_int),
                ('direct', DirectFormat), ('colormap', c.c_ulong)]


def create_argb(x):
    """Owned depth-32 TrueColor client, with XRender-verified ARGB channel layout."""
    ptr, window = c.c_void_p, c.c_ulong
    signatures = (
        ('XMatchVisualInfo', c.c_int, [ptr, c.c_int, c.c_int, c.c_int, c.POINTER(VisualInfo)]),
        ('XCreateColormap', window, [ptr, window, ptr, c.c_int]),
        ('XFreeColormap', c.c_int, [ptr, window]),
        ('XCreateWindow', window, [ptr, window, c.c_int, c.c_int, c.c_uint, c.c_uint,
                                  c.c_uint, c.c_int, c.c_uint, ptr, c.c_ulong,
                                  c.POINTER(WindowAttributes)]))
    for name, result, arguments in signatures:
        fn = getattr(x.x, name)
        fn.restype, fn.argtypes = result, arguments
    visual = VisualInfo()
    if not x.x.XMatchVisualInfo(x.handle, 0, 32, 4, c.byref(visual)):
        raise RuntimeError('No depth-32 TrueColor visual available')
    render = c.CDLL('libXrender.so.1')
    render.XRenderFindVisualFormat.restype = c.POINTER(PictureFormat)
    render.XRenderFindVisualFormat.argtypes = [ptr, ptr]
    found = render.XRenderFindVisualFormat(x.handle, visual.visual)
    if not found:
        raise RuntimeError('Depth-32 visual has no XRender format')
    direct = found.contents.direct
    if (found.contents.depth != 32 or found.contents.type != 1
            or tuple(getattr(direct, name) for name in
                     ('red', 'redMask', 'green', 'greenMask', 'blue', 'blueMask', 'alpha', 'alphaMask'))
            != (16, 255, 8, 255, 0, 255, 24, 255)):
        raise RuntimeError('Depth-32 visual is not the verified A8R8G8B8 format')
    colormap = x.x.XCreateColormap(x.handle, x.root, visual.visual, 0)
    try:
        attributes = WindowAttributes(background_pixel=0x8025a9df, border_pixel=0, colormap=colormap)
        client = x.x.XCreateWindow(x.handle, x.root, 100, 100, 420, 280, 0,
                                  32, 1, visual.visual, (1 << 1) | (1 << 3) | (1 << 13),
                                  c.byref(attributes))
        if not client:
            raise RuntimeError('ARGB fixture creation returned zero')
        x.windows.append(client)
        kind = c.c_ulong(x.atom('_NET_WM_WINDOW_TYPE_DIALOG'))
        x.x.XChangeProperty(x.handle, client, x.atom('_NET_WM_WINDOW_TYPE'),
                            4, 32, 0, c.byref(kind), 1)
        x.x.XStoreName(x.handle, client, b'Carpatic ARGB frame-surface probe')
        x.sync()
        return client, colormap
    except BaseException:
        x.x.XFreeColormap(x.handle, colormap)
        raise


class XErrorEvent(c.Structure):
    _fields_ = [('type', c.c_int), ('display', c.c_void_p), ('resourceid', c.c_ulong),
                ('serial', c.c_ulong), ('error_code', c.c_ubyte),
                ('request_code', c.c_ubyte), ('minor_code', c.c_ubyte)]


Handler = c.CFUNCTYPE(c.c_int, c.c_void_p, c.c_void_p)
HANDLER = Handler(lambda display, event: _record(event))
errors = []


def _record(event):  # nonzero return suppresses Xlib's default abort
    if event:
        errors.append(c.cast(event, c.POINTER(XErrorEvent)).contents.error_code)
    return 1


def guard():
    if (os.environ.get('CARPATIC_VM_TEST') != '1' or os.environ.get('DISPLAY') != ':0'
            or 'WAYLAND_DISPLAY' in os.environ or not Path('/etc/alpine-release').exists()):
        raise RuntimeError('Use only the explicitly marked isolated Alpine Xorg :0 fixture')
    for locker in ('i3lock', 'slock'):
        if subprocess.run(['pgrep', '-x', locker], stdout=subprocess.DEVNULL, timeout=3).returncode == 0:
            raise RuntimeError('Fixture is screen-locked; refuse to probe pixels')


def bind(x):
    window, integer = c.c_ulong, c.c_int
    for name, result, args in (
            ('XQueryTree', integer, [c.c_void_p, window, c.POINTER(window), c.POINTER(window),
                                     c.POINTER(c.POINTER(window)), c.POINTER(c.c_uint)]),
            ('XFree', integer, [c.c_void_p]),
            ('XGetGeometry', integer, [c.c_void_p, window, c.POINTER(window), c.POINTER(integer),
                                       c.POINTER(integer), c.POINTER(c.c_uint), c.POINTER(c.c_uint),
                                       c.POINTER(c.c_uint), c.POINTER(c.c_uint)]),
            ('XGetSelectionOwner', window, [c.c_void_p, window]),
            ('XSetErrorHandler', c.c_void_p, [Handler]),
            ('XFreePixmap', integer, [c.c_void_p, window])):
        fn = getattr(x.x, name)
        fn.restype, fn.argtypes = result, args


class Composite:
    def __init__(self, x):
        self.lib = c.CDLL('libXcomposite.so.1')
        self.lib.XCompositeQueryExtension.restype = c.c_int
        self.lib.XCompositeQueryExtension.argtypes = [c.c_void_p, c.POINTER(c.c_int), c.POINTER(c.c_int)]
        self.lib.XCompositeQueryVersion.restype = c.c_int
        self.lib.XCompositeQueryVersion.argtypes = [c.c_void_p, c.POINTER(c.c_int), c.POINTER(c.c_int)]
        self.lib.XCompositeNameWindowPixmap.restype = c.c_ulong
        self.lib.XCompositeNameWindowPixmap.argtypes = [c.c_void_p, c.c_ulong]
        base, error = c.c_int(), c.c_int()
        if not self.lib.XCompositeQueryExtension(x.handle, c.byref(base), c.byref(error)):
            raise RuntimeError('XComposite extension is unavailable')
        major, minor = c.c_int(), c.c_int()
        self.lib.XCompositeQueryVersion(x.handle, c.byref(major), c.byref(minor))
        self.version = (major.value, minor.value)
        if not x.x.XGetSelectionOwner(x.handle, x.atom(CM_ATOM)):
            raise RuntimeError('No compositor owns _NET_WM_CM_S0; refusing to name pixmaps')

    def name(self, x, window):
        return self.lib.XCompositeNameWindowPixmap(x.handle, window)


def children_of(x, w):
    root, parent, kids, count = c.c_ulong(), c.c_ulong(), c.POINTER(c.c_ulong)(), c.c_uint()
    if not x.x.XQueryTree(x.handle, w, c.byref(root), c.byref(parent), c.byref(kids), c.byref(count)):
        raise RuntimeError(f'XQueryTree failed for {hex(w)}')
    result = (root.value, parent.value, [kids[i] for i in range(count.value)])
    if kids:
        x.x.XFree(kids)
    return result


def xprop_value(output, name):
    for line in output.splitlines():
        if line.startswith(name):
            return (line.partition('=')[2] if '=' in line else line.partition(':')[2]).strip()
    return ''


def title_sibling(x, frame, client):
    root, frame_parent, kids = children_of(x, frame)
    if frame_parent != root or client not in kids:
        return None
    for kid in kids:
        if kid == client:
            continue
        out = command('xprop', '-id', hex(kid), '_CARPATIC_CLIENT', '_CARPATIC_BUTTONS')
        ids, buttons = xprop_value(out, '_CARPATIC_CLIENT'), xprop_value(out, '_CARPATIC_BUTTONS')
        if re.search(r'0x[0-9a-fA-F]+', ids) and int(re.search(r'0x[0-9a-fA-F]+', ids).group(), 16) == client:
            if buttons:
                return kid
    return None


def wait_for_frame(x, client, deadline=4.0):
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        root, parent, _ = children_of(x, client)
        if parent not in (0, root):
            title = title_sibling(x, parent, client)
            if title:
                return parent, title
        time.sleep(.05)
    raise RuntimeError('Frame reparenting plus _CARPATIC_CLIENT/_CARPATIC_BUTTONS title association not seen within 4s')


def require_viewable(*windows):
    for w in windows:
        if 'Map State: IsViewable' not in command('xwininfo', '-id', str(w)):
            raise RuntimeError(f'Window {hex(w)} is not viewable')


def geometry(w):
    raw = command('xdotool', 'getwindowgeometry', '--shell', str(w))
    found = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
    return {key: int(found[key]) for key in ('X', 'Y', 'WIDTH', 'HEIGHT')}


def drawable_geometry(x, d):
    root, px, py = c.c_ulong(), c.c_int(), c.c_int()
    pw, ph, border, depth = c.c_uint(), c.c_uint(), c.c_uint(), c.c_uint()
    if not x.x.XGetGeometry(x.handle, d, c.byref(root), c.byref(px), c.byref(py),
                            c.byref(pw), c.byref(ph), c.byref(border), c.byref(depth)):
        raise RuntimeError('XGetGeometry failed')
    return pw.value, ph.value, depth.value


def capture(x, drawable, width, height):
    image = x.x.XGetImage(x.handle, drawable, 0, 0, width, height, 0xFFFFFFFF, 2)
    if not image:
        raise RuntimeError(f'Cannot capture drawable {hex(drawable)}')
    return image


def pixel(x, image, px, py):
    return x.x.XGetPixel(image, px, py) & 0xFFFFFF


def distinct_rows(x, image, x0, x1, y0, y1, body):
    """Rows whose sampled pixels are neither the body colour nor black (uninitialised)."""
    step = max(1, (x1 - x0) // 24)
    return [y for y in range(y0, y1)
            if any(pixel(x, image, px, y) not in (body, 0) for px in range(x0, x1, step))]


def write_ppm(path, x, image, width, height):
    rows = []
    for y in range(height):
        row = bytearray()
        for px in range(width):
            v = pixel(x, image, px, y)
            row += bytes((v >> 16 & 255, v >> 8 & 255, v & 255))
        rows.append(bytes(row))
    path.write_bytes(b'P6\n%d %d\n255\n' % (width, height) + b''.join(rows))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--argb', action='store_true', help='Verify depth-32 native frame alpha and opaque caption')
    parser.add_argument('--output', type=Path, help='Optional PPM artifact of the named frame surface')
    args = parser.parse_args()
    guard()
    x, composite, pixmap = Display(), None, None
    bind(x)
    frame_image = title_image = root_image = None
    previous = None
    colormap = None
    try:
        if args.argb:
            client, colormap = create_argb(x)
        else:
            client = x.create('Carpatic frame-surface probe', COLOR, 420, 280)
        x.x.XMapWindow(x.handle, client)
        x.message(client, '_NET_ACTIVE_WINDOW', [1, 0, 0, 0, 0])
        frame, title = wait_for_frame(x, client)
        root, frame_parent, kids = children_of(x, frame)
        if frame_parent != root or client not in kids:
            raise RuntimeError(f'Frame {hex(frame)} parent {hex(frame_parent)} is not root, or client not reparented')
        ready = time.monotonic() + 3
        while True:
            try: require_viewable(frame, title, client); break
            except RuntimeError:
                if time.monotonic() >= ready: raise
                time.sleep(.05)
        time.sleep(.3)
        composite = Composite(x)
        fg, tg, cg = geometry(frame), geometry(title), geometry(client)
        previous = x.x.XSetErrorHandler(HANDLER)
        pixmap = composite.name(x, frame)  # frame only; never the client child
        x.sync()
        if errors:
            pixmap = None
            raise RuntimeError(f'X errors while naming frame pixmap (BadMatch={BAD_MATCH} expected shape): {errors}')
        if not pixmap:
            raise RuntimeError('XCompositeNameWindowPixmap returned zero')
        pw, ph, depth = drawable_geometry(x, pixmap)
        expected_depth = 32 if args.argb else 24
        if depth != expected_depth:
            raise RuntimeError(f'Named pixmap depth {depth} differs from expected {expected_depth}')
        depths = dict(frame=drawable_geometry(x, frame)[2],
                      client=drawable_geometry(x, client)[2], title=drawable_geometry(x, title)[2])
        if args.argb and depths != dict(frame=32, client=32, title=24):
            raise RuntimeError(f'ARGB frame/client/native-caption depths wrong: {depths}')
        if (pw, ph) != (fg['WIDTH'], fg['HEIGHT']):
            raise RuntimeError(f'Named pixmap {pw}x{ph} does not match frame {fg["WIDTH"]}x{fg["HEIGHT"]}')
        frame_image = capture(x, pixmap, pw, ph)
        body = [(pw * i // 4, ph * j // 4) for i in (1, 2, 3) for j in (1, 2, 3)]
        body_samples = {f'{px},{py}': f'{pixel(x, frame_image, px, py):06x}' for px, py in body}
        body_ok = all(v == f'{COLOR:06x}' for v in body_samples.values())
        body_argb = {f'{px},{py}': f'{x.x.XGetPixel(frame_image, px, py) & 0xffffffff:08x}'
                     for px, py in body} if args.argb else None
        alpha_ok = not args.argb or all(v == '8025a9df' for v in body_argb.values())
        tx, ty = tg['X'] - fg['X'], tg['Y'] - fg['Y']
        title_image = capture(x, title, tg['WIDTH'], tg['HEIGHT'])
        th, tw = tg['HEIGHT'], tg['WIDTH']
        if args.argb:
            root_image = x.x.XGetImage(x.handle, x.root, fg['X'], fg['Y'], pw, ph, 0xffffffff, 2)
            if not root_image:
                raise RuntimeError('Cannot capture visible ARGB frame rectangle from root')
        root_caption_ok = True
        title_samples, title_ok = {}, True
        for sx in dict.fromkeys((8, tw // 2, max(tw - 8, 0))):
            sy = th // 2
            own = pixel(x, title_image, min(sx, tw - 1), sy)
            named = pixel(x, frame_image, tx + min(sx, tw - 1), ty + sy)
            named_alpha = (x.x.XGetPixel(frame_image, tx + min(sx, tw - 1), ty + sy) >> 24) & 255
            if args.argb:
                alpha_ok = alpha_ok and named_alpha == 255
            root_caption = pixel(x, root_image, tx + min(sx, tw - 1), ty + sy) if args.argb else None
            if args.argb:
                # Native caption is 24-bit RGB: its composited parent pixels must
                # remain opaque and actually visible, not zero-alpha RGB debris.
                root_caption_ok = root_caption_ok and all(
                    abs(((own >> shift) & 255) - ((root_caption >> shift) & 255)) <= 3
                    for shift in (0, 8, 16))
            same = own == named
            distinct = own not in (COLOR, 0)
            title_ok = title_ok and same and distinct
            title_samples[f'{sx},{sy}'] = dict(title=f'{own:06x}', named_frame=f'{named:06x}',
                                               matches=same, distinct_from_body_and_zero=distinct,
                                               named_alpha=named_alpha if args.argb else None,
                                               root_caption=f'{root_caption:06x}' if args.argb else None)
        # Negative control: strictly body-only crop of the named FRAME pixmap must
        # show no distinct title; the detector must still find the real title band.
        cx0, cy0 = cg['X'] - fg['X'], cg['Y'] - fg['Y']
        # Stay inside content: the rounded native border is legitimately a
        # distinct colour near the bottom corners and is not a title band.
        body_crop = (cx0 + cg['WIDTH'] // 4, cx0 + 3 * cg['WIDTH'] // 4,
                     cy0 + cg['HEIGHT'] // 4, cy0 + 3 * cg['HEIGHT'] // 4)
        body_only = distinct_rows(x, frame_image, *body_crop, COLOR)
        title_band = distinct_rows(x, frame_image, cx0 + 2, cx0 + cg['WIDTH'] - 2, ty, ty + th, COLOR)
        control_ok = not body_only and bool(title_band)
        if args.output:
            write_ppm(args.output, x, frame_image, pw, ph)
        ok = body_ok and title_ok and control_ok and alpha_ok and root_caption_ok
        print(json.dumps(dict(guarded=True, compositor=dict(version=composite.version, selection=CM_ATOM),
                              parentage=dict(client=f'{client:#x}', frame=f'{frame:#x}', title=f'{title:#x}',
                                             frame_parent=f'{root:#x}', client_parent=f'{frame:#x}'),
                              frame_geometry=fg, title_offset=[tx, ty], title_size=[tw, th],
                              pixmap=dict(size=[pw, ph], depth=depth),
                              body_samples=body_samples, body_argb_samples=body_argb,
                              window_depths=depths, argb=args.argb, alpha_ok=alpha_ok, root_caption_ok=root_caption_ok,
                              title_samples=title_samples,
                              negative_control=dict(body_only_distinct_rows=len(body_only),
                                                    title_band_distinct_rows=len(title_band)),
                              artifact=str(args.output) if args.output else None,
                              summary=dict(ok=ok, failures=sum(not part for part in (body_ok, title_ok, control_ok, alpha_ok, root_caption_ok))))),
                             flush=True)
        if not ok:
            raise RuntimeError('Frame surface probe failed: body/title/control checks above')
        return 0
    finally:
        if frame_image:
            x.x.XDestroyImage(frame_image)
        if title_image:
            x.x.XDestroyImage(title_image)
        if root_image:
            x.x.XDestroyImage(root_image)
        if pixmap:
            x.x.XFreePixmap(x.handle, pixmap)
        x.sync()
        if previous is not None:
            x.x.XSetErrorHandler(c.cast(previous, Handler))
        if colormap:
            x.x.XFreeColormap(x.handle, colormap)
        x.close()  # destroys only windows this probe created


if __name__ == '__main__':
    sys.exit(main())
