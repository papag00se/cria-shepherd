"""Externalization: a spill is offered once, recorded only after checked storage of the retained original, and never costs an inline byte."""
import pytest

from cria import externalization as e, webfetch


def inp(call_id="x", events=None, spill=("p", "body", "pointer"), raw="raw", offer=None):
    events = [] if events is None else events
    return e.Input(call_id, raw, e.Services(lambda: e.Spill(*spill) if spill else None,
                                            offer or (lambda s: s.pointer), lambda s: events.append(s.target))), events


@pytest.mark.parametrize("outcome,stored,recorded", [(e.Outcome.RETAINED, True, True), (e.Outcome.RETAINED, False, False),
                                                      (e.Outcome.UNKNOWN, True, False), (e.Outcome.FAILED, True, False), (e.Outcome.CANCELLED, True, False)])
def test_a_claim_needs_checked_storage_and_a_retained_original_and_settles_once(outcome, stored, recorded):
    source, events = inp()
    state = e.State()
    result = e.externalize(source, state)
    assert result.payload == "pointer" and e.externalize(source, state) is result   # offered once, identical on retry
    assert state.settle(result, outcome, stored=stored) is recorded
    assert state.settle(result, outcome, stored=stored) is False and events == (["p"] if recorded else [])


def test_no_offer_or_a_declined_offer_or_absence_retains_every_inline_byte():
    """The model keeps all of the original when nothing was stored (no spill found, offer declined, feature absent)."""
    raw = "raw\r\n尾\x00"
    for source in (inp(raw=raw, spill=None)[0], inp(raw=raw, offer=lambda s: None)[0]):
        state = e.State()
        assert e.externalize(source, state) == e.Result(raw) and not state.settle(e.externalize(source, state), e.Outcome.RETAINED, stored=True)
    forbidden = lambda *a: pytest.fail("optional service reached")
    off = e.Input("c", raw, e.Services(forbidden, forbidden, forbidden))
    assert e.externalize(off, e.State(), enabled=False) == e.Result(raw)
    assert e.coder_fetch("url", find="", cursor=None, services=e.FetchServices(2, forbidden, forbidden)) is None   # navigation is not externalized


def test_a_reset_or_a_newer_task_cannot_be_settled_by_a_stale_delivery():
    """Late delivery from before a reset must not clear the new task's record; a reset during the offer does not resurrect state."""
    state, records = e.State(), []
    def source(owner):
        return e.Input("same-id", "raw", e.Services(lambda: e.Spill("p", "b", "pointer"), lambda s: s.pointer, lambda s: records.append(owner)))
    old = e.externalize(source("old"), state)
    state.reset()
    new = e.externalize(source("new"), state)
    assert not state.settle(old, e.Outcome.RETAINED, stored=True) and state.settle(new, e.Outcome.RETAINED, stored=True) and records == ["new"]
    mid = e.State()
    def offer(spill):
        mid.reset()
        return spill.pointer
    result = e.externalize(inp("y", offer=offer)[0], mid)
    assert result.payload == "pointer" and not mid.settle(result, e.Outcome.RETAINED, stored=True)


def test_search_storage_keeps_full_results_whichever_branch_is_inlined_and_demands_typed_facts():
    """Byte budget is inclusive and UTF-8 aware; the stored file is the full text either way; storage facts are typed, not success booleans."""
    full = "FULL\nα\nEND"
    assert e.coder_search(target="p", full=full, brief="α\n", pointer="PTR", inline_bytes=3) == e.Spill("p", full, "α\n")
    assert e.coder_search(target="p", full=full, brief="α\n", pointer="PTR", inline_bytes=2) == e.Spill("p", full, "PTR")
    for bad in ((-1, "0" * 64), (True, "0" * 64), (0, "A" * 64), (0, "a" * 63), (0, None)):
        with pytest.raises(ValueError):
            e.SearchStored("./tmp/reference/search-q.txt", *bad)
    with pytest.raises(ValueError):
        e.DEFINITION.search_program(-1)


def test_a_planner_spill_holds_the_full_document_and_the_full_results():
    """Planner gather: the stored content is the whole page / result text; below the threshold nothing is spilled."""
    body = "Search results for: Q\n1. Title\n  https://example.test\n  α tail\n"
    spill = e.planner_search("Q", body, scratch="/owned", inline_chars=1, remedy=lambda p: "READ " + p)
    assert spill.content == body and spill.target == "/owned/search-q.txt" and "saved IN FULL to /owned/search-q.txt" in spill.pointer
    assert e.planner_search("Q", body, scratch="/owned", inline_chars=len(body), remedy=lambda p: pytest.fail("remedy")) is None
    page = e.planner_fetch(status=200, url="https://example.test/doc", reduced="α\nEND\n", parsed=None, content_type="text/plain", root="/owned",
                           remedy=lambda p: "READ", services=e.PlannerFetchServices(2, webfetch.spill_content, webfetch._spill_name, lambda parsed, t: "OUTLINE\n"))
    assert page.content == "α\nEND\n" and "OUTLINE" in page.pointer and "do NOT re-fetch the url" in page.pointer
