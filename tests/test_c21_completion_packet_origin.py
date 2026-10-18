"""B5 0077/78: a deterministic dropped handoff was reclassified as coder prose.

Drive actual hardening -> reframe -> collector -> satisfaction -> final serialization.
The fake upstream only returns recorded replies/verdicts; it does not judge origin for
us. Assert the sent source frames, exact payloads, ordered outcomes, real floor behavior,
and actual parser/suppression/remediation results, not prompt source code.
"""
import copy
import json
import random
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cria import assistruntime, completiondiagnosis, contextfloor as cf, denial, loop, modelview, prompts, selfcompact, server, upstream, wsview
from cria.config import Role
from cria.plan import Plan, PlanItem
from tests.test_c13a_rejected_handoff_keeps_the_tool_ledger import _provider
from tests.wsfixture import survey
from tests.handoff_runtime import attach_session

ROOT = '/packet-work'
TASK = '''Fix these three problems in the supplier feed importer:

1. Make it at least 4× faster without changing any totals, row counts, or per-SKU results.
2. Fix the threading bug and re-enable parallel workers. Processing the same feed repeatedly must always produce identical results.
3. Handle malformed input safely: blank quantities, currency symbols in prices, missing columns, and quoted descriptions containing commas. A SKU appearing on several rows is normal — those rows all count. Decide and implement how each bad-row type is handled, and report skipped-row counts by reason in the summary. Use a third-party Java CSV library for parsing quoted CSV and add it to the project dependencies; do not write a CSV parser.

Keep `Importer.summarize(path)` compatible, including its returned `skus`, `rows`, and `totals`.

Add `REVIEW.md` describing remaining problems or risks in the code you changed. For every issue, include the file name and line number.'''
OUTPUT_SPAN = 'Add `REVIEW.md` describing remaining problems or risks in the code you changed.'
REPLIES = json.loads((Path(__file__).parent / 'fixtures/c21_completion_replies.json').read_text())


class Log:
    phase = ''

    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))


def call(cid, name, args):
    return {'id': cid, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}


def history():
    # A non-Java file, a refusal BETWEEN confirmed edits, and opaque shell result.
    return [
        {'role': 'user', 'content': TASK},
        {'role': 'assistant', 'tool_calls': [call('w1', 'write_file', {'path': 'worker.rb', 'content': 'one\n'})]},
        {'role': 'tool', 'tool_call_id': 'w1', 'content': 'Wrote worker.rb'},
        {'role': 'assistant', 'tool_calls': [call('e1', 'edit_file', {'path': 'worker.rb', 'old_string': 'one', 'new_string': 'two'})]},
        {'role': 'tool', 'tool_call_id': 'e1', 'content': denial.mark('not run')},
        {'role': 'assistant', 'tool_calls': [call('e2', 'edit_file', {'path': 'worker.rb', 'old_string': 'one', 'new_string': 'three'})]},
        {'role': 'tool', 'tool_call_id': 'e2', 'content': 'Wrote worker.rb'},
        {'role': 'assistant', 'tool_calls': [call('s1', 'exec_command', {'cmd': 'ls src'})]},
        {'role': 'tool', 'tool_call_id': 's1', 'content': 'nested\n'},
    ]


def stored(text):
    return {'role': 'user', 'content': loop._COMPACTION_MARKER + '\n' + loop._COMPACTION_BOUNDARY + '\n' + text}


class Runtime:
    """Real session store, hardener and inbound handler; only upstream judgments are fake."""
    key = 'sid:c21-origin'

    def __init__(self, key=None):
        self.key = key or self.key
        self.server = SimpleNamespace(cfg=SimpleNamespace(routing=SimpleNamespace(
            roles={'reasoner': Role(name='reasoner', backend='local')}, context_fixes=True)))
        self.sess = attach_session(self.server, self.key, TASK)
        self.sess.workspace_root = ROOT

    def harden(self, briefing, verdict, hist):
        out = server._harden_compaction_reply(
            {'choices': [{'message': {'role': 'assistant', 'content': briefing}}]},
            {'messages': hist}, _provider(verdict), self.server, Log(), self.key)
        # The harness only receives JSON, not a typed envelope or object attribute.
        return json.loads(json.dumps(out))['choices'][0]['message']['content']

    def reframe(self, reply, retained=()):
        incoming = json.loads(json.dumps({'messages': [*retained, stored(reply)]}))
        handler = object.__new__(server.CriaHandler)
        handler.server = self.server
        token = wsview.bind(wsview.current())
        try:
            handler._strip_and_reframe_inbound(incoming, self.key, Log())
        finally:
            wsview.unbind(token)
        return incoming['messages']


