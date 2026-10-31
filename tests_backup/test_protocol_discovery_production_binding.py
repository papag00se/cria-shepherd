"""Public protocol-discovery binding with fake providers and literal oracles.

The original unbound canary now must reject poisoned Source dispatch,
not claim that today's Root is unbound. The two observed-object callback
witnesses now target observe after the explicit API split; their old execute
before failures are historical, not identical callback preimages.
Every request provider here is fake; protocol parsers and formatters stay original.
"""
import json
from contextlib import ExitStack
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from cria import apidiscovery as api, discoverypolicy as p, webfetch as web

URL = 'https://example.invalid/mcp'
EXPECTED = (
    'HTTP 405 Method Not Allowed · https://example.invalid/mcp\n'
    'Content-Type: text/plain\n'
    'This is an MCP server (fixture) speaking JSON-RPC 2.0 over POST https://example.invalid/mcp '
    '(protocol 2025-06-18). Call a tool with method "tools/call" and params '
    '{"name": <tool>, "arguments": {…}}.\n'
    '[API endpoints (1): mcp tool echo(text: string)]\n'
)


def services():
    return p.DiscoveryServices(api.probe_kind, api._mcp_discover,
                              api._graphql_discover, api._unread,
                              api.ProbeTooLarge, web._render_discovery)


def fake_post(calls):
    def post(url, payload, headers):
        # Snapshot to prevent later header mutation from rewriting request provenance.
        calls.append((url, payload, dict(headers)))
        method = payload['method']
        if method == 'initialize':
            return 200, json.dumps({'result': {'protocolVersion': '2025-06-18',
                                               'serverInfo': {'name': 'fixture'}}}), {'mcp-session-id': 'session-A'}
        if method == 'tools/list':
            return 200, json.dumps({'result': {'tools': [{'name': 'echo', 'inputSchema': {
                'properties': {'text': {'type': 'string'}}, 'required': ['text']}}]}}), {}
        return 200, '{}', {}
    return post


def assert_requests(calls):
    base = {'Accept': 'application/json, text/event-stream', 'MCP-Protocol-Version': '2025-06-18'}
    session = {**base, 'Mcp-Session-Id': 'session-A'}
    assert calls == [
        (URL, {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
            'protocolVersion': '2025-06-18', 'capabilities': {},
            'clientInfo': {'name': 'cria', 'version': '1'}}}, base),
        (URL, {'jsonrpc': '2.0', 'method': 'notifications/initialized'}, session),
        (URL, {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}, session),
        (URL, {'jsonrpc': '2.0', 'id': 2, 'method': 'resources/list'}, session),
        (URL, {'jsonrpc': '2.0', 'id': 2, 'method': 'prompts/list'}, session),
    ]


def fetch_patches():
    return (
        patch.object(web, '_DOC_CACHE', {}),
        patch.object(web, 'fetch', return_value=SimpleNamespace(
            body='GET refused', content_type='text/plain', status=405, truncated=False)),
        patch.object(web, 'reduce_for_cache', return_value=('GET refused', None)),
        patch.object(web, '_cache_put'),
    )


@pytest.mark.parametrize('find,cursor,raw', [(None, None, False), ('echo', None, False),
                                           (None, 'c12', False), ('echo', 'c12', True)])
def test_original_fake_provider_baseline_and_source_literal(find, cursor, raw):
    original_calls = []
    a, b, c, d = fetch_patches()
    with a, b, c, d, patch.object(api, '_post_json', side_effect=fake_post(original_calls)):
        assert web._fetch_and_render(URL, find, cursor, 4000, 'fake-UA', raw) == (EXPECTED, 405, True)
    assert_requests(original_calls)
    source_calls = []
    value = p.DiscoveryInput(URL, 405, 'GET refused', 'text/plain', find, cursor, raw)
    with patch.object(api, '_post_json', side_effect=fake_post(source_calls)):
        result = p.selected_discovery(p.DEFINITION, value, services())
    assert result.text == EXPECTED
    assert result.observed.routes == ['mcp tool echo(text: string)']
    assert result.observed.kind == 'mcp'
    assert_requests(source_calls)


