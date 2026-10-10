#!/usr/bin/env python3
"""Private-Xvfb move/resize WM CPU diagnostic; NOT a wire-request oracle.

Runs an existing unmodified HOST WM executable on its own authenticated Xvfb.
No builds, VM access, compositor, screenshots or real desktop connection.
Protocol/allocator counts remain null: strace byte totals cannot identify SHAPE
requests reliably, and xtrace is not an available verified dependency here.
For A/B comparison run the exact same command separately for each frozen binary,
with no concurrent builds or suites. Xvfb results do not prove real-Xorg speed.
"""
import argparse
import ctypes as c
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rendering import Display, COLOR
from frame_surface import wait_for_frame, bind, geometry


def process_sample(pid):
    raw = Path(f'/proc/{pid}/stat').read_text()
    fields = raw[raw.rindex(')') + 2:].split()
    return dict(start_ticks=int(fields[19]), cpu_ticks=int(fields[11]) + int(fields[12]),
                minor_faults=int(fields[7]), rss_kib=int(fields[21]) * os.sysconf('SC_PAGE_SIZE') // 1024)


def stop_owned(process):
    if process is None:
        return
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wm', required=True, type=Path, help='Existing host-compatible frozen WM executable')
    parser.add_argument('--display', type=int, default=193, help='Unused private display number, 90–299')
    parser.add_argument('--seconds', type=int, default=12)
    parser.add_argument('--rate', type=int, default=30)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if not 90 <= args.display <= 299 or not 4 <= args.seconds <= 30 or not 10 <= args.rate <= 60:
        parser.error('Display must be 90–299, duration 4–30s, submission rate 10–60Hz')
    wm_path = args.wm.resolve(strict=True)
    if not wm_path.is_file() or not os.access(wm_path, os.X_OK):
        parser.error('WM must be an existing executable; this harness never builds it')
    for dependency in ('Xvfb', 'xauth', 'xprop', 'xdotool'):
        if not shutil.which(dependency):
            parser.error(f'Required installed dependency unavailable: {dependency}')
    display = f':{args.display}'
    if Path(f'/tmp/.X11-unix/X{args.display}').exists() or Path(f'/tmp/.X{args.display}-lock').exists():
        parser.error('Private display is already present; never attach to an existing server')
    if args.output.exists():
        parser.error('Output path already exists; keep each benchmark run immutable')
    binary_hash = hashlib.sha256(wm_path.read_bytes()).hexdigest()
    xvfb = wm = x = None
    cases = []
    with tempfile.TemporaryDirectory(prefix='carpatic-shape-benchmark-') as temporary:
        scratch = Path(temporary)
        config = scratch / 'config'; config.mkdir(mode=0o700)
        runtime = scratch / 'runtime'; runtime.mkdir(mode=0o700)
        (config / 'themes.toml').write_text("[appearance]\nworkspaces=4\ndefault_layout='float'\nborderpx=2\ncorner_radius=8\n[titlebar]\nenabled=1\nheight=32\nbutton_style='windows'\n")
        (config / 'window-rules.toml').write_text('rules=[]\n')
        authority = scratch / 'Xauthority'
        authority.touch(mode=0o600)
        # Disposable authentication cookie goes only to xauth stdin, never logs.
        subprocess.run(['xauth', '-f', str(authority)], input=f'add {display} . {secrets.token_hex(16)}\n',
                       text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
        environment = dict(os.environ)
        environment.pop('WAYLAND_DISPLAY', None)
        environment.pop('CARPATIC_VM_TEST', None)
        environment.update(DISPLAY=display, XAUTHORITY=str(authority), CARPATIC_CONFIG_DIR=str(config),
                           XDG_RUNTIME_DIR=str(runtime), CARPATIC_WM_TEST_DISPLAY='1', CARPATIC_SESSION='1')
        server_log = open(scratch / 'xvfb.log', 'w')
        wm_log = open(scratch / 'wm.log', 'w')
        previous = {name: os.environ.get(name) for name in ('DISPLAY', 'XAUTHORITY', 'WAYLAND_DISPLAY',
                                                         'CARPATIC_VM_TEST', 'CARPATIC_CONFIG_DIR', 'XDG_RUNTIME_DIR')}
        try:
            xvfb = subprocess.Popen(['Xvfb', display, '-screen', '0', '1280x800x24', '-nolisten', 'tcp',
                                     '-noreset', '-auth', str(authority)], stdout=server_log,
                                    stderr=subprocess.STDOUT, env=environment, start_new_session=True)
            until = time.monotonic() + 5
            while not Path(f'/tmp/.X11-unix/X{args.display}').exists():
                if xvfb.poll() is not None or time.monotonic() >= until:
                    raise RuntimeError('Owned Xvfb failed to become ready')
                time.sleep(.05)
            if xvfb.poll() is not None:
                raise RuntimeError('Owned Xvfb exited before WM startup')
            wm = subprocess.Popen([str(wm_path)], env=environment, stdout=wm_log,
                                  stderr=subprocess.STDOUT, start_new_session=True)
            until = time.monotonic() + 5
            while True:
                if wm.poll() is not None or xvfb.poll() is not None:
                    raise RuntimeError('Owned WM/Xvfb exited during startup')
                state = subprocess.run(['xprop', '-root', '_NET_SUPPORTING_WM_CHECK'], env=environment,
                                       text=True, capture_output=True, timeout=2)
                if state.returncode == 0 and 'window id #' in state.stdout:
                    break
                if time.monotonic() >= until:
                    raise RuntimeError('WM support metadata not published')
                time.sleep(.05)
            os.environ.update({key: environment[key] for key in ('DISPLAY', 'XAUTHORITY', 'CARPATIC_CONFIG_DIR', 'XDG_RUNTIME_DIR')})
            os.environ.pop('WAYLAND_DISPLAY', None)
            os.environ.pop('CARPATIC_VM_TEST', None)
            x = Display(); bind(x)
            client = x.create('Owned shape CPU workload', COLOR, 420, 280)
            x.x.XMapWindow(x.handle, client)
            frame, _ = wait_for_frame(x, client)
            x.x.XMoveWindow.argtypes = [c.c_void_p, c.c_ulong, c.c_int, c.c_int]
            x.x.XMoveWindow.restype = c.c_int
            x.x.XResizeWindow.argtypes = [c.c_void_p, c.c_ulong, c.c_uint, c.c_uint]
            x.x.XResizeWindow.restype = c.c_int
            x.x.XFlush.argtypes = [c.c_void_p]
            x.x.XFlush.restype = c.c_int
            time.sleep(.5)
            # ABBA order reduces one simple ordering bias; repeat whole runs for
            # independent binary A/B, preserving exact config/rate/workload.
            for index, kind in enumerate(('move', 'resize', 'resize', 'move')):
                x.x.XMoveWindow(x.handle, client, 180, 180)
                x.x.XResizeWindow(x.handle, client, 420, 248)
                x.sync(); time.sleep(.2)
                start_geometry = geometry(frame)
                before = process_sample(wm.pid)
                start = time.monotonic()
                lateness = []
                for tick in range(args.seconds * args.rate):
                    if wm.poll() is not None or xvfb.poll() is not None:
                        raise RuntimeError('Owned process exited during workload')
                    deadline = start + tick / args.rate
                    delay = deadline - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
                    phase = tick % 60
                    phase = phase if phase <= 30 else 60 - phase
                    lateness.append((time.monotonic() - deadline) * 1000)
                    if kind == 'move':
                        last_request = (180 + phase * 5, 180 + phase * 2)
                        x.x.XMoveWindow(x.handle, client, *last_request)
                    else:
                        last_request = (420 + phase * 3, 248 + phase * 2)
                        x.x.XResizeWindow(x.handle, client, *last_request)
                    x.x.XFlush(x.handle)
                # Include a bounded drain so submitted WM requests are processed;
                # CPU interval explicitly includes this, rather than equating
                # request submission with physical presentation.
                x.sync()
                drain_until = time.monotonic() + 3
                while True:
                    end_geometry = geometry(frame)
                    content_geometry = geometry(client)
                    observed = ((end_geometry['X'], end_geometry['Y']) if kind == 'move'
                                else (content_geometry['WIDTH'], content_geometry['HEIGHT']))
                    if observed == last_request:
                        break
                    if time.monotonic() >= drain_until or wm.poll() is not None:
                        raise RuntimeError(f'Final {kind} request not observed: {observed} != {last_request}')
                    time.sleep(.01)
                time.sleep(.05)
                after = process_sample(wm.pid)
                elapsed = time.monotonic() - start
                if before['start_ticks'] != after['start_ticks']:
                    raise RuntimeError('WM identity changed during benchmark')
                if kind == 'move' and (start_geometry['WIDTH'], start_geometry['HEIGHT']) != (end_geometry['WIDTH'], end_geometry['HEIGHT']):
                    raise RuntimeError('Move-only workload changed frame size')
                cases.append(dict(index=index, kind=kind, submissions=len(lateness), elapsed_seconds=elapsed,
                                  wm_cpu_seconds=(after['cpu_ticks'] - before['cpu_ticks']) / os.sysconf('SC_CLK_TCK'),
                                  wm_cpu_percent_one_core=100 * (after['cpu_ticks'] - before['cpu_ticks']) / os.sysconf('SC_CLK_TCK') / elapsed,
                                  wm_rss_kib=after['rss_kib'], minor_fault_delta=after['minor_faults'] - before['minor_faults'],
                                  submit_lateness_ms_max=max(lateness), start_geometry=start_geometry, end_geometry=end_geometry,
                                  protocol_shape_requests=None, allocator_calls=None))
            result = dict(status='DIAGNOSTIC', backend='private authenticated Xvfb, no compositor',
                          wm_sha256=binary_hash, wm_path=str(wm_path), rate=args.rate, cases=cases,
                          protocol_oracle='Unavailable: xtrace not verified; strace byte accounting is not SHAPE request counting',
                          limitations='WM CPU ticks/RSS/minor faults only; minor faults are not allocations. No real-Xorg, animation, FPS or speed superiority proof.')
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + '\n')
        except BaseException as error:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(dict(status='ERROR', failure=str(error), wm_sha256=binary_hash, cases=cases), indent=2) + '\n')
            raise
        finally:
            try:
                if x is not None:
                    x.close()
            finally:
                stop_owned(wm)
                stop_owned(xvfb)
                server_log.close(); wm_log.close()
                args.output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(scratch / 'xvfb.log', args.output.with_suffix('.xvfb.log'))
                shutil.copyfile(scratch / 'wm.log', args.output.with_suffix('.wm.log'))
                for key, value in previous.items():
                    if value is None: os.environ.pop(key, None)
                    else: os.environ[key] = value
    print(json.dumps(dict(output=str(args.output), cases=len(cases), status='DIAGNOSTIC')))


if __name__ == '__main__':
    main()
