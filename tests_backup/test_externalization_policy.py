"""Literal payload and operation-lifecycle oracles; no executor or workspace IO."""
import pytest

from cria import externalization as e, webfetch


def planner_services(*, content=webfetch.spill_content, outline=webfetch.spill_outline):
    return e.PlannerFetchServices(2, content, webfetch._spill_name, outline)


def test_module_reload_never_reaches_root_webfetch(monkeypatch):
    import builtins
    import importlib.util
    import sys
    original = builtins.__import__
    def guarded(name, globals=None, locals=None, fromlist=(), level=0):
        if name in ('webfetch', 'cria.webfetch') or 'webfetch' in (fromlist or ()):
            raise AssertionError('source reached Root webfetch')
        return original(name, globals, locals, fromlist, level)
    with monkeypatch.context() as guard:
        guard.setattr(builtins, '__import__', guarded)
        # Probe the whole module without replacing the authoritative registered
        # classes/Definition objects already held by production runtime imports.
        name = 'cria._externalization_import_probe'
        spec = importlib.util.spec_from_file_location(name, e.__file__)
        probe = importlib.util.module_from_spec(spec)
        guard.setitem(sys.modules, name, probe)
        spec.loader.exec_module(probe)
    with pytest.raises(TypeError):
        e.planner_fetch(status=200, url='url', reduced='body', parsed=None,
                        content_type=None, root='/owned', remedy=lambda p: '')


def test_exact_selected_definition_owns_settlement_cancel_reset(monkeypatch):
    from dataclasses import replace
    calls = []
    state = e.State()
    source = e.Input('old', 'raw', e.Services(lambda: e.Spill('p', 'body', 'pointer'),
        lambda s: s.pointer, lambda s: calls.append('record')))
    original = e.DEFINITION
    def settled(state, result, outcome, *, stored):
        calls.append('selected-settle')
        return original.settle(state, result, outcome, stored=stored)
    def cancelled(state, result):
        calls.append('selected-cancel')
        return original.cancel(state, result)
    def reset(state):
        calls.append('selected-reset')
        original.reset(state)
    selected = replace(original, settle=settled, cancel=cancelled, reset=reset)
    offered = e.selected_externalization(selected, source, state)
    assert offered.owner is selected
    # Deliberately replace canonical callbacks after offering. Any re-lookup fails.
    def forbidden(*a, **kw):
        pytest.fail('canonical replacement reached')
    monkeypatch.setattr(e, 'DEFINITION', replace(original, execute=forbidden, settle=forbidden,
                                                cancel=forbidden, reset=forbidden))
    assert e.selected_externalization(e.DEFINITION, source, state) is offered
    assert offered.settle(e.Outcome.RETAINED, stored=True)
    offered.cancel()
    offered.reset()
    assert calls == ['selected-settle', 'record', 'selected-cancel', 'selected-reset']
    assert not offered.settle(e.Outcome.RETAINED, stored=True)
    absent = e.selected_externalization(None, source, state)
    assert absent.owner is None
    assert absent.result == e.Result('raw')
    assert not absent.settle(e.Outcome.RETAINED, stored=True)
    assert not absent.cancel()
    absent.reset()
    assert state._operations == {}


def test_late_reset_from_original_delivery_cannot_clear_new_task():
    state = e.State()
    def source():
        return e.Input('same-id', 'raw', e.Services(lambda: e.Spill('p', 'b', 'pointer'),
                         lambda s: s.pointer, lambda s: None))
    old = e.selected_externalization(e.DEFINITION, source(), state)
    state.reset()
    new = e.selected_externalization(e.DEFINITION, source(), state)
    old.reset()
    assert new.settle(e.Outcome.RETAINED, stored=True)


def test_coder_threshold_is_source_choice_not_hidden_provider_admission():
    def forbidden():
        pytest.fail('renderer reached for inline/cache miss')
    for facts in [None, e.FetchFacts(2, forbidden)]:
        assert e.coder_fetch('url', find=None, cursor=None,
            services=e.FetchServices(2, lambda url: facts, lambda: False)) is None


