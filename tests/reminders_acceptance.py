#!/usr/bin/env python3
"""VM-only real FDO notification acceptance on owned Xvfb/session bus.

No host bus, :0, installed files, personal data, autostart or screenshots are used.
Run in an explicitly marked Alpine fixture: CARPATIC_VM_TEST=1 python3 this.py --output /artifact/path
"""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'integration/carpatic/reminders/bin/carpatic-reminders'


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(.05)
    raise AssertionError('Acceptance condition timed out')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if (os.environ.get('CARPATIC_VM_TEST') != '1' or 'WAYLAND_DISPLAY' in os.environ
            or not Path('/etc/alpine-release').is_file()):
        raise SystemExit('Refusing notification probe outside explicitly marked isolated Alpine VM')
    for executable in ('Xvfb', 'dbus-daemon', 'dunst', 'dunstctl'):
        if not shutil.which(executable): raise SystemExit('Missing fixture dependency: ' + executable)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()): raise SystemExit('Use a fresh empty acceptance output directory')
    processes = []
    streams = []
    report = {'passed': False, 'physical_visibility_verified': False}
    with tempfile.TemporaryDirectory(prefix='carpatic-reminders-acceptance-', dir='/var/tmp') as temporary:
        fixture = Path(temporary)
        env = dict(os.environ)
        for name in ('DISPLAY', 'WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS', 'DBUS_SESSION_BUS_PID',
                     'DBUS_STARTER_ADDRESS', 'DBUS_STARTER_BUS_TYPE', 'CARPATIC_CONFIG'):
            env.pop(name, None)
        for name, directory in (('XDG_DATA_HOME', 'data'), ('XDG_CONFIG_HOME', 'config'),
                                ('XDG_STATE_HOME', 'state'), ('XDG_RUNTIME_DIR', 'runtime')):
            path = fixture / directory
            path.mkdir(mode=0o700)
            env[name] = str(path)
        env['GDK_BACKEND'] = 'x11'
        def spawn(argv, name, **kwargs):
            stream = (output / (name + '.log')).open('wb')
            streams.append(stream)
            process = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL,
                                       stdout=kwargs.pop('stdout', stream), stderr=stream, **kwargs)
            processes.append(process)
            return process
        def cli(*arguments):
            result = subprocess.run([sys.executable, str(CLI), *arguments], env=env,
                                    capture_output=True, text=True, timeout=5, check=True)
            return json.loads(result.stdout)
        def count():
            result = subprocess.run(['dunstctl', 'count', 'displayed'], env=env,
                                    capture_output=True, text=True, timeout=3, check=True)
            return int(result.stdout.strip())
        try:
            display = next((number for number in range(192, 210)
                            if not Path(f'/tmp/.X11-unix/X{number}').exists()
                            and not Path(f'/tmp/.X{number}-lock').exists()), None)
            if display is None: raise AssertionError('No unoccupied private test display')
            xvfb = spawn(['Xvfb', f':{display}', '-screen', '0', '800x600x24', '-nolisten', 'tcp', '-ac'], 'xvfb')
            wait_for(lambda: xvfb.poll() is None and Path(f'/tmp/.X11-unix/X{display}').is_socket(), 3)
            env['DISPLAY'] = f':{display}'
            bus = spawn(['dbus-daemon', '--session', '--nofork', '--print-address=1'], 'bus', stdout=subprocess.PIPE)
            # Address pipe contains only our newly spawned bus; do not inherit an
            # ambient session address. Startup read is capped by readiness polling.
            import select
            if not select.select([bus.stdout], [], [], 3)[0]: raise AssertionError('Owned bus startup timed out')
            address = bus.stdout.readline().decode().strip()
            if not address.startswith('unix:'): raise AssertionError('Unexpected owned bus transport')
            env['DBUS_SESSION_BUS_ADDRESS'] = address
            import gi
            gi.require_version('Gio', '2.0')
            from gi.repository import Gio, GLib
            connection = Gio.DBusConnection.new_for_address_sync(address,
                Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
            connection.set_exit_on_close(False)
            config = fixture / 'dunstrc'
            config.write_text('[global]\n    timeout = 0\n    notification_limit = 5\n')
            dunst = spawn(['dunst', '-conf', str(config), '-print'], 'dunst')
            def server_ready():
                if dunst.poll() is not None: raise AssertionError('Owned notification server exited')
                return connection.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus',
                    'org.freedesktop.DBus', 'NameHasOwner', GLib.Variant('(s)', ('org.freedesktop.Notifications',)),
                    GLib.VariantType.new('(b)'), Gio.DBusCallFlags.NONE, 500, None).unpack()[0]
            wait_for(server_ready, 3)
            if count() != 0: raise AssertionError('Owned server unexpectedly contains previous notifications')
            overdue = dt.datetime.now() - dt.timedelta(minutes=2)
            reminder = cli('add', 'Owned VM reminder acceptance', '--notes', 'Fixture-only local data',
                           '--due-date', overdue.date().isoformat(), '--due-time', overdue.strftime('%H:%M'))
            ledger = Path(env['XDG_DATA_HOME']) / 'carpatic/reminders/delivery-ledger.json'
            first = spawn([sys.executable, str(CLI), 'notify-service'], 'notifier-first')
            def delivered():
                if first.poll() is not None: raise AssertionError('Notifier exited before acceptance')
                try: return reminder['id'] in json.loads(ledger.read_text())['delivered']
                except (FileNotFoundError, json.JSONDecodeError): return False
            wait_for(delivered, 5)
            wait_for(lambda: count() == 1, 3)
            first_ledger = ledger.read_bytes()
            report['accepted_by_owned_dunst'] = True
            report['displayed_notification_count'] = 1
            # Separate correctness capture after acceptance, never a performance
            # measurement or readback of the VM user's :0 desktop.
            time.sleep(.15)
            capture_code = """import gi, os, sys
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk
display = Gdk.Display.open(os.environ['DISPLAY'])
if display is None: raise SystemExit('Private screenshot display did not open')
root = display.get_default_screen().get_root_window()
image = Gdk.pixbuf_get_from_window(root, 0, 0, 800, 600)
if image is None: raise SystemExit('Private fixture screenshot failed')
image.savev(sys.argv[1], 'png', [], [])
"""
            capture = spawn([sys.executable, '-c', capture_code, str(output / 'due-notification.png')], 'screenshot')
            if capture.wait(timeout=3) != 0: raise AssertionError('Private screenshot child failed')
            report['fixture_screenshot'] = 'due-notification.png'
            cli('edit', reminder['id'], '--title', 'Title edit must not repeat alert')
            time.sleep(.75)
            if count() != 1 or ledger.read_bytes() != first_ledger:
                raise AssertionError('Title edit duplicated an accepted alert')
            first.terminate()
            if first.wait(timeout=5) != 0: raise AssertionError('Normal notifier shutdown failed')
            second = spawn([sys.executable, str(CLI), 'notify-service'], 'notifier-restart')
            time.sleep(1)
            if second.poll() is not None or count() != 1 or ledger.read_bytes() != first_ledger:
                raise AssertionError('Normal restart duplicated or failed to preserve delivery')
            report['normal_restart_deduplicated'] = True
            bus.terminate()
            bus.wait(timeout=3)
            if second.wait(timeout=5) != 0: raise AssertionError('Notifier did not exit cleanly on owned bus closure')
            log = (output / 'notifier-restart.log').read_text()
            if 'session bus closed; stopping' not in log:
                raise AssertionError('Bus-close lifecycle path was not observed')
            lock_path = ledger.parent / 'notifier.lock'
            with lock_path.open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            report['bus_close_exit_and_lock_release'] = True
            shutil.copy2(ledger, output / 'delivery-ledger.json')
            report['private_display'] = f':{display}'
            report['component_sha256'] = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                          for path in sorted((ROOT / 'integration/carpatic/reminders').rglob('*.py'))}
            report['cli_sha256'] = hashlib.sha256(CLI.read_bytes()).hexdigest()
            report['passed'] = True
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
                if process.stdout is not None: process.stdout.close()
            for stream in streams: stream.close()
            (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
