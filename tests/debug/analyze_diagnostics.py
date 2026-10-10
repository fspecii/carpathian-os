#!/usr/bin/env python3
"""Offline summary of buffered compositor events; never labels swaps as FPS."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import re
import statistics


def distribution(values):
    if not values:
        return None
    ordered = sorted(values)
    return dict(count=len(values), median=statistics.median(values),
                p95=ordered[min(len(values) - 1, int(len(values) * .95))],
                p99=ordered[min(len(values) - 1, int(len(values) * .99))], maximum=max(values))


def analyze(path, window=None):
    with path.open() as stream:
        header = stream.readline()
        match = re.fullmatch(r'# carpatic-picom-diag-v1 count=(\d+) overflow=(\d+) capacity=(\d+)\n', header)
        if not match or int(match[2]) != 0:
            raise ValueError('Missing/overflowed telemetry: ' + str(path))
        rows = [{k: int(v) for k, v in row.items()} for row in csv.DictReader(stream)]
    if len(rows) != int(match[1]) or not rows:
        raise ValueError('Incomplete telemetry: ' + str(path))
    if [r['sequence'] for r in rows] != list(range(len(rows))):
        raise ValueError('Sequence discontinuity')
    if any(a['monotonic_ns'] > b['monotonic_ns'] for a, b in zip(rows, rows[1:])):
        raise ValueError('Nonmonotonic event clock')
    all_rows = rows
    starts = {r['render']: r for r in rows if r['kind'] == 2}
    if window is not None:
        rows = [r for r in rows if window[0] <= r['monotonic_ns'] <= window[1]]
    successful = [r for r in rows if r['kind'] == 3 and r['flags'] == 1]
    if any(r['render'] not in starts for r in successful):
        raise ValueError('Renderer result without its attempt')
    kinds = Counter(r['kind'] for r in rows)
    def occupancy(begin, end):
        active = {}
        values = []
        for row in all_rows:
            if row['kind'] == begin:
                active[row['render']] = row['monotonic_ns']
            elif row['kind'] == end:
                if row['render'] not in active:
                    raise ValueError('Return without begin')
                begin_ns = active.pop(row['render'])
                if window is None or window[0] <= begin_ns <= row['monotonic_ns'] <= window[1]:
                    values.append((row['monotonic_ns'] - begin_ns) / 1e6)
        if active:
            raise ValueError('Incomplete call pair')
        return distribution(values)
    scheduler = [r for r in rows if r['kind'] in (8, 11)]
    valid_present = [r for r in rows if r['kind'] == 7 and r['a'] > 0 and r['c'] == 0]
    return dict(file=path.name, records=len(all_rows), analyzed_events=len(rows),
                workload_window_monotonic_ns=window, overflow=0, event_counts=dict(kinds),
                successful_renderer_calls=len(successful),
                failed_renderer_calls=sum(r['kind'] == 3 and r['flags'] == 0 for r in rows),
                renderer_call_ms=distribution([(r['monotonic_ns'] - starts[r['render']]['monotonic_ns']) / 1e6 for r in successful]),
                renderer_return_interval_ms=distribution([(b['monotonic_ns'] - a['monotonic_ns']) / 1e6 for a, b in zip(successful, successful[1:])]),
                callback_target_lateness_ms=distribution([(r['monotonic_ns'] / 1000 - r['a']) / 1000 for r in rows if r['kind'] == 1 and r['a'] > 0]),
                glx_swap_call_ms=occupancy(4, 5), xrender_present_call_ms=occupancy(6, 13),
                existing_gpu_elapsed_ms=distribution([r['b'] / 1e6 for r in rows if r['kind'] == 10 and r['a']]),
                scheduler_raw_events=len(scheduler), scheduler_invalid_or_synthetic=sum(bool(r['flags']) for r in scheduler),
                valid_raw_pixmap_completions=len(valid_present),
                note=('Timed workload event window' if window else 'Whole lifetime including startup/teardown') + '; guest submission/call timing, not physical presentation or FPS.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    runs = json.loads((args.directory / 'runs.json').read_text())
    if not runs['managed_compositor_restored'] or len(runs['runs']) != 8:
        raise ValueError('Incomplete experiment or compositor cleanup')
    by_label = {run['label']: run for run in runs['runs']}
    summaries = []
    for path in sorted(args.directory.glob('*.csv')):
        workload = by_label[path.stem]['workload']
        window = None
        if 'workload_start_monotonic_ns' in workload:
            window = [workload['workload_start_monotonic_ns'], workload['workload_end_monotonic_ns']]
        summaries.append(analyze(path, window))
    if len(summaries) != 4:
        raise ValueError('Expected four enabled diagnostic traces')
    print(json.dumps(dict(telemetry=summaries, experiment=runs), indent=2))


if __name__ == '__main__':
    main()