@pytest.mark.parametrize('budget,expected', [(3, 'α\n'), (2, 'POINTER')])
def test_search_program_uses_actual_parser_locals_inclusive_utf8(budget, expected):
    program = e.DEFINITION.search_program(budget)
    assert isinstance(program, e.SearchProgram)
    assert eval(program.expression, {}, {'brief': 'α\n', 'pointer': 'POINTER'}) == expected
    # Provider text remains data even when it resembles executable Python.
    malicious = '__import__("os").remove("anything")'
    assert eval(e.DEFINITION.search_program(100).expression, {},
                {'brief': malicious, 'pointer': 'POINTER'}) == malicious


@pytest.mark.parametrize('budget', [-1, True, 1.5, '3'])
def test_search_program_rejects_invalid_budget(budget):
    with pytest.raises(ValueError):
        e.DEFINITION.search_program(budget)


@pytest.mark.parametrize('count,digest', [
    (-1, '0' * 64), (True, '0' * 64), (1.5, '0' * 64),
    (0, 'A' * 64), (0, 'a' * 63), (0, 'g' * 64), (0, None)])
def test_search_storage_facts_are_typed_not_success_booleans(count, digest):
    with pytest.raises(ValueError):
        e.SearchStored('./tmp/reference/search-q.txt', count, digest)


@pytest.mark.parametrize('outcome,stored_kind,records_expected', [
    ('retained', 'checked', True), ('retained', 'bool', False),
    ('retained', 'wrong-target', False), ('unknown', 'checked', False),
    ('failed', 'checked', False), ('cancelled', 'checked', False)])
def test_search_operation_requires_checked_storage_and_retained_original_owner(
        outcome, stored_kind, records_expected):
    import hashlib
    from dataclasses import replace
    records, offered = [], []
    program = e.DEFINITION.search_program(3)
    offer = e.SearchOffer('./tmp/reference/search-q.txt', program)
    source = e.Input('search-call', 'full-inline-required', e.Services(
        lambda: offer, lambda captured: offered.append(captured) or captured.program.expression, records.append))
    state = e.State()
    owner = replace(e.DEFINITION)
    delivery = e.selected_externalization(owner, source, state)
    assert delivery.owner is owner
    assert delivery.result.spill is offer
    assert offer.program is program
    assert e.selected_externalization(replace(owner), source, state) is delivery
    actual_stored_bytes = '0 results:\n'.encode('utf-8')
    fact = e.SearchStored(offer.target if stored_kind != 'wrong-target' else 'foreign',
                         len(actual_stored_bytes), hashlib.sha256(actual_stored_bytes).hexdigest())
    stored = True if stored_kind == 'bool' else fact
    assert delivery.settle(e.Outcome(outcome), stored=stored) is records_expected
    assert records == ([offer] if records_expected else [])
    # Correct the extension's former bad expectation: a retained response with
    # invalid/foreign search storage facts remains pending for its ORIGINAL fact.
    valid_fact = e.SearchStored(offer.target, len(actual_stored_bytes),
                               hashlib.sha256(actual_stored_bytes).hexdigest())
    pending = outcome == 'retained' and stored_kind in ('bool', 'wrong-target')
    assert e.selected_externalization(replace(owner), source, state) is delivery
    assert delivery.owner is owner
    assert delivery.settle(e.Outcome.RETAINED, stored=valid_fact) is pending
    assert records == ([offer] if records_expected or pending else [])
    assert offered == [offer]
    assert not delivery.settle(e.Outcome.RETAINED, stored=valid_fact)


def test_retry_and_selected_owner():
    events = []
    spill = e.Spill('./tmp/reference/doc.txt', 'α\nEND\n', 'literal pointer\n')
    services = e.Services(lambda: spill,
                          lambda s: events.append(('offer', s.content)) or s.pointer,
                          lambda s: events.append(('original-owner', s.target)))
    source = e.Input('coder-call-1', 'original\x00response\n', services)
    state = e.State()
    result = e.externalize(source, state)
    assert result.payload == 'literal pointer\n'
    assert events == [('offer', 'α\nEND\n')]
    assert e.externalize(source, state) is result
    assert state.settle(result, e.Outcome.RETAINED, stored=True)
    assert not state.settle(result, e.Outcome.RETAINED, stored=True)
    assert events == [('offer', 'α\nEND\n'), ('original-owner', './tmp/reference/doc.txt')]
    with pytest.raises(ValueError, match='identity reused'):
        e.externalize(e.Input('coder-call-1', 'different', services), state)


