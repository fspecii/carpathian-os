#!/usr/bin/env python3
"""Action-frame body/chrome coverage on an explicitly owned Alpine Xorg fixture.

Samples Xorg root pixels, not hardware presentation/FPS. No preference changes.
Snap is explicitly uncovered: geometric resizing is not the native drop gesture.
"""
import argparse
from collections import Counter
import ctypes as c
import json
import os
from pathlib import Path
import subprocess
import time

BLUE = (0x25, 0xA9, 0xDF)
BACKGROUND = (7, 9, 13)


def opacity(pixel, target, background=BACKGROUND):
    vector = [target[i] - background[i] for i in range(3)]
    denominator = sum(v * v for v in vector)
    if denominator < 100:
        return None
    alpha = sum((pixel[i] - background[i]) * vector[i] for i in range(3)) / denominator
    residual = max(abs(pixel[i] - (background[i] + alpha * vector[i])) for i in range(3))
    # An 8-bit channel is rounded by at most half a unit. Dark chrome has a
    # larger projected error than the cyan body: at nominal alpha .30 its
    # estimate can be .29 while the body is exactly .30. Account for that
    # bounded quantization rather than reporting a nonexistent missing header.
    rounding_error = .5 * sum(abs(v) for v in vector) / denominator
    return alpha if .30 - rounding_error <= alpha <= 1.08 and residual <= 12 else None


def runs(rows):
    result = []
    for row in rows:
        if result and row == result[-1][-1] + 1:
            result[-1].append(row)
        else:
            result.append([row])
    return result


