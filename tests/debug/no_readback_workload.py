#!/usr/bin/env python3
"""Bounded deterministic X11 workload; no screenshot or GPU readback calls.

Reports request submission scheduling and CPU/RSS only.
Pair with compositor telemetry; these are not physical presentation timestamps.
"""
import argparse
import ctypes as c
import json
import os
from pathlib import Path
import statistics
import time

from rendering import Display, COLOR


def snapshot():
    result = {}
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            raw = (proc / 'stat').read_text()
            name = raw[raw.index('(') + 1:raw.rindex(')')]
            if name not in ('picom', 'Xorg', 'carpatic-wm', 'xfdesktop'):
                continue
            fields = raw[raw.rindex(')') + 2:].split()
            result[int(proc.name)] = (name, int(fields[11]) + int(fields[12]),
                                     int(fields[21]) * os.sysconf('SC_PAGE_SIZE') // 1024)
        except (OSError, ValueError, IndexError):
            pass
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=12)
    args = parser.parse_args()
    if not 4 <= args.seconds <= 60:
        parser.error('duration must be 4–60 seconds')
    if (os.environ.get('CARPATIC_VM_TEST') != '1' or not Path('/etc/alpine-release').is_file()
            or os.environ.get('DISPLAY') != ':0' or 'WAYLAND_DISPLAY' in os.environ):
        raise SystemExit('Explicit isolated Alpine Xorg :0 only')
    if any((p / 'comm').read_text().strip() == 'i3lock'
           for p in Path('/proc').glob('[0-9]*') if (p / 'comm').exists()):
        raise SystemExit('Fixture locked')
    x = Display()
    x.x.XMoveResizeWindow.argtypes = [c.c_void_p, c.c_ulong, c.c_int, c.c_int, c.c_uint, c.c_uint]
    x.x.XFlush.argtypes = [c.c_void_p]
    sample_start_ns = time.monotonic_ns()
    sample_start = sample_start_ns / 1e9
    before = snapshot()
    timings = []
    try:
        window = x.create('Carpathian no-readback diagnostic workload', COLOR, 500, 260)
        x.x.XMapWindow(x.handle, window)
        x.sync()
        time.sleep(.75)
        start_ns = time.monotonic_ns()
        start = start_ns / 1e9
        for tick in range(args.seconds * 30):
            deadline = start + tick / 30
            delay = deadline - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            phase = tick % 60
            phase = phase if phase <= 30 else 60 - phase
            request = time.monotonic()
            x.x.XMoveResizeWindow(x.handle, window, 180 + phase * 7,
                                  180 + phase * 3, 500 + phase * 4, 260 + phase)
            x.x.XFlush(x.handle)
            timings.append((request - deadline) * 1000)
        x.sync()
        end_ns = time.monotonic_ns()
        elapsed = end_ns / 1e9 - start
        after = snapshot()
        sample_elapsed = time.monotonic() - sample_start
        hz = os.sysconf('SC_CLK_TCK')
        samples = []
        for pid, (name, ticks, rss) in after.items():
            if pid in before:
                samples.append(dict(pid=pid, name=name, rss_kib=rss,
                                    cpu_percent=100 * (ticks - before[pid][1]) / hz / sample_elapsed))
        print(json.dumps(dict(seconds=elapsed, resource_sample_seconds=sample_elapsed,
                              sample_start_monotonic_ns=sample_start_ns,
                              workload_start_monotonic_ns=start_ns, workload_end_monotonic_ns=end_ns,
                              submissions=len(timings),
                              submit_lateness_ms_median=statistics.median(timings),
                              submit_lateness_ms_p95=sorted(timings)[int(len(timings) * .95)],
                              processes=samples, readback_calls=0,
                              note='Submission schedule and process samples; not presentation/FPS.')))
    finally:
        x.close()


if __name__ == '__main__':
    main()
