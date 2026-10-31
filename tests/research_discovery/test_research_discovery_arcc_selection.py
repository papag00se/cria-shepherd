"""A research stage the runtime deselects or replaces owns ITS OWN detector and settlement (webfetch consults the bound selection).

Real selection (assistruntime.AssistRuntime.select -> assistruntime.bound), real webfetch/planner entries; only the network
transport (_fetch_and_render) and the spill judge's callbacks are faked."""
from dataclasses import replace
from unittest.mock import Mock, patch

import pytest

from cria import assistruntime, denial, planner_tools, researchpolicies as rp, webfetch as wf

Q = "widget api docs"
URL = "https://example.org/docs"


@pytest.fixture(autouse=True)
def clean():
    wf.clear_cache()
    yield
    wf.clear_cache()


def runtime(*off):
    return assistruntime.AssistRuntime.select(level=5, disabled=tuple(d.policy.id for d in off))


def transport(status=200, discovered=False):
    return patch.object(wf, "_fetch_and_render", return_value=("exact fetched bytes", status, discovered))


def forbid(owner, name):
    return patch.object(owner, name, side_effect=AssertionError(f"{name}: a deselected stage ran its detector"))


def test_a_deselected_search_stage_neither_detects_nor_spends_a_clearance_but_keeps_the_facts():
    """The repeat gate, the one-use clearance and the planner's gate all belong to SEARCH: off means no detector, no settlement, plain results."""
    wf.set_visible("s", [], [Q])
    wf.allow_search("s", Q)
    with assistruntime.bound(runtime(rp.SEARCH)), forbid(rp, "normalize_search"), forbid(planner_tools, "normalize_search"):
        assert wf.prior_matching_search("s", Q) is None
        wf.allow_search("other", "new query")                            # settlement is the stage's too
        assert wf.gate_search("s", Q) is None
        assert planner_tools.gate_search([{"widget", "api", "docs"}], Q) is None
        wf.set_visible("s", [(URL, "", "")], [Q])
        assert wf.visible_urls("s") == {URL}                             # visibility is a fact, not a policy
    assert "other" not in wf._SEARCH_ALLOWED
    assert wf.gate_search("s", Q) is None and denial.is_denied(wf.gate_search("s", Q))   # the stored clearance was never consumed by the off run


def test_the_selected_search_stage_clears_once_per_session_and_refuses_the_rest():
    wf.set_visible("s", [], [Q])
    wf.set_visible("other", [], [Q])
    with assistruntime.bound(runtime()):
        wf.allow_search("s", Q)
        assert wf.gate_search("s", Q) is None                            # one run
        assert denial.is_denied(wf.gate_search("s", Q))
        assert denial.is_denied(wf.gate_search("other", Q))              # another session never inherits it


def test_a_replaced_stage_runs_instead_of_the_canonical_detector_and_owns_the_state():
    seen = []

    def search(source, state):
        seen.append(source.action)
        return rp.Admission(prior="replacement prior")

    fetch = Mock(return_value=rp.Admission(rp.Effect.REFUSED, "replacement refusal"))
    chosen = replace(rp.ResearchSelection(), search=replace(rp.SEARCH, execute=search), fetch=replace(rp.FETCH, execute=fetch))
    with rp.bound(chosen), forbid(rp, "normalize_search"), forbid(wf, "already_spilled"), transport() as net:
        assert wf.prior_matching_search("s", "q") == "replacement prior"
        wf.allow_search("s", "q")
        assert wf.gate_search("s", "q") is None
        assert wf.fetch_nav(URL, session="s") == "replacement refusal"
        net.assert_not_called()
    assert seen == [rp.SearchAction.PRIOR, rp.SearchAction.CLEAR, rp.SearchAction.ADMIT]
    assert not wf._SEARCH_ALLOWED


def test_domain_advice_is_its_own_switch_and_never_changes_admission():
    q = "example.org api docs"
    wf.set_visible("s", [], [q])
    with assistruntime.bound(runtime()):
        advised = wf.gate_search("s", q)
    with assistruntime.bound(runtime(rp.DOMAIN)), forbid(rp, "first_domain_in"):
        muted = wf.gate_search("s", q)
    assert denial.is_denied(advised) and denial.is_denied(muted)         # the repeat is refused either way
    assert "https://example.org" in advised and "https://example.org" not in muted
    replacement = Mock(return_value="replacement domain advice")
    with rp.bound(replace(rp.ResearchSelection(), domain=replace(rp.DOMAIN, execute=replacement))):
        assert "replacement domain advice" in wf.gate_search("s", q)
    assert replacement.call_args.args[0] == q and not wf._SEARCH_ALLOWED


