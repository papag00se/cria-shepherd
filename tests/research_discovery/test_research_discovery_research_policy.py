"""Research policy: re-hunt judged once and cleared once; reading back your own writing is not research."""
import json
import uuid
from unittest.mock import Mock

import pytest

from cria import bodykeys, denial, semanticquery as policy, webfetch
from cria.research import files_read

PRIOR = "ADA Handle API resolve handle to address holder address total handles"
QUERY = "ADA Handle API resolve handle holder"

def request(session, reply, query=QUERY):
    """A re-hunt question whose reasoner (the only external boundary) answers `reply`."""
    coder = {"choices": [{"message": {"tool_calls": [{"id": "s", "type": "function", "function": {"name": "web_search", "arguments": json.dumps({"query": query})}}]}}]}
    facts = Mock(return_value=policy.QuestionFacts("resolve an Ada Handle via the API", "menu"))
    ask = Mock(return_value=reply)
    judge = policy.Judge(ask, Mock(side_effect=AssertionError), object(), Mock())
    return policy.RehuntInput(coder, session, facts, judge), ask, facts

@pytest.mark.parametrize("reply,fresh", [("garbage", False), ("{}", False), ('{"new_direction":false}', False), ('{"new_direction":true}', True)])
def test_a_rehunt_is_judged_once_and_a_new_direction_runs_exactly_once(reply, fresh):
    """Only an affirmative reasoner verdict clears the repeat gate, the clearance is consumed by the run, and a cached verdict never re-mints it."""
    session = "semantic-" + uuid.uuid4().hex
    try:
        webfetch.set_visible(session, [], [PRIOR])
        req, ask, _ = request(session, reply)
        state = policy.RehuntState()
        out = policy.rehunt(req, state)
        assert out == policy.RehuntResult(QUERY, PRIOR.lower(), fresh, fresh) and state.verdicts == {QUERY: fresh}
        assert (webfetch.gate_search(session, QUERY) is None) is fresh      # the clearance licenses ONE run
        assert webfetch.gate_search(session, QUERY) is not None
        assert not policy.rehunt(req, state).clearance_requested and ask.call_count == 1   # cached: not asked again, no second clearance
        state.reset()
        assert policy.rehunt(req, state).clearance_requested is fresh and ask.call_count == 2
    finally:
        webfetch.reset_session(session)

def test_a_deferred_clearance_stays_requested_for_a_cached_positive_verdict_and_a_disabled_policy_asks_nothing():
    """MUT2 (semanticquery survivors): with the grant deferred to delivery a cached 'new direction' still asks for it on the next turn
    (nothing was spent); a historical record of that verdict mints nothing; a disabled policy never reaches the reasoner."""
    session = "semantic-" + uuid.uuid4().hex
    try:
        webfetch.set_visible(session, [], [PRIOR])
        req, ask, _ = request(session, '{"new_direction":true}')
        req = policy.RehuntInput(req.coder, req.session, req.facts, req.judge, defer_clearance=True)
        state = policy.RehuntState()
        assert policy.rehunt(req, state).clearance_requested and webfetch.gate_search(session, QUERY) is not None
        assert policy.rehunt(req, state) == policy.RehuntResult(QUERY, PRIOR.lower(), True, True) and ask.call_count == 1
        assert not policy.rehunt(req, policy.RehuntState({QUERY: True})).clearance_requested and ask.call_count == 1
        assert policy.rehunt(req, policy.RehuntState(), enabled=False) == policy.RehuntResult() and ask.call_count == 1
    finally:
        webfetch.reset_session(session)

@pytest.mark.parametrize("change,spent", [({}, True), ({"clearance_requested": False}, False), ({"new_direction": None}, False), ({"new_direction": False}, False),
                                          ({"prior": None}, False), ({"query": "something the coder did not ask"}, False)])
def test_a_clearance_is_spent_only_by_the_exact_search_call_that_was_judged(change, spent):
    """MUT2 (semanticquery survivors in settle_rehunt): every missing condition of a deferred clearance leaves the repeat gate shut."""
    session = "semantic-" + uuid.uuid4().hex
    try:
        webfetch.set_visible(session, [], [PRIOR])
        req, _, _ = request(session, '{"new_direction":true}')
        result = policy.RehuntResult(QUERY, PRIOR.lower(), True, True)
        result = policy.RehuntResult(**{**result.__dict__, **change})
        log = Mock()
        assert policy.settle_rehunt(result, req.coder, session, log) is spent
        assert (webfetch.gate_search(session, QUERY) is None) is spent and log.emit.called is spent
    finally:
        webfetch.reset_session(session)

def test_reading_back_what_the_coder_wrote_is_not_research_but_a_preexisting_file_is():
    """nemotron-elastic/rust 0033: the research step closed on a test file the coder had written four calls earlier."""
    call = lambda name, path, tid: {"role": "assistant", "content": None, "tool_calls": [{"id": tid, "type": "function", "function": {"name": name, "arguments": json.dumps({"path": path})}}]}
    result = lambda tid, body, outcome=None: {"role": "tool", "tool_call_id": tid, "content": body, **({bodykeys.RESULT_OUTCOME: outcome} if outcome else {})}
    wrote = [call("write_file", "tests/mine.rs", "w1"), result("w1", "Wrote it", "landed"), call("edit_file", "src/main.rs", "e1"), result("e1", "Edited", "landed")]
    read = [call("read_file", "tests/mine.rs", "r1"), result("r1", "fn t() {}"), call("read_file", "src/main.rs", "r2"), result("r2", "fn main() {}"),
            call("read_file", "Cargo.toml", "r3"), result("r3", "[package]")]
    assert [p for p, _ in files_read(wrote + read)] == ["Cargo.toml"]
    refused = [call("read_file", "big.json", "r9"), result("r9", denial.mark("too large to return"), denial.REFUSED)]
    assert files_read(refused) == []   # an attempted read is not a read


def test_an_identical_or_unrelated_visible_search_asks_nothing():
    """No visible near-duplicate means no re-hunt to judge: the reasoner is never called."""
    for visible in ([], [QUERY], ["entirely unrelated prior"]):
        session = "semantic-" + uuid.uuid4().hex
        webfetch.set_visible(session, [], visible)
        req, ask, _ = request(session, '{"new_direction": true}')
        assert not policy.rehunt(req, policy.RehuntState()).clearance_requested
        ask.assert_not_called()
