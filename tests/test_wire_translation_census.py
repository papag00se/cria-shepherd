"""Model-visible wire translations must appear in row metadata, not vanish as plumbing."""
import json

from suite import run


def test_row_event_census_discloses_authoritative_envelope_events(tmp_path, monkeypatch):
    monkeypatch.setattr(run, 'EVENTS_DIR', tmp_path)
    envelope = {'ts': 11, 'kind': 'upstream.history_args_enveloped', 'count': 3,
                'session': 'current', 'turn': 'wire-turn'}
    other = {'ts': 12, 'kind': 'upstream.done', 'count': 900,
             'message': 'upstream.history_args_enveloped '*20}
    outside = {**envelope, 'ts': 99, 'count': 700}
    (tmp_path/'cria-fixture.jsonl').write_text('\n'.join(json.dumps(e) for e in (envelope, other, outside))+'\n')
    census = run.collect_event_census(10, 20)
    assert census['wire_translations'] == [envelope]  # retain actual count3, not one string/event match
    assert census['assists'] == {}
    assert run.collect_assists(10, 20) == census['assists']


def test_empty_window_is_explicit_no_wire_translations(tmp_path, monkeypatch):
    monkeypatch.setattr(run, 'EVENTS_DIR', tmp_path)
    assert run.collect_event_census(10, 20) == {'assists': {}, 'wire_translations': []}
