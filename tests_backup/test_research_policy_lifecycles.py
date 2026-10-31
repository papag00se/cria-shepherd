"""Real research boundaries with fake transport; no network or workspace probes."""
from dataclasses import replace
from unittest.mock import Mock, patch

import pytest

from cria import denial, researchpolicies as rp, webfetch as wf


@pytest.fixture(autouse=True)
def clean_state():
    wf.clear_cache()
    yield
    wf.clear_cache()


def disabled(*definitions):
    return rp.ResearchSelection.select(tuple(d.policy.id for d in definitions))


def fake_fetch(status=200, discovered=False):
    return patch.object(wf, "_fetch_and_render", return_value=("exact fetched bytes", status, discovered))


def test_search_refusal_uses_recorded_query_and_spill_path():
    wf.set_visible("s", [], ["Ruby Gem EU Membership"])
    wf.note_search_spill("s", "Ruby Gem EU Membership", "./tmp/reference/original.txt")
    note = wf.gate_search("s", "ruby gem eu membership")
    assert denial.is_denied(note)
    assert "./tmp/reference/original.txt" in note
    assert "ruby gem eu membership" in note
    assert wf.spilled_search_files("s") == {"./tmp/reference/original.txt": "Ruby Gem EU Membership"}


def test_native_search_refusal_does_not_invent_a_spill():
    wf.set_visible("s", [], ["widget api docs"])
    note = wf.gate_search("s", "widget api docs")
    assert denial.is_denied(note)
    assert "tmp/reference" not in note
    wf.set_visible("s", [], [])
    assert wf.gate_search("s", "widget api docs") is None


def test_one_use_semantic_clearance_and_session_isolation():
    wf.set_visible("s", [], ["widget api docs"])
    wf.set_visible("other", [], ["widget api docs"])
    wf.allow_search("s", "widget api docs")
    assert wf.gate_search("s", "widget api docs") is None
    assert denial.is_denied(wf.gate_search("s", "widget api docs"))
    assert denial.is_denied(wf.gate_search("other", "widget api docs"))


def test_disabled_search_skips_detector_and_clearance_settlement_but_keeps_facts():
    wf.set_visible("s", [], ["widget api docs"])
    wf.allow_search("s", "widget api docs")
    before = {s: set(v) for s, v in wf._SEARCH_ALLOWED.items()}
    with rp.bound(disabled(rp.SEARCH)), patch.object(rp, "normalize_search", side_effect=AssertionError("detector")):
        assert wf.prior_matching_search("s", "widget api docs") is None
        wf.allow_search("other", "new query")
        assert wf.gate_search("s", "widget api docs") is None
        wf.set_visible("s", [("https://example.org", "", "")], ["widget api docs"])
        assert wf.visible_urls("s") == {"https://example.org"}
    assert wf._SEARCH_ALLOWED == before
    assert wf.gate_search("s", "widget api docs") is None
    assert denial.is_denied(wf.gate_search("s", "widget api docs"))


def test_replaced_search_owns_prior_clearance_and_admission():
    calls = []
    def replacement(source, state):
        calls.append(source.action)
        return rp.Admission(prior="replacement prior")
    with rp.bound(replace(rp.ResearchSelection(), search=replace(rp.SEARCH, execute=replacement))):
        assert wf.prior_matching_search("s", "q") == "replacement prior"
        wf.allow_search("s", "q")
        assert wf.gate_search("s", "q") is None
    assert calls == [rp.SearchAction.PRIOR, rp.SearchAction.CLEAR, rp.SearchAction.ADMIT]
    assert not wf._SEARCH_ALLOWED


def test_domain_advice_is_independently_selected_and_does_not_change_admission():
    q = "example.org api docs"
    wf.set_visible("s", [], [q])
    enabled = wf.gate_search("s", q)
    with rp.bound(disabled(rp.DOMAIN)), patch.object(rp, "first_domain_in", side_effect=AssertionError("domain detector")):
        muted = wf.gate_search("s", q)
    assert "https://example.org" in enabled
    assert "https://example.org" not in muted
    assert denial.is_denied(muted)


def test_domain_replacement_controls_advice_without_changing_repeat_state():
    q = "example.org api docs"
    wf.set_visible("s", [], [q])
    replacement = Mock(return_value="replacement domain advice")
    with rp.bound(replace(rp.ResearchSelection(), domain=replace(rp.DOMAIN, execute=replacement))):
        note = wf.gate_search("s", q)
    assert denial.is_denied(note) and "replacement domain advice" in note
    assert replacement.call_args.args[0] == q
    assert not wf._SEARCH_ALLOWED