def inspect_column(pixels, chrome, require_body=False):
    body_runs = [r for r in runs([i for i, p in enumerate(pixels) if opacity(p, BLUE) is not None]) if len(r) >= 8]
    if not body_runs:
        return dict(visible=False, failed=bool(require_body), reason='missing-body' if require_body else 'below-opacity-or-size-threshold')
    body = max(body_runs, key=len)
    top, bottom = body[0], body[-1]
    # Small shrinking surfaces have subpixel chrome; record rather than demand
    # the same four-pixel seam threshold used for a large surface.
    if len(body) < 24:
        return dict(visible=True, tiny=True, failed=False, top=top, bottom=bottom)
    chromes = [i for i in range(max(0, top - 75), top) if opacity(pixels[i], chrome) is not None]
    gap = top - max(chromes) - 1 if chromes else 999
    # Two sizeable cyan runs separated inside the same column expose a hole.
    sizeable = [r for r in body_runs if len(r) >= 24]
    hole = len(sizeable) > 1
    return dict(visible=True, tiny=False, failed=gap > 4 or hole, top=top,
                bottom=bottom, gap=gap, split_body=hole,
                alpha=round(sorted(opacity(pixels[i], BLUE) for i in body)[len(body) // 2], 4))


def locate_column(rgb, width, height, fallback):
    """Find the owned cyan surface on a sparse grid in one captured image."""
    candidates = []
    for column in range(12, width, 24):
        count = sum(opacity(tuple(rgb[(row * width + column) * 3:
                                      (row * width + column) * 3 + 3]), BLUE) is not None
                    for row in range(12, height, 24))
        if count >= 2:
            candidates.append((count, column))
    if not candidates:
        return fallback
    maximum = max(count for count, _ in candidates)
    columns = [column for count, column in candidates if count == maximum]
    return columns[len(columns) // 2]


def self_test():
    chrome = (80, 90, 110)
    pixels = [BACKGROUND] * 80 + [chrome] * 24 + [BLUE] * 100 + [BACKGROUND] * 30
    good = inspect_column(pixels, chrome, True)
    if good['failed']:
        raise AssertionError(good)
    missing = pixels[:80] + [BACKGROUND] * 24 + pixels[104:]
    stale = pixels[:125] + [(230, 80, 20)] * 12 + pixels[137:]
    absent = [BACKGROUND] * len(pixels)
    if not inspect_column(missing, chrome, True)['failed']:
        raise AssertionError('Missing-chrome fault was accepted')
    if not inspect_column(stale, chrome, True)['failed']:
        raise AssertionError('Interrupted-body stale-pixel fault was accepted')
    if not inspect_column(absent, chrome, True)['failed']:
        raise AssertionError('Missing opaque body was accepted')
    faded = [tuple(round(BACKGROUND[i] + .5 * (p[i] - BACKGROUND[i])) for i in range(3)) for p in pixels]
    if inspect_column(faded, chrome, True)['failed']:
        raise AssertionError('Legitimate faded body/chrome was rejected')
    dark_chrome = (48, 35, 36)
    boundary = ([BACKGROUND] * 80 + [dark_chrome] * 24
                + [BLUE] * 100 + [BACKGROUND] * 30)
    boundary = [tuple(round(BACKGROUND[i] + .30 * (p[i] - BACKGROUND[i]))
                      for i in range(3)) for p in boundary]
    if inspect_column(boundary, dark_chrome, True)['failed']:
        raise AssertionError('Quantized threshold chrome was rejected')
    boundary[80:104] = [BACKGROUND] * 24
    if not inspect_column(boundary, dark_chrome, True)['failed']:
        raise AssertionError('Missing threshold chrome was accepted')
    if inspect_column(absent, chrome, False)['failed']:
        raise AssertionError('Expected hidden surface was rejected')
    width, height = 512, 384
    rgb = bytearray(bytes(BACKGROUND) * width * height)
    for row in range(120, 280):
        for col in range(24, 104):
            offset = (row * width + col) * 3
            rgb[offset:offset + 3] = bytes(BLUE)
    if not 24 <= locate_column(rgb, width, height, width // 2) < 104:
        raise AssertionError('Translated surface tracking failed')
    print(json.dumps(dict(self_test=True, controls=['missing-chrome', 'stale-body', 'missing-body'], passed=True)))


def guard():
    if (os.environ.get('CARPATIC_VM_TEST') != '1'
            or os.environ.get('CARPATIC_ACTION_CONTINUITY_OWNED') != '1'
            or os.environ.get('DISPLAY') != ':0'
            or 'WAYLAND_DISPLAY' in os.environ or not Path('/etc/alpine-release').exists()):
        raise RuntimeError('Explicit exclusively reserved isolated Alpine Xorg :0 only')
    for locker in ('i3lock', 'slock'):
        if subprocess.run(['pgrep', '-x', locker], stdout=subprocess.DEVNULL).returncode == 0:
            raise RuntimeError('Fixture is locked')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--results', type=Path)
    parser.add_argument('--cycles', type=int, default=3)
    parser.add_argument('--diagnostic-captures', action='store_true', help='Capture full root/column in one XGetImage and retain first two failed snapshots')
    parser.add_argument('--shared-capture', action='store_true', help='Opt-in MIT-SHM full-scene capture; requires --diagnostic-captures')
    parser.add_argument('--shared-column', action='store_true', help='Narrow MIT-SHM column for short close transitions')
    parser.add_argument('--track-surface', action='store_true', help='Follow owned cyan body horizontally in full-scene snapshots')
    parser.add_argument('--retain-background-experiment', action='store_true', help='Controlled fixture only: set its frame background to None before closing')
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.results is None or not 1 <= args.cycles <= 20:
        parser.error('--results and cycles between 1 and 20 required')
    if args.shared_capture and not args.diagnostic_captures:
        parser.error('--shared-capture requires --diagnostic-captures')
    if args.shared_column and (args.shared_capture or args.diagnostic_captures):
        parser.error('--shared-column is separate from full-scene captures')
    if args.track_surface and not args.diagnostic_captures:
        parser.error('--track-surface requires --diagnostic-captures')
    guard()
    from rendering import Display, COLOR, command
    import fcntl
    lock = open('/var/tmp/carpatic-action-continuity.lock', 'a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    args.results.mkdir(parents=True, exist_ok=False)
    active = json.loads(command('carpatic-animations', 'get', '--json'))
    if (not active.get('running') or not active.get('enabled') or active.get('reduced')
            or not all(active.get(k) for k in ('open', 'close', 'minimize', 'geometry'))):
        raise RuntimeError('Production open/close/minimize/geometry animations must already be active')
    config = Path.home() / '.config/carpatic'
    preferences = {p: p.read_bytes() if p.exists() else None
                   for p in (config / 'animations.json', config / 'reduced-motion')}
    x = Display()
    for name, result, arguments in (
        ('XDisplayWidth', c.c_int, [c.c_void_p, c.c_int]),
        ('XDisplayHeight', c.c_int, [c.c_void_p, c.c_int]),
        ('XMoveResizeWindow', c.c_int, [c.c_void_p, c.c_ulong, c.c_int, c.c_int, c.c_uint, c.c_uint]),
        ('XRaiseWindow', c.c_int, [c.c_void_p, c.c_ulong]),
        ('XSetWindowBackground', c.c_int, [c.c_void_p, c.c_ulong, c.c_ulong])):
        fn = getattr(x.x, name)
        fn.restype, fn.argtypes = result, arguments
    width, height = x.x.XDisplayWidth(x.handle, 0), x.x.XDisplayHeight(x.handle, 0)
    if width < 1000 or height < 650:
        raise RuntimeError('Fixture requires at least 1000x650 root pixels')
    center = width // 2
    records, failures = [], []
    original_active = command('xprop', '-root', '_NET_ACTIVE_WINDOW')
    chrome_color = None
    calibration = {}
    last_frame = None
    frame_faults = 0
    shared = None
    sampled_column = center

    class ImageHeader(c.Structure):
        _fields_ = [('width', c.c_int), ('height', c.c_int), ('xoffset', c.c_int),
                    ('format', c.c_int), ('data', c.c_void_p), ('byte_order', c.c_int),
                    ('bitmap_unit', c.c_int), ('bitmap_bit_order', c.c_int),
                    ('bitmap_pad', c.c_int), ('depth', c.c_int),
                    ('bytes_per_line', c.c_int), ('bits_per_pixel', c.c_int),
                    ('red_mask', c.c_ulong), ('green_mask', c.c_ulong), ('blue_mask', c.c_ulong)]

    def diagnostic(label):
        if last_frame is None:
            return
        stamp, rgb = last_frame
        (args.results / (label + '.ppm')).write_bytes(
            f'P6\n{width} {height}\n255\n'.encode() + rgb)
        print(json.dumps(dict(diagnostic=label, captured_at=stamp,
                              scope='full root and column from the same snapshot',
                              capture='XShmGetImage' if shared is not None else 'XGetImage')), flush=True)

    def capture():
        nonlocal last_frame, sampled_column
        stamp = time.monotonic()
        shared_raw = shared.capture(center if args.shared_column else 0, 0)[0] if shared is not None else None
        image = shared.image if shared is not None else x.x.XGetImage(
            x.handle, x.root, 0 if args.diagnostic_captures else center,
            0, width if args.diagnostic_captures else 1, height, 0xFFFFFFFF, 2)
        if not image:
            raise RuntimeError('Cannot capture root column')
        try:
            if args.diagnostic_captures:
                header = c.cast(image, c.POINTER(ImageHeader)).contents
                if (header.bits_per_pixel != 32 or header.byte_order != 0
                        or (header.red_mask, header.green_mask, header.blue_mask) != (0xff0000, 0xff00, 0xff)):
                    raise RuntimeError('Same-frame diagnostic requires verified little-endian 32bpp RGB masks')
                raw = shared_raw if shared_raw is not None else c.string_at(header.data, header.bytes_per_line * height)
                if header.bytes_per_line != width * 4:
                    raw = b''.join(raw[y*header.bytes_per_line:y*header.bytes_per_line+width*4] for y in range(height))
                rgb = bytearray(width * height * 3)
                rgb[0::3], rgb[1::3], rgb[2::3] = raw[2::4], raw[1::4], raw[0::4]
                last_frame = (stamp, rgb)
                sampled_column = locate_column(rgb, width, height, center) if args.track_surface else center
                return [tuple(rgb[(y*width+sampled_column)*3:(y*width+sampled_column)*3+3]) for y in range(height)]
            return [tuple((x.x.XGetPixel(image, 0, y) >> shift) & 255 for shift in (16, 8, 0)) for y in range(height)]
        finally:
            if shared is None:
                x.x.XDestroyImage(image)

    def sample(action, trigger, end_visible, interrupt=None):
        nonlocal frame_faults
        start = time.monotonic()
        trigger()
        reverse_t = None
        case = []
        while time.monotonic() - start < .85:
            if interrupt and reverse_t is None and time.monotonic() - start >= .085:
                interrupt()
                reverse_t = time.monotonic() - start
            begin = time.monotonic()
            pixels = capture()
            end = time.monotonic()
            elapsed = end - start
            observation = inspect_column(pixels, chrome_color, require_body=end_visible and elapsed > .65)
            if not end_visible and elapsed > .65 and observation['visible']:
                observation.update(failed=True, reason='stale-after-hide-deadline')
            item = dict(action=action, t=round(elapsed, 5), capture_ms=round((end - begin) * 1000, 3),
                        interrupt_t=reverse_t, column=sampled_column, **observation)
            records.append(item)
            case.append(item)
            if item['failed']:
                failures.append(item)
                frame_faults += 1
                if frame_faults <= 6:
                    # Preserve the exact sampled column, enlarged for inspection.
                    # Full-frame screenshots after a transition are not substitutes.
                    raw = b''.join(bytes(pixel) * 32 for pixel in pixels)
                    (args.results / f'failed-column-{len(failures)}.ppm').write_bytes(
                        f'P6\n32 {len(pixels)}\n255\n'.encode() + raw)
                if frame_faults <= 2:
                    diagnostic(f'failed-root-{frame_faults}')
            time.sleep(.008)
        visible = [r for r in case if r['visible'] and not r.get('tiny')]
        # A case needs sampled transition content, not merely a successful final
        # settled snapshot. Lack of visibility is an explicit coverage failure.
        moving = (bool(visible) and
                  (max(r['top'] for r in visible) - min(r['top'] for r in visible) > 3
                   or max(r['bottom'] for r in visible) - min(r['bottom'] for r in visible) > 3
                   or max(r['column'] for r in visible) - min(r['column'] for r in visible) > 3
                   or any(r.get('alpha', 1) < .9 and r['t'] < .6 for r in visible)))
        covered = len(visible) >= 3 and moving
        if not covered:
            failures.append(dict(action=action, reason='insufficient-changing-action-samples',
                                 visible=len(visible), changing=bool(moving)))
        if (args.track_surface and active.get('style') == 'macos'
                and action.endswith(('-minimize', '-restore'))
                and 'interrupted' not in action):
            # A fade can satisfy generic changing-content coverage without
            # executing the configured panel-directed shrink/restore at all.
            # Qualify that intended motion separately from mere visibility.
            heights = [r['bottom'] - r['top'] for r in visible]
            transform_observed = (len(heights) >= 3 and max(heights) - min(heights) > 24)
            if not transform_observed:
                failures.append(dict(action=action, reason='missing-panel-directed-scale',
                                     heights=heights))
            if any(r.get('alpha', 1) < .9 for r in visible):
                failures.append(dict(action=action, reason='unexpected-panel-motion-fade'))
        if args.diagnostic_captures:
            diagnostic(action + '-final-root')
            if end_visible:
                # Final pixels and server state answer different questions.
                # Retain both: a mapped app can still be absent from the scene.
                state = dict(action=action,
                             tree=command('xwininfo', '-id', str(w), '-tree'),
                             geometry=command('xwininfo', '-id', str(w)),
                             properties=command('xprop', '-id', str(w), 'WM_STATE',
                                                '_CARPATIC_ANIMATION', '_CARPATIC_FRAME_GEOMETRY'))
                (args.results / (action + '-final-state.json')).write_text(json.dumps(state, indent=2))
        print(json.dumps(dict(action=action, samples=len(case), visible=len(visible),
                              failed=sum(bool(r['failed']) for r in case), coverage=covered)), flush=True)

    def create():
        w = x.create('Action continuity marker', COLOR, 540, 250)
        x.x.XMoveResizeWindow(x.handle, w, center - 270, 210, 540, 250)
        return w

    def map_window(w):
        x.x.XMapWindow(x.handle, w)
        x.sync()
        x.message(w, '_NET_ACTIVE_WINDOW', [1, 0, 0, 0, 0])

    def maximize(w, on):
        x.message(w, '_NET_WM_STATE', [int(on), x.atom('_NET_WM_STATE_MAXIMIZED_VERT'),
                                      x.atom('_NET_WM_STATE_MAXIMIZED_HORZ'), 1, 0])

    try:
        if args.shared_capture or args.shared_column:
            from shared_snapshot import Snapshot
            shared = Snapshot(x, 1 if args.shared_column else width, height)
        # A fixture-owned opaque backdrop makes partial-opacity classification
        # deterministic. It changes no wallpaper or settings and is destroyed.
        bg = x.create('Action continuity backdrop', 0x07090D, width, height,
                      kind_name='_NET_WM_WINDOW_TYPE_NOTIFICATION', override=True)
        x.x.XMoveResizeWindow(x.handle, bg, 0, 0, width, height)
        x.x.XMapWindow(x.handle, bg)
        x.sync()
        time.sleep(.8)
        calibrate = create()
        map_window(calibrate)
        time.sleep(.8)
        baseline = capture()
        blue = [i for i, p in enumerate(baseline) if opacity(p, BLUE) is not None]
        if not blue:
            raise RuntimeError('Owned cyan marker is not visible over backdrop')
        top = min(blue)
        chrome_color = Counter(baseline[max(0, top - 20):top - 3]).most_common(1)[0][0]
        if opacity(chrome_color, BLUE) is not None or chrome_color == BACKGROUND:
            raise RuntimeError('Native chrome cannot be distinguished')
        chrome_id = None
        import re
        for candidate in re.findall(r'^\s+(0x[0-9a-f]+)', command('xwininfo', '-root', '-tree'), re.M):
            association = command('xprop', '-id', candidate, '_CARPATIC_CLIENT')
            found = re.search(r'window id # (0x[0-9a-f]+)', association)
            if found and int(found.group(1), 16) == calibrate:
                chrome_id = int(candidate, 16)
                break
        if chrome_id is None:
            raise RuntimeError('No fixture-associated chrome')
        calibration.update(chrome_color=chrome_color, body_top=top,
                           client_geometry=command('xdotool', 'getwindowgeometry', '--shell', str(calibrate)),
                           chrome_geometry=command('xdotool', 'getwindowgeometry', '--shell', str(chrome_id)))
        raw = b''.join(bytes(pixel) * 32 for pixel in baseline)
        (args.results / 'calibration-column.ppm').write_bytes(f'P6\n32 {len(baseline)}\n255\n'.encode()+raw)
        print(json.dumps(dict(calibration=calibration)), flush=True)
        diagnostic('calibration-root')
        x.x.XUnmapWindow(x.handle, chrome_id)
        x.sync()
        time.sleep(.65)
        fault = inspect_column(capture(), chrome_color, True)
        if not fault['failed']:
            raise AssertionError('Real missing-chrome fault control was accepted')
        print(json.dumps(dict(control='missing-chrome', detected=True, observation=fault)), flush=True)
        x.x.XMapWindow(x.handle, chrome_id)
        x.x.XSetWindowBackground(x.handle, calibrate, 0xE65014)
        x.x.XClearWindow(x.handle, calibrate)
        x.sync()
        time.sleep(.4)
        fault = inspect_column(capture(), chrome_color, True)
        if not fault['failed']:
            raise AssertionError('Real wrong-body-pixel control was accepted')
        print(json.dumps(dict(control='wrong-body-pixels', detected=True, observation=fault)), flush=True)
        x.destroy(calibrate)
        time.sleep(.6)
        for cycle in range(args.cycles):
            w = create()
            sample(f'{cycle}-open', lambda: map_window(w), True)
            sample(f'{cycle}-maximize', lambda: maximize(w, True), True)
            sample(f'{cycle}-unmaximize', lambda: maximize(w, False), True)
            sample(f'{cycle}-interrupted-maximize', lambda: maximize(w, True), True,
                   lambda: maximize(w, False))
            sample(f'{cycle}-minimize', lambda: x.message(w, 'WM_CHANGE_STATE', [3, 0, 0, 0, 0]), False)
            sample(f'{cycle}-restore', lambda: x.message(w, '_NET_ACTIVE_WINDOW', [1, 0, 0, 0, 0]), True)
            sample(f'{cycle}-interrupted-minimize', lambda: x.message(w, 'WM_CHANGE_STATE', [3, 0, 0, 0, 0]), True,
                   lambda: x.message(w, '_NET_ACTIVE_WINDOW', [1, 0, 0, 0, 0]))
            if args.retain_background_experiment:
                parent = c.c_ulong(); root_id = c.c_ulong(); children = c.POINTER(c.c_ulong)(); count = c.c_uint()
                x.x.XQueryTree.argtypes = [c.c_void_p, c.c_ulong, c.POINTER(c.c_ulong), c.POINTER(c.c_ulong), c.POINTER(c.POINTER(c.c_ulong)), c.POINTER(c.c_uint)]
                x.x.XFree.argtypes = [c.c_void_p]
                assert x.x.XQueryTree(x.handle, w, c.byref(root_id), c.byref(parent), c.byref(children), c.byref(count))
                if children: x.x.XFree(children)
                assert parent.value != x.root, 'Experiment requires fixture-owned framed client'
                from rendering import WindowAttributes
                attributes = WindowAttributes(background_pixmap=0)
                x.x.XChangeWindowAttributes(x.handle, parent.value, 1, c.byref(attributes))
                x.sync()
            sample(f'{cycle}-close', lambda: x.destroy(w), False)
        changed = [str(p) for p, data in preferences.items() if (p.read_bytes() if p.exists() else None) != data]
        if changed:
            raise RuntimeError('Unexpected preference mutation: ' + ', '.join(changed))
        print(json.dumps(dict(summary=True, samples=len(records), failed=len(failures),
                              snap='uncovered; requires native Super drag/drop fixture',
                              scope='sampled root-column body/chrome coverage, not FPS or all presented frames')), flush=True)
        return 1 if failures else 0
    finally:
        (args.results / 'frames.json').write_text(json.dumps(dict(active=active, calibration=calibration, records=records, failures=failures), indent=2))
        if shared is not None:
            shared.close()
        x.close()
        import re
        found = re.search(r'window id # (0x[0-9a-f]+)', original_active)
        if found and int(found.group(1), 16):
            try:
                command('xdotool', 'windowactivate', found.group(1))
            except subprocess.SubprocessError:
                pass
        lock.close()


if __name__ == '__main__':
    raise SystemExit(main())
