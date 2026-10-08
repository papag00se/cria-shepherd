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
    assert after.split('## L5')[0] == before.split('## L5')[0]
    assert len(re.findall(r'^## L[0-5] ', after, re.M)) == 6
    assert after.count('| model |') == 6
    assert 'ASSISTS_ENABLED — steers, periodic gates, detectors, planner — 40%' in after
    assert '| gemma4_12b | 🔴 0% | 🟡 74%' in after
    assert '| 60% | 0 | 0 |' in after
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
