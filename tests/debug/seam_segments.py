#!/usr/bin/env python3
"""Exact-column seam diagnostic and bounded chromatic-bridge classifier.

Preserves the original threshold-8 / maximum-gap-4 decision. Reports whether
unclassified gap pixels resemble known backdrop or a monotonic chroma blend.
The offline report alone is not proof of chrome attachment; runtime controls remain required.
"""
import argparse
import json
from pathlib import Path


def near(a, b, tolerance=8):
    return max(abs(x-y) for x, y in zip(a, b)) <= tolerance


def blend_fit(pixel, chrome, body):
    delta = [b-c for c, b in zip(chrome, body)]
    norm = sum(d*d for d in delta)
    if not norm: return None
    amount = sum((p-c)*d for p, c, d in zip(pixel, chrome, delta))/norm
    expected = [c+amount*d for c, d in zip(chrome, delta)]
    residual = max(abs(p-e) for p, e in zip(pixel, expected))
    return {'amount': amount, 'residual': residual}


def analyze(item, backdrop=None):
    rows = item['sample_column_rgb']
    chrome, body = item['chrome_reference'], item['body_reference']
    edge = item['body_edge_row']
    matching = [i for i in range(max(0, edge-70), edge) if near(rows[i], chrome)]
    gap = edge-max(matching)-1 if matching else 999
    first = max(matching)+1 if matching else max(0, edge-70)
    pixels = rows[first:edge]
    fits = [blend_fit(p, chrome, body) for p in pixels]
    valid = bool(pixels) and all(f and 0 <= f['amount'] <= 1 and f['residual'] <= 8 for f in fits)
    monotonic = valid and all(a['amount'] <= b['amount'] + .02 for a, b in zip(fits, fits[1:]))
    background_rows = [first+i for i, p in enumerate(pixels) if backdrop is not None and near(p, backdrop)]
    return {'legacy_gap': gap, 'legacy_failed': gap > 4, 'recorded_gap_matches': gap == item.get('gap', gap),
            'gap_rows': list(range(first, edge)), 'gap_rgb': pixels, 'blend_fits': fits,
            'monotonic_blend_candidate': monotonic, 'known_backdrop_rows': background_rows,
            'classification': 'known-backdrop-in-gap' if background_rows else
                              'blend-candidate-unqualified' if monotonic else 'unclassified-gap',
            'acceptance': 'unchanged; runtime attachment still requires independent evidence'}


def classify_seam(rows, edge, chrome, body):
    """Classify visible seam coverage without changing legacy distance limits.

Interior blend residual permits at most one RGB quantization level, unlike
    endpoint color detection's existing eight-level tolerance. Both real chrome
    and a body run must flank the bridge. Any intervening unrelated pixels stay
    a failed legacy gap; long/missing-caption gaps cannot qualify as a bridge.
    """
    matches = [i for i in range(max(0, edge-70), edge) if near(rows[i], chrome)]
    gap = edge-max(matches)-1 if matches else 999
    last = max(matches) if matches else None
    bridge = False
    fits = []
    if last is not None and 0 < gap <= 5 and last >= 1 and edge+15 < len(rows):
        anchored = near(rows[last-1], chrome) and near(rows[edge], body) and near(rows[edge+15], body)
        fits = [blend_fit(p, chrome, body) for p in rows[last+1:edge]]
        contrast = max(abs(a-b) for a, b in zip(chrome, body)) >= 32
        bridge = (anchored and contrast and bool(fits)
                  and all(f and 0 <= f['amount'] <= 1 and f['residual'] <= 1 for f in fits)
                  and all(a['amount'] <= b['amount']+.02 for a, b in zip(fits, fits[1:])))
    return {'gap': gap, 'interpolated_bridge': bridge, 'failed': gap > 4 and not bridge,
            'bridge_fits': fits, 'chrome_matching_rows': matches}


def save_exact_column(item, path):
    """Lossless RGB artifact from original readback; no subsequent X capture."""
    rows = item['sample_column_rgb']
    Path(path).write_bytes(('P6\n1 %d\n255\n' % len(rows)).encode()+bytes(v for row in rows for v in row))


def self_test():
    chrome, body, background = [48, 35, 36], [37, 169, 223], [7, 9, 13]
    blend = [[round(c+(b-c)*n/6) for c, b in zip(chrome, body)] for n in range(1, 6)]
    for transition, expected in [(blend, True), ([background]*5, False)]:
        rows = [chrome]*20+transition+[body]*20
        item = dict(sample_column_rgb=rows, chrome_reference=chrome, body_reference=body, body_edge_row=25, gap=5)
        result = analyze(item, background)
        assert result['legacy_failed'] and result['legacy_gap'] == 5
        assert result['monotonic_blend_candidate'] is expected
        assert bool(result['known_backdrop_rows']) is not expected
    print('PASS blend/background distinction; both legacy gap5 decisions remain FAIL')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('records', nargs='?')
    ap.add_argument('--self-test', action='store_true')
    ap.add_argument('--backdrop', help='Known exact backdrop RGB as R,G,B; omit if unknown')
    ap.add_argument('--columns-dir')
    args = ap.parse_args()
    if args.self_test: self_test(); return
    if not args.records: ap.error('Records JSON required')
    backdrop = list(map(int, args.backdrop.split(','))) if args.backdrop else None
    records = json.loads(Path(args.records).read_text())
    if args.columns_dir: Path(args.columns_dir).mkdir(parents=True, exist_ok=True)
    reports = []
    for index, item in enumerate(records):
        if 'sample_column_rgb' not in item: continue
        report = analyze(item, backdrop)
        report.update(sample_index=index, backend=item.get('backend'), client=item.get('client'))
        reports.append(report)
        if args.columns_dir: save_exact_column(item, Path(args.columns_dir)/('column-%d.ppm' % index))
    print(json.dumps({'samples_with_exact_pixels': len(reports), 'diagnostics': reports}, indent=2))


if __name__ == '__main__': main()
