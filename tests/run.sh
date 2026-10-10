#!/bin/sh
# Rust test tiers and per-run evidence; no implicit VM or real desktop access.
set -eu
cd "$(dirname "$0")/.."
mode=quick
suites=
vm=
while [ "$#" -gt 0 ]; do
    case "$1" in
        --quick) mode=quick;;
        --standard) mode=standard;;
        --full) mode=full;;
        --suite) shift; suites=${1:?Missing suite list};;
        --vm) shift; vm=${1:?Missing disposable VM name};;
        --list) printf 'daily        quick     isolated updater/display fixtures and Settings search\ncontinuity   manual    visible chrome seams during interrupted geometry motion\nhost         quick     Rust, config, private Xvfb\nthemes       quick     era palette/profile registry and real template rendering\nalpine       standard  native musl build and private guest Xvfb\ndesktop      full      adapted desktop regressions on guest Xvfb\nperformance  manual    real Xorg compositor A/B measurement\nrendering    manual    real Xorg settled-frame pixel regression\nanimations   manual    styles/speeds/backends/action correctness matrix\nflyouts      manual    installed GTK first-paint, opaque slide and reduced motion\nlifecycle    manual    concurrent settings updates and owned compositor recovery\n'; exit 0;;
        --help|-h) printf 'Usage: tests/run.sh [--quick|--standard|--full|--suite host,themes,daily,alpine,desktop,performance,rendering,animations,flyouts,lifecycle,continuity] [--vm NAME]\nCreate a disposable VM first with scripts/vm-test.sh; see tests/README.md.\n'; exit 0;;
        *) printf 'Unknown option: %s\n' "$1" >&2; exit 2;;
    esac
    shift
done
if [ -z "$suites" ]; then
    case "$mode" in quick) suites=host,themes,daily;; standard) suites=host,themes,daily,alpine;; full) suites=host,themes,daily,alpine,desktop;; esac
fi
old_ifs=$IFS; IFS=,
set -- $suites
IFS=$old_ifs
for suite do
    case "$suite" in
        host|themes|daily) :;;
        alpine|desktop|performance|rendering|animations|flyouts|lifecycle|continuity) [ -n "$vm" ] || { echo 'VM suites require --vm NAME (disposable fixture).' >&2; exit 2; };;
        *) printf 'Unknown suite: %s\n' "$suite" >&2; exit 2;;
    esac
done
results=$(mktemp -d "$PWD/artifacts/test-run-$(date +%Y%m%d-%H%M%S)-XXXXXX")
export CARPATIC_RESULTS_DIR=$results CARPATIC_TEST_VM=$vm
printf 'TAP version 13\n' >"$results/results.tap"
printf '# Rust test run\n\nSuites: %s\n\n' "$suites" >"$results/summary.md"
failed=0; n=0
for suite do
    n=$((n+1))
    printf 'Running %s; log: %s/%s.log\n' "$suite" "$results" "$suite"
    rc=0
    case "$suite" in
        host) sh tests/host.sh >"$results/$suite.log" 2>&1 || rc=$?;;
        daily) sh tests/daily.sh >"$results/$suite.log" 2>&1 || rc=$?;;
        themes) python3 tests/theme-port.py >"$results/$suite.log" 2>&1 || rc=$?;;
        alpine) sh tests/alpine.sh >"$results/$suite.log" 2>&1 || rc=$?;;
        desktop) sh tests/legacy-vm.sh >"$results/$suite.log" 2>&1 || rc=$?;;
        continuity) sh tests/continuity.sh >"$results/$suite.log" 2>&1 || rc=$?;;
        lifecycle) sh tests/lifecycle.sh >"$results/$suite.log" 2>&1 || rc=$?;;
        flyouts) sh tests/flyouts.sh >"$results/$suite.log" 2>&1 || rc=$?;;
        animations) sh tests/animations.sh >"$results/$suite.log" 2>&1 || rc=$?;;
        rendering) sh tests/rendering.sh >"$results/$suite.log" 2>&1 || rc=$?;;
        performance) sh tests/performance.sh >"$results/$suite.log" 2>&1 || rc=$?;;
    esac
    if [ "$rc" -eq 0 ]; then line="ok $n - $suite"; state=PASS
    else line="not ok $n - $suite (exit $rc)"; state=FAIL; failed=$((failed+1)); tail -15 "$results/$suite.log"; fi
    printf '%s\n' "$line"; printf '%s\n' "$line" >>"$results/results.tap"
    printf -- '- %s: %s ([log](%s.log))\n' "$suite" "$state" "$suite" >>"$results/summary.md"
done
printf '1..%s\n' "$n" >>"$results/results.tap"
printf '[Latest test results](%s/summary.md)\n' "$(basename "$results")" > artifacts/test-latest.md
printf 'Results: %s (%s failed)\n' "$results" "$failed"
[ "$failed" -eq 0 ]
