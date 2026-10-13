import json
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
    # Sparse task rows must not accidentally count the row average as a task score.
    all_scores = [int(value) for line in prior_rows
                  for field in line.strip('|').split('|')[1:7]
                  for value in re.findall(r'(\d+)%', field)]
    original_ruby = int(re.search(r'(\d+)%$', fields[1]).group(1))
    expected_title = round((sum(all_scores) - original_ruby) / len(all_scores))
    assert f'ASSISTS_ENABLED — steers, periodic gates, detectors, planner — {expected_title}%' in after
    assert f'| gemma4_12b | 🔴 0% | {fields[2]}' in after
    assert f'| {round(sum(gemma_scores) / len(gemma_scores))}% | 0 | 0 |' in after
    assert after.split('Legend:')[1] == before.split('Legend:')[1]
    assert 'Attempt evidence' not in after and 'Row-average coverage' not in after
    evidence = (tmp_path / 'docs/battery-report-evidence.md').read_text()
    assert 'l5-new' in evidence and 'calls1/6' in evidence


@pytest.mark.parametrize('old_label', ['total', 'avg usefulness', 'avg pct'])
def test_publication_normalizes_average_label_without_changing_standings(tmp_path, monkeypatch, old_label):
    path = setup(tmp_path, monkeypatch)
    before = path.read_text()
    lines = before.splitlines()
    for index, line in enumerate(lines):
        if line.startswith('| model |'):
            fields = line.split('|')
            fields[8] = f' {old_label} '
            lines[index] = '|'.join(fields)
    path.write_text('\n'.join(lines) + '\n')
    # An empty campaign still exercises the real guarded publication pipeline.
    campaign = dict(campaign_id='label-only', level=5, models=[], cells=[])
    status.write_report([], campaign=campaign)
    after = path.read_text()
    headers = [line for line in after.splitlines() if line.startswith('| model |')]
    assert len(headers) == 6
    assert all(line.split('|')[8].strip() == 'avg pct' for line in headers)
    def standings(text):
        return sorted(line for line in text.splitlines()
                      if line.startswith('| ') and not line.startswith('| model |'))
    assert standings(after) == standings(before)
    assert after.split('Legend:')[1] == before.split('Legend:')[1]
    assert 'Usefulness: share of requested work delivered as useful code.' in after.split('Legend:')[1]
    preview = status.fresh_table(campaign, [], include_coverage=False)
    assert preview.splitlines()[0].split('|')[8].strip() == 'avg pct'


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


def standing_rows(text):
    return [{line.split('|')[1].strip(): line for line in section.splitlines()
             if line.startswith('| ') and not line.startswith('| model |')}
            for section in re.split(r'(?=^## L[0-5] — )', text, flags=re.M)[1:]]


def focused_fixture(tmp_path, monkeypatch):
    """A real six-table publication with saved sources, not latest-score guesses."""
    path = setup(tmp_path, monkeypatch)
    text = path.read_text()
    # Use the published table as a shape fixture; make only these two L5 rows controlled.
    old = standing_rows(text)[5]
    for model, score in [('ornith1.5_9b', 30), ('phi4', 0)]:
        replacement = ('| ' + model + ' | ' + ' | '.join([status._dot(score)] * 6)
                       + f' | {score}% | 2 | 12 | 56.2 |')
        text = text.replace(old[model], replacement)
    path.write_text(status.order_by_l5(text))
    rows = [dict(run_id=f'{model}-{i}', level=5, model=model, task=task,
                 usefulness_percent=score, wall_seconds=120, calls=12, avg_tok_s=56.2)
            for model, score in [('ornith1.5_9b', 30), ('phi4', 0)]
            for i, task in enumerate(status.TASKS)]
    for row, rate in zip(rows[6:], [48.7, 49.3, 54.8, 63.3, 56.0, 65.1]):
        row['avg_tok_s'] = rate
    evidence = path.with_name('battery-report-evidence.md')
    evidence.write_text('Retained evidence.\n' + '\n'.join(
        f'L5/{model}: tok/s6/6; sources ' + ', '.join(f'{model}-{i}' for i in range(6))
        for model in ('ornith1.5_9b', 'phi4')) + '\n')
    campaign = dict(campaign_id='focused', level=5, models=['ornith1.5_9b', 'phi4'], cells=[
        dict(model='ornith1.5_9b', task=status.TASKS[3], state='done', run_id='selected'),
        dict(model='ornith1.5_9b', task=status.TASKS[0], state='pending'),
        dict(model='phi4', task=status.TASKS[3], state='pending')])
    selected = dict(run_id='selected', campaign_id='focused', level=5, model='ornith1.5_9b',
                    task=status.TASKS[3], usefulness_percent=65,
                    wall_seconds=600, calls=60, avg_tok_s=100)
    rows += [selected,
             dict(rows[0], run_id='ornith-new-unselected', usefulness_percent=4,
                  wall_seconds=9999, calls=9999, avg_tok_s=9999),
             dict(rows[9], run_id='phi-new-unselected', usefulness_percent=4,
                  wall_seconds=9999, calls=9999, avg_tok_s=9999)]
    return path, evidence, campaign, rows


