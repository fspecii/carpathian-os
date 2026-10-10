#!/bin/sh
# Real Xorg workload inside an explicitly selected disposable VM.
set -eu
cd "$(dirname "$0")/.."
vm=${CARPATIC_TEST_VM:?Select a disposable VM}
scripts/vm-test.sh --name "$vm" wait
results=${CARPATIC_RESULTS_DIR:?Select results directory}
scripts/vm-test.sh --name "$vm" put tests/debug/performance.py /tmp/carpatic-performance.py
scripts/vm-test.sh --name "$vm" ssh 'export CARPATIC_VM_TEST=1 DISPLAY=:0 GDK_BACKEND=x11 CARPATIC_SESSION=1 XDG_CURRENT_DESKTOP=CarpaticRust XDG_RUNTIME_DIR=/tmp/carpatic-runtime-0; [ ! -r /etc/carpatic-test/graphics.env ] || . /etc/carpatic-test/graphics.env; python3 /tmp/carpatic-performance.py' >"$results/performance.jsonl"
cat "$results/performance.jsonl"