@pytest.mark.parametrize('url,status,body,ct,kind', [
    ('https://example.invalid/mcp.json', 200, '', None, 'mcp'),
    ('https://example.invalid/gql/', 200, 'playground', 'text/html', 'graphql'),
    ('https://example.invalid/graphiql', 200, '', None, 'graphql'),
    ('https://example.invalid/rpc', 400, 'jsonrpc', None, 'mcp'),
    ('https://example.invalid/query', 415, 'must provide query string', None, 'graphql'),
    ('https://example.invalid/stream', 200, 'mcp protocol', 'text/event-stream', 'mcp'),
    ('https://example.invalid/docs', 200, 'graphql documentation', 'text/html', None),
    ('https://example.invalid/docs', 404, 'missing document', None, None),
])
def test_existing_admission_facts_are_shared_not_copied(url, status, body, ct, kind):
    mcp, graphql = Mock(return_value=None), Mock(return_value=None)
    result = p.discovery(p.DiscoveryInput(url, status, body, ct),
                         replace(services(), mcp=mcp, graphql=graphql))
    assert result == p.DiscoveryResult()
    assert mcp.call_args_list == ([((url,), {})] if kind == 'mcp' else [])
    assert graphql.call_args_list == ([((url,), {})] if kind == 'graphql' else [])


def expected_guidance():
    from cria import assistruntime, documentguidance
    return (assistruntime.current().document_guidance,
            documentguidance.GuidanceServices(web._catalog_links, web._endpoint_routes,
                web.top_level_keys, web._endpoint_response_fields, web._shape_block))


def assert_guidance_identity(render, guidance):
    actual = render.call_args.kwargs['_guidance']
    assert actual[0] is guidance[0]
    assert actual[1] is guidance[1]
    assert actual[1].catalog is web._catalog_links
    assert actual[1].routes is web._endpoint_routes
    assert actual[1].keys is web.top_level_keys
    assert actual[1].shapes is web._endpoint_response_fields
    assert actual[1].shape_block is web._shape_block


def test_failed_original_and_source_preserve_requested_rendering():
    a, b, c, d = fetch_patches()
    guidance = expected_guidance()
    with a, b, c, d, patch.object(web, 'guidance_services', return_value=guidance[1]), \
            patch.object(api, '_post_json', side_effect=OSError('offline')), \
            patch.object(web, 'render_page', return_value='ordinary requested bytes') as render:
        assert web._fetch_and_render(URL, 'echo', 'c12', 4000, 'fake-UA', True) == (
            'ordinary requested bytes', 405, False)
        render.assert_called_once_with(URL, 405, 'text/plain', 'GET refused', None,
                                       12, 4000, False, _guidance=guidance)
        assert_guidance_identity(render, guidance)
        assert p.discovery(p.DiscoveryInput(URL, 405, 'GET refused', 'text/plain',
                                            'echo', 'c12', True), services()) == p.DiscoveryResult()


def test_graphql_existing_adapter_payload_and_literal_surface():
    url = 'https://example.invalid/graphql'
    calls = []

    def post(target, payload, headers):
        calls.append((target, payload, headers))
        return 200, json.dumps({'data': {'__schema': {'queryType': {
            'name': 'Query', 'fields': [{'name': 'ping', 'args': [],
                                        'type': {'kind': 'SCALAR', 'name': 'String'}}]},
            'types': []}}}), {}

    with patch.object(api, '_post_json', side_effect=post):
        result = p.discovery(p.DiscoveryInput(url, 400, 'must provide query string', None), services())
    assert result.text == (
        'HTTP 400 Bad Request · https://example.invalid/graphql\n'
        'Content-Type: (none)\n'
        'This is a GraphQL endpoint: every call is a POST to https://example.invalid/graphql '
        'with a JSON body {"query": "…"} — there are no REST paths. The callable surface is the root fields below.\n'
        '[API endpoints (1): Query.ping() -> String]\n')
    # Independent full payload oracle: seven type levels including the leaf.
    ref = 'kind name ofType { ' * 6 + 'kind name' + ' }' * 6
    fields = 'name fields { name description args { name type { ' + ref + ' } } type { ' + ref + ' } }'
    expected_query = ('query criaDiscovery { __schema { queryType { ' + fields + ' } '
                      'mutationType { ' + fields + ' } types { name kind fields { name type { '
                      + ref + ' } } } } }')
    assert calls == [(url, {'query': expected_query, 'operationName': 'criaDiscovery'},
                      {'Accept': 'application/json'})]