@pytest.mark.parametrize("url", ["http://localhost/x", "http://127.0.0.1/x", "http://[::1]/x", "http://192.168.1.1/x", "http://host.local/x"])
def test_internal_hosts_never_refuse_or_update_failure_streak(url):
    wf.set_visible("s", [(url, "", "")], [])
    with fake_fetch(404) as transport:
        assert wf.fetch_nav(url, session="s") == "exact fetched bytes"
    transport.assert_called_once()
    assert "s" not in wf._FETCH_STREAK


def test_fetch_identity_preserves_find_cursor_and_raw():
    url = "https://example.org/docs"
    wf.set_visible("s", [(url, "term", "c40", False)], [])
    with fake_fetch() as transport:
        assert denial.is_denied(wf.fetch_nav(url, session="s", find="term", cursor="c40"))
        transport.assert_not_called()
        assert wf.fetch_nav(url, session="s", find="other", cursor="c40") == "exact fetched bytes"
        assert wf.fetch_nav(url, session="s", find="term", cursor="c40", raw=True) == "exact fetched bytes"
    assert transport.call_count == 2
    assert transport.call_args.args[1:3] == ("term", None)


def test_disabled_fetch_retains_document_cache_visibility_and_exact_transport_bytes():
    url = "https://example.org/docs"
    wf._cache_put(url, 404, "text/plain", "cached body", None, False)
    wf.set_visible("s", [(url, "", "")], [])
    with rp.bound(disabled(rp.FETCH, rp.FAILURE)), fake_fetch(404), \
            patch.object(wf, "already_spilled", side_effect=AssertionError("spill detector")):
        assert wf.fetch_nav(url, session="s") == "exact fetched bytes"
        assert wf.cached_structure(url) is False
        assert wf.visible_urls("s") == {url}
    assert not wf._FETCH_STREAK


def test_fetch_replacement_runs_instead_of_old_detector():
    replacement = replace(rp.FETCH, execute=lambda source: rp.Admission(rp.Effect.REFUSED, "replacement refusal"))
    with rp.bound(replace(rp.ResearchSelection(), fetch=replacement)), fake_fetch() as transport, \
            patch.object(wf, "already_spilled", side_effect=AssertionError("old detector")):
        assert wf.fetch_nav("https://example.org", session="s") == "replacement refusal"
        transport.assert_not_called()


def test_failed_repeat_has_status_and_does_not_run_transport():
    url = "https://example.org/missing"
    wf._cache_put(url, 404, "text/plain", "error bytes", None, False)
    wf.set_visible("s", [(url, "", "")], [])
    with fake_fetch() as transport:
        note = wf.fetch_nav(url, session="s")
    assert denial.is_denied(note) and "404" in note
    transport.assert_not_called()


def test_spill_refusal_requires_verified_presence_and_keeps_outline():
    url = "https://example.org/docs"
    with patch.object(wf, "already_spilled", return_value=True), \
            patch.object(wf, "outline_for_url", return_value="exact outline"), fake_fetch() as transport:
        note = wf.fetch_nav(url, session="s")
        assert denial.is_denied(note) and "exact outline" in note
        transport.assert_not_called()
    with patch.object(wf, "already_spilled", return_value=False), fake_fetch():
        assert wf.fetch_nav(url, session="s") == "exact fetched bytes"


def test_failure_lifecycle_threshold_success_discovery_unknown_and_disabled():
    url = "https://example.org"
    with fake_fetch(404):
        assert wf.fetch_nav(url, session="s") == "exact fetched bytes"
        assert wf.fetch_nav(url, session="s") == "exact fetched bytes"
        assert "guessing" in wf.fetch_nav(url, session="s")
    with rp.bound(disabled(rp.FAILURE)), fake_fetch(200):
        assert wf.fetch_nav(url, session="s") == "exact fetched bytes"
    assert wf._FETCH_STREAK["s"] == 3
    with fake_fetch(None):
        assert wf.fetch_nav(url, session="s") == "exact fetched bytes"
    assert wf._FETCH_STREAK["s"] == 3
    with fake_fetch(405, discovered=True):
        assert wf.fetch_nav(url, session="s") == "exact fetched bytes"
    assert wf._FETCH_STREAK["s"] == 0
    with fake_fetch(404):
        wf.fetch_nav(url, session="s")
    with fake_fetch(200):
        wf.fetch_nav(url, session="s")
    assert wf._FETCH_STREAK["s"] == 0


