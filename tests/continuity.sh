#!/bin/sh
# Capture visible native chrome seams during interrupted real-Xorg motion.
set -eu
cd "$(dirname "$0")/.."
vm=${CARPATIC_TEST_VM:?Select a disposable VM}
results=${CARPATIC_RESULTS_DIR:?Select results directory}
scripts/vm-test.sh --name "$vm" wait
scripts/vm-test.sh --name "$vm" ssh 'mkdir -p /var/tmp/carpatic-continuity'
scripts/vm-test.sh --name "$vm" put tests/debug/rendering.py /var/tmp/carpatic-continuity/rendering.py
scripts/vm-test.sh --name "$vm" put tests/debug/continuity.py /var/tmp/carpatic-continuity/continuity.py
rc=0
scripts/vm-test.sh --name "$vm" ssh 'unset WAYLAND_DISPLAY; export DISPLAY=:0 GDK_BACKEND=x11 CARPATIC_VM_TEST=1 CARPATIC_SESSION=1 XDG_CURRENT_DESKTOP=CarpaticRust XDG_RUNTIME_DIR=/tmp/carpatic-runtime-0; [ ! -r /etc/carpatic-test/graphics.env ] || . /etc/carpatic-test/graphics.env; python3 /var/tmp/carpatic-continuity/continuity.py' >"$results/continuity.jsonl" 2>&1 || rc=$?
cat "$results/continuity.jsonl"
scripts/vm-test.sh --name "$vm" get /var/tmp/continuity-records.json "$results/continuity-records.json" || :
exit "$rc"
