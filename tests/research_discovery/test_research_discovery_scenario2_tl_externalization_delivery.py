"""A spill offer is owned by the definition that made it: retry returns the same bytes, an error on the offer is remembered (never re-run), an operation id may not be reused for
a different input, a search offer is only believed with checked storage facts, and an absent selection has no lifecycle at all. Also the planner's two spill projections."""
import hashlib

import pytest

from cria import externalization as e

SPILL = e.Spill("p", "body", "pointer")


def source(op="op", offer=None, detect=lambda: SPILL, events=None):
    events = [] if events is None else events
    return e.Input(op, "raw", e.Services(detect, offer or (lambda s: s.pointer), lambda s: events.append(s.target))), events


def test_a_retry_shares_the_offer_an_error_is_remembered_and_an_identity_is_not_reused():
    st, calls = e.State(), []
    src, _ = source(offer=lambda s: calls.append(1) or (_ for _ in ()).throw(OSError("disk full")))
    for _ in range(2):
        with pytest.raises(OSError, match="disk full"): e.externalize(src, st)
    assert calls == [1]                                                  # an unknown write outcome is never executed twice
    other, _ = source()
    with pytest.raises(ValueError, match="reused"): e.externalize(other, st)
    ok, _ = source("ok")
    st._operations["ok"] = e._Pending(ok, e.Result("x"))                 # an offer that is still in flight
    with pytest.raises(RuntimeError, match="already being offered"): e.externalize(ok, st)


def test_a_selected_definition_owns_delivery_settle_cancel_and_reset_and_an_absent_one_owns_nothing():
    st = e.State()
    gone = e.selected_externalization(None, source()[0], st)
    assert (gone.result, gone.owner) == (e.Result("raw"), None) and not gone.settle(e.Outcome.RETAINED, stored=True) and not gone.cancel() and gone.reset() is None
    src, recorded = source("a")
    d = e.selected_externalization(e.DEFINITION, src, st)
    assert e.selected_externalization(e.DEFINITION, src, st) is d and d.result.payload == "pointer"
    with pytest.raises(ValueError, match="reused"): e.selected_externalization(e.DEFINITION, source("a")[0], st)
    assert d.settle(e.Outcome.RETAINED, stored=True) and recorded == ["p"]
    src2, recorded2 = source("b")
    d2 = e.selected_externalization(e.DEFINITION, src2, st)
    assert d2.cancel() is False and recorded2 == []                      # cancelled -> terminal, nothing recorded
    old = e.selected_externalization(e.DEFINITION, source("c")[0], st)
    st.reset(); fresh = e.selected_externalization(e.DEFINITION, source("c")[0], st)
    old.reset()                                                          # a late reset from the previous task...
    assert fresh.result is st._operations["c"].result                    # ...does not clear the successor
    fresh.reset(); assert not st._operations
    plain = e.selected_externalization(e.DEFINITION, source("n", detect=lambda: None)[0], st)
    assert plain.result == e.Result("raw") and not plain.settle(e.Outcome.RETAINED, stored=True)


def test_a_search_offer_needs_checked_storage_facts_for_the_same_target():
    body = "3 results\nrow"
    sha = hashlib.sha256(body.encode()).hexdigest()
    offer = e.SearchOffer("tmp/s.txt", e.search_program(100))
    st = e.State()
    src, recorded = source("s", offer=lambda o: "see tmp/s.txt", detect=lambda: offer)
    r = e.externalize(src, st)
    for facts in (False, True, e.SearchStored("elsewhere.txt", 5, sha)):
        assert not st.settle(r, e.Outcome.RETAINED, stored=facts)       # not believed, and the offer stays pending for a retry
    assert st.settle(r, e.Outcome.RETAINED, stored=e.SearchStored("tmp/s.txt", len(body), sha)) and recorded == ["tmp/s.txt"]
    for bad in (("", 1, sha), ("t", -1, sha), ("t", True, sha), ("t", 1, "ABC"), (3, 1, sha)):
        with pytest.raises(ValueError, match="Invalid checked search"): e.SearchStored(*bad)


def test_the_planners_fetch_and_search_spills_keep_their_existing_thresholds_and_names(tmp_path):
    svc = e.PlannerFetchServices(10, lambda red, parsed, ct: f"[{ct}] {red}", lambda url: "x/" + url.rsplit("/", 1)[-1] + ".json", lambda parsed, target: "outline")
    assert e.planner_fetch(status=200, url="u", reduced="short", parsed=None, content_type=None, root="/s", remedy=lambda t: t, services=svc) is None
    big = e.planner_fetch(status=200, url="https://h/spec", reduced="x" * 50, parsed=1, content_type="json", root="/s", remedy=lambda t: "grep " + t, services=svc)
    assert big.target == "/s/spec.json" and big.content.startswith("[json] xxx") and "/s/spec.json" in big.pointer and "grep /s/spec.json" in big.pointer
    text = "Search results for: ada handles!\n1. First\nnoise\n2) Second\n10. Tenth"
    assert e.planner_search("q", text, scratch=None, inline_chars=5, remedy=lambda t: t) is None
    assert e.planner_search("q", text, scratch="/s", inline_chars=10_000, remedy=lambda t: t) is None
    s = e.planner_search("Ada Handles!!", text, scratch="/s", inline_chars=5, remedy=lambda t: "R:" + t)
    assert s.target == "/s/search-ada-handles.txt" and s.content == text and "1. First" in s.pointer and "10. Tenth" in s.pointer and "noise" not in s.pointer
    assert e.planner_search("!!!", text, scratch="/s", inline_chars=5, remedy=str).target == "/s/search-search.txt"
    assert e.planner_search("a" * 100, text, scratch="/s", inline_chars=5, remedy=str).target == "/s/search-" + "a" * 60 + ".txt"