def test_a_fetch_is_identified_by_url_find_cursor_and_raw_and_a_deselected_fetch_stage_keeps_the_exact_transport_bytes():
    wf.set_visible("s", [(URL, "term", "c40", False)], [])
    with assistruntime.bound(runtime()), transport() as net:
        assert denial.is_denied(wf.fetch_nav(URL, session="s", find="term", cursor="c40"))
        net.assert_not_called()
        assert wf.fetch_nav(URL, session="s", find="other", cursor="c40") == "exact fetched bytes"
        assert wf.fetch_nav(URL, session="s", find="term", cursor="c40", raw=True) == "exact fetched bytes"
        assert net.call_args.args[1:3] == ("term", None)
    wf.clear_cache()
    wf._cache_put(URL, 404, "text/plain", "cached body", None, False)
    wf.set_visible("s", [(URL, "", "")], [])
    with assistruntime.bound(runtime(rp.FETCH, rp.FAILURE)), transport(404), forbid(wf, "already_spilled"):
        assert wf.fetch_nav(URL, session="s") == "exact fetched bytes"   # a repeat that WOULD be refused is just fetched
        assert wf.visible_urls("s") == {URL}
    assert not wf._FETCH_STREAK                                          # and no streak was counted


def test_the_failure_streak_is_owned_by_its_stage_and_ignores_internal_hosts():
    with assistruntime.bound(runtime()), transport(404):
        assert [wf.fetch_nav("https://example.org", session="s") for _ in range(2)] == ["exact fetched bytes"] * 2
        assert "guessing" in wf.fetch_nav("https://example.org", session="s")        # the third consecutive external failure
        for internal in ("http://localhost/x", "http://127.0.0.1/x", "http://[::1]/x", "http://192.168.1.1/x", "http://host.local/x"):
            assert wf.fetch_nav(internal, session="i") == "exact fetched bytes"
    assert wf._FETCH_STREAK == {"s": 3}
    with assistruntime.bound(runtime(rp.FAILURE)), transport(404):
        wf.fetch_nav("https://example.org", session="s")
    assert wf._FETCH_STREAK == {"s": 3}                                  # off: the stage did not touch history

    def observe(source, state):
        return rp.Admission(rp.Effect.NOTED, "replacement note")
    with rp.bound(replace(rp.ResearchSelection(), failure=replace(rp.FAILURE, execute=observe))), transport(404):
        assert wf.fetch_nav("https://example.org", session="r") == "exact fetched bytesreplacement note"
    assert "r" not in wf._FETCH_STREAK


def spill():
    src = dict(key="exact/path", query=Mock(return_value="Original Query"), results=Mock(return_value="exact source bytes"),
               task=Mock(return_value="task text"), judge=Mock(return_value=rp.SpillVerdict(False, "better query")),
               protected=Mock(return_value=False))
    return rp.SpillInput(**src), rp.SpillState(), src


def test_a_deselected_or_replaced_spill_stage_owns_all_detection_and_settlement():
    source, state, callbacks = spill()
    state.recommendation = "existing recommendation"
    with assistruntime.bound(runtime(rp.SPILL)):
        assert rp.current().spill_read(source, state).effect is rp.Effect.NO_OP
    assert not state.judged and not state.poisoned and state.recommendation == "existing recommendation"
    assert not any(c.called for k, c in callbacks.items() if k != "key")                 # no read, no question, no veto check
    replacement = Mock(return_value=rp.SpillResult(rp.Effect.WITHHELD, reason="replacement"))
    assert replace(rp.ResearchSelection(), spill=replace(rp.SPILL, execute=replacement)).spill_read(source, state).reason == "replacement"
    assert not state.judged and not callbacks["results"].called


def test_an_empty_selection_stops_every_research_stage_in_every_entry_at_once():
    recent = [{"widget", "api", "docs"}]
    source, state, callbacks = spill()
    wf.set_visible("s", [(URL, "", "")], [Q])
    wf.note_search_spill("s", Q, "recorded/path")
    wf.allow_search("s", Q)
    wf._cache_put(URL, 404, "text/plain", "shared cached bytes", None, False)
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=0)), forbid(rp, "normalize_search"), \
            forbid(planner_tools, "normalize_search"), forbid(rp, "first_domain_in"), forbid(wf, "already_spilled"), transport(404):
        assert wf.prior_matching_search("s", Q) is None and wf.gate_search("s", Q) is None
        assert planner_tools.gate_search(recent, Q) is None
        assert wf.fetch_nav(URL, session="s") == "exact fetched bytes"
        assert rp.current().spill_read(source, state).effect is rp.Effect.NO_OP
        assert wf.spilled_search_files("s") == {"recorded/path": Q}      # facts survive
    assert not wf._FETCH_STREAK and not any(c.called for k, c in callbacks.items() if k != "key")
    assert wf.gate_search("s", Q) is None                                # the stored clearance is intact: the first run after re-selection spends it
    assert denial.is_denied(wf.gate_search("s", Q))
