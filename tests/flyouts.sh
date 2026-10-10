#!/bin/sh
# Actual installed GTK popup first-paint, opaque motion and accessibility checks.
set -eu
cd "$(dirname "$0")/.."
vm=${CARPATIC_TEST_VM:?Select a disposable VM}
results=${CARPATIC_RESULTS_DIR:?Select results directory}
scripts/vm-test.sh --name "$vm" wait
scripts/vm-test.sh --name "$vm" put tests/debug/rendering.py /var/tmp/carpatic-flyout-rendering.py
scripts/vm-test.sh --name "$vm" ssh 'mkdir -p /var/tmp/carpatic-flyout-probe; mv /var/tmp/carpatic-flyout-rendering.py /var/tmp/carpatic-flyout-probe/rendering.py'
scripts/vm-test.sh --name "$vm" put tests/debug/flyout.py /var/tmp/carpatic-flyout-probe/flyout.py
scripts/vm-test.sh --name "$vm" ssh 'export DISPLAY=:0 GDK_BACKEND=x11 CARPATIC_VM_TEST=1 CARPATIC_SESSION=1 XDG_CURRENT_DESKTOP=CarpaticRust XDG_RUNTIME_DIR=/tmp/carpatic-runtime-0; [ ! -r /etc/carpatic-test/graphics.env ] || . /etc/carpatic-test/graphics.env; cfg=$(mktemp -d /var/tmp/carpatic-flyout-config-XXXXXX); trap '\''rm -rf "$cfg"'\'' EXIT; CARPATIC_CONFIG="$cfg" python3 /var/tmp/carpatic-flyout-probe/flyout.py' >"$results/flyouts.jsonl" 2>&1
cat "$results/flyouts.jsonl"

scripts/vm-test.sh --name "$vm" put tests/debug/flyout_lifecycle.py /var/tmp/carpatic-flyout-probe/flyout_lifecycle.py
scripts/vm-test.sh --name "$vm" ssh 'export DISPLAY=:0 GDK_BACKEND=x11 CARPATIC_VM_TEST=1 CARPATIC_SESSION=1 XDG_CURRENT_DESKTOP=CarpaticRust XDG_RUNTIME_DIR=/tmp/carpatic-runtime-0; [ ! -r /etc/carpatic-test/graphics.env ] || . /etc/carpatic-test/graphics.env; python3 /var/tmp/carpatic-flyout-probe/flyout_lifecycle.py' >"$results/flyout-lifecycle.jsonl" 2>&1
cat "$results/flyout-lifecycle.jsonl"

scripts/vm-test.sh --name "$vm" put tests/debug/menu_corners.py /var/tmp/carpatic-flyout-probe/menu_corners.py
scripts/vm-test.sh --name "$vm" ssh 'set -eu; unset WAYLAND_DISPLAY; export DISPLAY=:0 GDK_BACKEND=x11 CARPATIC_VM_TEST=1 CARPATIC_SESSION=1 XDG_CURRENT_DESKTOP=CarpaticRust XDG_RUNTIME_DIR=/tmp/carpatic-runtime-0; [ ! -r /etc/carpatic-test/graphics.env ] || . /etc/carpatic-test/graphics.env; python3 /var/tmp/carpatic-flyout-probe/menu_corners.py --negative-control; python3 /var/tmp/carpatic-flyout-probe/menu_corners.py' >"$results/menu-corners.jsonl" 2>&1
cat "$results/menu-corners.jsonl"