def handoff(accepted=False, extra=None):
    hist = history() + (extra or [])
    ledger = selfcompact.work_ledger(hist)
    runtime = Runtime()
    # Identical ledger-looking bytes: accepted MODEL prose vs rejected prose with
    # deterministic effects. The real hardener, not a manually tagged body, decides.
    shipped = runtime.harden(ledger if accepted else 'Add another worker now.',
                             'RETROSPECTIVE' if accepted else 'PLAN', hist)
    reframed = runtime.reframe(shipped)
    return hist, ledger, reframed[0], runtime


class Wire:
    def __init__(self, replies, window=65536):
        self.replies = iter(replies)
        self.bodies = []
        self.u = upstream.Upstream('http://fake.invalid', api_key='offline',
                                   context_window=window, engagement_level=5)

    def prepare(self, body, log=None):
        original = copy.deepcopy(body)
        selected_runtime = (assistruntime.current() if assistruntime.is_bound() else
                            assistruntime.AssistRuntime.select(level=self.u._engagement_level))
        selected = selected_runtime.capacity
        runtime, density_models = selected_runtime, []
        def density(model):
            assert assistruntime.current() is runtime
            assert runtime.capacity is controlled
            density_models.append(model)
            return 1.05
        if selected is not None:
            controlled = replace(selected, density=density)
            assert controlled.policy is selected.policy and controlled.execute is selected.execute
            runtime = replace(selected_runtime, ordered_stages=tuple(
                controlled if member.policy.id == selected.policy.id else member
                for member in selected_runtime.ordered_stages))
            assert runtime.capacity is controlled
            assert runtime.registrations is selected_runtime.registrations
            assert all(after is (controlled if before is selected else before)
                       for before, after in zip(selected_runtime.ordered_stages, runtime.ordered_stages))
        with assistruntime.bound(runtime), \
             patch('cria.upstream.urllib.request.urlopen', side_effect=AssertionError('network forbidden')), \
             patch('cria.upstream.contextfloor.fit', wraps=cf.fit) as floor:
            data, _est, _rendered = self.u._prep(body, False, log or Log())
        assert body == original
        if floor.called and selected is not None:
            assert density_models == [body.get('model')]
            assert all(call.kwargs['safety'] == 1.05 for call in floor.call_args_list)
        else:
            assert density_models == []
        if floor.called:
            print('CONTROLLED DENSITY WIRE', json.dumps({'models': density_models,
                'floor_safety': [call.kwargs['safety'] for call in floor.call_args_list],
                'wire': json.loads(data)}, ensure_ascii=False))
        return json.loads(data)

    def __call__(self, body, log):
        self.bodies.append(self.prepare(body, log))
        return json.dumps({'choices': [{'message': {'role': 'assistant', 'content': next(self.replies)},
                                       'finish_reason': 'stop'}]}).encode()


def text(body):
    return '\n'.join(m.get('content') or '' for m in body['messages'])


def run_judge(evidence, replies=None, window=65536, root=''):
    wire = Wire(replies or [json.dumps({'satisfied': False})], window)
    log = Log()
    result = loop.judge_satisfaction(TASK, evidence, wire, None, log, workspace_root=root)
    return result, wire.bodies, log


def assert_source_not_overridden(body, continuation, ledger, accepted):
    # The whole producer-selected source frame and its exact payload survive.
    assert continuation['content'] in text(body)
    assert ledger in text(body)
    assert selfcompact.parse_ledger(text(body)) == [
        ('write_file worker.rb: confirmed written', 1),
        ('edit_file worker.rb: refused, not written', 1),
        ('edit_file worker.rb: confirmed written', 1),
        ('issued (result recorded; execution not established): ls src', 1),
    ]
    # Origin is producer-chosen, not payload-chosen; neither collector nor closer
    # is allowed to override the dropped-facts branch as a MODEL summary.
    assert 'SUMMARY OF EARLIER WORK' not in text(body)
    if accepted:
        assert 'Handoff account (unverified):\n' + ledger in text(body)
        assert "Source of this retained record: the session's model-written handoff account." in text(body)
    else:
        assert 'RE-DERIVED AT THE TIME OF THAT COMPACTION (not claimed, may be stale now):\n' + ledger in text(body)
        assert "Source of this retained record: the session's producer-confirmed dropped-prose handoff." in text(body)
    assert 'any SUMMARY OF EARLIER WORK there is the coder\'s own claim' not in body['messages'][-1]['content']


