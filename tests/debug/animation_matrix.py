#!/usr/bin/env python3
"""Animation correctness matrix in an explicitly owned real-Xorg Alpine VM."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def run(*args):
    return subprocess.check_output(args, text=True, timeout=10).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--iterations', type=int, default=3)
    args = parser.parse_args()
    if not 3 <= args.iterations <= 40:
        parser.error('Iterations must be between 3 and 40')
    if (os.environ.get('CARPATIC_VM_TEST') != '1' or os.environ.get('WAYLAND_DISPLAY')
            or os.environ.get('DISPLAY') != ':0' or not Path('/etc/alpine-release').exists()):
        parser.error('Use only an explicitly marked isolated Alpine Xorg :0 VM')
    cfg = Path.home()/'.config/carpatic'
    paths = [cfg/'animations.json', cfg/'reduced-motion']
    saved = {path: path.read_bytes() if path.exists() else None for path in paths}
    old_backend = os.environ.get('CARPATIC_ANIMATION_BACKEND')
    state = json.loads(run('carpatic-animations', 'get', '--json'))
    args.results.mkdir(parents=True, exist_ok=True)
    failures, samples = 0, 0
    try:
        for backend in ('glx', 'xrender'):
            os.environ['CARPATIC_ANIMATION_BACKEND'] = backend
            for style in ('macos', 'subtle'):
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
                    print(json.dumps(dict(case=case, status='running')), flush=True)
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
                    print(json.dumps(dict(case=case, ok=ok, summary=summary, returncode=result.returncode)), flush=True)
        print(json.dumps(dict(summary=True, cases=12, failed_cases=failures, settled_samples=samples)), flush=True)
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
