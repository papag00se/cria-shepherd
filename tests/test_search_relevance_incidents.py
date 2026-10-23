"""Retain incident inputs without retaining the removed relevance mechanism.

Prior incidents: spiral query / on-target disagreement; malformed wrapper and two-query
recommendations; repeated repository 404 substitution; a registry 200 mistaken for a
successful gem load; invented eu-membership fetch blamed on the coder. No recommendation
is now requested, parsed, surfaced, substituted, or recorded as delivered guidance.
"""
from copy import deepcopy
import json

import pytest

from cria import bodykeys, refusalledger
from test_loop import _Rlog
from test_search_relevance_is_removed import rig, SESSION

SPIRAL = ('go.mod decimal module golang.org/x/exp math/bits? no — "github.com/bsb" or '
          '"github.com/joelschaefer"? Actually: which Go library provides a Decimal type for money, '
          'e.g. github.com/shopspring/supercharge? Let me search properly.')


@pytest.mark.parametrize('query,recommendation', [
    (SPIRAL, 'Go third-party Decimal type for money calculations go.mod'),
    ('ada handles resolve endpoint pattern', "web_search('Ada Handles API documentation')"),
    ('api.handle.me openapi.json', 'Search for "Cardano Ada Handle openapi.json" or "api.handle.me spec"'),
    ('ada handles api documentation', 'ada handles api documentation'),
    ('cardano python sdk package name', 'Cardano Python SDK package name'),
    ('oklog decimal go module', 'https://github.com/oklog/decimal'),
    ('eu countries ruby gem', 'https://rubygems.org/gems/eu-membership'),
    ('ada handles', 'https://totally-invented.example/api'),
])
def test_historical_recommendation_inputs_cannot_replace_or_note_a_search(monkeypatch, query, recommendation):
    driver, state, body, questions = rig(monkeypatch, synthetic=True, query=query,
        answer={'on_target': False, 'recommendation': recommendation})
    original = deepcopy(body['messages'])
    out = driver.drive(body, SESSION, None, _Rlog())
    call = out['choices'][0]['message']['tool_calls'][0]['function']
    assert call == {'name': 'web_search', 'arguments': json.dumps({'query': query})}
    assert bodykeys.NOTES not in out and questions == []
    assert body['messages'] == original


@pytest.mark.parametrize('succeeded', [False, True])
def test_registry_page_success_never_erases_real_load_refusal_or_fetch_facts(monkeypatch, succeeded):
    driver, state, body, questions = rig(monkeypatch, synthetic=True,
        answer={'on_target': True, 'recommendation': 'eu_countries'})
    def event(outcome, seq):
        return refusalledger.RefusalEvent(ecosystem='rubygems', raw_coordinate='eu_countries',
            package='eu_countries', version='', outcome=outcome,
            evidence='cannot load such file -- iso3166', sequence=seq)
    events = [event(refusalledger.REFUSED, 1)]
    if succeeded:
        events.append(event(refusalledger.SUCCEEDED, 2))
    ledger = refusalledger.RefusalLedger(events)
    state.refusal_events = ledger
    facts = {'https://rubygems.org/gems/eu_countries': (200, ''), 'https://github.com/oklog/decimal': (404, '')}
    state.fetched_pages = facts.copy()
    driver.drive(body, SESSION, None, _Rlog())
    assert questions == []
    assert state.refusal_events is ledger and state.fetched_pages == facts
    assert bool(ledger.active()) is (not succeeded)
