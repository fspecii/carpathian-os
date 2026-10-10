#!/usr/bin/env python3
"""Owned Alpine Xorg move/resize CPU diagnostic, preserving session policies.

Uses rendering.Display's nonblocking display lease. Runs ABBA floating-client
move/resize submissions at 30 Hz for 12 seconds by default, with a strict 3-second
final-geometry acknowledgement. No preferences, compositor or WM changes.
CPU=one core at 100%; submission timing is NOT frame presentation/FPS.
Run only after all builds and other suites stop, sequentially for frozen A/B WMs.
"""
import argparse
import ctypes as c
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rendering import Display, COLOR, command
from frame_surface import guard, bind, wait_for_frame, require_viewable, geometry, Composite


def environment_value(pid, key):
    prefix = key.encode() + b'='
    for item in Path(f'/proc/{pid}/environ').read_bytes().split(b'\0'):
        if item.startswith(prefix):
            return os.fsdecode(item[len(prefix):])
    return None


def stat_sample(pid):
    raw = Path(f'/proc/{pid}/stat').read_text()
    fields = raw[raw.rindex(')') + 2:].split()
    return dict(start_ticks=int(fields[19]), cpu_ticks=int(fields[11]) + int(fields[12]),
                minor_faults=int(fields[7]), rss_kib=int(fields[21]) * os.sysconf('SC_PAGE_SIZE') // 1024)


def digest(path):
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


def wm_identity():
    metadata = command('xprop', '-root', '_NET_SUPPORTING_WM_CHECK')
    ids = re.findall(r'0x[0-9a-fA-F]+', metadata)
    if len(ids) != 1:
        raise RuntimeError('Cannot identify the actual WM support window')
    support = ids[0]
    if 'Carpathian OS' not in command('xprop', '-id', support, '_NET_WM_NAME'):
        raise RuntimeError('Fixture is not managed by the Carpathian OS WM')
    pid_property = command('xprop', '-id', support, '_NET_WM_PID')
    pid_match = re.search(r'=\s*(\d+)\s*$', pid_property)
    if not pid_match:
        raise RuntimeError('WM PID is absent from support window')
    pid = int(pid_match.group(1))
    proc = Path(f'/proc/{pid}')
    if proc.stat().st_uid != os.getuid() or environment_value(pid, 'DISPLAY') not in (':0', ':0.0'):
        raise RuntimeError('WM UID/display does not match the owned fixture account')
    return dict(pid=pid, start_ticks=stat_sample(pid)['start_ticks'],
                executable_sha256=digest(proc / 'exe'), support_window=support)


def process_set(wm):
    result = {wm['pid']: 'wm'}
    for proc in Path('/proc').glob('[0-9]*'):
        pid = int(proc.name)
        try:
            name = (proc / 'comm').read_text().strip()
            if name == 'picom' and proc.stat().st_uid == os.getuid():
                if environment_value(pid, 'DISPLAY') in (':0', ':0.0'):
                    result[pid] = 'picom'
            elif name == 'Xorg':
                arguments = (proc / 'cmdline').read_bytes().split(b'\0')
                if b':0' in arguments or b':0.0' in arguments:
                    result[pid] = 'xorg'
        except (OSError, ValueError):
            continue
    counts = {kind: list(result.values()).count(kind) for kind in ('wm', 'picom', 'xorg')}
    if counts != dict(wm=1, picom=1, xorg=1):
        raise RuntimeError(f'Need exactly one matching WM/Picom/Xorg: {counts}')
    return result


def sample(processes):
    return {pid: stat_sample(pid) for pid in processes}


def resource_delta(processes, before, after, elapsed):
    rows = []
    hz = os.sysconf('SC_CLK_TCK')
    for pid, kind in processes.items():
        if before[pid]['start_ticks'] != after[pid]['start_ticks']:
            raise RuntimeError(f'Process identity changed during sample: {kind}')
        ticks = after[pid]['cpu_ticks'] - before[pid]['cpu_ticks']
        rows.append(dict(kind=kind, pid=pid, cpu_seconds=ticks / hz,
                         cpu_percent_one_core=100 * ticks / hz / elapsed,
                         rss_kib=after[pid]['rss_kib'],
                         minor_fault_delta=after[pid]['minor_faults'] - before[pid]['minor_faults']))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--seconds', type=int, default=12)
    parser.add_argument('--rate', type=int, default=30)
    parser.add_argument('--idle-seconds', type=int, default=5)
    args = parser.parse_args()
    if not 4 <= args.seconds <= 30 or not 10 <= args.rate <= 60 or not 2 <= args.idle_seconds <= 10:
        parser.error('Duration 4–30s, rate 10–60Hz, idle duration 2–10s required')
    if args.output.exists():
        parser.error('Evidence path exists; use a fresh per-run output path')
    guard()  # Alpine :0, no WAYLAND variable, no i3lock/slock; before XOpenDisplay
    x = None
    result = dict(status='RUNNING', probe_sha256=digest(Path(__file__)), cases=[], idle=[],
                  protocol_shape_requests=None, allocator_calls=None)
    preferences_before = None
    old_handlers = {}
    def interrupted(_signal, _frame):
        raise KeyboardInterrupt('Owned guest probe interrupted')
    for sig in (signal.SIGTERM, signal.SIGINT):
        old_handlers[sig] = signal.signal(sig, interrupted)
    try:
        x = Display()  # Lease covers environment checks, owned client and cleanup.
        bind(x)
        Composite(x)  # Actual compositor selection owner required.
        wm = wm_identity()
        if not wm['executable_sha256']:
            raise RuntimeError('Actual running WM executable hash unavailable')
        processes = process_set(wm)
        identities = sample(processes)
        wm_config = environment_value(wm['pid'], 'CARPATIC_CONFIG_DIR')
        animation_config = Path(os.environ.get('CARPATIC_CONFIG') or
                                str(Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'carpatic'))
        paths = [animation_config / name for name in ('animations.json', 'reduced-motion', 'window-animations.conf', 'panel.conf')]
        if wm_config:
            wm_candidates = [Path(wm_config)]
        else:
            config_home = Path(environment_value(wm['pid'], 'XDG_CONFIG_HOME') or str(Path.home() / '.config'))
            data_home = Path(environment_value(wm['pid'], 'XDG_DATA_HOME') or str(Path.home() / '.local/share'))
            wm_candidates = [config_home / 'dwm-titus', data_home / 'dwm-titus/config',
                             Path('/usr/share/carpatic-rust/config')]
        for directory in wm_candidates:
            paths.extend(directory / name for name in ('themes.toml', 'hotkeys.toml', 'window-rules.toml'))
        paths = list(dict.fromkeys(paths))
        preferences_before = {str(path): digest(path) for path in paths}
        state = json.loads(command('carpatic-animations', 'get', '--json'))
        config = (animation_config / 'window-animations.conf').read_text()
        backend_match = re.search(r'backend\s*=\s*"(glx|xrender)"', config)
        if not backend_match or not state.get('running'):
            raise RuntimeError('Active generated compositor backend unavailable')
        renderer = command('glxinfo', '-B')
        result.update(wm=wm, alpine=Path('/etc/alpine-release').read_text().strip(),
                      backend=backend_match.group(1), glxinfo=renderer, animation_state=state,
                      preferences_before=preferences_before, process_counts={kind: list(processes.values()).count(kind) for kind in ('wm', 'picom', 'xorg')},
                      rate=args.rate, seconds=args.seconds, final_ack_deadline_seconds=3,
                      note='CPU ticks/RSS/minor faults; minor faults are not allocations. No readback, presentation timestamps, FPS or dwm comparison.')
        def check_identity():
            current = sample(processes)
            for pid in processes:
                if current[pid]['start_ticks'] != identities[pid]['start_ticks']:
                    raise RuntimeError('Process restarted during owned measurement')
            if process_set(wm) != processes:
                raise RuntimeError('Matching process set changed during owned measurement')
            return current
        def idle(label):
            before = check_identity(); start = time.monotonic()
            time.sleep(args.idle_seconds)
            after = check_identity(); elapsed = time.monotonic() - start
            result['idle'].append(dict(kind=label, elapsed_seconds=elapsed,
                                       processes=resource_delta(processes, before, after, elapsed)))
        client = x.create('Owned shape move guest diagnostic', COLOR, 420, 280)
        x.x.XMapWindow(x.handle, client)
        x.message(client, '_NET_ACTIVE_WINDOW', [1, 0, 0, 0, 0])
        frame, title = wait_for_frame(x, client)
        time.sleep(.6)
        require_viewable(client, frame, title)
        for name, arguments in (
                ('XMoveWindow', [c.c_void_p, c.c_ulong, c.c_int, c.c_int]),
                ('XResizeWindow', [c.c_void_p, c.c_ulong, c.c_uint, c.c_uint]),
                ('XFlush', [c.c_void_p])):
            fn = getattr(x.x, name); fn.restype, fn.argtypes = c.c_int, arguments
        workarea = command('xprop', '-root', '_NET_WORKAREA')
        desktop = command('xprop', '-root', '_NET_CURRENT_DESKTOP')
        result.update(client=f'{client:#x}', frame=f'{frame:#x}', workarea=workarea, desktop=desktop)
        def acknowledge(kind, expected):
            until = time.monotonic() + 3
            while True:
                fg, cg = geometry(frame), geometry(client)
                observed = ((fg['X'], fg['Y']) if kind == 'move' else (cg['WIDTH'], cg['HEIGHT']))
                if observed == expected:
                    return fg, cg
                if time.monotonic() >= until:
                    raise RuntimeError(f'Final {kind} request not observed: {observed} != {expected}')
                time.sleep(.01)
        idle('settled-before-workload')
        for index, kind in enumerate(('move', 'resize', 'resize', 'move')):
            guard()  # Refuse if a locker appears between phases; never unlock it.
            x.x.XMoveWindow(x.handle, client, 180, 180)
            x.x.XResizeWindow(x.handle, client, 420, 248)
            x.sync()
            acknowledge('move', (180, 180)); acknowledge('resize', (420, 248))
            time.sleep(.2)
            initial = geometry(frame)
            before = check_identity(); start = time.monotonic()
            lateness = []
            for tick in range(args.seconds * args.rate):
                if tick % (args.rate * 2) == 0:
                    guard()  # Bounded locker recheck; no input is synthesized.
                deadline = start + tick / args.rate
                delay = deadline - time.monotonic()
                if delay > 0: time.sleep(delay)
                phase = tick % 60
                phase = phase if phase <= 30 else 60 - phase
                lateness.append((time.monotonic() - deadline) * 1000)
                if kind == 'move':
                    expected = (180 + phase * 5, 180 + phase * 2)
                    x.x.XMoveWindow(x.handle, client, *expected)
                else:
                    expected = (420 + phase * 3, 248 + phase * 2)
                    x.x.XResizeWindow(x.handle, client, *expected)
                x.x.XFlush(x.handle)
            x.sync()
            final, content = acknowledge(kind, expected)
            time.sleep(.05)
            after = check_identity(); elapsed = time.monotonic() - start
            if kind == 'move' and (initial['WIDTH'], initial['HEIGHT']) != (final['WIDTH'], final['HEIGHT']):
                raise RuntimeError('Position-only workload changed frame size')
            result['cases'].append(dict(index=index, kind=kind, submissions=len(lateness), elapsed_seconds=elapsed,
                                        start_geometry=initial, end_geometry=final, end_content_geometry=content,
                                        processes=resource_delta(processes, before, after, elapsed),
                                        submit_lateness_ms_median=statistics.median(lateness),
                                        submit_lateness_ms_max=max(lateness)))
            idle(f'after-{index}-{kind}')
        result['status'] = 'DIAGNOSTIC'
    except BaseException as error:
        result.update(status='ERROR', failure=str(error))
        raise
    finally:
        try:
            if x is not None:
                x.close()  # Only this probe's client; existing session processes stay live.
        except BaseException as cleanup:
            result.update(status='ERROR', cleanup_error=str(cleanup))
            raise
        finally:
            if preferences_before is not None:
                after = {path: digest(Path(path)) for path in preferences_before}
                result.update(preferences_after=after, preferences_unchanged=after == preferences_before)
                if after != preferences_before:
                    result.update(status='ERROR', preference_error='Session policies changed externally during probe; A/B evidence invalid')
            for sig, handler in old_handlers.items(): signal.signal(sig, handler)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(status=result['status'], output=str(args.output), cases=len(result['cases']))), flush=True)
    return 0 if result['status'] == 'DIAGNOSTIC' else 1


if __name__ == '__main__':
    raise SystemExit(main())