def test_absence_never_detects_offers_or_allocates():
    def forbidden(*args):
        raise AssertionError('optional service reached')
    state = e.State()
    source = e.Input('call', 'raw\r\n\x00尾', e.Services(forbidden, forbidden, forbidden))
    assert e.externalize(source, state, enabled=False) == e.Result('raw\r\n\x00尾')
    assert state._operations == {}


@pytest.mark.parametrize('outcome,stored', [
    (e.Outcome.UNKNOWN, True), (e.Outcome.FAILED, True),
    (e.Outcome.CANCELLED, True), (e.Outcome.RETAINED, False)])
def test_no_claim_without_storage_and_retention(outcome, stored):
    records = []
    source = e.Input('x', 'raw', e.Services(
        lambda: e.Spill('path', 'body', 'pointer'), lambda s: s.pointer, records.append))
    state = e.State()
    result = e.externalize(source, state)
    assert not state.settle(result, outcome, stored=stored)
    assert not state.settle(result, e.Outcome.RETAINED, stored=True)
    assert records == []
    assert e.externalize(source, state) is result


def test_reset_foreign_cancel_and_new_owner():
    records = []
    def source(owner):
        return e.Input('same-id', 'raw', e.Services(
            lambda: e.Spill('path', 'body', 'pointer'), lambda s: s.pointer,
            lambda s: records.append(owner)))
    state = e.State()
    old = e.externalize(source('old'), state)
    state.reset()
    new = e.externalize(source('new'), state)
    assert not state.settle(old, e.Outcome.RETAINED, stored=True)
    assert not state.settle(e.Result('pointer', new.spill), e.Outcome.RETAINED, stored=True)
    assert state.settle(new, e.Outcome.RETAINED, stored=True)
    cancelled = e.externalize(e.Input('cancel', 'raw', source('cancel').services), state)
    assert not state.cancel(cancelled)
    assert not state.settle(cancelled, e.Outcome.RETAINED, stored=True)
    assert records == ['new']


@pytest.mark.parametrize('found,offered', [(False, True), (True, False)])
def test_no_offer_or_failed_storage_retains_every_inline_byte(found, offered):
    events = []
    source = e.Input('x', 'raw\r\n尾\x00', e.Services(
        lambda: e.Spill('p', 'b', 'm') if found else None,
        lambda s: events.append('offered') or (s.pointer if offered else None),
        events.append))
    state = e.State()
    result = e.externalize(source, state)
    assert result == e.Result('raw\r\n尾\x00')
    assert events == (['offered'] if found else [])
    assert not state.settle(result, e.Outcome.RETAINED, stored=True)


def test_planner_search_literal_payload_and_threshold():
    body = 'Search results for: Q\n1. Title\n  https://example.test\n  α tail\n'
    spill = e.planner_search('Q', body, scratch='/owned', inline_chars=1,
                             remedy=lambda p: 'READ ' + p)
    assert spill == e.Spill('/owned/search-q.txt', body,
        'Search results for: Q — 63 characters of titles and snippets, saved IN FULL to /owned/search-q.txt. '
        'The titles are below; to read a snippet in full: READ /owned/search-q.txt Do NOT re-run this search.\n'
        'Search results for: Q\n1. Title')
    assert e.planner_search('Q', body, scratch='/owned', inline_chars=len(body),
                            remedy=lambda p: pytest.fail('remedy')) is None
    assert e.planner_search('Q', body, scratch=None, inline_chars=0,
                            remedy=lambda p: pytest.fail('remedy')) is None


def test_planner_fetch_full_content_and_guidance_owner(monkeypatch):
    spill = e.planner_fetch(status=200, url='https://example.test/doc', reduced='α\nEND\n',
                            parsed=None, content_type='text/plain', root='/owned',
                            remedy=lambda p: 'READ',
                            services=planner_services(outline=lambda parsed, target: 'OUTLINE\n'))
    assert spill == e.Spill('/owned/example.test_doc.txt', 'α\nEND\n',
        'HTTP 200 · https://example.test/doc\nThis document is too large to hand back inline (6 chars) '
        '— it was saved IN FULL to /owned/example.test_doc.txt.\nOUTLINE\n'
        'Read it from there — do NOT re-fetch the url. READ')