def test_failure_replacement_owns_observation_without_original_history_updates():
    seen = []
    def observe(source, state):
        seen.append(source.status)
        return rp.Admission(rp.Effect.NOTED, "replacement note")
    with rp.bound(replace(rp.ResearchSelection(), failure=replace(rp.FAILURE, execute=observe))), fake_fetch(404):
        assert wf.fetch_nav("https://example.org", session="s") == "exact fetched bytesreplacement note"
    assert seen == [404] and not wf._FETCH_STREAK


def test_task_reset_keeps_shared_cache_and_other_session():
    wf._cache_put("https://example.org", 200, None, "bytes", None, False)
    for session in ("s", "other"):
        wf.allow_search(session, "q")
        wf.set_visible(session, [("https://example.org", "", "")], ["q"])
        wf.note_search_spill(session, "q", "recorded")
        with fake_fetch(404):
            wf.fetch_nav("https://failure.org", session=session)
    wf.reset_session("s")
    assert wf.visible_urls("s") == set() and not wf.spilled_search_files("s")
    assert "s" not in wf._SEARCH_ALLOWED and "s" not in wf._FETCH_STREAK
    assert wf.visible_urls("other") and wf.spilled_search_files("other")
    assert wf.cached_structure("https://example.org") is False


def spill_source(**changes):
    values = dict(key="exact/path", query=Mock(return_value="Original Query"), results=Mock(return_value="exact source bytes"),
                  task=Mock(return_value="task text"), judge=Mock(return_value=rp.SpillVerdict(False, "better query")),
                  protected=Mock(return_value=False))
    return rp.SpillInput(**{**values, **changes})


def test_spill_poisoning_owns_judgment_repeat_and_recommendation():
    source, state = spill_source(), rp.SpillState()
    assert rp.SPILL.execute(source, state) == rp.SpillResult(rp.Effect.POISONED, "better query")
    source.judge.assert_called_once_with("task text", "Original Query", "exact source bytes")
    assert rp.SPILL.execute(source, state).effect is rp.Effect.POISONED
    assert source.results.call_count == source.judge.call_count == 1
    assert not rp.SpillState().judged  # new task/fork state has no inherited poison


@pytest.mark.parametrize("change,reason", [(dict(query=Mock(return_value="")), "no query"),
                                         (dict(results=Mock(return_value="")), "unavailable evidence"),
                                         (dict(task=Mock(return_value="")), "unavailable evidence"),
                                         (dict(judge=Mock(return_value=rp.SpillVerdict(None))), "unknown verdict")])
def test_spill_unknown_is_silent_and_one_shot(change, reason):
    source, state = spill_source(**change), rp.SpillState()
    result = rp.SPILL.execute(source, state)
    assert result.effect is rp.Effect.WITHHELD and result.reason == reason
    assert not state.poisoned and not state.recommendation
    assert rp.SPILL.execute(source, state).effect is rp.Effect.NO_OP
    assert source.results.call_count == 1


def test_spill_task_host_veto_preserves_results():
    source, state = spill_source(protected=Mock(return_value=True)), rp.SpillState()
    assert rp.SPILL.execute(source, state).effect is rp.Effect.NO_OP
    assert not state.poisoned
    source.protected.assert_called_once_with("task text", "exact source bytes")


def test_disabled_and_replaced_spill_own_all_detection_and_settlement():
    source, state = spill_source(), rp.SpillState()
    state.recommendation = "existing recommendation"
    assert disabled(rp.SPILL).spill_read(source, state).effect is rp.Effect.NO_OP
    assert not state.judged and not state.poisoned
    assert state.recommendation == "existing recommendation"
    for callback in (source.query, source.results, source.task, source.judge, source.protected):
        callback.assert_not_called()
    replacement = Mock(return_value=rp.SpillResult(rp.Effect.WITHHELD, reason="replacement"))
    selection = replace(rp.ResearchSelection(), spill=replace(rp.SPILL, execute=replacement))
    assert selection.spill_read(source, state).reason == "replacement"
    replacement.assert_called_once_with(source, state)
    assert not state.judged and not state.poisoned
    source.results.assert_not_called()


