"""Report fixed paired native/INT4 calls, separately by exposure and family."""
import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def read(path):
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    by_key = {(r['scope'], r['id']): r for r in rows}
    if len(by_key) != len(rows):
        raise ValueError('duplicate evaluation identities')
    return by_key

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, default=ROOT / 'baseline-001')
    parser.add_argument('--candidate', type=Path, default=ROOT / 'candidate-eval-001')
    parser.add_argument('--out', type=Path, help='optional report path; omit to print only')
    args = parser.parse_args()
    old_dir = args.baseline
    new_dir = args.candidate
    if not (old_dir / 'completed.json').exists() or not (new_dir / 'completed.json').exists():
        raise ValueError('both evaluations must complete')
    old = read(old_dir / 'results.jsonl')
    new = read(new_dir / 'results.jsonl')
    if old.keys() != new.keys():
        raise ValueError('evaluation cases differ')
    groups = defaultdict(list)
    for key, a in old.items():
        b = new[key]
        if (a['family'], a['target'], a['native_input']) != (b['family'], b['target'], b['native_input']):
            raise ValueError(f'evaluation input or target differs: {key}')
        groups[(a['scope'], a['family'])].append((a, b))
    report = {}
    for (scope, family), pairs in sorted(groups.items()):
        results = {}
        for name, which, kind in (('original_native', 0, 'native'), ('original_int4', 0, 'int4'),
                                  ('candidate_native', 1, 'native'), ('candidate_int4', 1, 'int4')):
            rows = [pair[which] for pair in pairs]
            matrix = Counter((r['target'], r[kind + '_prediction']) for r in rows)
            seconds = sorted(r[kind + '_seconds'] for r in rows)
            results[name] = {'matched': sum(r['target'] == r[kind + '_prediction'] for r in rows),
                             'confusion': {f'{target} -> {prediction}': count for (target, prediction), count in sorted(matrix.items())},
                             'seconds_mean': statistics.mean(seconds), 'seconds_median': statistics.median(seconds),
                             'seconds_p95': seconds[max(0, (95 * len(seconds) + 99) // 100 - 1)]}
        results['paired_changes_int4'] = {'corrected': sum(a['int4_prediction'] != a['target'] and b['int4_prediction'] == b['target'] for a, b in pairs),
             'new_errors': sum(a['int4_prediction'] == a['target'] and b['int4_prediction'] != b['target'] for a, b in pairs),
             'changed_decisions': sum(a['int4_prediction'] != b['int4_prediction'] for a, b in pairs)}
        results['native_int4_disagreements'] = {'original': sum(a['native_prediction'] != a['int4_prediction'] for a, b in pairs),
                                                 'candidate': sum(b['native_prediction'] != b['int4_prediction'] for a, b in pairs)}
        report[f'{scope}/{family}'] = {'count': len(pairs), **results}
    if args.out:
        args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))

if __name__ == '__main__':
    main()
