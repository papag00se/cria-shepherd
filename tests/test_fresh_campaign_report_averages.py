import copy
import json
from pathlib import Path
import pytest
from suite import battery_status as status


def fixture():
    manifest={'campaign_id':'fresh','models':['gemma4_12b','ornith1.5_9b'], 'cells':[
        {'model':'gemma4_12b','task':status.TASKS[0],'state':'done','run_id':'zero'},
        {'model':'gemma4_12b','task':status.TASKS[1],'state':'done','run_id':'full'},
        {'model':'ornith1.5_9b','task':status.TASKS[0],'state':'infrastructure-failed','run_id':'failed'},
        {'model':'ornith1.5_9b','task':status.TASKS[1],'state':'pending'}],
        'judged_operator_dispositions':{'failed':{'run_id':'stopped','campaign_id':'linked','termination':'operator-ended','natural_completion':False}}}
    rows=[dict(run_id='zero',campaign_id='fresh',model='gemma4_12b',task=status.TASKS[0],usefulness_percent=0,wall_seconds=0,calls=0),
          dict(run_id='full',campaign_id='fresh',model='gemma4_12b',task=status.TASKS[1],usefulness_percent=100,wall_seconds=120,calls=10),
          dict(run_id='failed',campaign_id='fresh',model='ornith1.5_9b',task=status.TASKS[0],terminal='harness-error',usefulness_percent=100,wall_seconds=9999,calls=9999),
          dict(run_id='stopped',campaign_id='linked',model='ornith1.5_9b',task=status.TASKS[0],terminal='operator-ended',natural_completion=False,usefulness_percent=30,wall_seconds=180,calls='unknown'),
          dict(run_id='historical',campaign_id='old',model='gemma4_12b',task=status.TASKS[0],usefulness_percent=99,wall_seconds=9999,calls=9999),
          dict(run_id='pending',campaign_id='fresh',model='ornith1.5_9b',task=status.TASKS[1],wall_seconds=9999,calls=9999)]
    return manifest,rows


def test_selected_logical_cells_only_and_explicit_coverage():
    m,r=fixture(); before=copy.deepcopy((m,r)); table=status.fresh_table(m,r)
    assert '| gemma4_12b | 🔴 0% | 🟢 100% |  |  |  |  | 50% | 1 | 5 |' in table
    assert '| ornith1.5_9b | 🔴 30% |  |  |  |  |  | 30% | 3 | · |' in table
    assert 'gemma4_12b: usefulness2/2, minutes2/2, calls2/2' in table
    assert 'ornith1.5_9b: usefulness1/1, minutes1/1, calls0/1' in table
    assert (m,r)==before


def test_missing_nonfinite_and_boolean_metrics_are_not_zero():
    m,r=fixture();r[0].update(calls=None,wall_seconds=float('nan'));r[1].update(calls=False,wall_seconds=-1)
    text=status.fresh_table(m,r)
    assert '| 50% | · | · |' in text
    assert 'minutes0/2, calls0/2' in text


def test_ambiguous_or_unjudged_selection_fails_closed():
    m,r=fixture()
    with pytest.raises(ValueError):status.fresh_table(m,r+[r[0]])
    r[0].pop('usefulness_percent')
    with pytest.raises(ValueError):status.fresh_table(m,r)


def test_successful_replacement_counted_once_and_failure_never_averaged():
    m,r=fixture(); m.pop('judged_operator_dispositions')
    m['successful_replacements']={'failed':{'run_id':'replacement','campaign_id':'linked'}}
    r.append(dict(run_id='replacement',campaign_id='linked',model='ornith1.5_9b',task=status.TASKS[0],terminal='completed',usefulness_percent=90,wall_seconds=60,calls=4))
    text=status.fresh_table(m,r)
    assert '| 90% | 1 | 4 |' in text
    assert 'ornith1.5_9b: usefulness1/1, minutes1/1, calls1/1' in text
    m['judged_operator_dispositions']={'failed':{'run_id':'replacement','campaign_id':'linked'}}
    with pytest.raises(ValueError):status.fresh_table(m,r)


def test_link_must_match_original_logical_cell_and_termination():
    m,r=fixture();r[3]['natural_completion']=True
    with pytest.raises(ValueError):status.fresh_table(m,r)
    r[3]['natural_completion']=False;r[3]['task']=status.TASKS[2]
    with pytest.raises(ValueError):status.fresh_table(m,r)


def test_write_refreshes_fresh_table_without_destroying_attempts_or_history(tmp_path,monkeypatch):
    m,r=fixture();suite=tmp_path/'suite';suite.mkdir();docs=tmp_path/'docs';docs.mkdir()
    path=docs/'battery-report.md';text='# report\n<!-- fresh-fresh:start -->\nScope stays.\n\n| model | ruby |\n|---|---|\n| old | |\n\n### Attempt evidence\nPreserve failed originals and checkpoint prose.\n<!-- fresh-fresh:end -->\n\nHistorical ladder stays byte-for-byte.\n';path.write_text(text)
    monkeypatch.setattr(status,'SUITE',suite)
    with pytest.raises(ValueError):status.write_report(r)
    assert path.read_text()==text
    wrong={**m,'campaign_id':'wrong'}
    with pytest.raises(ValueError):status.write_report(r,campaign=wrong)
    assert path.read_text()==text
    status.write_report(r,campaign=m)
    got=path.read_text();assert 'avg usefulness | avg min | avg calls' in got
    assert 'Scope stays.' in got and got.endswith('Historical ladder stays byte-for-byte.\n')
    assert 'Preserve failed originals and checkpoint prose.' in got
