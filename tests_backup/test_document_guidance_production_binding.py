"""Original public-route baselines, not a claim of production selection binding.

Only pure public render/spill routes and planner note functions are invoked.
No fetch, cache insertion, scratch writer, filesystem or socket operation occurs.
Primary must add selected/absent public-route assertions after integration.
"""
import pytest
from cria import webfetch, planner_tools
from cria.documentguidance import GuidanceInput, GuidanceServices, guidance as execute_guidance, DEFINITION


def guidance(value):
    services = GuidanceServices(webfetch._catalog_links, webfetch._endpoint_routes,
                                webfetch.top_level_keys, webfetch._endpoint_response_fields,
                                webfetch._shape_block)
    return execute_guidance(value, services)


def test_original_public_spill_literal():
    expected = "[top-level keys (1): alpha]\n[grep for a key as a FIXED string, e.g.: grep -n -F 'alpha' doc.json, or read_file it with a start_line/end_line range]\n"
    assert webfetch.spill_outline({'alpha': 1}, 'doc.json') == expected
    assert guidance(GuidanceInput('spill', {'alpha': 1}, 'doc.json')).text == expected


def test_original_public_inline_full_payload():
    expected = 'HTTP 200 OK · https://example.invalid/doc\nContent-Type: application/json\n--- (chars 0–11 of 11) ---\n{"alpha":1}\n'
    assert webfetch.render_page('https://example.invalid/doc', 200, 'application/json', '{"alpha":1}', {'alpha': 1}, 0, 100) == expected


def test_original_route_full_payload():
    parsed = {'paths': {'/items/{id}': {}, '/health': {}}}
    expected = ("[API endpoints (2): /items/{id}, /health]\n"
                "[grep for a route as a FIXED string, e.g.: grep -n -F '/items/{id}' doc.json — the METHOD (GET/POST) is a key INSIDE the route's section, so grepping 'GET /path' matches nothing]\n")
    assert webfetch.spill_outline(parsed, 'doc.json') == expected
    assert guidance(GuidanceInput('spill', parsed, 'doc.json')).text == expected


def test_original_schema_literal():
    parsed = {'paths': {'/items/{id}': {'get': {'responses': {'200': {'schema': {'type': 'object', 'properties': {'name': {'type': 'string'}}}}}}}, '/health': {}}}
    expected = ("[API endpoints (2): /items/{id}, /health]\n"
                "[response shape — the fields each endpoint MAY return — `?` marks a field the spec does NOT guarantee, so read it defensively; use these EXACT names and nesting, and do not guess:\n"
                "  GET /items/{id} returns:\n```ts\n{\n  name?: string;\n}\n```]\n"
                "[grep for a route as a FIXED string, e.g.: grep -n -F '/items/{id}' doc.json — the METHOD (GET/POST) is a key INSIDE the route's section, so grepping 'GET /path' matches nothing]\n")
    assert webfetch.spill_outline(parsed, 'doc.json') == expected
    assert guidance(GuidanceInput('spill', parsed, 'doc.json')).text == expected


def test_original_planner_note_and_pending_binding():
    assert planner_tools._no_structure_note({}) == guidance(GuidanceInput('planner_fetch', facts={})).text
    assert DEFINITION.policy.migrated is False


# Public contracts activated after Primary's registration/projection readiness.
# No skip or setup failure counts as behavioral evidence.
def document_runtime(disabled=False, replacement=None):
    from cria.assistruntime import AssistRuntime
    from cria import documentguidance
    from dataclasses import replace
    canonical = documentguidance.DEFINITION
    runtime = AssistRuntime.select(disabled=(canonical.policy.id,) if disabled else ())
    if replacement is not None:
        runtime = replace(runtime, ordered_stages=tuple(
            replacement if item.policy.id == DEFINITION.policy.id else item
            for item in runtime.ordered_stages))
    assert runtime.document_guidance is (None if disabled else replacement or canonical)
    return runtime


