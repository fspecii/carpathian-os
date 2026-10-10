#!/usr/bin/env python3
"""Settled-frame pixel oracle for a real isolated Alpine Xorg desktop.

Opaque clients must retain their pixels after animated resize and occlusion.
This measures correctness, not animation frame rate. Never run on a host desktop.
"""
import argparse
import ctypes as c
import fcntl
import stat
import json
import os
from pathlib import Path
import subprocess
import time
import re

COLOR = 0x25A9DF

class MessageData(c.Union):
    _fields_ = [('bytes', c.c_char * 20), ('shorts', c.c_short * 10), ('longs', c.c_long * 5)]

class ClientMessage(c.Structure):
    _fields_ = [('type', c.c_int), ('serial', c.c_ulong), ('send_event', c.c_int),
                ('display', c.c_void_p), ('window', c.c_ulong), ('message_type', c.c_ulong),
                ('format', c.c_int), ('data', MessageData)]

class WindowAttributes(c.Structure):
    _fields_ = [('background_pixmap', c.c_ulong), ('background_pixel', c.c_ulong),
                ('border_pixmap', c.c_ulong), ('border_pixel', c.c_ulong),
                ('bit_gravity', c.c_int), ('win_gravity', c.c_int), ('backing_store', c.c_int),
                ('backing_planes', c.c_ulong), ('backing_pixel', c.c_ulong), ('save_under', c.c_int),
                ('event_mask', c.c_long), ('do_not_propagate_mask', c.c_long),
                ('override_redirect', c.c_int), ('colormap', c.c_ulong), ('cursor', c.c_ulong)]


def command(*args):
    return subprocess.check_output(args, text=True, timeout=8).strip()


def map_state(output):
    match = re.search(r'^\s*Map State:\s*(\w+)\s*$', output, re.MULTILINE)
    return match.group(1) if match else None


def hidden(output):
    # A mapped child of an unmapped native frame is IsUnviewable. Both
    # forms hide the application; IsViewable and missing state must fail.
    return map_state(output) in ('IsUnMapped', 'IsUnviewable')


class ProbeLease:
    """Kernel-held, nonblocking lease; persistent inode, no PID/staleness guesses."""
    def __init__(self, path=None):
        self.fd = None
        self.path = Path(path) if path is not None else Path(f'/tmp/carpatic-xorg-probe-{os.getuid()}-0.lock')
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                raise RuntimeError(f'Unsafe probe lease file: {self.path}')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError(f'Another probe owns this Xorg display: {self.path}') from error
            self.fd = fd
        except BaseException:
            os.close(fd)
            raise

    def close(self):
        if self.fd is not None:
            fd, self.fd = self.fd, None
            os.close(fd)  # Kernel releases the lease; never unlink its inode.


def fixture_lease_required():
    return (os.environ.get('CARPATIC_VM_TEST') == '1'
            and os.environ.get('DISPLAY') == ':0'
            and 'WAYLAND_DISPLAY' not in os.environ
            and Path('/etc/alpine-release').is_file())


