#!/usr/bin/env python3
"""Concurrent live updates and crash recovery on an owned Alpine Xorg fixture."""
import concurrent.futures
import ctypes as c
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import time

if (os.environ.get('CARPATIC_VM_TEST') != '1' or not Path('/etc/alpine-release').exists()
        or os.environ.get('DISPLAY') != ':0' or os.environ.get('WAYLAND_DISPLAY')):
    raise SystemExit('Isolated Alpine Xorg :0 only')
spec = importlib.util.spec_from_file_location('motion', '/usr/local/share/carpatic/motion/window_animations.py')
motion = importlib.util.module_from_spec(spec); spec.loader.exec_module(motion)
original = motion.load()
if not original['enabled'] or motion.owned_pid() is None:
    raise SystemExit('Start the fixture compositor before the lifecycle check')
paths = [motion.config_dir() / name for name in ('animations.json', 'reduced-motion')]
saved = {path: path.read_bytes() if path.exists() else None for path in paths}

def run(*argv):
    return subprocess.check_output(argv, text=True, timeout=20).strip()

def owners():
    matches = []
    expected = str(motion.config_dir() / 'window-animations.conf').encode()
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            argv = (proc / 'cmdline').read_bytes().split(b'\0')
            if argv and Path(os.fsdecode(argv[0])).name == 'picom' and expected in argv:
                matches.append(int(proc.name))
        except (OSError, ValueError): pass
    return matches

x = c.CDLL('libX11.so.6')
x.XOpenDisplay.argtypes = [c.c_char_p]; x.XOpenDisplay.restype = c.c_void_p
x.XInternAtom.argtypes = [c.c_void_p, c.c_char_p, c.c_int]; x.XInternAtom.restype = c.c_ulong
x.XGetSelectionOwner.argtypes = [c.c_void_p, c.c_ulong]; x.XGetSelectionOwner.restype = c.c_ulong
x.XCloseDisplay.argtypes = [c.c_void_p]
handle = x.XOpenDisplay(None)
assert handle, 'Display unavailable'
selection = x.XInternAtom(handle, b'_NET_WM_CM_S0', 0)
clients = run('xprop', '-root', '_NET_CLIENT_LIST')
measurements = []
try:
    for iteration in range(18):
        state = dict(original)
        state['speed'] = ('slow', 'normal', 'fast')[iteration % 3]
        state['style'] = ('macos', 'subtle')[iteration % 2]
        state['enabled'] = iteration % 6 != 5
        reduced = paths[1]
        if iteration % 6 == 4: reduced.touch()
        else: reduced.unlink(missing_ok=True)
        motion.save(state)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(run, 'carpatic-animations', 'apply') for _ in range(4)]
            for future in futures: future.result()
        active = owners()
        assert len(active) == int(state['enabled']), active
        owner = x.XGetSelectionOwner(handle, selection)
        assert bool(owner) == state['enabled'], 'Compositor selection has wrong ownership'
        memory = None
        if active:
            assert motion.owned_pid() == active[0], 'Controller has a different owner'
            status = Path(f'/proc/{active[0]}/status').read_text().splitlines()
            memory = int(next(line.split()[1] for line in status if line.startswith('VmRSS:')))
        assert run('xprop', '-root', '_NET_CLIENT_LIST') == clients, 'Live update lost a client'
        result = dict(iteration=iteration, concurrent_applies=4, enabled=state['enabled'],
                      owners=active, selection=owner, rss_kib=memory, ok=True)
        measurements.append(result); print(json.dumps(result), flush=True)
    state['enabled'] = True; motion.save(state); motion.apply()
    old = motion.owned_pid(); assert old is not None
    os.kill(old, signal.SIGKILL)
    time.sleep(.2)
    motion.apply()
    active = owners()
    assert len(active) == 1 and active[0] != old and motion.owned_pid() == active[0], active
    assert x.XGetSelectionOwner(handle, selection), 'Recovery did not own compositor selection'
    assert run('xprop', '-root', '_NET_CLIENT_LIST') == clients, 'Recovery lost a client'
    print(json.dumps(dict(crash_recovery=True, previous=old, owner=active[0], ok=True)), flush=True)
    print(json.dumps(dict(summary=True, cycles=len(measurements), applies=72, failed=0)), flush=True)
finally:
    for path, data in saved.items():
        if data is None: path.unlink(missing_ok=True)
        else: motion.atomic_write(path, data.decode())
    motion.apply()
    x.XCloseDisplay(handle)
