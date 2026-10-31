"""Wave 9 coverage: the per-session ledgers a research turn leans on, and what a judge is told cria has read.

`depsurface`'s anchor / abstain / withheld ledgers are keyed by session: no key means no memory (never a shared bucket), a
runaway count of sessions or of coordinates is bounded rather than leaking, an abstain counts down to a real retry, and a
withheld pointer is only surfaced while its coordinate is still declared. `groundtruth.researched_facts` says what was
READ (routes, shapes) and is silent, never "(none)", when nothing spec-shaped was fetched.
"""
import pytest

from cria import depsurface as ds, fetchfacts as ff, groundtruth as gt

C1, C2 = ("go", "mod/a", "v1"), ("go", "mod/b", "v2")


@pytest.fixture(autouse=True)
def clean():
    """The ledgers are module dicts shared by the whole process: empty them for the test and put back what was there."""
    saved = [dict(s) for s in (ds._ANCHOR, ds._ABSTAINED, ds._WITHHELD)]
    for s in (ds._ANCHOR, ds._ABSTAINED, ds._WITHHELD): s.clear()
    yield
    for s, old in zip((ds._ANCHOR, ds._ABSTAINED, ds._WITHHELD), saved): s.clear(); s.update(old)


def test_a_missing_session_key_means_no_memory_in_every_ledger():
    ds.set_anchor_state("", C1, "c1", "note"); ds.set_anchor_state("s", C1, "", "note"); ds.record_abstain("", C1); ds.record_withheld("", C1, "l", "/r", "h")
    assert ds._ANCHOR == {} and ds._ABSTAINED == {} and ds._WITHHELD == {}
    assert ds.anchor_state("", C1) is None and ds.should_retry_gather("", C1) is True
    assert ds.is_withheld("", C1) is False and ds.withheld_pointers("", {C1}) == []
    ds.clear_abstain("", C1)


def test_anchors_move_on_anchor_loss_and_a_runaway_ledger_is_bounded_not_leaked(monkeypatch):
    ds.set_anchor_state("s", C1, "c1", "note A"); ds.set_anchor_state("s", C1, "c9", "note A")       # anchor loss: the SAME coordinate moves
    assert ds.anchor_state("s", C1) == ("c9", "note A") and ds.anchor_state("s", C2) is None and ds.anchor_state("other", C1) is None
    monkeypatch.setattr(ds, "_ANCHOR_MAX_PER_SESSION", 1)
    ds.set_anchor_state("s", C2, "c2", "note B")                                                      # full bucket: a NEW coordinate is not recorded...
    ds.set_anchor_state("s", C1, "c10", "note C")                                                     # ...but a known one still moves
    assert ds.anchor_state("s", C2) is None and ds.anchor_state("s", C1) == ("c10", "note C")
    monkeypatch.setattr(ds, "_ANCHOR_MAX_SESSIONS", 1)
    ds.set_anchor_state("t", C1, "c1", "n"); ds.set_anchor_state("u", C1, "c1", "n")                  # a third session past the cap clears the stale ledger
    assert set(ds._ANCHOR) == {"u"}


def test_an_abstained_coordinate_skips_requests_then_retries_for_real_and_a_success_forgets_it(monkeypatch):
    ds.record_abstain("s", C1)
    skips = [ds.should_retry_gather("s", C1) for _ in range(ds._ABSTAIN_RETRY_EVERY)]
    assert skips[:-1] == [False] * (ds._ABSTAIN_RETRY_EVERY - 1) and skips[-1] is True                # skipped N-1 times, the Nth really retries
    assert ds.should_retry_gather("s", C2) is True and ds.should_retry_gather("other", C1) is True
    ds.record_abstain("s", C1); ds.clear_abstain("s", C1); ds.clear_abstain("s", C2)
    assert ds.should_retry_gather("s", C1) is True
    monkeypatch.setattr(ds, "_ABSTAIN_MAX_SESSIONS", 1)
    ds.record_abstain("a", C1); ds.record_abstain("b", C1)
    assert set(ds._ABSTAINED) == {"b"}


def test_withheld_pointers_are_permanent_but_only_surfaced_while_their_coordinate_is_declared(monkeypatch):
    ds.record_withheld("s", C1, "mod/a v1", "/root/a", "ls /root/a"); ds.record_withheld("s", C2, "mod/b v2", "/root/b", "ls /root/b")
    assert ds.is_withheld("s", C1) and not ds.is_withheld("s", ("go", "mod/c", "v1")) and not ds.is_withheld("t", C1)
    assert ds.withheld_pointers("s", {C2}) == [("mod/b v2", "/root/b", "ls /root/b")]                # a version bump removed C1 from the manifest
    assert ds.withheld_pointers("s", set()) == [] and ds.withheld_pointers("nobody", {C1}) == []
    monkeypatch.setattr(ds, "_WITHHELD_MAX_PER_SESSION", 2)
    ds.record_withheld("s", ("go", "mod/c", "v1"), "c", "/c", "h"); ds.record_withheld("s", C1, "mod/a v1", "/root/a2", "ls /root/a2")
    assert not ds.is_withheld("s", ("go", "mod/c", "v1")) and ds.withheld_pointers("s", {C1}) == [("mod/a v1", "/root/a2", "ls /root/a2")]
    monkeypatch.setattr(ds, "_WITHHELD_MAX_SESSIONS", 1)
    ds.record_withheld("t", C1, "l", "/r", "h"); ds.record_withheld("u", C1, "l", "/r", "h")
    assert set(ds._WITHHELD) == {"u"}


def test_researched_facts_names_what_was_read_and_says_nothing_when_nothing_was_fetched():
    shape = ff.Shape("GET /handles/{h}", route="/handles/{h}", body='{"total_handles": 3}')
    ledger = {"https://x/openapi.json": ("HTTP 200", ("GET /handles/{h}", "GET /holders"), (shape,), ()),
              "https://x/page": ("HTTP 200", (), (), ()), "https://x/other": ("HTTP 404",)}
    facts = gt.researched_facts(ledger)
    assert "Endpoints read: GET /handles/{h}, GET /holders" in facts and 'GET /handles/{h} returns:\n{"total_handles": 3}' in facts
    assert gt.researched_facts({"https://x/page": ("HTTP 200", (), (), ())}) == "" and gt.researched_facts({}) == "" and gt.researched_facts(None) == ""
    only_routes = gt.researched_facts({"u": ("HTTP 200", ("GET /a",), (), ())})
    assert "GET /a" in only_routes and "returns:" not in only_routes