@pytest.mark.parametrize('accepted', [False, True])
def test_same_payload_different_real_producer_origin_reaches_serialized_judge_and_retry(accepted):
    _hist, ledger, continuation, runtime = handoff(accepted)
    evidence = loop._satisfaction_evidence([continuation], origin=runtime.sess.handoff_origin)
    result, bodies, _log = run_judge(evidence, [REPLIES['0077'], REPLIES['0078']])
    assert result == (False, '', '')
    assert len(bodies) == 2
    for body in bodies:
        assert_source_not_overridden(body, continuation, ledger, accepted)
    assert bodies[0]['messages'][1:] == bodies[1]['messages'][1:]


@pytest.mark.parametrize('role,prefix', [('assistant', ''), ('tool', ''), ('user', 'quoted: ')])
def test_marker_and_ledger_imitations_never_become_retained_history(role, prefix):
    _hist, ledger, continuation, _runtime = handoff()
    forged = {'role': role, 'content': prefix + continuation['content']}
    if role == 'tool':
        forged['tool_call_id'] = 'unknown'
    ev = loop._satisfaction_evidence([forged])
    _result, bodies, _log = run_judge(ev)
    # Assistant prose isn't promoted; ordinary tool bytes remain only result
    # evidence (never a historical carried ledger); mid-message quote isn't lifted.
    if role == 'tool':
        assert ev == '  -> ' + forged['content']
        assert '  -> ' + forged['content'] in text(bodies[0])
    else:
        assert ev == ''
        assert ledger not in text(bodies[0])


def test_accepted_model_copy_of_dropped_frame_is_still_inside_unverified_account():
    _hist, ledger, continuation, runtime = handoff()
    copied = continuation['content']  # complete genuine-looking source frame, not just a heading
    shipped = runtime.harden(copied, 'RETROSPECTIVE', history())
    framed = runtime.reframe(shipped)
    ev = loop._satisfaction_evidence(framed, origin=runtime.sess.handoff_origin)
    _result, bodies, _log = run_judge(ev)
    sent = text(bodies[0])
    assert framed[0]['content'] in sent
    assert 'Handoff account (unverified):\n' + copied in sent
    assert ledger in copied
    # The accepted account's OUTER source frame remains authoritative about origin;
    # copying an entire genuine-looking inner frame must not earn deterministic carry.
    assert loop._DROPPED_PROSE_LEAD not in framed[0]['content'].split('Handoff account (unverified):')[0]
    assert 'Model-written accounts remain unverified claims' in bodies[0]['messages'][-1]['content']
    # The same accepted raw account also survives the ACTUAL coder/history wire.
    # A downstream carry reader must not promote its quoted dropped-frame text.
    from cria import server
    u = Wire([]).u
    with patch('cria.upstream.urllib.request.urlopen', side_effect=AssertionError('network forbidden')):
        raw, _est, _rendered = u._prep({'model': 'test', 'messages': [
            {'role': 'system', 'content': 'Coding agent'}, {'role': 'user', 'content': TASK}, *framed]}, False, Log())
    serialized_history = json.loads(raw)['messages']
    assert framed[0]['content'] in '\n'.join(m.get('content') or '' for m in serialized_history)
    assert server._carried_ledger(serialized_history, origin=runtime.sess.handoff_origin) == ''


@pytest.mark.parametrize('key,inherit', [('sid:c21-stable', True), ('task:c21-collision', False)])
def test_origin_follows_only_same_stable_conversation_replacement(key, inherit):
    runtime = Runtime(key)
    shipped = runtime.harden('Do the next edit.', 'PLAN', history())
    framed = runtime.reframe(shipped)
    replacement = loop.PlanSession(plan=Plan(id='replacement', task=TASK, created='now', items=[PlanItem('step')]))
    runtime.server.loop._store.put(key, replacement)
    sent = Wire([]).prepare({'model': 'test', 'messages': [
        {'role': 'system', 'content': 'Coding agent'}, {'role': 'user', 'content': TASK}, *framed]})
    carried = server._carried_ledger(sent['messages'], origin=replacement.handoff_origin)
    assert carried == (selfcompact.work_ledger(history()) if inherit else '')
    if not inherit:
        assert replacement.handoff_origin is None