def test_root_binding_rejects_historical_unbound_canary_and_restores():
    # Historical canary now rejects: actual Root must reach selected Source.
    # Keep its original literal assertion and restore the same real public path.
    a, b, c, d = fetch_patches()
    with a, b, c, d, patch.object(api, '_post_json', side_effect=fake_post([])), \
            patch.object(p, 'selected_discovery', side_effect=AssertionError('unbound Source')):
        with pytest.raises(AssertionError, match='unbound Source'):
            assert web._fetch_and_render(URL, None, None, 4000, 'fake-UA') == (EXPECTED, 405, True)
    a, b, c, d = fetch_patches()
    with a, b, c, d, patch.object(api, '_post_json', side_effect=fake_post([])):
        assert web._fetch_and_render(URL, None, None, 4000, 'fake-UA') == (EXPECTED, 405, True)
    value = p.DiscoveryInput(URL, 405, 'GET refused', 'text/plain')

    def oracle(definition):
        with patch.object(api, '_post_json', side_effect=fake_post([])):
            assert p.selected_discovery(definition, value, services()).text == EXPECTED

    oracle(p.DEFINITION)
    with pytest.raises(AssertionError):
        oracle(replace(p.DEFINITION, execute=lambda *_: p.DiscoveryResult('GET refused')))
    oracle(p.DEFINITION)


# Public-path scenarios activated after Main's actual registration/projection
# readiness and BEFORE GO. Missing API/setup is never behavioral evidence.
# The accepted Source-only tests and unbound canary above remain untouched.
def prepared_runtime(definition=p.DEFINITION):
    from cria import assistruntime
    runtime = assistruntime.AssistRuntime.select(level=0)
    assert runtime.protocol_discovery is p.DEFINITION
    assert runtime.experimental_planning is False
    if definition is None:
        runtime = assistruntime.AssistRuntime.select(
            level=0, disabled=('automatic-protocol-discovery',))
    elif definition is not p.DEFINITION:
        runtime = replace(runtime, ordered_stages=tuple(
            definition if item is p.DEFINITION else item for item in runtime.ordered_stages))
    assert runtime.protocol_discovery is definition
    return runtime


@pytest.mark.parametrize('find,cursor,raw', [(None, None, False), ('echo', None, False),
                                           (None, 'c12', False), ('echo', 'c12', True)])
def test_public_mcp_literal(find, cursor, raw):
    from cria import assistruntime
    runtime = prepared_runtime()
    calls = []
    with ExitStack() as stack:
        for seam in fetch_patches():
            stack.enter_context(seam)
        stack.enter_context(assistruntime.bound(runtime))
        stack.enter_context(patch.object(api, '_post_json', side_effect=fake_post(calls)))
        text = web.fetch_nav(URL, find=find, cursor=cursor, raw=raw, cap_tokens=4000,
                             user_agent='fake-UA', session=None)
    assert text == EXPECTED
    assert_requests(calls)


def test_absent_public_fetch_keeps_required_get():
    from cria import assistruntime
    runtime = prepared_runtime(None)
    with ExitStack() as stack:
        for seam in fetch_patches():
            stack.enter_context(seam)
        stack.enter_context(assistruntime.bound(runtime))
        classify = stack.enter_context(patch.object(api, 'probe_kind', side_effect=AssertionError('optional classifier')))
        post = stack.enter_context(patch.object(api, '_post_json', side_effect=AssertionError('optional POST')))
        guidance = expected_guidance()
        stack.enter_context(patch.object(web, 'guidance_services', return_value=guidance[1]))
        ordinary = stack.enter_context(patch.object(web, 'render_page', return_value='ordinary GET bytes'))
        assert web.fetch_nav(URL, find='echo', cursor='c12', raw=True,
                             cap_tokens=4000, user_agent='fake-UA') == 'ordinary GET bytes'
        ordinary.assert_called_once_with(URL, 405, 'text/plain', 'GET refused', None,
                                         0, 4000, False, _guidance=guidance)
        assert_guidance_identity(ordinary, guidance)
        classify.assert_not_called()
        post.assert_not_called()


