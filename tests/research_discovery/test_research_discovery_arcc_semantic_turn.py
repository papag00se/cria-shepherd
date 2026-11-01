"""The new-direction clearance is EARNED by the search call the coder actually receives, through the real prepare_turn/settle_turn pair
(the entries Loop.drive calls); only the reasoner's reply is faked.

ADA Handle incident shape: an overlapping search is judged once; a 'new direction' verdict licenses ONE run, but only if that exact
call (same id, same query) is the one retained - a discarded or rewritten turn must not spend the grant."""
import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cria import assistruntime, denial, researchpolicies as rp, semanticquery as sq, webfetch

PRIOR = "ADA Handle API resolve handle to address holder address total handles"
QUERY = "ADA Handle API resolve handle holder"
TASK = "resolve an Ada Handle via the API (api.handle.me)"
SESSION = "arcc-semantic-turn"


@pytest.fixture(autouse=True)
def visible_prior():
    webfetch.reset_session(SESSION)
    webfetch.set_visible(SESSION, [], [PRIOR])
    yield
    webfetch.reset_session(SESSION)


def completion(query=QUERY, call_id="s"):
    return {"choices": [{"message": {"tool_calls": [{"id": call_id, "type": "function", "function": {
        "name": "web_search", "arguments": json.dumps({"query": query})}}]}}]}


class Rig:
    def __init__(self, verdict='{"new_direction":true}'):
        self.ask, self.events = Mock(return_value=verdict), []
        self.owner = SimpleNamespace(rehunt_verdicts=None, semantic_pending=None)
        log = SimpleNamespace(emit=lambda kind, **fields: self.events.append((kind, fields)))
        self.judge = sq.Judge(self.ask, Mock(side_effect=AssertionError), object(), log)

    def prepare(self, coder, selection=sq.Selection(sq.REHUNT)):
        return sq.prepare_turn(sq.TurnInput(coder, SESSION, lambda: sq.QuestionFacts(TASK, "menu"), self.judge), self.owner, selection)

    def cleared(self):
        return [e for e in self.events if e[0] == "loop.search_rehunt_cleared"]


def spend():
    """True when ONE grant was available (and it is now used up)."""
    first = webfetch.gate_search(SESSION, QUERY)
    assert denial.is_denied(webfetch.gate_search(SESSION, QUERY))
    return first is None


def test_a_new_direction_search_runs_once_and_only_when_the_judged_call_is_the_one_retained():
    rig = Rig()
    coder = rig.prepare(completion())
    assert rig.ask.call_count == 1 and not rig.cleared()
    assert denial.is_denied(webfetch.gate_search(SESSION, QUERY))          # judged, not yet earned: delivery grants it
    assert rig.owner.semantic_pending is not None
    assert sq.settle_turn(rig.owner, coder) == sq.Settlement(True)
    assert spend() and len(rig.cleared()) == 1 and rig.owner.semantic_pending is None


def test_a_discarded_turn_spends_nothing_but_its_verdict_is_kept_so_the_retained_retry_is_not_asked_again():
    rig = Rig()
    stale = rig.prepare(completion())
    sq.discard_turn(rig.owner)                                              # the driver discarded this candidate
    assert sq.settle_turn(rig.owner, stale) == sq.Settlement(False)         # a late settle of the dropped reply grants nothing
    assert not spend() and rig.owner.rehunt_verdicts == {QUERY: True}
    retained = rig.prepare(completion())                                    # the retry: same query, cached verdict
    assert rig.ask.call_count == 1
    assert sq.settle_turn(rig.owner, retained) == sq.Settlement(True)
    assert spend() and len(rig.cleared()) == 1
    again = rig.prepare(completion())                                       # the grant was spent exactly once
    assert sq.settle_turn(rig.owner, again) == sq.Settlement(False) and not spend() and rig.ask.call_count == 1


@pytest.mark.parametrize("rewrite", ["call id", "query", "a copy of the reply"])
def test_a_rewritten_or_substituted_reply_cannot_settle_the_grant(rewrite):
    rig = Rig()
    coder = rig.prepare(completion())
    retained = copy.deepcopy(coder) if rewrite == "a copy of the reply" else coder
    call = retained["choices"][0]["message"]["tool_calls"][0]
    if rewrite == "call id":
        call["id"] = "different-unjudged-call"
    elif rewrite == "query":
        call["function"]["arguments"] = json.dumps({"query": QUERY + " lookup"})
    assert sq.settle_turn(rig.owner, retained) == sq.Settlement(False)
    assert not rig.cleared() and not spend() and rig.owner.semantic_pending is None


def test_a_historical_positive_of_unknown_spend_never_invents_a_grant():
    """Plain dict verdicts come from a reloaded session: whether their grant was spent is unknown, so none is minted."""
    rig = Rig()
    rig.owner.rehunt_verdicts = {QUERY: True}
    coder = rig.prepare(completion())
    assert rig.ask.call_count == 0 and rig.owner.semantic_pending is None
    assert sq.settle_turn(rig.owner, coder) == sq.Settlement(False) and not spend()


@pytest.mark.parametrize("reply", ["garbage", "{}", '{"new_direction":false}', '{"new_direction":"yes"}', '{"new_direction":1}'])
def test_anything_but_an_affirmative_verdict_asks_once_and_earns_nothing(reply):
    rig = Rig(reply)
    coder = rig.prepare(completion())
    assert sq.settle_turn(rig.owner, coder) == sq.Settlement(False) and not spend()
    rig.prepare(completion())
    assert rig.ask.call_count == 1 and rig.owner.rehunt_verdicts == {QUERY: False}


def test_a_deselected_rehunt_or_search_stage_never_asks_and_never_clears():
    rig = Rig()
    rig.prepare(completion(), sq.Selection())                                # no rehunt definition selected
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5, disabled=(rp.SEARCH.policy.id,))):
        rig.prepare(completion())                                            # the repeat owner is off: nothing to clear
        assert rig.ask.call_count == 0 and rig.owner.semantic_pending is None
    assert rig.ask.call_count == 0 and not rig.cleared()
    assert denial.is_denied(webfetch.gate_search(SESSION, QUERY))            # nothing was cleared behind the off switch


SPIRAL = ('go.mod decimal module golang.org/x/exp math/bits? no — "github.com/bsb" or "github.com/joelschaefer"? Actually: which Go '
          'library provides a Decimal type for money, e.g. github.com/shopspring/supercharge? Let me search properly.')


@pytest.mark.parametrize("query", [
    SPIRAL,                                                                  # on-target subject, unusable as a query string
    "web_search('Ada Handles API documentation')",                           # a literal wrapper
    'Search for "Cardano Ada Handle openapi.json" or "api.handle.me spec"',  # an instruction sentence with two quoted candidates
    "Cardano Python SDK package name",                                       # a case-only rewrite of an earlier search
    "oklog decimal go module", "eu countries ruby gem",                      # the 404 and invented-registry incidents
])
def test_incident_search_strings_reach_the_coder_unchanged_and_ask_nothing(query):
    """The removed search-relevance judge (docs/search-guidance.md): whatever the search string looks like, nothing is asked, rewritten,
    noted or recorded for a query that does not overlap an earlier visible search, and no clearance is pending."""
    rig = Rig()
    reply = completion(query)
    before = copy.deepcopy(reply)
    assert rig.prepare(reply) is reply and reply == before
    assert rig.ask.call_count == 0 and rig.events == [] and rig.owner.semantic_pending is None and not rig.owner.rehunt_verdicts
    assert webfetch.gate_search(SESSION, query) is None                      # the repeat gate admits a first-time search