def test_registered_public_spill_selected_absent_and_replacement():
    from cria.assistruntime import bound
    from cria.documentguidance import GuidanceResult
    from dataclasses import replace
    parsed = {'alpha': 1}
    literal = "[top-level keys (1): alpha]\n[grep for a key as a FIXED string, e.g.: grep -n -F 'alpha' doc.json, or read_file it with a start_line/end_line range]\n"
    with bound(document_runtime()):
        assert webfetch.spill_outline(parsed, 'doc.json') == literal
    with bound(document_runtime(disabled=True)):
        assert webfetch.spill_outline(parsed, 'doc.json') == ''
    calls = []

    def replacement(value, services):
        assert services.catalog is webfetch._catalog_links
        assert services.routes is webfetch._endpoint_routes
        assert services.keys is webfetch.top_level_keys
        assert services.shapes is webfetch._endpoint_response_fields
        assert services.shape_block is webfetch._shape_block
        calls.append(value)
        return GuidanceResult('[replacement-owned]\n')

    from cria import documentguidance
    selected = replace(documentguidance.DEFINITION, execute=replacement)
    with bound(document_runtime(replacement=selected)):
        assert webfetch.spill_outline(parsed, 'doc.json') == '[replacement-owned]\n'
    assert calls == [documentguidance.GuidanceInput('spill', parsed, 'doc.json')]


def test_registered_public_schema_and_plain_negative():
    from cria.assistruntime import bound
    parsed = {'paths': {'/items/{id}': {'get': {'responses': {'200': {'schema': {'type': 'object', 'properties': {'name': {'type': 'string'}}}}}}}, '/health': {}}}
    literal = ("[API endpoints (2): /items/{id}, /health]\n"
               "[response shape — the fields each endpoint MAY return — `?` marks a field the spec does NOT guarantee, so read it defensively; use these EXACT names and nesting, and do not guess:\n"
               "  GET /items/{id} returns:\n```ts\n{\n  name?: string;\n}\n```]\n"
               "[grep for a route as a FIXED string, e.g.: grep -n -F '/items/{id}' doc.json — the METHOD (GET/POST) is a key INSIDE the route's section, so grepping 'GET /path' matches nothing]\n")
    with bound(document_runtime()):
        assert webfetch.spill_outline(parsed, 'doc.json') == literal
        assert webfetch.spill_outline(None, 'plain.txt') == ''
    with bound(document_runtime(disabled=True)):
        assert webfetch.spill_outline(parsed, 'doc.json') == ''
        assert webfetch._endpoint_routes(parsed) == ['/items/{id}', '/health']
        assert webfetch._endpoint_response_fields(parsed) == ['GET /items/{id} returns:\n```ts\n{\n  name?: string;\n}\n```']


def test_registered_public_catalog_full_payload():
    from cria.assistruntime import bound
    parsed = {'linkset': [{'anchor': 'https://api.invalid', 'service-desc': [{'href': 'https://api.invalid/spec'}]}]}
    body = '{}'
    prefix = 'HTTP 200 OK · https://api.invalid/catalog\nContent-Type: application/json\n'
    advice = "[API descriptions (1): where each API's spec and docs live — fetch one of these urls]\n  https://api.invalid → service-desc: https://api.invalid/spec\n"
    payload = '--- (chars 0–2 of 2) ---\n{}\n'
    with bound(document_runtime()):
        assert webfetch.render_page('https://api.invalid/catalog', 200, 'application/json', body, parsed, 0, 100) == prefix + advice + payload
    with bound(document_runtime(disabled=True)):
        assert webfetch.render_page('https://api.invalid/catalog', 200, 'application/json', body, parsed, 0, 100) == prefix + payload


def test_registered_absence_is_lazy_but_plain_response_remains(monkeypatch):
    from cria.assistruntime import bound

    def forbidden(*args, **kwargs):
        raise AssertionError('optional guidance observation ran')

    with bound(document_runtime(disabled=True)):
        for name in ('_catalog_links', '_endpoint_routes', '_endpoint_response_fields', 'top_level_keys', '_shape_block'):
            monkeypatch.setattr(webfetch, name, forbidden)
        assert webfetch.spill_outline({'alpha': 1}, 'doc.json') == ''
        assert webfetch.render_page('https://example.invalid/plain', 200, 'text/plain', 'plain', None, 0, 100) == (
            'HTTP 200 OK · https://example.invalid/plain\nContent-Type: text/plain\n--- (chars 0–5 of 5) ---\nplain\n')


