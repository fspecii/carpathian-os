#!/bin/sh
# Check each project shell entry point (sh -n accepts only one script at a time).
set -eu
cd "$(dirname "$0")/.."
for script in scripts/*.sh alpine/*.sh tests/*.sh tests/legacy/*.sh tests/legacy/lib/*.sh tests/legacy/guest/*.sh; do
    sh -n "$script"
done
python3 -m py_compile scripts/vm-test.py tests/debug/*.py integration/carpatic/panel/lib/carpatic_panel/popup.py integration/carpatic/panel/lib/carpatic_panel/motion.py
printf 'Shell syntax and diagnostic Python compilation passed.\n'