def test_original_discover_observed_identity():
    from cria import assistruntime
    runtime = prepared_runtime()
    observed = api.Discovery(kind='mcp', note='observed', routes=['mcp tool echo()'])
    seen = []
    observe = runtime.protocol_discovery.observe

    def capture(value, providers):
        result = observe(value, providers)
        seen.append((value, providers, result))
        return result

    runtime = prepared_runtime(replace(p.DEFINITION, observe=capture))
    with assistruntime.bound(runtime), patch.object(api, '_mcp_discover', return_value=observed):
        assert api.discover(URL, 405, 'GET refused', 'text/plain') is observed
    assert len(seen) == 1
    assert seen[0][2] is observed
    assert (seen[0][0].url, seen[0][0].status, seen[0][0].body,
            seen[0][0].content_type) == (URL, 405, 'GET refused', 'text/plain')


def test_captured_selection_does_not_relookup_during_callback():
    from cria import assistruntime
    observed = api.Discovery(kind='mcp', note='observed', routes=['mcp tool echo()'])
    received = []
    second = prepared_runtime(None)
    observe = p.DEFINITION.observe

    def replacement(value, providers):
        # Synchronous real public path: a nested ambient selection must not
        # replace the exact already-captured A callback/input/services.
        received.append((value, providers))
        with assistruntime.bound(second):
            result = observe(value, providers)
        assert received[0][0] is value
        assert received[0][1] is providers
        assert result is observed
        return result

    first = prepared_runtime(replace(p.DEFINITION, observe=replacement))
    with assistruntime.bound(first), patch.object(api, '_mcp_discover', return_value=observed):
        assert api.discover(URL, 405, 'GET refused', 'text/plain') is observed
        assert assistruntime.current() is first
    assert len(received) == 1


def test_public_fetch_execute_captures_definition_and_services_before_get():
    from cria import assistruntime
    observed = api.Discovery(kind='mcp', note='observed', routes=['mcp tool echo()'])
    received = []
    execute = p.DEFINITION.execute
    second = prepared_runtime(None)

    def replacement(value, providers):
        received.append((value, providers))
        assert assistruntime.current() is second
        result = execute(value, providers)
        assert result.observed is observed
        return result

    first = prepared_runtime(replace(p.DEFINITION, execute=replacement))
    with ExitStack() as stack:
        stack.enter_context(assistruntime.bound(first))
        for seam in fetch_patches():
            stack.enter_context(seam)
        original_adapter = stack.enter_context(patch.object(api, '_mcp_discover', return_value=observed))
        poison = Mock(side_effect=AssertionError('late adapter must not replace captured provider'))

        def get(url, user_agent):
            stack.enter_context(assistruntime.bound(second))
            stack.enter_context(patch.object(api, '_mcp_discover', poison))
            return SimpleNamespace(body='GET refused', content_type='text/plain',
                                   status=405, truncated=False)

        stack.enter_context(patch.object(web, 'fetch', side_effect=get))
        assert web.fetch_nav(URL, find='echo', raw=True, cursor='c12', cap_tokens=4000) == (
            'HTTP 405 Method Not Allowed · https://example.invalid/mcp\n'
            'Content-Type: text/plain\nobserved\n[API endpoints (1): mcp tool echo()]\n')
        assert len(received) == 1
        assert received[0][1].mcp is original_adapter
        assert received[0][0].url == URL
        original_adapter.assert_called_once_with(URL)
        poison.assert_not_called()


def test_public_graphql_full_request_and_render():
    from cria import assistruntime
    url = 'https://example.invalid/graphql'
    calls = []

    def post(target, payload, headers):
        calls.append((target, payload, headers))
        return 200, json.dumps({'data': {'__schema': {'queryType': {
            'name': 'Query', 'fields': [{'name': 'ping', 'args': [],
                                        'type': {'kind': 'SCALAR', 'name': 'String'}}]},
            'types': []}}}), {}

    with ExitStack() as stack:
        for seam in fetch_patches():
            stack.enter_context(seam)
        stack.enter_context(assistruntime.bound(prepared_runtime()))
        stack.enter_context(patch.object(api, '_post_json', side_effect=post))
        assert web.fetch_nav(url) == (
            'HTTP 405 Method Not Allowed · https://example.invalid/graphql\n'
            'Content-Type: text/plain\n'
            'This is a GraphQL endpoint: every call is a POST to https://example.invalid/graphql '
            'with a JSON body {"query": "…"} — there are no REST paths. The callable surface is the root fields below.\n'
            '[API endpoints (1): Query.ping() -> String]\n')
    ref = 'kind name ofType { ' * 6 + 'kind name' + ' }' * 6
    fields = 'name fields { name description args { name type { ' + ref + ' } } type { ' + ref + ' } }'
    query = ('query criaDiscovery { __schema { queryType { ' + fields + ' } '
             'mutationType { ' + fields + ' } types { name kind fields { name type { '
             + ref + ' } } } } }')
    assert calls == [(url, {'query': query, 'operationName': 'criaDiscovery'},
                      {'Accept': 'application/json'})]


