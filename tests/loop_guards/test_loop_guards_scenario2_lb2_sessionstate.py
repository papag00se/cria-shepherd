"""Session-scoped memory and the thin adapters around it: the durable refusal/fetch ledgers a steer may cite after the window moves on, the
aliases that let a named pending probe settle through the shared state, the per-reply receipts of what reached the wire, and the search-file reader."""
import json
from types import SimpleNamespace

import pytest

from cria import loop, refusalledger, wsview


def test_a_session_remembers_what_was_refused_and_fetched_only_when_there_is_a_session():
    for track in (loop._track_fetched_pages, loop._track_refused_names):
        track(None, [])                                                                              # no session: nothing to remember
    assert loop._session_refusals(None) is None
    sess = SimpleNamespace(refused_names={"github.com/x/y"})
    assert loop._session_refusals(sess) == {"github.com/x/y"}                                         # the legacy set until a ledger exists
    loop._track_refused_names(sess, [])
    assert isinstance(sess.refusal_events, refusalledger.RefusalLedger) and sess.refused_names == {"github.com/x/y"}
    assert loop._session_refusals(sess) is sess.refusal_events
    sess.refusal_events = refusalledger.RefusalLedger.from_legacy(set())                              # a ledger emptied by a later success is not the stale set
    assert loop._session_refusals(sess) is sess.refusal_events and loop._session_refusals(SimpleNamespace()) is None
    fresh = SimpleNamespace()
    loop._track_fetched_pages(fresh, [])
    assert fresh.fetched_pages == {}


def test_a_named_pending_probe_reads_and_writes_through_to_the_state_it_wraps():
    state = SimpleNamespace(page_probe="", other=7)
    alias = loop._NamedProbeState(state, "page_probe")
    assert alias.done_probe is False and alias.other == 7 and alias.probe_call_id == ""
    alias.probe_call_id = "p1"
    assert (state.page_probe, state.probe_call_id, alias.done_probe) == ("p1", "p1", True)
    alias.gate_fresh = True
    assert state.gate_fresh is True


def test_the_runner_signature_lives_on_the_guard_state_not_on_the_view():
    gs = loop.GuardState()
    view = loop._RunnerStateView(gs)
    view.signature = "sig-1"
    assert gs.runner_reset_signature == "sig-1" and view.signature == "sig-1"


def test_each_coder_reply_keeps_the_receipt_and_remediation_of_the_call_that_produced_it():
    sess = SimpleNamespace(guidance_history=[], guidance_delivered_seq={}, action_seq=4)
    rlog = SimpleNamespace(guidance_on_wire=[])

    def chat(body, rlog_):
        rlog_.restored_on_wire = {"a.py": "sha"}
        rlog_.guidance_on_wire = ["note one"]
        return b"{}"
    receipts = loop._CoderReplyReceipts(chat, sess)
    assert receipts.chat({"cria_completion_remediation": ""}, rlog) == b"{}"
    first = {"choices": []}
    receipts.record(first)
    receipts.record({"choices": ["other"]}, {"b.py": "x"}, remediation="missing.py")
    assert receipts.receipt(first) == {"a.py": "sha"} and receipts.remediation_receipt(first) == ""
    assert receipts.remediation_receipt(receipts._replies[1][0]) == "missing.py" and receipts.receipt({"unknown": 1}) == {}
    assert receipts.remediation_receipt({"unknown": 1}) == "" and sess.guidance_history == ["note one"] and sess.guidance_delivered_seq == {"note one": 4}


def test_a_search_file_is_read_from_the_workspace_never_from_crias_own_directory(tmp_path):
    (tmp_path / "tmp").mkdir()
    (tmp_path / "tmp" / "search.txt").write_text("results here")
    token = wsview.bind(wsview.DirectView(str(tmp_path)))
    try:
        assert loop.search_file_text(str(tmp_path), "./tmp/search.txt") == "results here"
        assert loop.search_file_text(str(tmp_path), "tmp/gone.txt") == "" and loop.search_file_text(str(tmp_path), "") == ""
        assert loop.search_file_text("", "tmp/search.txt") == ""
    finally:
        wsview.unbind(token)
    assert loop._results_name_the_tasks_host("use api.handle.me docs", "see https://API.handle.me/x") == "api.handle.me"
    assert loop._results_name_the_tasks_host("", "x.com") == "" and loop._results_name_the_tasks_host("use x.com", "") == ""
    assert loop._results_name_the_tasks_host("use x.com", "nothing relevant") == ""


@pytest.mark.parametrize("one,two,root,same", [("a.py", "a.py", "", True), ("/w/a.py", "a.py", "/w", True), ("/w/a.py", "b.py", "/w", False),
                                                ("", "a.py", "/w", False), ("a/../a.py", "a.py", "", True)])
def test_two_spellings_are_one_file_only_when_they_normalise_to_one_path(one, two, root, same):
    assert loop._same_workspace_file(one, two, root) is same


def test_nested_argument_values_flatten_in_order():
    assert loop._flat_values({"a": [1, {"b": "x"}], "c": None}) == [1, "x", None] and loop._flat_values("s") == ["s"]
