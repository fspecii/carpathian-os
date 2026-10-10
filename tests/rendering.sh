#!/bin/sh
# Real compositor pixel checks; callers explicitly own the VM and Xorg session.
set -eu
cd "$(dirname "$0")/.."
vm=${CARPATIC_TEST_VM:?Select a disposable VM}
results=${CARPATIC_RESULTS_DIR:?Select results directory}
scripts/vm-test.sh --name "$vm" wait
scripts/vm-test.sh --name "$vm" put tests/debug/rendering.py /tmp/carpatic-rendering.py
scripts/vm-test.sh --name "$vm" ssh 'export DISPLAY=:0 GDK_BACKEND=x11 CARPATIC_VM_TEST=1 CARPATIC_SESSION=1 XDG_CURRENT_DESKTOP=CarpaticRust XDG_RUNTIME_DIR=/tmp/carpatic-runtime-0; [ ! -r /etc/carpatic-test/graphics.env ] || . /etc/carpatic-test/graphics.env; python3 /tmp/carpatic-rendering.py --actions' >"$results/rendering.jsonl"
cat "$results/rendering.jsonl"
