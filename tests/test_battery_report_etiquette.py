import re
from pathlib import Path
import pytest
from suite import battery_status as status


def setup(tmp_path, monkeypatch):
    suite = tmp_path / 'suite'
    suite.mkdir()
    docs = tmp_path / 'docs'
    docs.mkdir()
    path = docs / 'battery-report.md'
    # Normal publication preserves other levels; column migration is tested separately.
    path.write_text(status.add_throughput_column(Path('docs/battery-report.md').read_text(), [])[0])
    monkeypatch.setattr(status, 'SUITE', suite)
    return path


def test_writer_preserves_six_tables_titles_and_pending_standings(tmp_path, monkeypatch):
    path = setup(tmp_path, monkeypatch)
    before = path.read_text()
    manifest = dict(campaign_id='l5-new', level=5, models=['gemma4_12b'], cells=[
        dict(model='gemma4_12b', task=status.TASKS[0], state='done', run_id='new'),
        dict(model='gemma4_12b', task=status.TASKS[1], state='pending')])
    row = dict(run_id='new', campaign_id='l5-new', level=5, model='gemma4_12b',
               task=status.TASKS[0], usefulness_percent=0, wall_seconds=0, calls=0)
    status.write_report([row], campaign=manifest)
    after = path.read_text()
    # Shared L5 ranking may move rows at every level, never change their contents.
    def other_levels(text):
        return [sorted(section.splitlines()) for section in
                re.split(r'(?=^## L[0-5] — )', text, flags=re.M)[1:6]]
    assert other_levels(after) == other_levels(before)
    assert len(re.findall(r'^## L[0-5] ', after, re.M)) == 6
    assert after.count('| model |') == 6
    # Published standings are live fixtures: assert their retained values, not yesterday's scores.
    prior_rows = [line for line in before.split('## L5')[1].splitlines()
                  if line.startswith('| ') and not line.startswith('| model |')]
    prior_gemma = next(line for line in prior_rows if line.startswith('| gemma4_12b |'))
    fields = [f.strip() for f in prior_gemma.strip('|').split('|')]
    gemma_scores = [0] + [int(re.search(r'(\d+)%$', f).group(1)) for f in fields[2:7]]
    all_scores = [int(value) for line in prior_rows for value in re.findall(r'(\d+)%', line)[:6]]
    original_ruby = int(re.search(r'(\d+)%$', fields[1]).group(1))
    expected_title = round((sum(all_scores) - original_ruby) / len(all_scores))
    assert f'ASSISTS_ENABLED — steers, periodic gates, detectors, planner — {expected_title}%' in after
    assert f'| gemma4_12b | 🔴 0% | {fields[2]}' in after
    assert f'| {round(sum(gemma_scores) / len(gemma_scores))}% | 0 | 0 |' in after
    assert after.split('Legend:')[1] == before.split('Legend:')[1]
    assert 'Attempt evidence' not in after and 'Row-average coverage' not in after
    evidence = (tmp_path / 'docs/battery-report-evidence.md').read_text()
    assert 'l5-new' in evidence and 'calls1/6' in evidence


def test_writer_refuses_without_campaign_and_preserves_bytes(tmp_path, monkeypatch):
    path = setup(tmp_path, monkeypatch)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        status.write_report([])
    assert path.read_bytes() == before


def test_writer_refuses_unjudged_or_wrong_level_before_any_write(tmp_path, monkeypatch):
    path = setup(tmp_path, monkeypatch)
    before = path.read_bytes()
    manifest = dict(campaign_id='new', level=5, models=['gemma4_12b'], cells=[
        dict(model='gemma4_12b', task=status.TASKS[0], state='done', run_id='new')])
    row = dict(run_id='new', campaign_id='new', level=0, model='gemma4_12b',
               task=status.TASKS[0], usefulness_percent=100)
    with pytest.raises(ValueError):
        status.write_report([row], campaign=manifest)
    assert path.read_bytes() == before
