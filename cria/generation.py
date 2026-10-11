"""Terminal generation facts and action release at the harness boundary.

Evidence is data, never a second source of executable calls. Native content
authority comes from the prepared backend parser's response, not request hints.
"""
import copy
import json
from . import bodykeys


EVIDENCE = 'generation_evidence'
PROTOCOL_ERROR = 'invalid_model_output_error'
INCOMPLETE_STREAM_ERROR = 'incomplete_stream_error'


def is_protocol_error(error) -> bool:
    return isinstance(error, dict) and error.get('type') == PROTOCOL_ERROR


def is_generation_error(error) -> bool:
    return isinstance(error, dict) and error.get('type') in (PROTOCOL_ERROR, INCOMPLETE_STREAM_ERROR)


def incomplete(completion: dict) -> bool:
    evidence = completion.get(EVIDENCE) or {}
    return bool(completion.get(bodykeys.RUMINATION)) or (isinstance(evidence, dict) and evidence.get('incomplete') is True) or any(
        choice.get('finish_reason') == 'length' for choice in completion.get('choices', []))


def content_is_non_action(completion: dict) -> bool:
    evidence = completion.get(EVIDENCE) or {}
    return isinstance(evidence, dict) and evidence.get('content_is_non_action') is True


def may_recover(completion: dict) -> bool:
    return not (incomplete(completion) or content_is_non_action(completion) or is_protocol_error(completion.get('error')))


def safe_completion(completion: dict) -> dict:
    """Withhold all calls on an incomplete turn, retaining their complete evidence."""
    if not incomplete(completion):
        return completion
    evidence = copy.deepcopy(completion.get(EVIDENCE) or {})
    evidence['incomplete'] = True
    local_abort = completion.get(bodykeys.RUMINATION)
    evidence.setdefault('wire_finish_reason', 'rumination' if local_abort else 'length')
    if local_abort:
        evidence['local_abort'] = copy.deepcopy(local_abort)
    if 'withheld_choices' not in evidence:
        evidence['withheld_choices'] = copy.deepcopy(completion.get('choices', []))
    prefixes = []
    for choice in completion.get('choices', []):
        message = choice.get('message') or {}
        for call in message.get('tool_calls') or []:
            function = call.get('function') or {}
            prefixes.append({'name': function.get('name'), 'arguments': function.get('arguments'), 'id': call.get('id')})
        message.pop('tool_calls', None)
        choice['finish_reason'] = 'rumination' if local_abort else 'length'
    if prefixes:
        evidence.setdefault('call_prefixes', prefixes)
        evidence['collected_call_prefixes'] = prefixes
    completion[EVIDENCE] = evidence
    return completion


def incomplete_reason(completion: dict) -> str:
    evidence = completion.get(EVIDENCE) or {}
    return 'generation_aborted' if evidence.get('local_abort') else 'generation_limit'


def _frame(obj: dict) -> bytes:
    return b'data: ' + json.dumps(obj, ensure_ascii=False).encode() + b'\n\n'


def quarantine_stream(chunks):
    """Release action fragments only after that choice's explicit successful stop.

    Ordinary content and reasoning remain live. Length and error turns retain
    held fragments and all original wire bytes as evidence without releasing them.
    """
    held = {}
    undecided = set()
    wire = bytearray()
    def unfinished():
        return _frame({'error': {'type': INCOMPLETE_STREAM_ERROR,
            'message': 'Stream ended without a terminal generation status',
            EVIDENCE: {'incomplete': True, 'wire_raw_hex': bytes(wire).hex(),
                'withheld_action_deltas': [value for values in held.values() for value in values]}}})
    for raw in chunks:
        wire.extend(raw)
        if not raw.startswith(b'data:'):
            yield raw
            continue
        payload = raw[5:].strip()
        if payload == b'[DONE]':
            if undecided or held:
                yield unfinished()
            yield raw
            return
        try:
            obj = json.loads(payload)
        except (ValueError, UnicodeDecodeError):
            yield raw
            continue
        if not isinstance(obj, dict):
            yield raw
            continue
        if obj.get('error'):
            error = copy.deepcopy(obj['error'])
            if isinstance(error, dict):
                evidence = error.setdefault(EVIDENCE, {})
                evidence['wire_raw_hex'] = bytes(wire).hex()
                evidence['withheld_action_deltas'] = [value for values in held.values() for value in values]
            yield _frame({**obj, 'error': error})
            return
        if not obj.get('choices'):
            yield raw
            continue
        for choice in obj['choices']:
            index = choice.get('index', 0)
            undecided.add(index)
            delta = copy.deepcopy(choice.get('delta') or {})
            calls = delta.pop('tool_calls', None)
            if calls:
                held.setdefault(index, []).append({**copy.deepcopy(obj), 'choices': [{
                    **choice, 'finish_reason': None, 'delta': {'tool_calls': calls}}]})
            finish = choice.get('finish_reason')
            if delta:
                yield _frame({**obj, 'choices': [{**choice, 'delta': delta, 'finish_reason': None}]})
            if finish:
                undecided.discard(index)
                evidence = copy.deepcopy(obj.get(EVIDENCE) or {})
                pending = held.pop(index, [])
                if finish in ('stop', 'tool_calls') and evidence.get('incomplete') is not True:
                    for frame in pending:
                        yield _frame(frame)
                else:
                    evidence['incomplete'] = True
                    evidence['wire_finish_reason'] = finish
                    evidence['withheld_action_deltas'] = pending
                    evidence['wire_raw_hex'] = bytes(wire).hex()
                frame = {**obj, 'choices': [{**choice, 'delta': {}}]}
                if evidence:
                    frame[EVIDENCE] = evidence
                yield _frame(frame)
            elif not delta and not calls:
                yield _frame({**obj, 'choices': [choice]})
    if undecided or held:
        yield unfinished()