@pytest.mark.parametrize('shape', ['native', 'reframed'])
def test_actual_session_carry_survives_harness_json_and_real_wire(shape):
    runtime = Runtime()
    hist = history()
    original = selfcompact.work_ledger(hist)
    shipped = runtime.harden('Do the next edit.', 'PLAN', hist)
    native = json.loads(json.dumps(stored(shipped)))
    messages = [native] if shape == 'native' else runtime.reframe(shipped)
    wire = Wire([]).prepare({'model': 'test', 'messages': [
        {'role': 'system', 'content': 'Coding agent'}, {'role': 'user', 'content': TASK}, *messages]})
    carried = server._carried_ledger(wire['messages'], origin=runtime.sess.handoff_origin)
    assert carried == original
    assert selfcompact.parse_ledger(carried) == selfcompact.parse_ledger(original)
    next_call = {'role': 'assistant', 'tool_calls': [call('next', 'exec_command', {'cmd': 'next command'})]}
    later = runtime.harden('Do another edit.', 'PLAN', [*wire['messages'], next_call])
    expected = selfcompact.parse_ledger(original) + [('issued (no result recorded; execution not established): next command', 1)]
    assert selfcompact.parse_ledger(later) == expected
    assert selfcompact.parse_ledger(runtime.sess.handoff_origin.ledger) == expected
    # The original unknown-execution statuses are never rewritten as success.
    assert 'confirmed written' in later and 'refused, not written' in later
    assert '- ran:' not in later


