"""Canonical root selection governs all existing repeat-research callers."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from cria import assistruntime, loop, planner_tools, researchpolicies as rp, webfetch as wf


@pytest.fixture(autouse=True)
def clean_research_state():
    wf.clear_cache()
    yield
    wf.clear_cache()


def test_root_disabled_repeat_bypasses_outer_defaults_detector_clearance_and_planner():
    query = 'widget api docs'
    session = 'disabled-repeat'
    wf.set_visible(session, [], [query])
    before = {key: set(values) for key, values in wf._SEARCH_ALLOWED.items()}
    calls = []
    def spy(source, state):
        calls.append(source.action)
        return rp.SEARCH.execute(source, state)
    outer = replace(rp.ResearchSelection(), search=replace(rp.SEARCH, execute=spy))
    runtime = assistruntime.AssistRuntime.select(disabled=(rp.SEARCH.policy.id,))
    state = SimpleNamespace(web_session=session, query_verdicts={query: (True, '')},
                            rehunt_verdicts={}, fetched_pages={}, refused_names=set(), semantic_pending=None)
    coder = {'choices': [{'message': {'role': 'assistant', 'content': None, 'tool_calls': [
        {'id': 'search', 'type': 'function', 'function': {'name': 'web_search',
         'arguments': '{"query":"widget api docs"}'}}]}}]}
    body = {'messages': [{'role': 'user', 'content': 'Find widget documentation'}]}
    with rp.bound(outer), assistruntime.bound(runtime), \
            patch.object(loop, 'judge_query', side_effect=AssertionError('cached unrelated question')), \
            patch.object(loop, 'judge_rehunt', side_effect=AssertionError('disabled repeat question')):
        assert loop.guard_search_query(state, coder, body, Mock(), Mock(), Mock()) is coder
        wf.allow_search(session, query)
        first = wf.gate_search(session, query)
        second = wf.gate_search(session, query)
        planner = planner_tools.gate_search([query], query)
        assert calls == []
        assert wf._SEARCH_ALLOWED == before
        assert first is None and second is None and planner is None
        assert state.rehunt_verdicts == {}
    assert rp.current().search is rp.SEARCH


def test_root_uses_canonical_research_definitions_and_preserves_empty_selection():
    registered = {d.policy.id: d for d in assistruntime.DEFINITIONS}
    for definition in rp.DEFINITIONS:
        assert registered[definition.policy.id] is definition
    assert len(registered) == len(assistruntime.DEFINITIONS)
    empty = assistruntime.AssistRuntime.select(level=0,
        disabled=tuple(d.policy.id for d in assistruntime.DEFINITIONS if d.policy.default_level == 0))
    with assistruntime.bound(empty):
        assert rp.current() == rp.ResearchSelection(None, None, None, None, None)
        wf.allow_search('empty', 'query')
        assert wf.gate_search('empty', 'query') is None
    assert not wf._SEARCH_ALLOWED


def test_root_projects_all_research_replacements_and_restores_outer_on_exception():
    runtime = assistruntime.AssistRuntime.select()
    replacements = tuple(replace(d, execute=Mock()) for d in rp.DEFINITIONS)
    by_id = {d.policy.id: d for d in replacements}
    runtime = replace(runtime, ordered_stages=tuple(
        by_id.get(d.policy.id, d) for d in runtime.ordered_stages))
    expected = rp.ResearchSelection(*replacements)
    outer = rp.ResearchSelection(None, None, None, None, None)
    assert not rp.is_bound()
    with rp.bound(outer):
        with pytest.raises(RuntimeError, match='task failed'):
            with assistruntime.bound(runtime):
                assert rp.current() == expected and rp.is_bound()
                assert all(actual is replacement for actual, replacement in zip(
                    (rp.current().search, rp.current().domain, rp.current().fetch,
                     rp.current().failure, rp.current().spill), replacements))
                raise RuntimeError('task failed')
        assert rp.current() is outer and rp.is_bound()
    assert not rp.is_bound()


def test_root_disabled_spill_skips_actual_loop_detection_state_and_evidence():
    runtime = assistruntime.AssistRuntime.select(disabled=(rp.SPILL.policy.id,))
    sess = SimpleNamespace(judged_search_files=None, poisoned_search_files=None,
                           search_recommend='unchanged')
    messages = [{'role': 'user', 'content': 'Task'}]
    with assistruntime.bound(runtime), \
            patch.object(loop, '_toolcall_reads_search_file', side_effect=AssertionError('detector')), \
            patch.object(wf, 'spilled_search_files', side_effect=AssertionError('provenance')), \
            patch.object(loop, 'search_file_text', side_effect=AssertionError('file')), \
            patch.object(loop, 'judge_search', side_effect=AssertionError('question')):
        assert loop.Loop._judge_search_reads(None, sess, {'messages': messages}, Mock()) is messages
    assert sess.judged_search_files is None and sess.poisoned_search_files is None
    assert sess.search_recommend == 'unchanged'
