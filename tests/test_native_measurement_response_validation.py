"""Native metadata must never grant capacity from malformed response shapes."""
import io
import json

import pytest

from cria.upstream import Upstream


class Log:
    def emit(self, *args, **kwargs):
        pass


@pytest.mark.parametrize('response', [None, [], {'tokens': []}, {'tokens': [True]},
                                      {'tokens': [-1]}, {'tokens': ['12']}, {'tokens': None}])
def test_invalid_native_token_counts_are_unknown(response):
    up = Upstream('http://unused.invalid')
    up._ordinary_open = lambda *a, **k: io.BytesIO(json.dumps(response).encode())
    assert up._tokenize_prompt('real input', Log()) is None


def test_valid_native_token_count_is_used():
    up = Upstream('http://unused.invalid')
    up._ordinary_open = lambda *a, **k: io.BytesIO(b'{"tokens":[0,1,42]}')
    assert up._tokenize_prompt('real input', Log()) == 3


@pytest.mark.parametrize('response', [None, [], {'prompt': ''}, {'prompt': None}])
def test_invalid_native_template_response_is_unknown(response):
    up = Upstream('http://unused.invalid')
    up._ordinary_open = lambda *a, **k: io.BytesIO(json.dumps(response).encode())
    assert up._render_prompt({'messages': [{'role': 'user', 'content': 'hello'}]}) is None
