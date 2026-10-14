"""Success expectations for genuine cached stdlib proxy policy, fake lower IO only."""
import os, json, urllib.request
from pathlib import Path
import pytest
from .fixtures import Lower, Log, wire
from .fixtures import assemble, stdlib_lower, consume
from .test_assembly import BODY


@pytest.mark.parametrize('cached_proxy,bypass', [(True, False), (False, False), (True, True)])
def test_render_and_chat_preserve_cached_proxy_policy(tmp_path, monkeypatch, cached_proxy, bypass):
    # Child-only normal environment. Genuine stdlib proxy discovery/bypass functions.
    for key in list(os.environ):
        if key.lower().endswith('_proxy'): monkeypatch.delenv(key)
    monkeypatch.setattr(urllib.request, 'getproxies', urllib.request.getproxies_environment)
    if cached_proxy: monkeypatch.setenv('http_proxy', 'http://cached-proxy.invalid:8101')
    lower = Lower([wire(b'{"data":[{"id":"supplied"}]}'),
                   wire(b'{"prompt":"labelled cached-policy template"}'), wire(b'final')])
    calls = stdlib_lower(monkeypatch, lower)
    _, u = assemble(tmp_path, 'shared', True)
    log = Log()
    assert u.loaded_model(log) == 'supplied'
    cache = urllib.request._opener
    owner = u._receive_open
    policy = owner._policy(cache)
    proxy = next((h for h in cache.handlers if type(h) is urllib.request.ProxyHandler), None)
    if cached_proxy: assert proxy.proxies == {'http':'http://cached-proxy.invalid:8101'}
    else: assert proxy is None  # stdlib omits the inactive empty handler
    parents = [h.parent for h in cache.handlers]
    monkeypatch.setenv('http_proxy', 'http://new-proxy.invalid:8102')
    if bypass: monkeypatch.setenv('no_proxy', 'fixture.invalid')
    estimate, path = consume(u, BODY, lower, log)
    expected = {**BODY, 'stream':False}
    assert json.loads(path.read_bytes())['body'] == expected
    assert json.loads(calls[-1][1]) == expected
    assert path.with_suffix('.prompt.txt').read_text() == 'labelled cached-policy template'
    initial = 'cached-proxy.invalid' if cached_proxy else 'fixture.invalid'
    dispatch = initial if not bypass else 'fixture.invalid'
    # BEFORE must fail here when fresh chat construction silently selects ambient B.
    assert [f['host'] for f in lower.factories] == [initial, dispatch, dispatch]
    assert urllib.request._opener is cache and owner._policy(cache) == policy
    assert [h.parent for h in cache.handlers] == parents
    assert all(h.parent is cache for h in cache.handlers)
    assert all(s.sent and s.returned for s in lower.sockets)
    assert [url.rsplit('/',1)[-1] for url, _, _ in calls] == ['models','apply-template','completions']
    target = b'http://fixture.invalid/v1/chat/completions' if cached_proxy and not bypass else b'/v1/chat/completions'
    assert b'POST ' + target + b' HTTP/1.1' in b''.join(lower.sockets[2].sent)
    lower.assert_closed()
