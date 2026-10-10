#!/bin/sh
# Full installed animation policy matrix on isolated guest Xorg.
set -eu
cd "$(dirname "$0")/.."
vm=${CARPATIC_TEST_VM:?Select a disposable VM}
results=${CARPATIC_RESULTS_DIR:?Select results directory}
scripts/vm-test.sh --name "$vm" wait
scripts/vm-test.sh --name "$vm" ssh 'mkdir -p /var/tmp/carpatic-animation-matrix; rm -f /var/tmp/carpatic-animation-matrix/*.jsonl'
scripts/vm-test.sh --name "$vm" put tests/debug/rendering.py /var/tmp/carpatic-animation-matrix/rendering.py
scripts/vm-test.sh --name "$vm" put tests/debug/animation_matrix.py /var/tmp/carpatic-animation-matrix/animation_matrix.py
rc=0
scripts/vm-test.sh --name "$vm" ssh 'export DISPLAY=:0 GDK_BACKEND=x11 CARPATIC_VM_TEST=1 CARPATIC_SESSION=1 XDG_CURRENT_DESKTOP=CarpaticRust XDG_RUNTIME_DIR=/tmp/carpatic-runtime-0; [ ! -r /etc/carpatic-test/graphics.env ] || . /etc/carpatic-test/graphics.env; python3 /var/tmp/carpatic-animation-matrix/animation_matrix.py --results /var/tmp/carpatic-animation-matrix/results' >"$results/animation-matrix.jsonl" 2>&1 || rc=$?
scripts/vm-test.sh --name "$vm" ssh 'tar -C /var/tmp/carpatic-animation-matrix/results -cf - .' | tar -xf - -C "$results"
cat "$results/animation-matrix.jsonl"
exit "$rc"