def test_registered_planner_fetch_full_payload_and_facts(monkeypatch):
    from cria.assistruntime import bound
    result = webfetch.FetchResult(200, 'https://example.invalid/doc', 'text/plain', 'plain', False)
    monkeypatch.setattr(webfetch, 'fetch', lambda url: result)
    monkeypatch.setattr(webfetch, '_cache_put', lambda *args: None)
    base = 'HTTP 200 · https://example.invalid/doc\nplain'
    note = '\n[this page answered, but no endpoints or field names could be read from it — that is a fact about the REQUEST, not about what the API returns. Nothing you have read so far DEFINES a route, so any endpoint in your plan would be a guess: find and read the document that defines them before planning against one.]'
    for disabled, expected in ((False, base + note), (True, base)):
        facts = {}
        with bound(document_runtime(disabled=disabled)):
            assert planner_tools._web_fetch({'url': result.final_url}, facts=facts).text == expected
        assert facts == {result.final_url: ('HTTP 200', (), (), (), '')}


def test_registered_planner_search_full_payload_and_unknown_negative(monkeypatch):
    from cria.assistruntime import bound
    monkeypatch.setattr(planner_tools, 'brave_search', lambda *args: [])
    base = 'No results for query: unrelated topic'
    note = '\n[these results are titles and snippets — POINTERS, not the source. Nothing you have read so far DEFINES a route, so any endpoint in your plan would be a guess: web_fetch the document that defines them (a spec, docs page, or the API root) and read it before planning against one.]'
    for disabled, expected in ((False, base + note), (True, base)):
        with bound(document_runtime(disabled=disabled)):
            assert planner_tools._web_search({'query': 'unrelated topic'}, 'fake-key', [], facts={}).text == expected
    with bound(document_runtime()):
        assert planner_tools._no_structure_note(None) == ''
        assert planner_tools._no_structure_note({}, parsed={}) == ''
        assert planner_tools._search_no_structure_note({'url': ('HTTP 200', ('/real',), (), (), '')}) == ''


def test_planner_retains_entry_definition_and_services_across_provider_rebinding(monkeypatch):
    from contextlib import ExitStack
    from dataclasses import replace
    from cria.assistruntime import bound
    from cria import documentguidance

    for route in ('fetch', 'search'):
        calls = []

        def owner_a(value, services):
            assert services.catalog is webfetch._catalog_links
            assert services.routes is webfetch._endpoint_routes
            assert services.keys is webfetch.top_level_keys
            assert services.shapes is webfetch._endpoint_response_fields
            assert services.shape_block is webfetch._shape_block
            calls.append(value)
            return documentguidance.GuidanceResult('\n[entry-owner-A]')

        def forbidden_b(*args):
            raise AssertionError('ambient replacement B stole entry A result')

        runtime_a = document_runtime(replacement=replace(documentguidance.DEFINITION, execute=owner_a))
        runtime_b = document_runtime(replacement=replace(documentguidance.DEFINITION, execute=forbidden_b))
        facts = {}
        with bound(runtime_a), ExitStack() as provider_binding:
            def provider(*args):
                provider_binding.enter_context(bound(runtime_b))
                if route == 'fetch':
                    return webfetch.FetchResult(200, 'https://example.invalid/doc', 'text/plain', 'plain', False)
                return []

            monkeypatch.setattr(webfetch, 'fetch', provider)
            monkeypatch.setattr(webfetch, '_cache_put', lambda *args: None)
            monkeypatch.setattr(planner_tools, 'brave_search', provider)
            if route == 'fetch':
                result = planner_tools._web_fetch({'url': 'https://example.invalid/doc'}, facts=facts)
                assert result.text == 'HTTP 200 · https://example.invalid/doc\nplain\n[entry-owner-A]'
                assert facts == {'https://example.invalid/doc': ('HTTP 200', (), (), (), '')}
            else:
                result = planner_tools._web_search({'query': 'unrelated topic'}, 'fake-key', [], facts=facts)
                assert result.text == 'No results for query: unrelated topic\n[entry-owner-A]'
        assert len(calls) == 1
        assert calls[0].mode == 'planner_' + route
        assert calls[0].facts is facts


