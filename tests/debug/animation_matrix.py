#!/usr/bin/env python3
"""Animation correctness matrix in an explicitly owned real-Xorg Alpine VM."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import re
import importlib.util
import ctypes as c


def validate_policy(mode, state, configuration, prepare):
    """Disabled stops Picom; reduced keeps it running with instant scripts."""
    if mode not in ('disabled', 'reduced'):
        raise ValueError('Unknown policy mode')
    if (state.get('enabled') != (mode == 'reduced')
            or state.get('running') != (mode == 'reduced')
            or state.get('reduced') != (mode == 'reduced')):
        raise RuntimeError(f'{mode}: actual controller state violates requested policy')
    if 'duration =' in configuration or 'saved-image-blend =' in configuration:
        raise RuntimeError(f'{mode}: timed animation remains in generated configuration')
    if prepare != 0:
        raise RuntimeError(f'{mode}: WM minimize staging remains enabled')


def validate_backend(configuration, expected, case):
    match = re.search(r'backend\s*=\s*"(glx|xrender)"\s*;', configuration)
    actual = match.group(1) if match else None
    if actual != expected:
        raise RuntimeError(f'{case}: generated backend {actual} != {expected}')
    return actual


def policy_actions(iterations):
    """Settled correctness only; no assertion about presented transition frames."""
    spec = importlib.util.spec_from_file_location('matrix_rendering', Path(__file__).with_name('rendering.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    lock = subprocess.run(['pgrep', '-x', 'i3lock'], stdout=subprocess.DEVNULL, timeout=5)
    if lock.returncode == 0:
        raise RuntimeError('Owned fixture is screen-locked')
    display = module.Display()
    samples = 0
    try:
        display.x.XGetSelectionOwner.restype = c.c_ulong
        display.x.XGetSelectionOwner.argtypes = [c.c_void_p, c.c_ulong]
        owner = display.x.XGetSelectionOwner(display.handle, display.atom('_NET_WM_CM_S0'))
        base = display.create('Carpathian instant-policy fixture', module.COLOR, 400, 260)
        display.x.XMapWindow(display.handle, base)
        display.sync()
        for iteration in range(iterations):
            run('xdotool', 'windowactivate', '--sync', str(base))
            for phase in ('resize', 'maximize', 'restore', 'minimize', 'unminimize'):
                if phase == 'resize':
                    run('xdotool', 'windowsize', str(base), str(400 + iteration % 3 * 40), '260')
                elif phase in ('maximize', 'restore'):
                    display.message(base, '_NET_WM_STATE', [int(phase == 'maximize'), display.atom('_NET_WM_STATE_MAXIMIZED_VERT'), display.atom('_NET_WM_STATE_MAXIMIZED_HORZ'), 1, 0])
                elif phase == 'minimize':
                    display.message(base, 'WM_CHANGE_STATE', [3, 0, 0, 0, 0])
                else:
                    run('xdotool', 'windowactivate', '--sync', str(base))
                time.sleep(.3)
                if phase == 'minimize':
                    if not module.hidden(run('xwininfo', '-id', str(base))):
                        raise RuntimeError('Instant-policy minimize left client viewable')
                else:
                    if module.map_state(run('xwininfo', '-id', str(base))) != 'IsViewable':
                        raise RuntimeError(f'{phase}: instant-policy app is not viewable')
                    if phase in ('maximize', 'restore'):
                        maximized = '_NET_WM_STATE_MAXIMIZED_VERT' in run('xprop', '-id', str(base), '_NET_WM_STATE')
                        if maximized != (phase == 'maximize'):
                            raise RuntimeError(f'{phase}: state request was not applied')
                    pixels, _ = display.pixels(base)
                    if any(pixel != module.COLOR for pixel in pixels):
                        raise RuntimeError(f'{phase}: instant-policy body pixels corrupted')
                    samples += 1
        display.destroy(base)
        return dict(samples=samples, failed=0, compositor_owner=int(owner), scope='settled pixels and actual window states; no transition-timing qualification')
    finally:
        display.close()


def run(*args):
    return subprocess.check_output(args, text=True, timeout=10).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--iterations', type=int, default=3)
    parser.add_argument('--policy-only', action='store_true', help='Run only disabled/reduced modes for both backends (four cases)')
    args = parser.parse_args()
    if not 3 <= args.iterations <= 40:
        parser.error('Iterations must be between 3 and 40')
    if (os.environ.get('CARPATIC_VM_TEST') != '1' or 'WAYLAND_DISPLAY' in os.environ
            or os.environ.get('DISPLAY') != ':0' or not Path('/etc/alpine-release').exists()):
        parser.error('Use only an explicitly marked isolated Alpine Xorg :0 VM')
    cfg = Path.home()/'.config/carpatic'
    paths = [cfg/'animations.json', cfg/'reduced-motion']
    saved = {path: path.read_bytes() if path.exists() else None for path in paths}
    old_backend = os.environ.get('CARPATIC_ANIMATION_BACKEND')
    state = json.loads(run('carpatic-animations', 'get', '--json'))
    args.results.mkdir(parents=True, exist_ok=True)
    failures, samples, active_cases, policy_cases = 0, 0, 0, 0
    try:
        for backend in ('glx', 'xrender'):
            os.environ['CARPATIC_ANIMATION_BACKEND'] = backend
            for style in (() if args.policy_only else ('macos', 'subtle')):
                for speed in ('slow', 'normal', 'fast'):
                    case = f'{backend}-{style}-{speed}'
                    settings = {key: state[key] for key in ('enabled', 'style', 'speed', 'open', 'close', 'minimize', 'geometry', 'workspaces', 'menus')}
                    settings.update(enabled=True, style=style, speed=speed,
                                    open=True, close=True, minimize=True, geometry=True, workspaces=True, menus=True)
                    paths[0].write_text(json.dumps(settings))
                    paths[1].unlink(missing_ok=True)
                    run('carpatic-animations', 'apply')
                    active = json.loads(run('carpatic-animations', 'get', '--json'))
                    if not active['running'] or active['reduced']:
                        raise RuntimeError(f'{case}: compositor did not start with full animations')
                    actual_backend = validate_backend((cfg/'window-animations.conf').read_text(), backend, case)
                    print(json.dumps(dict(case=case, status='running', actual_backend=actual_backend)), flush=True)
                    with (args.results/f'{case}.jsonl').open('w') as output:
                        result = subprocess.run([sys.executable, str(Path(__file__).with_name('rendering.py')),
                                                 '--actions', '--iterations', str(args.iterations)],
                                                stdout=output, stderr=subprocess.STDOUT, timeout=180)
                    summary = None
                    for line in (args.results/f'{case}.jsonl').read_text().splitlines():
                        try:
                            item = json.loads(line)
                            if item.get('summary'): summary = item
                        except json.JSONDecodeError:
                            pass
                    ok = result.returncode == 0 and summary is not None and summary['failed'] == 0
                    samples += summary['samples'] if summary else 0
                    failures += not ok
                    active_cases += 1
                    print(json.dumps(dict(case=case, ok=ok, actual_backend=actual_backend, summary=summary, returncode=result.returncode)), flush=True)
            for mode in ('disabled', 'reduced'):
                case = f'{backend}-{mode}'
                settings = {key: state[key] for key in ('enabled', 'style', 'speed', 'open', 'close', 'minimize', 'geometry', 'workspaces', 'menus')}
                settings.update(enabled=mode == 'reduced', style='macos', speed='normal')
                paths[0].write_text(json.dumps(settings))
                if mode == 'reduced': paths[1].touch(mode=0o600)
                else: paths[1].unlink(missing_ok=True)
                run('carpatic-animations', 'apply')
                active = json.loads(run('carpatic-animations', 'get', '--json'))
                configuration = (cfg/'window-animations.conf').read_text()
                expected_backend = 'xrender' if mode == 'disabled' else backend
                actual_backend = validate_backend(configuration, expected_backend, case)
                prepare_output = run('xprop', '-root', '_CARPATIC_ANIMATION_PREPARE')
                match = re.search(r'=\s*(\d+)\s*$', prepare_output)
                validate_policy(mode, active, configuration, int(match.group(1)) if match else None)
                try:
                    summary = policy_actions(args.iterations)
                    if bool(summary['compositor_owner']) != (mode == 'reduced'):
                        raise RuntimeError(f'{case}: compositor selection owner contradicts policy')
                    ok = True
                except Exception as error:
                    summary = dict(failed=1, samples=0, error=str(error))
                    ok = False
                record = dict(case=case, ok=ok, requested_backend=backend,
                              actual_backend=actual_backend,
                              animation_state=active, summary=summary)
                (args.results/f'{case}.json').write_text(json.dumps(record, indent=2)+'\n')
                samples += summary['samples']
                failures += not ok
                policy_cases += 1
                print(json.dumps(record), flush=True)
        print(json.dumps(dict(summary=True, cases=active_cases + policy_cases, active_cases=active_cases, policy_cases=policy_cases, failed_cases=failures, settled_samples=samples)), flush=True)
        return 1 if failures else 0
    finally:
        for path, data in saved.items():
            if data is None: path.unlink(missing_ok=True)
            else: path.write_bytes(data)
        if old_backend is None: os.environ.pop('CARPATIC_ANIMATION_BACKEND', None)
        else: os.environ['CARPATIC_ANIMATION_BACKEND'] = old_backend
        run('carpatic-animations', 'apply')


if __name__ == '__main__':
    sys.exit(main())
