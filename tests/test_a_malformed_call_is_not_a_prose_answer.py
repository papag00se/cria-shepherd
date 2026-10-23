"""A toolless author must not turn erased tool syntax into a private-analysis directive.

The incident reply had a bash function tag and a duplicate closing parameter tag.
Text-answer coercion erased that content, promoted reasoning, and summarize accepted
it because its leak check inspected only the transformed text. Exercise the actual
shared owner and its reorientation adapter, without a live provider or workspace.
"""
import copy
import json

import pytest

from cria import loop, massage, prompts, reorientation


MALFORMED = ('<tool_call>\n<function=bash>\n<parameter=command>\n'
             'find . -type f -print\n</parameter>\n</parameter>\n</tool_call>')
PRIVATE = 'Am I the coder or the author? I should inspect files, then decide what to tell the coder.'
PUBLIC = 'Inspect the existing files before continuing the work.'


class Log:
    phase = 'reasoner'
    def __init__(self):
        self.events = []
    def emit(self, kind, **fields):
        self.events.append((kind, fields))


def completion(content='', *, reasoning='', calls=None, finish='stop'):
    message = {'role': 'assistant', 'content': content, 'reasoning_content': reasoning}
    if calls is not None:
        message['tool_calls'] = calls
    return {'choices': [{'message': message, 'finish_reason': finish}]}


class Chat:
    def __init__(self, *replies):
        self.replies = replies
        self.calls = []
    def __call__(self, body, log):
        self.calls.append((copy.deepcopy(body), log.phase))
        reply = self.replies[len(self.calls) - 1]
        if isinstance(reply, Exception):
            raise reply
        return json.dumps(reply).encode()


def summarize(chat, **kwargs):
    return loop.summarize(chat, None, prompts.load('reanchor_reasoned'),
                          '⟦ctx:continuation⟧ Existing work needs inspection.', Log(),
                          phase='reasoner', **kwargs)


def assert_reasoning_off_retry(chat):
    assert len(chat.calls) == 2
    assert chat.calls[0][1] == 'reasoner'
    assert chat.calls[1][1] == 'reasoner-noreason'
    assert chat.calls[1][0]['chat_template_kwargs']['enable_thinking'] is False
    assert chat.calls[0][0]['messages'] == chat.calls[1][0]['messages']


def test_malformed_saved_reply_shape_uses_the_existing_off_retry_and_preserves_capture():
    first = completion(MALFORMED, reasoning=PRIVATE)
    second = completion(PUBLIC)
    saved = []
    chat = Chat(first, second)
    assert massage.has_tool_call_leak(first['choices'][0]['message']['content'])
    assert summarize(chat, capture=saved) == PUBLIC
    assert_reasoning_off_retry(chat)
    assert saved == [first, second]  # exact original reasoning remains evidence, not a directive


def test_real_reorientation_adapter_delivers_public_retry_not_the_private_analysis():
    log = Log()
    chat = Chat(completion(MALFORMED, reasoning=PRIVATE), completion(PUBLIC))
    source = reorientation.ReorientationInput(
        rewritten=True,
        facts=lambda: reorientation.ReorientationFacts(
            ('⟦ctx:continuation⟧ Existing work needs inspection.',), True),
        inventory=lambda: 'Existing files are on disk.',
        author=reorientation.SummaryAuthor(loop.summarize, chat, None, log),
        consume_rewrite=None, log=log)
    result = reorientation.reorient(source)
    assert result.message == {'role': 'user', 'content': '⟦ctx:steer⟧ ' + PUBLIC}
    assert result.reason == 'authored'
    assert_reasoning_off_retry(chat)


@pytest.mark.parametrize('retry', [completion(), completion(MALFORMED, reasoning=PRIVATE),
                                  completion('incomplete answer', finish='length'),
                                  RuntimeError('provider unavailable')],
                         ids=['empty', 'malformed-with-reasoning', 'truncated', 'failed'])
def test_empty_or_failed_retry_does_not_return_the_erased_tool_calls_private_analysis(retry):
    chat = Chat(completion(MALFORMED, reasoning=PRIVATE), retry)
    assert summarize(chat) == ''
    assert_reasoning_off_retry(chat)


def test_single_pass_author_rejects_raw_malformed_intent_without_adding_a_retry():
    chat = Chat(completion(MALFORMED, reasoning=PRIVATE))
    assert summarize(chat, retry_off=False) == ''
    assert len(chat.calls) == 1


@pytest.mark.parametrize('first,expected', [
    (completion(PUBLIC, reasoning=PRIVATE), PUBLIC),
    (completion('', reasoning='The existing work needs inspection before continuing.'),
     'The existing work needs inspection before continuing.')],
    ids=['clean-public-answer', 'completed-reasoning-only-contract'])
def test_non_tool_answers_keep_the_existing_text_and_reasoning_recovery_contracts(first, expected):
    chat = Chat(first)
    assert summarize(chat) == expected
    assert len(chat.calls) == 1


def test_native_tool_answer_keeps_its_existing_retry_and_exact_raw_capture():
    native = [{'id': 'native-1', 'type': 'function',
               'function': {'name': 'bash', 'arguments': '{"command":"find . -type f -print"}'}}]
    first = completion(None, reasoning=PRIVATE, calls=native, finish='tool_calls')
    chat = Chat(first, completion(PUBLIC))
    saved = []
    assert summarize(chat, capture=saved) == PUBLIC
    assert_reasoning_off_retry(chat)
    assert saved[0] == first


def test_coder_with_real_tools_still_receives_native_calls():
    native = [{'id': 'native-1', 'type': 'function',
               'function': {'name': 'bash', 'arguments': '{"command":"find . -type f -print"}'}}]
    tools = [{'type': 'function', 'function': {'name': 'bash', 'parameters': {
        'type': 'object', 'properties': {'command': {'type': 'string'}}, 'required': ['command']}}}]
    result = massage.apply(completion(None, calls=native, finish='tool_calls'), tools)
    assert result['choices'][0]['message']['tool_calls'] == native
