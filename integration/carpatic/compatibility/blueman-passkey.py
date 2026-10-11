#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Compatibility adaptation for Blueman's GPL-licensed BluezAgent numeric filter.
"""Avoid GtkEditable insert-text in/out marshaling; preserve numeric validation."""
import importlib.util
import os
from pathlib import Path
import stat
import tempfile

OLD_FILTER = '''        def on_insert_text(editable: Gtk.Entry, new_text: str, _new_text_length: int, _position: int) -> None:
            if not new_text.isdigit():
                editable.stop_emission("insert-text")
'''
NEW_FILTER = '''        # Carpathian compatibility: GtkEditable insert-text's in/out position
        # triggers a PyGObject critical. Validate changed text without that signal.
        previous_text = ""
        def on_numeric_changed(editable: Gtk.Entry) -> None:
            nonlocal previous_text
            text = editable.get_text()
            if all("0" <= char <= "9" for char in text):
                previous_text = text
                return
            position = editable.get_position()
            editable.set_text(previous_text)
            editable.set_position(min(max(position, 0), len(previous_text)))
'''
OLD_CONNECT = '            pin_entry.connect("insert-text", on_insert_text)'
NEW_CONNECT = '            pin_entry.connect("changed", on_numeric_changed)'


def transform(source):
    if NEW_FILTER in source or NEW_CONNECT in source:
        if (source.count(NEW_FILTER) == source.count(NEW_CONNECT) == 1
                and OLD_FILTER not in source and OLD_CONNECT not in source):
            return source
        raise ValueError('Unsupported partially patched Blueman numeric filter')
    if source.count(OLD_FILTER) != 1 or source.count(OLD_CONNECT) != 1:
        raise ValueError('Unsupported Blueman numeric filter; review compatibility before installation')
    return source.replace(OLD_FILTER, NEW_FILTER).replace(OLD_CONNECT, NEW_CONNECT)


def main():
    if os.getuid() != 0: raise SystemExit('Install Blueman compatibility as root')
    spec = importlib.util.find_spec('blueman.main.applet.BluezAgent')
    if spec is None or not spec.origin: raise SystemExit('Blueman agent module is missing')
    path = Path(spec.origin)
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
        raise SystemExit('Blueman agent source must be a root-owned regular file')
    source = path.read_text(); updated = transform(source)
    if updated == source: return
    descriptor, name = tempfile.mkstemp(prefix='.carpathian-blueman-', dir=path.parent)
    try:
        os.fchmod(descriptor, stat.S_IMODE(metadata.st_mode))
        with os.fdopen(descriptor, 'w') as file:
            file.write(updated); file.flush(); os.fsync(file.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)
    print('Installed Blueman numeric-input compatibility')


if __name__ == '__main__': main()
