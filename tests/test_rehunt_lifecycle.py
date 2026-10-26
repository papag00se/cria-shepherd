"""Surviving research ownership boundaries after removing outgoing relevance."""
from dataclasses import replace
import json

import pytest

from cria import loop, semanticquery as policy, webfetch
from test_loop import _Rlog
from test_semantic_query_production_binding import SESSION, QUERY, PRIOR, rig, runtime


@pytest.mark.parametrize('field', ['execute', 'settle'])
def test_registration_rejects_missing_rehunt_lifecycle_callback(field):
    with pytest.raises(ValueError):
        runtime(rehunt=replace(policy.REHUNT, **{field: None}))


def test_rehunt_live_cache_reset_and_real_store_durable_cleanliness(monkeypatch, tmp_path):
    webfetch.set_visible(SESSION, [], [PRIOR])
    try:
        driver, state, body, questions, posted = rig(monkeypatch, runtime(), answer={'new_direction': False})
        driver.drive(body, SESSION, None, _Rlog())
        cache = state.rehunt_verdicts
        assert cache == {QUERY: False}
        store = loop.LoopStore(str(tmp_path / 'sessions.json'))
        store.put(SESSION, state)
        store.persist(SESSION)
        assert store.get(SESSION) is state and store.get(SESSION).rehunt_verdicts is cache
        encoded = json.loads((tmp_path / 'sessions.json').read_text())['sessions'][SESSION]
        assert 'rehunt_verdicts' not in encoded and 'semantic_pending' not in encoded
        restored = loop.LoopStore(str(tmp_path / 'sessions.json')).get(SESSION)
        assert restored is not state and restored.rehunt_verdicts is None and restored.semantic_pending is None
        state.fetched_pages = {'https://api.handle.me/': ('HTTP 200', (), (), (), '')}
        policy.reset_turn(state)
        assert state.rehunt_verdicts is None and state.semantic_pending is None
        assert state.fetched_pages == {'https://api.handle.me/': ('HTTP 200', (), (), (), '')}
        assert webfetch.prior_matching_search(SESSION, QUERY) == PRIOR.lower()
        driver.drive(body, SESSION, None, _Rlog())
        assert len(questions) == 2 and len(posted) == 2
        assert state.rehunt_verdicts == {QUERY: False} and state.rehunt_verdicts is not cache
        driver._store.drop(SESSION)
        driver._store.put(SESSION, restored)
        driver.drive(body, SESSION, None, _Rlog())
        assert len(questions) == 3 and len(posted) == 3
        assert restored.rehunt_verdicts == {QUERY: False} and restored.rehunt_verdicts is not state.rehunt_verdicts
    finally:
        webfetch.reset_session(SESSION)
