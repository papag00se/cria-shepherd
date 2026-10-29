"""Both real response producers frame compaction, including fit retries."""
import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from cria import indicators, server, upstream
from cria.loop import completion_to_sse
from test_the_compaction_turn_never_asks_the_classifier import body, Rlog


@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('retry', [False, True])
def test_compaction_owner_reframes_buffered_stream_and_fit_retry(stream, retry):
    request = {**body(), 'model': 'fixture', 'tools': []}
    framed = []
    reply = {'id':'c', 'object':'chat.completion', 'created':1, 'model':'fixture',
             'choices':[{'index':0, 'message':{'role':'assistant','content':'brief'}, 'finish_reason':'stop'}]}
    class Provider:
        def chat(self, actual, rlog):
            framed.append(copy.deepcopy(actual))
            if retry and len(framed)==1:
                raise upstream.ReadFitUnknown('fixture', ())
            return json.dumps(reply)
        def stream_chat(self, actual, rlog):
            yield from completion_to_sse(json.loads(self.chat(actual, rlog)))
    provider = Provider()
    h = object.__new__(server.CriaHandler)
    h.headers = {}
    h.server = SimpleNamespace(cfg=SimpleNamespace(routing=SimpleNamespace(context_fixes=True, engagement_level=2)),
                               pilot_runtime=SimpleNamespace(wire_folds=()), loop=None)
    h._classify = Mock(return_value=None)
    h._engages_loop = Mock(return_value=False)
    h._route = Mock(return_value=(provider, indicators.Indicator(False, False, 'fixture')))
    h._focus_trim = lambda b, r: (b, None)
    h._apply_route_role = lambda b, i, r: b
    h._translate_out = lambda c, s, r: c
    h._retain_external_output = lambda c, s: c
    h._finalize = lambda c, s, r: c
    h._fit_fallback = lambda error, session, rlog: copy.deepcopy(request)
    original_compaction = server._compaction_body
    definition = server._selected_handoff()
    with patch.object(server, '_selected_handoff', return_value=definition), \
         patch.object(server, '_observe_handoff_write_results', return_value=None), \
         patch.object(server, '_recognize_compaction', return_value=True), \
         patch.object(server, '_handoff_facts', return_value=None), \
         patch.object(server, '_handoff_distiller', return_value=None), \
         patch.object(server, '_compaction_body', side_effect=lambda b, **kw: original_compaction(b)), \
         patch.object(server, '_harden_compaction_reply', side_effect=lambda c, *a, **kw: c), \
         patch.object(server, '_report_context_usage'):
        if stream:
            output = b''.join(x if isinstance(x,bytes) else x.encode() for x in h._produce_stream(copy.deepcopy(request), Rlog()))
            assert b'brief' in output
        else:
            output, _ = h._produce_completion(copy.deepcopy(request), Rlog(), 'sid:s')
            assert output['choices'][0]['message']['content']=='brief'
    assert len(framed)==(2 if retry else 1)
    for actual in framed:
        assert 'build the shipping calculator' in str(actual['messages'])
        assert '<<<LOCAL_COMPACT>>>' not in str(actual['messages'])
        assert 'Preserve edits, blockers' not in str(actual['messages'])