@pytest.mark.parametrize('listed_pairs', [1, 2])
def test_all_listed_pairs_withdrawn_by_real_floor_preserve_origin_and_next_actual_carry(listed_pairs):
    runtime = Runtime()
    pairs = []
    ids = {f'old-read-{i}' for i in range(listed_pairs)}
    for cid in sorted(ids):
        pairs.extend([{'role': 'assistant', 'tool_calls': [call(cid, 'read_file', {'path': 'worker.rb'})]},
                      {'role': 'tool', 'tool_call_id': cid, 'content': 'observed worker bytes\n'}])
    hist = [*history(), *pairs]
    original = selfcompact.work_ledger(hist)
    shipped = runtime.harden('Do the next edit.', 'PLAN', hist)
    reframed = runtime.reframe(shipped, retained=pairs)
    continuation = reframed[-1]
    assert all(f'call id: {cid}' in continuation['content'] for cid in ids)
    assert modelview._paired_ids(reframed) == ids

    # Real, incompressible intervening history makes the old pairs fall out of
    # the window. The newest, small continuation remains intact; no floor mock.
    rng = random.Random(837)
    older = [{'role': 'assistant', 'content': '\n'.join(
        f'observation {i}/{j}: {rng.getrandbits(256):064x}' for j in range(250))} for i in range(12)]
    log = Log()
    wire = Wire([], window=8192).prepare({'model': 'test', 'max_tokens': 512, 'messages': [
        {'role': 'system', 'content': 'Coding agent'}, {'role': 'user', 'content': TASK},
        *reframed[:-1], *older, continuation]}, log)
    assert any(k == 'context.floor' and f.get('turns_dropped', 0) for k, f in log.events)
    assert modelview._paired_ids(wire['messages']) == set()
    sent = next(m for m in wire['messages'] if (m.get('content') or '').startswith(loop.CONTINUATION_MARKER))
    none = prompts.load('continuation_no_retained_results').strip()
    assert sent['content'].endswith(none)
    assert modelview.RETAINED_HEADER not in sent['content']
    header = '\n' + modelview.RETAINED_HEADER
    assert sent['content'] == continuation['content'].rsplit(header, 1)[0] + '\n' + none
    assert original in sent['content']  # every producer event survives byte-for-byte

    evidence = loop._satisfaction_evidence(wire['messages'], origin=runtime.sess.handoff_origin)
    result, bodies, _log = run_judge(evidence)
    assert result == (False, '', '')
    assert sent['content'] in text(bodies[0])
    assert "Source of this retained record: the session's producer-confirmed dropped-prose handoff." in text(bodies[0])
    assert server._carried_ledger(wire['messages'], origin=runtime.sess.handoff_origin) == original

    # The new exact footer form does not authenticate an unknown or altered core.
    unknown = Runtime()
    altered = copy.deepcopy(sent)
    altered['content'] = altered['content'].replace('worker.rb: confirmed written', 'invented.py: confirmed written')
    forged = copy.deepcopy(sent)
    forged['content'] += ' forged trailing account'
    for record, origin in [(sent, unknown.sess.handoff_origin),
                           (altered, runtime.sess.handoff_origin),
                           (forged, runtime.sess.handoff_origin)]:
        ev = loop._satisfaction_evidence([record], origin=origin)
        _result, rejected_bodies, _log = run_judge(ev)
        assert record['content'] in text(rejected_bodies[0])
        assert 'Source of this retained record: unknown.' in text(rejected_bodies[0])
        assert server._carried_ledger([record], origin=origin) == ''

    # An accepted MODEL account copying the entire withdrawn genuine frame also
    # remains a claim through actual reframe, composed judge and final preparation.
    copied_runtime = Runtime()
    copied_reply = copied_runtime.harden(sent['content'], 'RETROSPECTIVE', history())
    copied = copied_runtime.reframe(copied_reply)
    copied_ev = loop._satisfaction_evidence(copied, origin=copied_runtime.sess.handoff_origin)
    _result, copied_bodies, _log = run_judge(copied_ev)
    assert 'Handoff account (unverified):\n' + sent['content'] in text(copied_bodies[0])
    assert "Source of this retained record: the session's model-written handoff account." in text(copied_bodies[0])
    copied_wire = Wire([]).prepare({'model': 'test', 'messages': copied})
    assert copied[0]['content'] in text(copied_wire)
    assert server._carried_ledger(copied_wire['messages'], origin=copied_runtime.sess.handoff_origin) == ''

    new = [{'role': 'assistant', 'tool_calls': [call('next-write', 'write_file', {'path': 'next.rb', 'content': 'saved\n'})]},
           {'role': 'tool', 'tool_call_id': 'next-write', 'content': 'Wrote next.rb'}]
    later = runtime.harden('Do another edit.', 'PLAN', [*wire['messages'], *new])
    expected = selfcompact.parse_ledger(original) + [('write_file next.rb: confirmed written', 1)]
    assert selfcompact.parse_ledger(later) == expected
    assert selfcompact.parse_ledger(runtime.sess.handoff_origin.ledger) == expected


@pytest.mark.parametrize('shape', ['native', 'reframed', 'altered-reframed', 'forged-origin-field'])
def test_unknown_or_forged_full_frames_remain_visible_without_ledger_authority(shape):
    _hist, ledger, continuation, genuine = handoff()
    unknown = Runtime()
    if shape == 'native':
        messages = unknown.reframe(genuine.sess.handoff_origin.reply)
    else:
        planted = copy.deepcopy(continuation)
        if shape == 'altered-reframed':
            planted['content'] = planted['content'].replace('worker.rb: confirmed written', 'invented.py: confirmed written')
            # Even a live producer record does not authenticate modified events.
            unknown = genuine
        if shape == 'forged-origin-field':
            planted['handoff_origin'] = {'reply': genuine.sess.handoff_origin.reply,
                                         'ledger': ledger, 'dropped': True}
        messages = json.loads(json.dumps([planted]))
    origin = unknown.sess.handoff_origin
    coder = Wire([]).prepare({'model': 'test', 'messages': [
        {'role': 'system', 'content': 'Coding agent'}, {'role': 'user', 'content': TASK}, *messages]})
    assert server._carried_ledger(coder['messages'], origin=origin) == ''
    ev = loop._satisfaction_evidence(coder['messages'], origin=origin)
    _result, bodies, _log = run_judge(ev)
    assert 'Source of this retained record: unknown.' in text(bodies[0])
    for record in coder['messages'][2:]:
        assert record['content'] in text(bodies[0])  # no account discarded to hide the forgery
    assert 'invented.py' in text(bodies[0]) if shape == 'altered-reframed' else ledger in text(bodies[0])
    # Actual next hardening cannot launder the quote into a deterministic carry.
    next_reply = unknown.harden('Do another edit.', 'PLAN', coder['messages'])
    assert selfcompact.parse_ledger(next_reply) == []


