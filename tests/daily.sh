#!/bin/sh
# Isolated command fixtures and actual Settings search metadata; no real updates.
set -eu
cd "$(dirname "$0")/.."
python3 tests/update-commands.py
python3 tests/update-status.py
python3 tests/display-commands.py
python3 tests/settings-search.py
python3 tests/default-apps.py
python3 tests/desktop-commands.py
python3 tests/desktop-files-settings.py
python3 tests/removable-media-install.py
python3 tests/desktop-wallpaper.py
python3 tests/reminders.py
python3 tests/notes-storage.py
python3 tests/notes-install.py
python3 tests/reminders_notifier.py
python3 tests/reminders_service.py
python3 tests/session-logging.py
python3 tests/session-process.py
python3 integration/carpatic/store/tests/test_architecture.py