def test_focused_writer_preserves_unselected_rows_and_bound_task_metrics(tmp_path, monkeypatch):
    path, evidence, campaign, rows = focused_fixture(tmp_path, monkeypatch)
    before, prior_evidence = path.read_text(), evidence.read_text()
    status.write_report(rows, campaign=campaign)
    after = path.read_text()
    old, new = standing_rows(before), standing_rows(after)
    assert set(old[5]) == set(new[5])
    for level in range(6):
        for model, line in old[level].items():
            if (level, model) != (5, 'ornith1.5_9b'):
                assert new[level][model] == line
    # Five explicitly bound retained tasks plus the selected row, not newer unselected work.
    fields = [v.strip() for v in new[5]['ornith1.5_9b'].strip('|').split('|')]
    assert fields[1:7] == [status._dot(30)] * 3 + [status._dot(65)] + [status._dot(30)] * 2
    assert fields[7:] == ['36%', '3', '20', '63.5']
    assert after.count('| model |') == 6 and after.count('Legend:') == 1
    assert after.split('Legend:')[1] == before.split('Legend:')[1]
    assert status.order_by_l5(after) == after
    before_sections = re.split(r'(?=^## L[0-5] — )', before, flags=re.M)[1:]
    after_sections = re.split(r'(?=^## L[0-5] — )', after, flags=re.M)[1:]
    assert [s.splitlines()[0] for s in after_sections[:5]] == [s.splitlines()[0] for s in before_sections[:5]]
    assert after_sections[5].splitlines()[0].rsplit(' — ', 1)[0] == before_sections[5].splitlines()[0].rsplit(' — ', 1)[0]
    scores = [int(pct) for line in new[5].values() for field in line.split('|')[2:8]
              for pct in re.findall(r'(\d+)%', field)]
    assert after_sections[5].splitlines()[0].endswith(f' — {round(sum(scores) / len(scores))}%')
    saved = evidence.read_text()
    assert saved.startswith(prior_evidence)
    update = saved[len(prior_evidence):]
    assert 'L5/phi4:' not in update  # retained coverage/source binding remains authoritative
    assert 'L5/ornith1.5_9b: tok/s6/6; sources ornith1.5_9b-0, ornith1.5_9b-1, ornith1.5_9b-2, selected, ornith1.5_9b-4, ornith1.5_9b-5' in update
    assert 'minutes6/6, calls6/6' in update


def test_selected_exact_run_not_shadowed_by_later_same_score_unknown_metrics(tmp_path, monkeypatch):
    path, evidence, campaign, rows = focused_fixture(tmp_path, monkeypatch)
    # A later independently judged attempt has the same score but is NOT manifest-selected.
    rows.append(dict(rows[-3], run_id='later-same-score', campaign_id='other',
                     wall_seconds=None, calls=None, avg_tok_s=None))
    status.write_report(rows, campaign=campaign)
    assert standing_rows(path.read_text())[5]['ornith1.5_9b'].endswith('| 36% | 3 | 20 | 63.5 |')
    assert 'later-same-score' not in evidence.read_text()


