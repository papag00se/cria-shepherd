"""Standing rankings follow L5, including when publication changes another level."""
import re
import pytest
from suite import battery_status as status


def scorecard():
    out = ['# Battery report', '']
    for level in range(6):
        out += [f'## L{level} — description {level} — 81%', '',
                '| model | ruby | go | python | java | node | rust | avg usefulness | avg min | avg calls | avg tok/s |',
                '|---|' + '---|' * 6 + '---:|' * 4]
        for model in ('zeta', 'alpha', 'beta', 'unknown'):
            scores = {'alpha': [80, 81], 'beta': [81, 81], 'zeta': [81, 81],
                      'unknown': []}[model] if level == 5 else [100 if model == 'alpha' else 0]
            cells = [status._dot(p) for p in scores] + ['·'] * (6 - len(scores))
            out.append('| ' + ' | '.join([model, *cells, '81%', '7', '11', '12.3']) + ' |')
        out.append('')
    return '\n'.join(out) + '\nLegend: retained exactly.\n'


def tables(text):
    return [[line for line in section.splitlines() if line.startswith('| ') and
             not line.startswith('| model |')] for section in
            re.split(r'(?=^## L[0-5] — )', text, flags=re.M)[1:]]


def names(table):
    return [line.split('|')[1].strip() for line in table]


def setup(tmp_path, monkeypatch):
    suite = tmp_path / 'suite'
    suite.mkdir()
    docs = tmp_path / 'docs'
    docs.mkdir()
    path = docs / 'battery-report.md'
    path.write_text(scorecard())
    monkeypatch.setattr(status, 'SUITE', suite)
    return path


def test_shared_exact_l5_rank_preserves_all_rows_and_is_idempotent():
    before = scorecard()
    after = status.order_by_l5(before)
    # All displayed means tie at 81%, but alpha's true mean is only 80.5%.
    assert all(names(t) == ['beta', 'zeta', 'alpha', 'unknown'] for t in tables(after))
    assert [sorted(t) for t in tables(after)] == [sorted(t) for t in tables(before)]
    assert [l for l in after.splitlines() if not l.startswith('| ')] == [
        l for l in before.splitlines() if not l.startswith('| ')]
    assert status.order_by_l5(after) == after


def test_l5_publication_reorders_every_level_and_keeps_other_cells(tmp_path, monkeypatch):
    path = setup(tmp_path, monkeypatch)
    before = tables(path.read_text())
    manifest = dict(campaign_id='new', level=5, models=['alpha'], cells=[
        dict(model='alpha', task=status.TASKS[0], state='done', run_id='new')])
    row = dict(run_id='new', campaign_id='new', level=5, model='alpha',
               task=status.TASKS[0], usefulness_percent=100, wall_seconds=60, calls=1)
    status.write_report([row], campaign=manifest)
    after = tables(path.read_text())
    assert all(names(t) == ['alpha', 'beta', 'zeta', 'unknown'] for t in after)
    assert [sorted(t) for t in after[:5]] == [sorted(t) for t in before[:5]]
    assert '| alpha | 🟢 100% | 🟡 81%' in path.read_text()
    assert 'Legend: retained exactly.' in path.read_text()


def test_non_l5_publication_uses_retained_l5_rank(tmp_path, monkeypatch):
    path = setup(tmp_path, monkeypatch)
    status.write_report([], campaign=dict(campaign_id='other', level=0, models=[], cells=[]))
    assert all(names(t) == ['beta', 'zeta', 'alpha', 'unknown'] for t in tables(path.read_text()))


def test_missing_history_is_not_fabricated_and_zero_beats_unknown():
    text = scorecard().replace('| 🟡 80% | 🟡 81% |', '| 🔴 0% | · |')
    # Historical-only identity ranks after the L5 roster, and missing rows stay missing.
    sections = re.split(r'(?=^## L[0-5] — )', text, flags=re.M)
    sections[1] = sections[1].replace('| unknown |', '| historical-only |')
    sections[2] = '\n'.join(l for l in sections[2].splitlines() if not l.startswith('| alpha |')) + '\n\n'
    after = tables(status.order_by_l5(''.join(sections)))
    assert names(after[0]) == ['beta', 'zeta', 'alpha', 'historical-only']
    assert names(after[1]) == ['beta', 'zeta', 'unknown']
    assert names(after[5]) == ['beta', 'zeta', 'alpha', 'unknown']


@pytest.mark.parametrize('bad', ['| alpha | 🔴 101%', '| zeta | 🟡 80%'])
def test_invalid_or_duplicate_row_refuses_before_writing(tmp_path, monkeypatch, bad):
    path = setup(tmp_path, monkeypatch)
    path.write_text(path.read_text().replace('| alpha | 🟡 80%', bad))
    before = path.read_bytes()
    with pytest.raises(ValueError):
        status.write_report([], campaign=dict(campaign_id='other', level=0, models=[], cells=[]))
    assert path.read_bytes() == before
    assert not (path.parent / 'battery-report-evidence.md').exists()