def test_projected_empty_selection_stops_coder_planner_detection_and_state():
    from cria import planner_tools
    wf.set_visible("s", [("https://example.org", "", "")], ["widget api docs"])
    wf.note_search_spill("s", "widget api docs", "recorded/path")
    wf.allow_search("s", "widget api docs")
    before = {session: set(queries) for session, queries in wf._SEARCH_ALLOWED.items()}
    recent = [{"widget", "api", "docs"}]
    source, state = spill_source(), rp.SpillState()
    wf._cache_put("https://example.org", 404, "text/plain", "shared cached bytes", None, False)
    with rp.bound(rp.ResearchSelection.from_definitions(())), \
            patch.object(rp, "normalize_search", side_effect=AssertionError("coder detector")), \
            patch.object(planner_tools, "normalize_search", side_effect=AssertionError("planner detector")), \
            patch.object(rp, "first_domain_in", side_effect=AssertionError("domain detector")), \
            patch.object(wf, "already_spilled", side_effect=AssertionError("fetch detector")), fake_fetch(404):
        assert wf.prior_matching_search("s", "widget api docs") is None
        wf.allow_search("other", "new query")
        assert wf.gate_search("s", "widget api docs") is None
        assert planner_tools.gate_search(recent, "widget api docs") is None
        assert wf.fetch_nav("https://example.org", session="s") == "exact fetched bytes"
        assert rp.current().spill_read(source, state).effect is rp.Effect.NO_OP
        assert wf.visible_urls("s") == {"https://example.org"}
        assert wf.spilled_search_files("s") == {"recorded/path": "widget api docs"}
        assert wf._DOC_CACHE["https://example.org"][2] == "shared cached bytes"
    assert wf._SEARCH_ALLOWED == before and not wf._FETCH_STREAK
    assert recent == [{"widget", "api", "docs"}]
    assert not state.judged and not state.poisoned
    for callback in (source.query, source.results, source.task, source.judge, source.protected):
        callback.assert_not_called()
    assert wf.gate_search("s", "widget api docs") is None  # clearance was not consumed
    assert denial.is_denied(wf.gate_search("s", "widget api docs"))


def test_projection_preserves_every_typed_replacement_without_defaulting_absent_stages():
    replacements = tuple(replace(definition, execute=Mock()) for definition in rp.DEFINITIONS)
    for replacement, field in zip(replacements, ("search", "domain", "fetch", "failure", "spill")):
        selection = rp.ResearchSelection.from_definitions((replacement,))
        assert getattr(selection, field) is replacement
        assert sum(value is not None for value in vars(selection).values()) == 1
    selection = rp.ResearchSelection.from_definitions(reversed(replacements))
    assert tuple(vars(selection).values()) == replacements
    assert rp.ResearchSelection.from_definitions(()) == rp.ResearchSelection(None, None, None, None, None)


def test_projected_replacements_reach_actual_search_fetch_and_spill_boundaries():
    from cria import planner_tools
    actions = []
    def search(source, state):
        actions.append(source.action)
        if source.action is rp.SearchAction.ADMIT:
            return rp.Admission(rp.Effect.REFUSED, source.domain_note(source.query))
        return rp.Admission(prior="replacement prior")
    domain = Mock(return_value="replacement advice")
    fetch = Mock(return_value=rp.Admission())
    failure = Mock(return_value=rp.Admission(rp.Effect.NOTED, "replacement observation"))
    spill = Mock(return_value=rp.SpillResult(rp.Effect.WITHHELD, reason="replacement judgment"))
    selected = rp.ResearchSelection.from_definitions((replace(rp.SEARCH, execute=search),
        replace(rp.DOMAIN, execute=domain), replace(rp.FETCH, execute=fetch),
        replace(rp.FAILURE, execute=failure), replace(rp.SPILL, execute=spill)))
    source, state = spill_source(), rp.SpillState()
    recent = [{"widget", "api", "docs"}]
    with rp.bound(selected), fake_fetch(404), \
            patch.object(rp, "normalize_search", side_effect=AssertionError("canonical detector")), \
            patch.object(wf, "already_spilled", side_effect=AssertionError("canonical fetch detector")):
        assert wf.prior_matching_search("s", "widget api docs") == "replacement prior"
        wf.allow_search("s", "widget api docs")
        assert wf.gate_search("s", "widget api docs") == "replacement advice"
        assert "replacement advice" in planner_tools.gate_search(recent, "widget api docs")
        assert wf.fetch_nav("https://example.org", session="s") == "exact fetched bytesreplacement observation"
        assert selected.spill_read(source, state).reason == "replacement judgment"
    assert actions == [rp.SearchAction.PRIOR, rp.SearchAction.CLEAR, rp.SearchAction.ADMIT, rp.SearchAction.ADMIT]
    assert domain.call_count == 2 and fetch.call_count == failure.call_count == spill.call_count == 1
    assert not wf._SEARCH_ALLOWED and not wf._FETCH_STREAK
    assert not state.judged and not state.poisoned
    assert recent == [{"widget", "api", "docs"}]
    for callback in (source.query, source.results, source.task, source.judge, source.protected):
        callback.assert_not_called()