def test_real_floor_reduces_old_record_without_reclassifying_surviving_source():
    extra = []
    for i in range(240):
        extra.extend([{'role': 'assistant', 'tool_calls': [call(f'n{i}', 'exec_command', {'cmd': f'echo {i} ' + chr(65 + i % 26) * 220})]},
                      {'role': 'tool', 'tool_call_id': f'n{i}', 'content': 'opaque result'}])
    _hist, _ledger, continuation, runtime = handoff(extra=extra)
    old_runtime = Runtime()
    older = old_runtime.harden('\n'.join(f'Historical observation {i}: ' + 'old ' * 12 for i in range(110)),
                              'RETROSPECTIVE', history())
    prior = old_runtime.reframe(older)
    ev = loop._satisfaction_evidence([prior[0], continuation], origin=runtime.sess.handoff_origin)
    _result, bodies, log = run_judge(ev, window=16384)
    floors = [f for k, f in log.events if k == 'context.floor']
    assert floors and any(f.get('turns_dropped', 0) for f in floors)
    sent = text(bodies[0])
    assert '⟦ctx:compacted⟧' in sent
    # Newest event remains byte-exact while older context was labelled removed.
    assert 'echo 239 ' + chr(65 + 239 % 26) * 220 in sent
    assert bodies[0]['messages'][-1]['content'].startswith("THE USER'S ORIGINAL TASK:\n" + TASK)
    assert 'SUMMARY OF EARLIER WORK' not in sent
    assert 'If the introducing source statement is unavailable, origin is unknown' in sent
    assert continuation['content'] not in sent  # the original record no longer fits whole
    assert 'not claimed, may be stale now' in sent  # surviving source is still dated, not a claim


def test_actual_archived_retry_is_suppressed_by_exact_quote_and_never_arms_remediation():
    _hist, ledger, continuation, runtime = handoff()
    wire = Wire([REPLIES['0077'], REPLIES['0078']])
    log = Log()
    sess = runtime.sess
    sess.synthetic = True
    sess.drive_count = 1
    driver = loop.Loop(loop.LoopContext(None, None, wire, reasoner_role=Role(name='reasoner', backend='local'),
                                       satisfaction_check_start=1, satisfaction_check_every=1))
    result = driver._periodic_satisfaction(sess, {'messages': [continuation], 'tools': []}, log,
                                            plan_off=True, blocked=False)
    assert result is None and sess.latest_satisfaction is False
    assert sess.nudge_reason == '' and not sess.completion_remediation_subject
    assert len(wire.bodies) == 2  # no required-output/semantic question
    assert ('loop.negative_diagnosis_suppressed', {'level': 'info', 'phase': 'satisfaction-retry-diagnosis',
            'cause': 'task quote is not exact', 'diagnosis_kind': 'failed_check',
            'assist_id': completiondiagnosis.DEFINITION.policy.id,
            'family_id': completiondiagnosis.DEFINITION.policy.family_id}) in log.events
    for body in wire.bodies:
        assert_source_not_overridden(body, continuation, ledger, False)


def test_archived_retry_with_only_quote_corrected_still_fails_source_contract():
    diagnosis = json.loads(REPLIES['0078'])
    diagnosis['task_quote'] = 'Handle malformed input safely: blank quantities, currency symbols in prices, missing columns, and quoted descriptions containing commas.'
    wire = Wire([json.dumps(diagnosis)])
    log = Log()
    result = loop.judge_satisfaction(TASK, 'record', wire, Role(name='reasoner', backend='local'), log)
    assert result == (False, '', '')
    assert len(wire.bodies) == 1
    assert any(k == 'loop.negative_diagnosis_suppressed' and f['cause'] == 'failed-check source contract'
               for k, f in log.events)


