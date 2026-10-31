"""Genuine stdlib cache/HTTP lifecycle, with labelled in-memory lower IO only."""
import copy, dataclasses, http.client, json, urllib.request, urllib.error
from pathlib import Path
from unittest.mock import patch
import pytest
from cria import __main__ as entry, config, server, receivecapture as rc, contextfloor
from .fixtures import Lower, Log, wire
from .test_assembly import cfg, BODY, ORIGINAL_URLOPEN


from .fixtures import assemble, stdlib_lower, consume

@pytest.mark.parametrize('endpoint,rendered,prelude,error,repeated', [
    ('shared', True, None, False, False),
    ('served', True, None, False, False),
    ('shared', False, 'models', False, False),
    ('keyed', True, 'failed-open', False, False),
    ('shared', True, None, True, False),
    ('shared', False, None, False, True),
])
def test_normal_cache_then_chat(tmp_path, monkeypatch, endpoint, rendered, prelude, error, repeated):
    monkeypatch.setenv('C21_CACHE_FIXTURE_KEY', 'labelled-not-secret')
    wires = [wire(b'{"data":[{"id":"supplied"}]}')] if prelude == 'models' else []
    metadata = rendered and endpoint != 'keyed'
    if metadata: wires.append(wire(b'{"error":"offline"}', 503) if error else wire(b'{"prompt":"labelled template"}'))
    wires += [wire(b'final')] * (2 if repeated else 1)
    lower = Lower(wires)
    calls = stdlib_lower(monkeypatch, lower)
    shared, u = assemble(tmp_path, endpoint, rendered)
    log = Log()
    if prelude == 'models': assert shared.loaded_model(log) == 'supplied'
    if prelude == 'failed-open':
        # Ordinary failed opening by the shared owner still creates the genuine cache.
        with patch.object(urllib.request.HTTPHandler, 'http_open', side_effect=OSError('labelled offline opening failure')):
            assert shared._render_prompt(BODY) is None
        assert urllib.request._opener is not None
    cached_before = urllib.request._opener
    for turn in range(2 if repeated else 1):
        estimate, path = consume(u, BODY, lower, log)
        expected = {**BODY, 'stream': False}
        assert json.loads(path.read_bytes())['body'] == expected
        assert calls[-1][1] == json.dumps(expected).encode()
        assert estimate == contextfloor.est_total(expected['messages'], expected.get('tools'))
        if metadata and not error: assert path.with_suffix('.prompt.txt').read_text() == 'labelled template'
        else: assert not path.with_suffix('.prompt.txt').exists()
        if endpoint == 'keyed': assert calls[-1][2]['Authorization'] == 'Bearer labelled-not-secret'
    cached = urllib.request._opener
    if metadata or prelude:
        assert cached is not None
        if cached_before is not None: assert cached is cached_before
        assert all(h.parent is cached for h in cached.handlers)
    else: assert cached is None
    assert sum(url.endswith('/v1/chat/completions') for url, _, _ in calls) == (2 if repeated else 1)
    lower.assert_closed()


def test_implicit_model_and_window_discovery_then_render(tmp_path, monkeypatch):
    lower = Lower([wire(b'{"data":[{"id":"supplied"}]}'),
                   wire(b'{"default_generation_settings":{"n_ctx":49152},"chat_template":"labelled"}'),
                   wire(b'{"prompt":"labelled template"}'), wire(b'final')])
    calls = stdlib_lower(monkeypatch, lower)
    _, u = assemble(tmp_path, 'shared', True, window=0)
    body = copy.deepcopy(BODY)
    del body['model']
    estimate, path = consume(u, body, lower, Log())
    expected = {**body, 'model':'supplied', 'stream':False}
    assert json.loads(path.read_bytes())['body'] == expected
    assert json.loads(calls[-1][1]) == expected
    assert u._window == 49152 and u._window_final and not u._window_guessed
    assert estimate == contextfloor.est_total(expected['messages'], expected.get('tools'))
    assert path.with_suffix('.prompt.txt').read_text() == 'labelled template'
    assert [url.rsplit('/', 1)[-1] for url, _, _ in calls] == ['models', 'props', 'apply-template', 'completions']
    lower.assert_closed()


def test_discovery_measurement_refit_repeated_order(tmp_path, monkeypatch):
    props = wire(b'{"chat_template":"labelled","default_generation_settings":{"n_ctx":49152}}')
    rendered = wire(b'{"prompt":"measured labelled template"}')
    tokens = wire(b'{"tokens":[1,2,3]}')
    rejection = wire(b'{"error":{"message":"labelled context rejection","n_prompt_tokens":8000,"n_ctx":4096}}', 400)
    lower = Lower([props, rendered, tokens, rejection, rendered, tokens, wire(b'final'), rendered, tokens, wire(b'final')])
    calls = stdlib_lower(monkeypatch, lower)
    _, u = assemble(tmp_path, 'shared', True, level=5, window=4096)
    log = Log()
    assert u.props(log)['chat_template'] == 'labelled'
    cache = urllib.request._opener
    body = {'model':'supplied', 'max_tokens':64, 'messages':[
        {'role':'user','content':'old ' * 400}, {'role':'assistant','content':'old response ' * 100},
        {'role':'user','content':'Keep this last question.'}]}
    # Actual preparation, measured template and actual overflow owner; no substituted _prep.
    estimate, path = consume(u, body, lower, log)
    sent = json.loads(calls[6][1])
    assert sent != json.loads(calls[3][1])
    assert json.loads(path.read_bytes())['body'] == sent
    assert path.with_suffix('.prompt.txt').read_text() == 'measured labelled template'
    assert estimate == contextfloor.est_total(sent['messages'], sent.get('tools'))
    consume(u, body, lower, log)
    assert urllib.request._opener is cache and all(h.parent is cache for h in cache.handlers)
    assert [url.rsplit('/',1)[-1] for url, _, _ in calls] == [
        'props','apply-template','tokenize','completions','apply-template','tokenize','completions',
        'apply-template','tokenize','completions']
    assert any(e['kind'] == 'context.measured' for e in log.events)
    assert any(e['kind'] == 'context.refit' for e in log.events)
    lower.assert_closed()


@pytest.mark.parametrize('after_ordinary', [False, True])
def test_custom_installed_policy_not_replaced(tmp_path, monkeypatch, after_ordinary):
    lower = Lower([wire(b'{"data":[{"id":"supplied"}]}')])
    stdlib_lower(monkeypatch, lower)
    shared, u = assemble(tmp_path, 'shared', False)
    if after_ordinary: assert shared.loaded_model(Log()) == 'supplied'
    class Custom(urllib.request.BaseHandler):
        def default_open(self, req): raise AssertionError('custom policy must not be silently dispatched or replaced')
    installed = urllib.request.build_opener(Custom())
    parents = [h.parent for h in installed.handlers]
    monkeypatch.setattr(urllib.request, '_opener', installed)
    count = len(lower.factories)
    with pytest.raises(ValueError, match='installed opener'):
        u._open_with_refit(copy.deepcopy(BODY), False, Log())
    assert len(lower.factories) == count
    assert urllib.request._opener is installed and [h.parent for h in installed.handlers] == parents
    lower.assert_closed()