def test_projection_rejects_duplicate_and_wrong_typed_canonical_ids():
    from types import SimpleNamespace
    with pytest.raises(ValueError):
        rp.ResearchSelection.from_definitions((rp.SEARCH, rp.SEARCH))
    with pytest.raises(ValueError):
        rp.ResearchSelection.from_definitions((SimpleNamespace(policy=rp.SEARCH.policy, execute=Mock()),))
    unrelated = SimpleNamespace(policy=replace(rp.SEARCH.policy, id="unrelated"), execute=Mock())
    assert rp.ResearchSelection.from_definitions((unrelated,)).search is None


def test_projected_disabled_canonical_search_leaves_other_stages_selected():
    from cria import planner_tools
    selection = rp.ResearchSelection.from_definitions(d for d in rp.DEFINITIONS if d is not rp.SEARCH)
    wf.set_visible("s", [], ["widget api docs"])
    wf.allow_search("s", "widget api docs")
    before = {session: set(queries) for session, queries in wf._SEARCH_ALLOWED.items()}
    recent = [{"widget", "api", "docs"}]
    with rp.bound(selection), patch.object(rp, "normalize_search", side_effect=AssertionError("coder detector")), \
            patch.object(planner_tools, "normalize_search", side_effect=AssertionError("planner detector")):
        assert wf.gate_search("s", "widget api docs") is None
        assert wf.prior_matching_search("s", "widget api docs") is None
        wf.allow_search("other", "q")
        assert planner_tools.gate_search(recent, "widget api docs") is None
    assert wf._SEARCH_ALLOWED == before and recent == [{"widget", "api", "docs"}]
    assert (selection.domain, selection.fetch, selection.failure, selection.spill) == (rp.DOMAIN, rp.FETCH, rp.FAILURE, rp.SPILL)


def test_explicit_binding_presence_includes_empty_and_restores_after_errors():
    original = rp.current()
    assert not rp.is_bound()
    empty = rp.ResearchSelection.from_definitions(())
    with rp.bound(empty):
        assert rp.is_bound() and rp.current() is empty
        with pytest.raises(RuntimeError, match="nested failure"):
            with rp.bound(original):
                assert rp.is_bound() and rp.current() is original
                raise RuntimeError("nested failure")
        assert rp.is_bound() and rp.current() is empty
    assert not rp.is_bound() and rp.current() is original
    with pytest.raises(RuntimeError, match="outer failure"):
        with rp.bound(original):
            # An explicit binding of the default is still a binding.
            assert rp.is_bound() and rp.current() is original
            raise RuntimeError("outer failure")
    assert not rp.is_bound() and rp.current() is original


def test_binding_presence_is_context_local():
    from contextvars import Context
    assert not rp.is_bound()
    with rp.bound(rp.ResearchSelection.from_definitions(())):
        assert rp.is_bound()
        assert Context().run(rp.is_bound) is False
        assert Context().run(rp.current) is not rp.current()
    assert not rp.is_bound()


def test_selection_is_context_local_and_rejects_invalid_replacements():
    original = rp.current()
    with rp.bound(disabled(rp.SPILL)):
        assert rp.current().spill is None
        with rp.bound(original):
            assert rp.current().spill is rp.SPILL
        assert rp.current().spill is None
    assert rp.current() is original
    with pytest.raises(ValueError):
        rp.ResearchSelection.select(("unknown",))
    with pytest.raises(ValueError):
        rp.ResearchSelection.select((rp.SEARCH.policy.id,) * 2)
    with pytest.raises(ValueError):
        replace(original, search=replace(rp.SEARCH, policy=replace(rp.SEARCH.policy, family_id="F20")))
