#!/usr/bin/env python3
"""Guest-only compositor A/B probe; CPU percentages use one core as 100%.

Xprop times include client startup and X11 round trip, not frame presentation.
Run only in a disposable Alpine fixture; preferences are restored on exit.
"""
import json
import os
from pathlib import Path
import re
import signal
import statistics
import subprocess
import time


def run(*args):
    return subprocess.check_output(args, text=True, timeout=8).strip()


def snapshot():
    out = {}
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            text = (proc / 'stat').read_text()
            name = text[text.index('(')+1:text.rindex(')')]
            values = text[text.rindex(')')+2:].split()
            if name in ('picom', 'Xorg', 'carpatic-wm'):
                out[int(proc.name)] = (name, int(values[11])+int(values[12]),
                                      int(values[21])*os.sysconf('SC_PAGE_SIZE')//1024)
        except (OSError, ValueError, IndexError):
            pass
    return out


def main():
    if (os.environ.get('CARPATIC_VM_TEST') != '1' or not Path('/etc/alpine-release').exists()
            or os.environ.get('WAYLAND_DISPLAY') or not os.environ.get('DISPLAY')):
        raise RuntimeError('Run only on Xorg inside an explicitly marked disposable Alpine VM')
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    cfg = Path(os.environ.get('CARPATIC_CONFIG') or str(Path.home()/'.config/carpatic'))
    paths = [cfg/'animations.json', cfg/'reduced-motion']
    saved = {path: path.read_bytes() if path.exists() else None for path in paths}
    state = json.loads(run('carpatic-animations', 'get', '--json'))
    desktop = int(run('xprop', '-root', '_NET_CURRENT_DESKTOP').split('=')[1].strip())
    renderer = run('glxinfo', '-B')
    print(json.dumps(dict(kind='environment', alpine=Path('/etc/alpine-release').read_text().strip(),
                         renderer=renderer, cpu_count=os.cpu_count(),
                         note='CPU: 100%=one core; xprop latency is not frame time')), flush=True)
    terminal = subprocess.Popen(['xterm', '-title', 'Carpatic performance probe'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    hz = os.sysconf('SC_CLK_TCK')
    try:
        # Normalize only animation preferences for comparable runs.
        cfg.mkdir(parents=True, exist_ok=True)
        defaults = dict(enabled=True, style='macos', speed='normal', open=True, close=True,
                        minimize=True, geometry=True, workspaces=True, menus=True)
        (cfg/'animations.json').write_text(json.dumps(defaults))
        time.sleep(5)
        for mode in ('glx', 'reduced', 'off', 'xrender', 'auto'):
            os.environ['CARPATIC_ANIMATION_BACKEND'] = 'xrender' if mode == 'xrender' else 'auto' if mode == 'auto' else 'glx'
            run('carpatic-animations', 'set', 'enabled', 'off')
            (cfg/'reduced-motion').unlink(missing_ok=True)
            if mode == 'reduced': (cfg/'reduced-motion').touch()
            if mode != 'off': run('carpatic-animations', 'set', 'enabled', 'on')
            if mode != 'off' and not json.loads(run('carpatic-animations','get','--json'))['running']:
                raise RuntimeError('Compositor did not stay running')
            rendered = (cfg/'window-animations.conf').read_text()
            backend = re.search(r'backend = "([^"]+)"', rendered).group(1)
            time.sleep(2)
            for phase in ('idle', 'workspaces'):
                before = snapshot(); start = time.monotonic(); latency = []
                for i in range(24):
                    if phase == 'workspaces': run('xdotool', 'key', 'super+'+str(1+i%2))
                    tick = time.monotonic()
                    actual = run('xprop', '-root', '_NET_CURRENT_DESKTOP')
                    latency.append((time.monotonic()-tick)*1000)
                    if phase == 'workspaces' and int(actual.split('=')[1].strip()) != i%2:
                        raise RuntimeError('Workspace command was not processed')
                    time.sleep(.25)
                elapsed = time.monotonic()-start; after = snapshot(); cpu = {}; rss = {}
                for pid, (name, ticks, memory) in after.items():
                    rss[name] = rss.get(name, 0)+memory
                    if pid in before:
                        cpu[name] = cpu.get(name, 0)+100*(ticks-before[pid][1])/hz/elapsed
                print(json.dumps(dict(kind='sample', mode=mode, backend=backend, phase=phase,
                                      elapsed_s=round(elapsed,3), cpu_percent={k:round(v,2) for k,v in cpu.items()},
                                      rss_kib=rss, xprop_ms_mean=round(statistics.mean(latency),3),
                                      xprop_ms_p95=round(sorted(latency)[22],3), xprop_ms_max=round(max(latency),3))), flush=True)
    finally:
        terminal.terminate()
        try: terminal.wait(timeout=3)
        except subprocess.TimeoutExpired: terminal.kill(); terminal.wait()
        for path, data in saved.items():
            if data is None: path.unlink(missing_ok=True)
            else: path.write_bytes(data)
        os.environ.pop('CARPATIC_ANIMATION_BACKEND', None)
        if not state['running']:
            run('carpatic-animations', 'set', 'enabled', 'off')
            data = saved[cfg/'animations.json']
            if data is None: (cfg/'animations.json').unlink(missing_ok=True)
            else: (cfg/'animations.json').write_bytes(data)
        else:
            run('carpatic-animations', 'apply')
        run('xdotool', 'key', 'super+'+str(desktop+1))
        print(json.dumps(dict(kind='restored', preferences=True, initial_compositor=state['running'])), flush=True)


if __name__ == '__main__':
    main()
