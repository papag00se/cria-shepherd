import copy
import math
from pathlib import Path
from suite import battery_status as status


def test_every_standing_row_gets_known_rate_mean_without_changing_scores():
    source = Path('docs/battery-report.md').read_text()
    rows = [dict(level=0, model='gemma4_12b', task=status.TASKS[0], usefulness_percent=0,
                 avg_tok_s=0, run_id='zero'),
            dict(level=0, model='gemma4_12b', task=status.TASKS[1], usefulness_percent=80,
                 avg_tok_s=20, run_id='twenty'),
            dict(level=0, model='gemma4_12b', task=status.TASKS[2], usefulness_percent=2,
                 avg_tok_s=True, run_id='bool'),
            dict(level=0, model='gemma4_12b', task=status.TASKS[3], usefulness_percent=3,
                 avg_tok_s=float('nan'), run_id='nan'),
            dict(level=0, model='gemma4_12b', task=status.TASKS[4], usefulness_percent=99,
                 avg_tok_s=999, run_id='wrong-standing'),
            dict(level=0, model='gemma4_12b', task=status.TASKS[5], usefulness_percent=95,
                 avg_tok_s=999, terminal='harness-error', run_id='failed')]
    before = copy.deepcopy(rows)
    text, coverage = status.add_throughput_column(source, rows)
    assert text.count('avg tok/s') == 6
    assert source.split('Legend:')[0].count('| gemma4_12b |') == text.split('Legend:')[0].count('| gemma4_12b |')
    old = [line for line in source.splitlines() if line.startswith('| ') and not line.startswith('| model |')]
    new = [line for line in text.splitlines() if line.startswith('| ') and not line.startswith('| model |')]
    for a, b in zip(old, new):
        # All prior score/metric cells retained; migration is only one new column.
        assert [f.strip() for f in b.strip('|').split('|')][:10] == [f.strip() for f in a.strip('|').split('|')][:10]
    assert '| 36% | 1 | 24 | 10.0 |' in text
    assert 'L0/gemma4_12b: tok/s2/6' in coverage
    assert 'zero' in coverage and 'twenty' in coverage
    assert '| 0% | 0 | 1 | · |' in text
    assert rows[0] == before[0] and math.isnan(rows[3]['avg_tok_s'])
    again, same_coverage = status.add_throughput_column(text, rows)
    assert again == text and same_coverage == coverage
    partial, _ = status.add_throughput_column(text, [], refresh_levels={5})
    assert partial.split('## L5')[0] == text.split('## L5')[0]


def test_selected_campaign_rate_excludes_failed_original_and_invalid_metrics():
    manifest = dict(campaign_id='fresh', models=['m'], cells=[
        dict(model='m', task=status.TASKS[0], state='done', run_id='a'),
        dict(model='m', task=status.TASKS[1], state='infrastructure-failed', run_id='bad'),
        dict(model='m', task=status.TASKS[2], state='done', run_id='unknown')],
        successful_replacements={'bad': dict(run_id='b', campaign_id='linked')})
    rows = [dict(model='m', task=status.TASKS[i], campaign_id=c, run_id=r,
                 usefulness_percent=50, avg_tok_s=t) for i, c, r, t in
            [(0, 'fresh', 'a', 0), (1, 'linked', 'b', 20), (2, 'fresh', 'unknown', -1)]]
    rows += [dict(model='m', task=status.TASKS[1], campaign_id='fresh', run_id='bad',
                  terminal='harness-error', usefulness_percent=100, avg_tok_s=999)]
    text = status.fresh_table(manifest, rows)
    assert 'avg tok/s' in text
    assert '| 50% | · | · | 10.0 |' in text
    assert 'tok/s2/3' in text


def test_latest_matching_unknown_rate_does_not_borrow_older_timing():
    source = Path('docs/battery-report.md').read_text()
    row = dict(level=0, model='gemma4_12b', task=status.TASKS[0], usefulness_percent=0)
    text, coverage = status.add_throughput_column(source, [
        dict(row, avg_tok_s=90, run_id='old'), dict(row, avg_tok_s=None, run_id='latest')])
    first = next(line for line in text.splitlines() if line.startswith('| gemma4_12b |'))
    assert first.endswith('| · |')
    assert 'L0/gemma4_12b: tok/s0/6; sources none' in coverage
