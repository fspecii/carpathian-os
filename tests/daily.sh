#!/bin/sh
# Isolated command fixtures and actual Settings search metadata; no real updates.
set -eu
cd "$(dirname "$0")/.."
python3 tests/update-commands.py
python3 tests/display-commands.py
python3 tests/settings-search.py
python3 tests/desktop-commands.py
python3 tests/desktop-wallpaper.py
python3 tests/reminders.py
python3 tests/reminders_notifier.py
python3 tests/reminders_service.py
python3 tests/session-logging.py
python3 tests/session-process.py
