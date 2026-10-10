#!/usr/bin/env python3
"""Run same-binary buffered Picom diagnostics off/on, then restore managed CM."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=12)
    args = parser.parse_args()
    if (os.environ.get('CARPATIC_VM_TEST') != '1' or os.environ.get('CARPATIC_TIMING_OWNED') != '1'
            or os.environ.get('DISPLAY') != ':0' or 'WAYLAND_DISPLAY' in os.environ
            or not Path('/etc/alpine-release').is_file()):
        raise SystemExit('Exclusive isolated Alpine Xorg :0 only')
    if args.binary.name != 'picom' or not args.binary.is_absolute():
        parser.error('use an absolute fixture diagnostic executable named picom')
    if not 4 <= args.seconds <= 60:
        parser.error('duration must be 4–60 seconds')
    for name in ('i3lock', 'slock'):
        if subprocess.run(['pgrep', '-x', name], stdout=subprocess.DEVNULL).returncode == 0:
            raise SystemExit('Fixture locked')
    sys.path.insert(0, '/usr/local/share/carpatic/motion')
    import window_animations as controller
    state = controller.load()
    if not state['enabled'] or state['reduced']:
        raise SystemExit('Normal enabled animation policy required')
    args.results.mkdir(parents=True, exist_ok=False)
    workload = Path(__file__).with_name('no_readback_workload.py')
    pid = controller.owned_pid()
    if pid is None:
        raise SystemExit('Managed compositor must initially be alive')
    config = controller.config_dir()
    preference_paths = [config / 'animations.json', config / 'reduced-motion']
    saved = {p: p.read_bytes() if p.exists() else None for p in preference_paths}
    process = None
    lock = (controller.runtime_dir() / 'apply.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    records = []
    try:
        controller.signal_owned(pid, signal.SIGTERM)
        deadline = time.monotonic() + 3
        while controller.owned_pid() == pid and time.monotonic() < deadline:
            time.sleep(.02)
        if controller.owned_pid() == pid:
            raise RuntimeError('Managed compositor failed to stop')
        for backend in ('glx', 'xrender'):
            conf = args.results / f'{backend}.conf'
            conf.write_text(controller.render(state, backend))
            for index, enabled in enumerate((False, True, True, False)):
                label = f'{backend}-{index}-' + ('on' if enabled else 'off')
                env = dict(os.environ)
                env.pop('CARPATIC_PICOM_DIAGNOSTIC', None)
                telemetry = args.results / f'{label}.csv'
                if enabled:
                    env['CARPATIC_PICOM_DIAGNOSTIC'] = str(telemetry)
                with (args.results / f'{label}-compositor.log').open('wb') as log:
                    process = subprocess.Popen([str(args.binary), '--config', str(conf)], env=env,
                                               stdin=subprocess.DEVNULL, stdout=log, stderr=log)
                    time.sleep(1)
                    if process.poll() is not None:
                        raise RuntimeError('Diagnostic compositor startup failed: ' + label)
                    result = subprocess.run([sys.executable, str(workload), '--seconds', str(args.seconds)],
                                            env=env, capture_output=True, text=True, timeout=args.seconds + 10)
                    (args.results / f'{label}-workload.log').write_text(result.stdout + result.stderr)
                    result.check_returncode()
                    # Picom13 registers SIGINT for orderly event-loop exit;
                    # SIGTERM uses default termination and cannot flush atexit.
                    process.send_signal(signal.SIGINT)
                    status = process.wait(timeout=5)
                    process = None
                    if status != 0:
                        raise RuntimeError('Diagnostic compositor did not exit normally')
                if enabled:
                    header = telemetry.open().readline().strip()
                    if 'overflow=0 ' not in header or 'count=0 ' in header:
                        raise RuntimeError('Telemetry missing or overflowed: ' + header)
                records.append(dict(label=label, backend=backend, instrumented=enabled,
                                    config_sha256=hashlib.sha256(conf.read_bytes()).hexdigest(),
                                    workload=json.loads(result.stdout)))
        if any((p.read_bytes() if p.exists() else None) != value for p, value in saved.items()):
            raise RuntimeError('Preference mutation during exclusive diagnostic experiment')
    finally:
        if process is not None and process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        lock.close()
        controller.apply()
        (args.results / 'runs.json').write_text(json.dumps(dict(
            binary_sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest(),
            state=state, runs=records, managed_compositor_restored=controller.owned_pid() is not None), indent=2))
    print(json.dumps(dict(runs=len(records), passed=True, scope='diagnostic submission timing, not physical presentation')))


if __name__ == '__main__':
    main()