class Display:
    def __init__(self):
        self.handle = None
        self.windows = []
        self.lease = ProbeLease() if fixture_lease_required() else None
        try:
            self.x = c.CDLL('libX11.so.6')
            pointer, window, integer = c.c_void_p, c.c_ulong, c.c_int
            signatures = {
                'XOpenDisplay': (pointer, [c.c_char_p]),
                'XDefaultRootWindow': (window, [pointer]),
                'XCreateSimpleWindow': (window, [pointer, window, integer, integer, c.c_uint, c.c_uint, c.c_uint, window, window]),
                'XInternAtom': (window, [pointer, c.c_char_p, integer]),
                'XChangeProperty': (integer, [pointer, window, window, window, integer, integer, pointer, integer]),
                'XStoreName': (integer, [pointer, window, c.c_char_p]),
                'XChangeWindowAttributes': (integer, [pointer, window, window, pointer]),
                'XSendEvent': (integer, [pointer, window, integer, c.c_long, pointer]),
                'XMapWindow': (integer, [pointer, window]),
                'XUnmapWindow': (integer, [pointer, window]),
                'XClearWindow': (integer, [pointer, window]),
                'XSync': (integer, [pointer, integer]),
                'XGetImage': (pointer, [pointer, window, integer, integer, c.c_uint, c.c_uint, window, integer]),
                'XGetPixel': (window, [pointer, integer, integer]),
                'XDestroyImage': (integer, [pointer]),
                'XDestroyWindow': (integer, [pointer, window]),
                'XCloseDisplay': (integer, [pointer]),
            }
            for name, (result, arguments) in signatures.items():
                function = getattr(self.x, name)
                function.restype, function.argtypes = result, arguments
            self.handle = self.x.XOpenDisplay(None)
            if not self.handle:
                raise RuntimeError('Xorg display is unavailable')
            self.root = self.x.XDefaultRootWindow(self.handle)
        except BaseException as original:
            try:
                if self.handle:
                    self.x.XCloseDisplay(self.handle)
                    self.handle = None
            except BaseException as cleanup:
                original.add_note(f'Display cleanup also failed: {cleanup}')
            finally:
                if self.lease:
                    try:
                        self.lease.close()
                    except BaseException as cleanup:
                        original.add_note(f'Lease cleanup also failed: {cleanup}')
            raise

    def create(self, name, color, width, height, kind_name='_NET_WM_WINDOW_TYPE_DIALOG', override=False):
        w = self.x.XCreateSimpleWindow(self.handle, self.root, 100, 100, width, height, 0, 0, color)
        self.windows.append(w)
        # Dialog type gives an independent floating rectangle without relying
        # on profile-specific keyboard bindings to change the layout.
        kind = c.c_ulong(self.x.XInternAtom(self.handle, kind_name.encode(), 0))
        atom = self.x.XInternAtom(self.handle, b'_NET_WM_WINDOW_TYPE', 0)
        self.x.XChangeProperty(self.handle, w, atom, 4, 32, 0, c.byref(kind), 1)
        self.x.XStoreName(self.handle, w, name.encode())
        if override:
            attributes = WindowAttributes(override_redirect=1)
            self.x.XChangeWindowAttributes(self.handle, w, 1 << 9, c.byref(attributes))
        return w

    def message(self, w, name, values):
        event = ClientMessage(type=33, display=self.handle, window=w,
                              message_type=self.x.XInternAtom(self.handle, name.encode(), 0), format=32)
        for i, value in enumerate(values):
            event.data.longs[i] = value
        if not self.x.XSendEvent(self.handle, self.root, 0, (1 << 19) | (1 << 20), c.byref(event)):
            raise RuntimeError('Cannot send window-management request')
        self.sync()

    def atom(self, name):
        return self.x.XInternAtom(self.handle, name.encode(), 0)

    def destroy(self, w):
        self.x.XDestroyWindow(self.handle, w)
        self.windows.remove(w)
        self.sync()

    def sync(self):
        self.x.XSync(self.handle, 0)

    def pixels(self, w):
        raw = command('xdotool', 'getwindowgeometry', '--shell', str(w))
        g = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
        gx, gy, width, height = (int(g[key]) for key in ('X', 'Y', 'WIDTH', 'HEIGHT'))
        image = self.x.XGetImage(self.handle, self.root, gx, gy, width, height, 0xFFFFFFFF, 2)
        if not image:
            raise RuntimeError('Cannot capture the visible client rectangle')
        try:
            # Stay away from rounded borders and titlebars; test nine points,
            # not just the centre, so partial holes also fail the check.
            pixels = [self.x.XGetPixel(image, width * i // 4, height * j // 4) & 0xFFFFFF
                      for i in (1, 2, 3) for j in (1, 2, 3)]
        finally:
            self.x.XDestroyImage(image)
        return pixels, g

    def close(self):
        failures = []
        def attempt(operation):
            try:
                operation()
            except BaseException as error:
                failures.append(error)
        try:
            if self.handle:
                handle = self.handle
                windows, self.windows = self.windows, []
                for window in reversed(windows):
                    attempt(lambda window=window: self.x.XDestroyWindow(handle, window))
                attempt(lambda: self.x.XSync(handle, 0))
                attempt(lambda: self.x.XCloseDisplay(handle))
                self.handle = None
        finally:
            if self.lease:
                attempt(self.lease.close)
        if failures:
            for extra in failures[1:]:
                failures[0].add_note(f'Additional display cleanup failure: {extra}')
            raise failures[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--iterations', type=int, default=40)
    parser.add_argument('--actions', action='store_true', help='Also exercise maximize, minimize/restore, workspaces and popup close')
    args = parser.parse_args()
    if args.self_test:
        for state in ('IsUnMapped', 'IsUnviewable'):
            assert hidden('  Map State: ' + state)
        for state in ('IsViewable', 'Unknown'):
            assert not hidden('  Map State: ' + state)
        assert not hidden('Missing Map State')
        assert map_state('  Map State: IsViewable\n') == 'IsViewable'
        print('PASS hidden and restored X11 state oracles')
        return
    if not 1 <= args.iterations <= 500:
        parser.error('Iterations must be between 1 and 500')
    if (os.environ.get('CARPATIC_VM_TEST') != '1' or not Path('/etc/alpine-release').exists()
            or os.environ.get('WAYLAND_DISPLAY') or os.environ.get('DISPLAY') != ':0'):
        parser.error('Use only real Xorg :0 in an explicitly marked isolated Alpine VM')
    lock = subprocess.run(['pgrep', '-x', 'i3lock'], stdout=subprocess.DEVNULL)
    if lock.returncode == 0:
        raise RuntimeError('Fixture is screen-locked; stop its test-session locker before probing pixels')
    state = json.loads(command('carpatic-animations', 'get', '--json'))
    if not state.get('enabled') or state.get('reduced') or not state.get('running') or not state.get('geometry'):
        raise RuntimeError('Rendering regression requires running full geometry animations')
    print(json.dumps(dict(environment=True, animation_state=state)), flush=True)
    display = Display()
    failures = 0
    samples = 0
    sizes = set()
    original_desktop = int(command('xprop', '-root', '_NET_CURRENT_DESKTOP').split('=')[1])
    settle = .7 if args.actions else .45
    try:
        base = display.create('Carpatic pixel regression', COLOR, 420, 260)
        overlay = display.create('Carpatic occlusion regression', 0xDC683B, 220, 180)
        display.x.XMapWindow(display.handle, base)
        display.sync()
        time.sleep(1)
        command('xdotool', 'windowactivate', '--sync', str(base))
        phases = ('resize', 'occlusion', 'maximize', 'minimize', 'workspace', 'popup') if args.actions else ('resize', 'occlusion')
        for phase in phases:
            for i in range(args.iterations):
                if phase == 'resize':
                    command('xdotool', 'windowsize', str(base), str(380 + i % 3 * 80), str(240 + i % 4 * 30))
                    command('xdotool', 'windowmove', str(base), str(180 + i % 5 * 20), str(150 + i % 3 * 20))
                    display.x.XClearWindow(display.handle, base)
                    display.sync()
                elif phase == 'occlusion':
                    display.x.XMapWindow(display.handle, overlay)
                    display.sync()
                    time.sleep(.08)  # interrupt opening while it is animated
                    command('xdotool', 'windowmove', str(overlay), str(240 + i % 3 * 50), str(190 + i % 3 * 30))
                    time.sleep(.05)
                    display.x.XUnmapWindow(display.handle, overlay)
                    display.sync()
                    command('xdotool', 'windowactivate', '--sync', str(base))
                elif phase == 'maximize':
                    vertical = display.atom('_NET_WM_STATE_MAXIMIZED_VERT')
                    horizontal = display.atom('_NET_WM_STATE_MAXIMIZED_HORZ')
                    display.message(base, '_NET_WM_STATE', [1, vertical, horizontal, 1, 0])
                    time.sleep(settle)
                    if '_NET_WM_STATE_MAXIMIZED_VERT' not in command('xprop', '-id', str(base), '_NET_WM_STATE'):
                        raise RuntimeError('Maximize request was not applied')
                    pixels, _ = display.pixels(base)
                    failures += not all(pixel == COLOR for pixel in pixels)
                    samples += 1
                    print(json.dumps(dict(phase='maximized', iteration=i, ok=all(pixel == COLOR for pixel in pixels), pixels=[f'{pixel:06x}' for pixel in pixels])), flush=True)
                    display.message(base, '_NET_WM_STATE', [0, vertical, horizontal, 1, 0])
                elif phase == 'minimize':
                    display.message(base, 'WM_CHANGE_STATE', [3, 0, 0, 0, 0])
                    time.sleep(settle)
                    if '_NET_WM_STATE_HIDDEN' not in command('xprop', '-id', str(base), '_NET_WM_STATE'):
                        raise RuntimeError('Minimize request was not applied')
                    if not hidden(command('xwininfo', '-id', str(base))):
                        raise RuntimeError('Minimized application is still viewable')
                    command('xdotool', 'windowactivate', '--sync', str(base))
                elif phase == 'workspace':
                    count = int(command('xprop', '-root', '_NET_NUMBER_OF_DESKTOPS').split('=')[1])
                    if count < 2:
                        raise RuntimeError('Workspace workload requires at least two workspaces')
                    other = (original_desktop + 1) % count
                    command('xdotool', 'set_desktop', str(other))
                    time.sleep(settle)
                    if int(command('xprop', '-root', '_NET_CURRENT_DESKTOP').split('=')[1]) != other:
                        raise RuntimeError('Workspace switch was not applied')
                    if not hidden(command('xwininfo', '-id', str(base))):
                        raise RuntimeError('Original client was not hidden on the other workspace')
                    command('xdotool', 'set_desktop', str(original_desktop))
                    command('xdotool', 'windowactivate', '--sync', str(base))
                elif phase == 'popup':
                    popup = display.create('Carpatic popup regression', 0xDC683B, 220, 180, '_NET_WM_WINDOW_TYPE_POPUP_MENU', True)
                    display.x.XMapWindow(display.handle, popup)
                    display.sync()
                    command('xdotool', 'windowmove', str(popup), '260', '210')
                    time.sleep(settle)
                    pixels, _ = display.pixels(popup)
                    popup_ok = all(pixel == 0xDC683B for pixel in pixels)
                    samples += 1
                    failures += not popup_ok
                    print(json.dumps(dict(phase='popup-open', iteration=i, ok=popup_ok, pixels=[f'{pixel:06x}' for pixel in pixels])), flush=True)
                    display.destroy(popup)
                    command('xdotool', 'windowactivate', '--sync', str(base))
                time.sleep(settle)
                if map_state(command('xwininfo', '-id', str(base))) != 'IsViewable':
                    raise RuntimeError('Base application did not become viewable after action')
                pixels, geometry = display.pixels(base)
                ok = all(pixel == COLOR for pixel in pixels)
                failures += not ok
                samples += 1
                if phase == 'resize':
                    sizes.add((geometry['WIDTH'], geometry['HEIGHT']))
                print(json.dumps(dict(phase=phase, iteration=i, ok=ok,
                                      pixels=[f'{pixel:06x}' for pixel in pixels], geometry=geometry)), flush=True)
        if args.iterations >= 3 and len(sizes) < 3:
            raise RuntimeError('Resize workload was not actually applied')
        print(json.dumps(dict(summary=True, samples=samples, failed=failures)), flush=True)
        if failures:
            raise RuntimeError(f'{failures} settled frames have corrupted opaque pixels')
    finally:
        command('xdotool', 'set_desktop', str(original_desktop))
        display.close()


if __name__ == '__main__':
    main()