def test_saved_bindings_survive_next_focused_update_and_do_not_fill_unknowns(tmp_path, monkeypatch):
    path, evidence, campaign, rows = focused_fixture(tmp_path, monkeypatch)
    # No authoritative source survives for a historical standing task. Do not invent one.
    rows = [r for r in rows if r['run_id'] not in ('ornith1.5_9b-0', 'ornith-new-unselected')]
    prior = evidence.read_text().replace('ornith1.5_9b-0, ', '')
    evidence.write_text(prior)
    status.write_report(rows, campaign=campaign)
    first = standing_rows(path.read_text())[5]['ornith1.5_9b']
    assert first.endswith('| 36% | 4 | 22 | 65.0 |')
    binding_line = next(line for line in evidence.read_text().splitlines()
                        if line.startswith('Standing metric sources L5/ornith1.5_9b: '))
    bindings = json.loads(binding_line.split(': ', 1)[1])
    assert bindings[status.TASKS[0]] is None and bindings[status.TASKS[3]] == 'selected'
    # Later judgments cannot fill an explicit standing gap or replace a bound run.
    rows += [dict(run_id='new-gap', level=5, model='ornith1.5_9b', task=status.TASKS[0],
                  usefulness_percent=30, wall_seconds=9999, calls=9999, avg_tok_s=9999),
             dict(next(r for r in rows if r['run_id'] == 'selected'),
                  run_id='not-published', avg_tok_s=None, wall_seconds=None, calls=None)]
    next_row = dict(rows[0], run_id='next', campaign_id='next', avg_tok_s=0,
                    wall_seconds=0, calls=0)
    # rows[0] is the retained Go task; publish exactly that row's replacement.
    rows.append(next_row)
    next_campaign = dict(campaign_id='next', level=5, models=['ornith1.5_9b'], cells=[
        dict(model='ornith1.5_9b', task=status.TASKS[1], state='done', run_id='next')])
    status.write_report(rows, campaign=next_campaign)
    assert standing_rows(path.read_text())[5]['ornith1.5_9b'].endswith('| 36% | 3 | 19 | 53.7 |')
    latest = evidence.read_text().split('## Standing update — next')[1]
    assert 'new-gap' not in latest and 'not-published' not in latest
    assert 'tok/s5/6' in latest and 'minutes5/6, calls5/6' in latest
    assert 'selected' in latest


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'wrong-score', 'wrong-task', 'failed', 'malformed'])
def test_bad_retained_binding_refuses_before_either_file_changes(tmp_path, monkeypatch, damage):
    path, evidence, campaign, rows = focused_fixture(tmp_path, monkeypatch)
    if damage == 'missing':
        rows = [r for r in rows if r['run_id'] != 'ornith1.5_9b-0']
    elif damage == 'duplicate':
        rows.append(dict(rows[0]))
    elif damage == 'wrong-score':
        rows[0]['usefulness_percent'] = 99
    elif damage == 'wrong-task':
        rows[0]['task'] = status.TASKS[1]
    elif damage == 'failed':
        rows[0]['terminal'] = 'harness-error'
    else:
        evidence.write_text(evidence.read_text() + 'Standing metric sources L5/ornith1.5_9b: {}\n')
    before = path.read_bytes(), evidence.read_bytes()
    with pytest.raises(ValueError):
        status.write_report(rows, campaign=campaign)
    assert (path.read_bytes(), evidence.read_bytes()) == before


def test_full_campaign_replaces_metrics_without_loading_obsolete_bindings(tmp_path, monkeypatch):
    path, evidence, campaign, rows = focused_fixture(tmp_path, monkeypatch)
    # Every task is selected. No retained old source is needed, even if no longer present.
    evidence.write_text('L5/ornith1.5_9b: tok/s6/6; sources missing-old-run\n')
    prior_evidence = evidence.read_text()
    selected = [dict(run_id=f'full-{i}', campaign_id='full', level=5, model='ornith1.5_9b',
                     task=task, usefulness_percent=0, wall_seconds=0, calls=0, avg_tok_s=0)
                for i, task in enumerate(status.TASKS)]
    full = dict(campaign_id='full', level=5, models=['ornith1.5_9b'], cells=[
        dict(model=row['model'], task=row['task'], state='done', run_id=row['run_id'])
        for row in selected])
    status.write_report(rows + selected, campaign=full)
    assert standing_rows(path.read_text())[5]['ornith1.5_9b'].endswith('| 0% | 0 | 0 | 0.0 |')
    assert evidence.read_text().startswith(prior_evidence)
    assert 'tok/s6/6; sources full-0, full-1, full-2, full-3, full-4, full-5' in evidence.read_text()


def test_selected_unknown_timing_is_not_frozen_or_borrowed(tmp_path, monkeypatch):
    path, evidence, campaign, rows = focused_fixture(tmp_path, monkeypatch)
    selected = next(row for row in rows if row['run_id'] == 'selected')
    selected['avg_tok_s'] = None
    rows.append(dict(selected, run_id='unselected-rate', avg_tok_s=9999))
    status.write_report(rows, campaign=campaign)
    assert standing_rows(path.read_text())[5]['ornith1.5_9b'].endswith('| 36% | 3 | 20 | 56.2 |')
    update = evidence.read_text().split('## Standing update — focused')[1]
    assert 'tok/s5/6' in update and 'unselected-rate' not in update
    bindings = json.loads(update.split('Standing metric sources L5/ornith1.5_9b: ')[1].splitlines()[0])
    assert bindings[status.TASKS[3]] == 'selected'


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'unjudged', 'bool', 'wrong-campaign', 'wrong-level', 'failed'])
def test_focused_selected_guard_still_refuses_before_writes(tmp_path, monkeypatch, damage):
    path, evidence, campaign, rows = focused_fixture(tmp_path, monkeypatch)
    selected = next(row for row in rows if row['run_id'] == 'selected')
    if damage == 'missing':
        rows.remove(selected)
    elif damage == 'duplicate':
        rows.append(dict(selected))
    else:
        key, value = {'unjudged': ('usefulness_percent', None), 'bool': ('usefulness_percent', True),
                      'wrong-campaign': ('campaign_id', 'other'), 'wrong-level': ('level', 0),
                      'failed': ('terminal', 'harness-error')}[damage]
        selected[key] = value
    before = path.read_bytes(), evidence.read_bytes()
    with pytest.raises(ValueError):
        status.write_report(rows, campaign=campaign)
    assert (path.read_bytes(), evidence.read_bytes()) == before
