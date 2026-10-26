"""A summary request keeps room for its own reply and is sized with its own token density.

Incident: Ornith/Java L5-only run 1792480002 call 0051 (internal self-compaction). The floor sized
the flattened-history summary with the coder's learned density (~1.1; summary text is ~1.33), saw
no need to trim, and the measured prompt (48,192 of a 49,152 window) was accepted because the
measured check compared it with the window alone. The briefing got 959 tokens and was cut off.
"""
import json
from unittest.mock import patch

from cria import assistruntime, bodykeys, selfcompact, tokenratio
from cria.upstream import Upstream


class Log:
    def __init__(self, phase):
        self.phase = phase
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))


def summary_body(n=24, reserve=4000):
    return {'model': 'm', 'max_tokens': reserve, bodykeys.DENSITY_KIND: 'summary', 'messages': [
        {'role': 'system', 'content': 'Write a briefing.'},
        selfcompact.internal_evidence_message('Evidence follows.'),
        *[selfcompact.internal_evidence_message(f'turn {i}: ' + 'word ' * 120) for i in range(n)],
        {'role': 'user', 'content': 'Write the briefing now.'}]}


def render(body):
    return json.dumps(body['messages'])


def test_measured_prompt_must_leave_the_reply_reserve_free():
    up = Upstream('http://unused', context_window=8000)
    up._props = {'chat_template': 'served'}
    body = summary_body(reserve=4000)
    # The real prompt fits the 8,000 window but not with 4,000 left for the reply.
    count = lambda text, log: len(text) * 3 // 8   # denser than the chars/4 estimate
    with patch.object(up, '_render_prompt', side_effect=render), \
         patch.object(up, '_tokenize_prompt', side_effect=count, create=True), \
         assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
        assert 4000 < count(render(body), None) < 8000
        data, _, _ = up._prep(body, False, Log('self-compact'), safety_override=1)
    wire = json.loads(data)
    assert count(render(wire), None) <= 8000 - 4000
    assert wire['messages'][-1]['content'] == 'Write the briefing now.'
    assert bodykeys.DENSITY_KIND not in wire


def test_summary_density_is_learned_separately_from_the_coder():
    tokenratio.reset()
    try:
        up = Upstream('http://unused', context_window=8000)
        for _ in range(8):
            up._calibrate('m', {'prompt_tokens': 1000}, 1000, Log('coder-s1'))     # coder: 1.0
        up._calibrate('m', {'prompt_tokens': 1400}, 1000, Log('proxy'),
                      {bodykeys.DENSITY_KIND: 'summary'})                         # summary: 1.4
        from cria.upstream import _density_key
        coder = tokenratio.observed(_density_key('m', Log('coder-s1')))
        summary = tokenratio.observed(_density_key('m', Log('proxy'), {bodykeys.DENSITY_KIND: 'summary'}))
        internal = tokenratio.observed(_density_key('m', Log('self-compact')))
        assert coder < 1.2 and summary > 1.3 and internal == summary
    finally:
        tokenratio.reset()
