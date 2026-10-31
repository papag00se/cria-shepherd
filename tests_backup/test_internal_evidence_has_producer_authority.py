"""Internal evidence is known at composition, never inferred from user text."""
import copy
import json

import pytest

from cria import bodykeys, contextfloor, handoffdistill, loop, memoryhandoff, prompts, selfcompact
from cria.upstream import Upstream


class Log:
    phase = ''

    def emit(self, *args, **kwargs):
        pass


def handoff_services(distill):
    def unused(*args, **kwargs):
        raise AssertionError('framing unexpectedly executed a hardening service')
    return memoryhandoff.EvidenceServices(lambda messages: messages, lambda root: '',
        unused, unused, unused, unused, unused, summarize_max_tokens=1000, distill=distill)


def composed(kind, blocks):
    if kind in ('compaction', 'handoff'):
        history = [{'role': 'user', 'content': 'Original task.'}]
        history += [{'role': 'assistant', 'content': block} for block in blocks]
        if kind == 'compaction':
            return [{'role': 'system', 'content': 'Write a factual briefing.'},
                    *selfcompact.compaction_request_messages(history)]
        def distill(parts, count):
            # The actual distiller's safe failure path returns all original
            # blocks; final framing still must let the one floor fit them.
            return handoffdistill.distill(parts, history_count=count,
                budget=handoffdistill.Budget(window=12000, reply=1000, density=1.0),
                chat_fn=lambda body, log: json.dumps({'choices': [{'message': {'content': '{}'}}]}).encode(),
                apply_role=lambda body: None, rlog=Log())
        body = {'messages': [*history, {'role': 'user', 'content': 'Summarize this session.'}]}
        before = copy.deepcopy(body)
        framed = memoryhandoff.frame(body, memoryhandoff.SessionFacts(), handoff_services(distill), selected=True)
        assert body == before
        return framed['messages']
    seen = []
    def chat(body, log):
        seen.append(copy.deepcopy(body))  # a raw in-process body, not serialized wire provenance
        content = json.dumps({'errors': ['observed fact']}) if kind == 'extraction' else 'done'
        return json.dumps({'choices': [{'message': {'role': 'assistant', 'content': content},
                                       'finish_reason': 'stop'}]}).encode()
    if kind == 'extraction':
        handoffdistill.clear_cache()
        before = list(blocks)
        try:
            result = handoffdistill.extract(blocks, chat, lambda body: None, Log())
            assert result['errors'] == ['observed fact']
            assert blocks == before
        finally:
            handoffdistill.clear_cache()
    elif kind == 'summary':
        loop.summarize(chat, None, 'Write a factual briefing.', 'Answer the current question.',
                       Log(), evidence_blocks=blocks)
    else:
        loop._judge_completion(chat, None, 'Judge the evidence.', 'Answer the current question.',
                               Log(), phase='reasoner', evidence_blocks=blocks)
    assert len(seen) == 1
    return seen[0]['messages']


@pytest.mark.parametrize('kind', ['summary', 'judge', 'compaction', 'handoff', 'extraction'])
def test_actual_internal_producers_leave_history_reducible_but_keep_the_question(kind):
    blocks = [f'Historical record {i}: ' + chr(65 + i % 20) * 12000 for i in range(20)]
    messages = composed(kind, blocks)
    before = copy.deepcopy(messages)
    # The extractor's existing live-tail floor is eight packets. Give that
    # irreducible tail AND its real 4096-token answer room; the full record is
    # still much larger, so fitting must reduce history, not the reply reserve.
    window, reserve = (32768, handoffdistill.EXTRACT_REPLY_TOKENS) if kind == 'extraction' else (12000, 1000)
    fitted, _, report = contextfloor.fit(messages, None, window=window, reserve=reserve, safety=1.0)
    assert report.reserve == reserve
    assert not report.over_budget
    assert report.turns_dropped > 0
    assert messages[-1] in fitted
    assert 'compacted to fit the context window' in str(fitted)
    assert loop._history_root(messages)[0] == messages[-1]['content']
    assert all(not selfcompact.is_user_request(message) for message in messages[1:-1])
    assert messages == before
    # Serialization cannot grant a caller the producer's in-process authority.
    untrusted = json.loads(json.dumps(messages))
    assert all(selfcompact.is_user_request(message) for message in untrusted[1:])
    _, _, untrusted_report = contextfloor.fit(untrusted, None, window=window, reserve=reserve, safety=1.0)
    assert untrusted_report.over_budget