def test_coder_search_byte_boundary_keeps_full_storage_in_both_branches():
    assert e.coder_search(target='p', full='FULL\nα\nEND', brief='α\n', pointer='PTR', inline_bytes=3) == e.Spill(
        'p', 'FULL\nα\nEND', 'α\n')
    assert e.coder_search(target='p', full='FULL\nα\nEND', brief='α\n', pointer='PTR', inline_bytes=2) == e.Spill(
        'p', 'FULL\nα\nEND', 'PTR')


def test_inflight_owner_is_not_replaced_by_another_selection():
    records = []
    state = e.State()
    old = e.Input('old', 'raw', e.Services(lambda: e.Spill('old-p', 'b', 'old'),
        lambda s: s.pointer, lambda s: records.append('old-owner')))
    new = e.Input('new', 'raw', e.Services(lambda: e.Spill('new-p', 'b', 'new'),
        lambda s: s.pointer, lambda s: records.append('new-owner')))
    first = e.externalize(old, state)
    second = e.externalize(new, state)
    assert state.settle(first, e.Outcome.RETAINED, stored=True)
    assert state.settle(second, e.Outcome.RETAINED, stored=True)
    assert records == ['old-owner', 'new-owner']


def test_offer_unknown_exception_never_repeats_effect():
    events = []
    def offer(spill):
        events.append(spill.content)
        raise OSError('outcome unknown')
    source = e.Input('x', 'raw', e.Services(lambda: e.Spill('p', 'bytes', 'pointer'), offer, events.append))
    state = e.State()
    for _ in range(2):
        with pytest.raises(OSError, match='outcome unknown'):
            e.externalize(source, state)
    assert events == ['bytes']


def test_reset_during_offer_does_not_resurrect_state():
    state = e.State()
    records = []
    def offer(spill):
        state.reset()
        return spill.pointer
    result = e.externalize(e.Input('x', 'raw', e.Services(
        lambda: e.Spill('p', 'body', 'pointer'), offer, records.append)), state)
    assert result.payload == 'pointer'
    assert not state.settle(result, e.Outcome.RETAINED, stored=True)
    assert records == []
    assert state._operations == {}


def test_coder_navigation_skips_optional_cache_and_storage_checks(monkeypatch):
    def forbidden(*args):
        pytest.fail('spill detection reached during navigation')
    services = e.FetchServices(2, forbidden, forbidden)
    assert e.coder_fetch('url', find='', cursor=None, services=services) is None
    assert e.coder_fetch('url', find=None, cursor=0, services=services) is None
    assert e.coder_fetch('url', find=None, cursor=None,
                         services=e.FetchServices(2, forbidden, lambda: True)) is None
    services = e.FetchServices(2, lambda url: e.FetchFacts(5,
        lambda: e.Spill('p', 'α\nEND', 'pointer\r\n')), lambda: False)
    assert e.coder_fetch('url', find=None, cursor=None, services=services) == e.Spill(
        'p', 'α\nEND', 'pointer\r\n')


def test_premature_record_fault_is_detected_then_restored(monkeypatch):
    original = e.State.settle
    def oracle():
        records = []
        state = e.State()
        source = e.Input('x', 'raw', e.Services(lambda: e.Spill('p', 'b', 'pointer'),
                         lambda s: s.pointer, records.append))
        result = e.externalize(source, state)
        state.settle(result, e.Outcome.UNKNOWN, stored=True)
        assert records == []
    oracle()
    def faulty(state, result, outcome, *, stored):
        for pending in state._operations.values():
            if pending.result is result:
                pending.source.services.record(result.spill)
        return original(state, result, outcome, stored=stored)
    with monkeypatch.context() as fault:
        fault.setattr(e.State, 'settle', faulty)
        with pytest.raises(AssertionError):
            oracle()
    oracle()


def test_semantic_content_loss_fault_is_detected_then_restored(monkeypatch):
    def oracle(services):
        result = e.planner_fetch(status=200, url='https://example.test/doc', reduced='α\nEND\n',
            parsed=None, content_type='text/plain', root='/owned', remedy=lambda p: 'READ',
            services=services)
        assert result.content == 'α\nEND\n'
    original = planner_services()
    oracle(original)
    with pytest.raises(AssertionError):
        oracle(planner_services(content=lambda *args: 'α\n'))
    oracle(original)
