#!/usr/bin/env python3
"""Actual GTK focus regression; run only on private Xvfb or an isolated Alpine VM.

Example: unset WAYLAND_DISPLAY; DISPLAY=:97 CARPATIC_XVFB_TEST=1 python3 tests/debug/settings_focus.py
The private-display marker also requires a matching live Xvfb process.
"""
import argparse
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace


def guard():
    if 'WAYLAND_DISPLAY' in os.environ:
        raise SystemExit('WAYLAND_DISPLAY must be unset')
    display = os.environ.get('DISPLAY', '')
    if (os.environ.get('CARPATIC_VM_TEST') == '1'
            and Path('/etc/alpine-release').is_file() and display == ':0'):
        return
    match = re.fullmatch(r':([1-9][0-9]*)(?:\.0)?', display)
    if match and os.environ.get('CARPATIC_XVFB_TEST') == '1':
        target = ':' + match.group(1)
        for process in Path('/proc').iterdir():
            if not process.name.isdigit():
                continue
            try:
                args = (process / 'cmdline').read_bytes().split(b'\0')
                if args and Path(os.fsdecode(args[0])).name == 'Xvfb' and target.encode() in args:
                    return
            except (OSError, PermissionError):
                continue
    raise SystemExit('Refusing GUI test outside a verified private Xvfb or isolated Alpine VM')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings-lib', type=Path, default=Path(__file__).resolve().parents[2]
                        / 'integration/carpatic/settings/lib')
    args = parser.parse_args()
    guard()
    sys.path.insert(0, str(args.settings_lib))
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk
    from cset.ui import Row
    from cset.app import SettingsWindow

    window = Gtk.Window(title='Carpathian isolated settings focus test')
    window.set_default_size(600, 400)
    stack = Gtk.Stack()
    window.add(stack)
    box = Gtk.ListBox()
    stack.add_named(box, 'test')
    rows = {}
    actions = []
    view = SimpleNamespace(scroll_to=lambda row: actions.append(('scroll', row)),
                           flash=lambda row: actions.append(('flash', row)))
    page = SimpleNamespace(pb=SimpleNamespace(find=lambda anchor: rows.get(anchor)), view=view)
    harness = SimpleNamespace(stack=stack, trail=['test'])

    def add(name, controls, expected=None):
        row = Row(name, key=name)
        for control in controls:
            row.add_control(control)
        box.add(row)
        rows[name] = row
        return (name, row, expected if expected is not None else row)

    switch = Gtk.Switch()
    slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
    slider.set_size_request(140, -1)
    entry = Gtk.Entry()
    button = Gtk.Button(label='Configure')
    disabled = Gtk.Button(label='Unavailable')
    disabled.set_sensitive(False)
    nested = Gtk.Box()
    nested_button = Gtk.Button(label='Nested control')
    nested.pack_start(nested_button, False, False, 0)
    hidden = Gtk.Button(label='Hidden')
    available = Gtk.Button(label='Available')
    first = Gtk.Button(label='First')
    second = Gtk.Button(label='Second')
    cases = [add('switch', [switch], switch), add('slider', [slider], slider),
             add('entry', [entry], entry), add('button', [button], button),
             add('disabled fallback', [disabled]), add('information fallback', []),
             add('nested control', [nested], nested_button),
             add('hidden control skipped', [hidden, available], available),
             add('reveal chooses first control again', [first, second], first)]
    window.show_all()
    hidden.hide()
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    try:
        print('1..' + str(len(cases)))
        for number, (name, row, expected) in enumerate(cases, 1):
            window.set_focus(None)
            if name == 'reveal chooses first control again': second.grab_focus()
            actions.clear()
            SettingsWindow.reveal(harness, page, name)
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)
            actual = window.get_focus()
            if actual is not expected:
                raise AssertionError(f'{name}: expected {type(expected).__name__}, got {type(actual).__name__}')
            if actions != [('scroll', row), ('flash', row)]:
                raise AssertionError(f'{name}: reveal lost scroll/flash behavior')
            print(f'ok {number} - {name}')
    finally:
        window.destroy()
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)


if __name__ == '__main__':
    main()