@pytest.mark.parametrize('answer', [None, api.Discovery(kind='mcp', shapes=['not a callable surface'])])
def test_public_empty_discovery_keeps_actual_requested_rendering(answer):
    from cria import assistruntime
    with ExitStack() as stack:
        for seam in fetch_patches():
            stack.enter_context(seam)
        stack.enter_context(assistruntime.bound(prepared_runtime()))
        stack.enter_context(patch.object(api, '_mcp_discover', return_value=answer))
        guidance = expected_guidance()
        stack.enter_context(patch.object(web, 'guidance_services', return_value=guidance[1]))
        render = stack.enter_context(patch.object(web, 'render_page', return_value='ordinary GET bytes'))
        assert web.fetch_nav(URL, find='echo', cursor='c12', raw=True, cap_tokens=4000) == 'ordinary GET bytes'
        render.assert_called_once_with(URL, 405, 'text/plain', 'GET refused', None,
                                       0, 4000, False, _guidance=guidance)
        assert_guidance_identity(render, guidance)


def test_public_observed_absence_is_lazy_without_renderer():
    from cria import assistruntime
    with assistruntime.bound(prepared_runtime(None)), \
            patch.object(api, 'probe_kind', side_effect=AssertionError('must not classify')) as classifier:
        assert api.discover(URL, 405, 'GET refused', 'text/plain') is None
        classifier.assert_not_called()


def test_public_oversize_discloses_bound_without_empty_route_fact():
    from cria import assistruntime
    with ExitStack() as stack:
        for seam in fetch_patches():
            stack.enter_context(seam)
        stack.enter_context(assistruntime.bound(prepared_runtime()))
        stack.enter_context(patch.object(api, '_post_json', side_effect=api.ProbeTooLarge(URL)))
        assert web.fetch_nav(URL) == (
            'HTTP 405 Method Not Allowed · https://example.invalid/mcp\n'
            'Content-Type: text/plain\n'
            'This endpoint answered, but its reply ran past 32 MB — more than can be read here — '
            'so the list of what it offers is NOT known — that is a limit here, not an endpoint '
            'with nothing to offer. Ask it yourself: POST https://example.invalid/mcp with '
            '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"} and read the reply in pieces.')


def test_public_fetch_execute_replacement_literal_and_fault_restoration():
    from cria import assistruntime
    observed = api.Discovery(kind='mcp', routes=['mcp tool replacement()'])
    received = []

    def replacement(value, providers):
        received.append((value, providers))
        return p.DiscoveryResult('exact selected replacement bytes', observed)

    runtime = prepared_runtime(replace(p.DEFINITION, execute=replacement))
    with ExitStack() as stack:
        for seam in fetch_patches():
            stack.enter_context(seam)
        stack.enter_context(assistruntime.bound(runtime))
        post = stack.enter_context(patch.object(api, '_post_json', side_effect=AssertionError('replacement owns decision')))
        assert web.fetch_nav(URL) == 'exact selected replacement bytes'
        assert len(received) == 1
        post.assert_not_called()

    def oracle(definition):
        with ExitStack() as stack:
            for seam in fetch_patches():
                stack.enter_context(seam)
            stack.enter_context(assistruntime.bound(prepared_runtime(definition)))
            stack.enter_context(patch.object(api, '_post_json', side_effect=fake_post([])))
            assert web.fetch_nav(URL) == EXPECTED

    oracle(p.DEFINITION)
    with pytest.raises(AssertionError):
        oracle(replace(p.DEFINITION, execute=lambda *_: p.DiscoveryResult('wrong output', observed)))
    oracle(p.DEFINITION)
