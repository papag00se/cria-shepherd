import copy, urllib.request
import pytest
from .fixtures import Lower, Log, wire
from .test_assembly import BODY
from .fixtures import assemble, stdlib_lower

@pytest.mark.parametrize('change', ['handler', 'headers', 'handler-setting', 'dispatch-table'])
def test_changed_owned_cache_requires_explicit_owner(tmp_path, monkeypatch, change):
    lower = Lower([wire(b'{"data":[{"id":"supplied"}]}')])
    stdlib_lower(monkeypatch, lower)
    _, u = assemble(tmp_path, 'shared', False)
    assert u.loaded_model(Log()) == 'supplied'
    cached = urllib.request._opener
    class Custom(urllib.request.BaseHandler):
        def default_open(self, req): raise AssertionError('must not replace or dispatch changed policy')
    if change == 'handler': cached.add_handler(Custom())
    elif change == 'headers': cached.addheaders.append(('X-Custom', 'custom-policy'))
    elif change == 'handler-setting':
        next(h for h in cached.handlers if type(h) is urllib.request.HTTPRedirectHandler).max_repeats = 1
    else: cached.handle_open['http'].clear()
    parents = [h.parent for h in cached.handlers]
    with pytest.raises(ValueError, match='installed opener'):
        u._open_with_refit(copy.deepcopy(BODY), False, Log())
    assert len(lower.factories) == 1 and urllib.request._opener is cached
    assert [h.parent for h in cached.handlers] == parents
    lower.assert_closed()