def captured_public_payload(monkeypatch, route, disabled, *, late_capture=False):
    """Real public composition with scripted GET and process-local filesystem only."""
    from contextlib import ExitStack
    from dataclasses import replace
    from cria import assistruntime, documentguidance
    url = 'https://example.invalid/doc'
    body = 'plain' if route == 'inline' else 'x' * 10000
    events, stored = [], []

    def a(value, services):
        events.append('A')
        return documentguidance.GuidanceResult('[entry-A]\n')

    def b(value, services):
        events.append('B')
        return documentguidance.GuidanceResult('[ambient-B]\n')

    entry = document_runtime(disabled=disabled, replacement=None if disabled else replace(documentguidance.DEFINITION, execute=a))
    ambient = document_runtime(replacement=replace(documentguidance.DEFINITION, execute=b))
    cache = {}
    monkeypatch.setattr(webfetch, '_DOC_CACHE', cache)
    monkeypatch.setattr(webfetch, '_cache_put', lambda url, *facts: cache.__setitem__(url, facts))
    monkeypatch.setattr(webfetch, '_spill_name', lambda url: './tmp/reference/doc.txt')
    if route == 'find':
        monkeypatch.setattr(webfetch, 'find_in', lambda *args: 'chosen\n' + 'z' * 9001)
    if late_capture:
        original = documentguidance.selected_guidance
        monkeypatch.setattr(documentguidance, 'selected_guidance',
            lambda definition, value, services: original(assistruntime.current().document_guidance, value, services))

    class File:
        def __enter__(self):
            return self
        def write(self, content):
            stored.append(content)
        def __exit__(self, *args):
            return False

    monkeypatch.setattr(planner_tools.os, 'makedirs', lambda *args, **kwargs: None)
    monkeypatch.setattr(planner_tools, 'open', lambda *args, **kwargs: File(), raising=False)
    with assistruntime.bound(entry), ExitStack() as provider_binding:
        def provider(*args):
            provider_binding.enter_context(assistruntime.bound(ambient))
            return webfetch.FetchResult(200, url, 'text/plain', body, False)
        monkeypatch.setattr(webfetch, 'fetch', provider)
        if route == 'planner_spill':
            actual = planner_tools._web_fetch({'url': url}, facts={}, scratch='/fake/scratch').text
            outline = '' if disabled else '[entry-A]\n'
            expected = ('HTTP 200 · https://example.invalid/doc\nThis document is too large to hand back inline (10,000 chars) — it was saved IN FULL to /fake/scratch/doc.txt.\n'
                        + outline + 'Read it from there — do NOT re-fetch the url. Find the part you need with grep_files (pattern=<term>, path=/fake/scratch/doc.txt), then read_file /fake/scratch/doc.txt.' + outline)
            assert stored == [body]
        else:
            actual = webfetch.fetch_nav(url, find='alpha' if route == 'find' else None, cap_tokens=1)
            advice = '' if disabled else '[entry-A]\n'
            if route == 'find':
                expected = ('HTTP 200 OK · https://example.invalid/doc\nContent-Type: text/plain\nfind="alpha"\n\n---\nchosen\n'
                            '\n\n⚠ This find="alpha" match is large (9,008 chars) and is only part of the document — narrow it (a more specific keyword), or grep ./tmp/reference/doc.txt for exact lines, or fetch this URL again WITHOUT find= to get the document\'s full route/shape outline.'
                            + ('' if disabled else '\n\n[entry-A]'))
            else:
                total = 5 if route == 'inline' else 10000
                left = 1 if route == 'inline' else 9996
                expected = ('HTTP 200 OK · https://example.invalid/doc\nContent-Type: text/plain\n' + advice
                            + f'--- (chars 0–4 of {total}) ---\n{body[:4]}\n'
                            + f'\n⚠ More remains ({left} of {total} chars left). Continue with the SAME url and cursor="c4", or call find="<keyword>" to jump to a section.')
    assert actual == expected
    assert 'B' not in events
    assert (not events) if disabled else ('A' in events)


@pytest.mark.parametrize('route', ['inline', 'large_plain', 'find', 'planner_spill'])
@pytest.mark.parametrize('disabled', [False, True])
def test_public_entry_selection_survives_provider_swap(monkeypatch, route, disabled):
    captured_public_payload(monkeypatch, route, disabled)


@pytest.mark.parametrize('route', ['inline', 'large_plain', 'find', 'planner_spill'])
@pytest.mark.parametrize('disabled', [False, True])
def test_late_capture_fault_and_restored_public_control(monkeypatch, route, disabled):
    with monkeypatch.context() as fault:
        with pytest.raises(AssertionError):
            captured_public_payload(fault, route, disabled, late_capture=True)
    with monkeypatch.context() as restored:
        captured_public_payload(restored, route, disabled)