def test_proper_missing_output_uses_original_root_and_arms_only_exact_path():
    v = wsview.View(ROOT)
    assert wsview.apply_survey(v, survey('F\t1\t4\tworker.rb', root=ROOT))
    v.note_written('worker.rb', 'one\n')
    token = wsview.bind(v)
    obj = {'satisfied': False, 'diagnosis_kind': 'missing_file', 'subject': 'REVIEW.md',
           'task_quote': 'invented initial quote', 'evidence_source': 'workspace_absence',
           'evidence_quote': '', 'reason': 'untrusted essay', 'proposed_fix': 'untrusted command'}
    wire = Wire([json.dumps(obj), json.dumps({'required_output': True, 'subject': 'REVIEW.md',
                                             'task_quote': OUTPUT_SPAN})])
    log = Log()
    sess = loop.PlanSession(plan=Plan(id='c21-positive', task=TASK, created='now',
                                     items=[PlanItem('Generated task: read REVIEW.md as an input.')]),
                            workspace_root=ROOT)
    sess.drive_count = 1
    driver = loop.Loop(loop.LoopContext(None, None, wire, reasoner_role=Role(name='reasoner', backend='local'),
                                       satisfaction_check_start=1, satisfaction_check_every=1))
    try:
        driver._periodic_satisfaction(sess, {'messages': [{'role': 'user', 'content': 'Generated claim'}],
                                            'tools': []}, log, plan_off=False, blocked=False)
    finally:
        wsview.unbind(token)
    assert sess.latest_satisfaction is False
    assert sess.completion_remediation_subject == 'REVIEW.md'
    assert OUTPUT_SPAN in sess.nudge_reason
    assert 'untrusted' not in sess.nudge_reason
    assert len(wire.bodies) == 2
    assert TASK in text(wire.bodies[1])
    assert 'Generated task:' not in text(wire.bodies[1])
    assert obj['proposed_fix'] not in text(wire.bodies[1])


@pytest.mark.parametrize('surveyed,requested_root', [(False, ROOT), (True, ROOT), (True, '/unobserved-workspace')])
def test_capability_framing_is_conditional_on_real_menu_not_root(surveyed, requested_root):
    v = wsview.View(ROOT)
    if surveyed:
        assert wsview.apply_survey(v, survey('F\t1\t4\tworker.rb', root=ROOT))
        v.note_written('worker.rb', 'one\n')
    token = wsview.bind(v)
    try:
        _result, bodies, _log = run_judge('record', root=requested_root)
    finally:
        wsview.unbind(token)
    body = bodies[0]
    names = {(t.get('function') or {}).get('name') for t in body.get('tools', [])}
    assert names == ({'list_dir', 'read_file', 'verdict'} if surveyed and requested_root == ROOT else set())
    assert 'If `list_dir` and `read_file` are offered in this request' in body['messages'][0]['content']
    assert 'what the log and your two read-only tools actually show' not in body['messages'][0]['content']
    assert 'Only tools present in this request\'s tool menu are available' in body['messages'][0]['content']


def test_retry_and_forced_inspection_closure_do_not_inherit_a_positive_menu_claim():
    v = wsview.View(ROOT)
    assert wsview.apply_survey(v, survey('F\t1\t4\tworker.rb', root=ROOT))
    v.note_written('worker.rb', 'one\n')
    token = wsview.bind(v)
    try:
        wire = Wire([REPLIES['0077'], REPLIES['0078']])
        log = Log()
        loop.judge_satisfaction(TASK, 'record', wire, None, log, workspace_root=ROOT)
    finally:
        wsview.unbind(token)
    assert wire.bodies[0].get('tools')
    assert not wire.bodies[1].get('tools')
    assert 'Only tools present in this request\'s tool menu are available' in text(wire.bodies[1])

    # Shared loop's actual round-cap branch: tool exists initially, then is withdrawn.
    wire = Wire(['<tool_call>{"name":"read_file","arguments":{"path":"worker.rb"}}</tool_call>',
                 json.dumps({'satisfied': False})])
    token = wsview.bind(v)
    try:
        with patch.object(loop.verifytools, 'VERIFY_MAX_ROUNDS', 0):
            loop._judge_completion(wire, None, prompts.load('satisfaction'), 'judge', Log(),
                                   phase='test', workspace_root=ROOT, verdict_key='satisfied')
    finally:
        wsview.unbind(token)
    assert all(not b.get('tools') for b in wire.bodies)
    assert all('Only tools present in this request\'s tool menu are available' in text(b) for b in wire.bodies)
