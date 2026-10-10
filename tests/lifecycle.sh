#!/bin/sh
# Concurrent application and owned compositor crash/recovery in the fixture.
set -eu
cd "$(dirname "$0")/.."
vm=${CARPATIC_TEST_VM:?Select a disposable VM}
results=${CARPATIC_RESULTS_DIR:?Select results directory}
scripts/vm-test.sh --name "$vm" wait
scripts/vm-test.sh --name "$vm" put tests/debug/animation_lifecycle.py /var/tmp/carpatic-animation-lifecycle.py
scripts/vm-test.sh --name "$vm" ssh 'export DISPLAY=:0 GDK_BACKEND=x11 CARPATIC_VM_TEST=1 CARPATIC_SESSION=1 XDG_CURRENT_DESKTOP=CarpaticRust XDG_RUNTIME_DIR=/tmp/carpatic-runtime-0; [ ! -r /etc/carpatic-test/graphics.env ] || . /etc/carpatic-test/graphics.env; python3 /var/tmp/carpatic-animation-lifecycle.py' >"$results/lifecycle.jsonl" 2>&1
cat "$results/lifecycle.jsonl"
