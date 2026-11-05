"""Collect lexical near-duplicate candidates against historical progress TRAIN only.

Candidates require semantic review. This deliberately never opens either fresh split.
"""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import re

from suite.progress_correctness.build import OUT
from suite.progress_dataset import render_state
from suite.gliclass_probe import render_state as render_text

OLD_TRAIN = Path.home() / '.cria/training/progress-v1/dataset.jsonl'


def shingles(text: str) -> set[tuple[str, ...]]:
    words = re.findall(r'\w+|[^\w\s]', text.lower(), re.UNICODE)
    return set(zip(*(words[n:] for n in range(5))))


def main() -> None:
    new = [json.loads(line) for line in (OUT / 'train.jsonl').read_text().splitlines()]
    # Sibling requirements repeat in three rows. The evidence stays complete.
    new_shingles = [shingles(r['evidence']) for r in new]
    inverse = defaultdict(set)
    for i, s in enumerate(new_shingles):
        for gram in s:
            inverse[gram].add(i)
    best = [None] * len(new)
    exact = []
    new_inputs = defaultdict(list)
    for row in new:
        new_inputs[render_text(render_state(row['requirement'], row['evidence']))].append(row)
    old_count = 0
    with OLD_TRAIN.open() as f:
        for line in f:
            old = json.loads(line)
            old_count += 1
            rendered = render_text(render_state(old.get('requirement', ''), old.get('evidence', '')))
            for row in new_inputs.get(rendered, ()):
                exact.append({'id': row['id'], 'new_label': row['label'],
                              'historical_id': old.get('id'), 'historical_label': old.get('label')})
            s = shingles(old.get('evidence', ''))
            common = defaultdict(int)
            for gram in s:
                for i in inverse.get(gram, ()):
                    common[i] += 1
            for i, n in common.items():
                union = len(s) + len(new_shingles[i]) - n
                score = n / union if union else 0.0
                if best[i] is None or score > best[i]['jaccard']:
                    best[i] = {'historical_id': old.get('id'), 'jaccard': score}
    result = {'historical_source': str(OLD_TRAIN), 'historical_rows_scanned': old_count,
              'note': 'Five-token evidence shingles; highest lexical match per row, not a semantic verdict.',
              'exact_inputs': exact,
              'candidates': [{'id': row['id'], 'candidate': hit} for row, hit in zip(new, best)]}
    (OUT / 'historical-near-candidates.json').write_text(json.dumps(result, indent=2) + '\n')
    print(f"Scanned {old_count} historical TRAIN rows against {len(new)} synthetic inputs.")


if __name__ == '__main__':
    main()