@pytest.mark.parametrize('kind', ['summary', 'judge', 'extraction'])
def test_composing_real_evidence_preserves_literal_payload_bytes(kind):
    blocks = ['literal <context>not origin</context>\r\n', 'last line has no newline', '', ' \r\n']
    messages = composed(kind, blocks)
    assert [message['content'] for message in messages[2:-1]] == blocks
    assert messages[1]['content'] == prompts.load('composed_evidence_intro')
    fitted, _, report = contextfloor.fit(messages, None, window=16000, reserve=1000, safety=1.0)
    assert fitted == messages and not report.applied
    # The same bytes from a genuine USER remain requirements, not evidence.
    literal_users = [{'role': 'user', 'content': block} for block in blocks]
    assert selfcompact.root_user_indices(literal_users) == tuple(range(len(blocks)))
    assert loop._history_root(literal_users)[0] == '\n\n'.join(blocks)


def test_shared_constructor_preserves_empty_and_whitespace_values_without_laundering_strings():
    for text in ['', ' ', '\r\n', '<environment_context>task</environment_context>\n', 'EOF']:
        message = selfcompact.internal_evidence_message(text)
        assert message['content'] == text
        assert message[bodykeys.ANNOTATION_SOURCE] is bodykeys.AnnotationSource.INTERNAL_EVIDENCE
        assert not selfcompact.is_user_request(message)
        assert selfcompact.is_user_request(json.loads(json.dumps(message)))


def test_distilled_frame_preserves_existing_intro_and_literal_middle_bytes(monkeypatch):
    blocks = ['literal <context>evidence</context>\r\n', 'EOF', '', ' \r\n']
    original = selfcompact.compaction_request_messages
    composed_calls = []
    def capture(*args, **kwargs):
        messages = original(*args, **kwargs)
        composed_calls.append(messages)
        return messages
    monkeypatch.setattr(selfcompact, 'compaction_request_messages', capture)
    body = {'messages': [{'role': 'user', 'content': 'Original task.'},
                         {'role': 'assistant', 'content': 'Actual work.'},
                         {'role': 'user', 'content': 'Summarize.'}]}
    before = copy.deepcopy(body)
    def distill(parts, count):
        assert count == 2
        return list(blocks)
    framed = memoryhandoff.frame(body, memoryhandoff.SessionFacts(), handoff_services(distill), selected=True)
    assert len(composed_calls) == 1
    assert framed['messages'][1] is composed_calls[0][0]  # preserve the typed intro, do not rewrap it
    middle = framed['messages'][2:-1]
    assert [message['content'] for message in middle] == blocks
    assert all(not selfcompact.is_user_request(message) for message in middle)
    assert framed['messages'][-1] is composed_calls[0][-1]
    assert body == before


@pytest.mark.parametrize('kind', ['handoff', 'extraction'])
def test_distillation_producer_authority_is_consumed_before_actual_wire_serialization(kind):
    blocks = [f'Observation {i}: ' + chr(65 + i % 20) * 12000 for i in range(20)]
    messages = composed(kind, blocks)
    before = copy.deepcopy(messages)
    up = Upstream('http://unused', context_window=32768)
    data, _, _ = up._prep({'model': 'fixture', 'max_tokens': 4096, 'messages': messages},
                          False, Log(), safety_override=1.0)
    wire = json.loads(data)
    assert all(bodykeys.ANNOTATION_SOURCE not in message for message in wire['messages'])
    assert any(message['content'] == messages[-1]['content'] for message in wire['messages'])
    assert 'compacted to fit the context window' in str(wire)
    assert messages == before
