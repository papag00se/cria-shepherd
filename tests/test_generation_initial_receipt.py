"""Initial delivered text must authorize paste provenance before later reply settlement."""
import copy
from dataclasses import replace
import io
import json

import pytest
from cria import assistruntime, bodykeys, generationguards as guards
from cria.config import Role
from cria.upstream import Upstream
from tests import test_text_write_recovery as tw
from tests.test_loop import _single_loop, _synth


@pytest.mark.parametrize('retry', [False, True])
def test_actual_paste_check_gets_initial_wire_credit_then_final_reply_replaces_it(retry):
    holder = tw.TextWriteTests('test_the_a1_pasted_class_becomes_that_files_write_and_the_pom_excerpt_never_does')
    holder.setUp()
    try:
        content, tools, finish = tw._reply('a1_0022')
        posts, checked = [], []
        def send(request, **options):
            if not request.full_url.endswith('/v1/chat/completions'):
                return io.BytesIO(b'{}')
            posts.append(json.loads(request.data))
            message = ({'role': 'assistant', 'content': content} if len(posts) == 1 else
                       {'role': 'assistant', 'tool_calls': [{'id': 'final', 'type': 'function', 'function': {
                           'name': 'read_file', 'arguments': '{"path":"pom.xml"}'}}]})
            return io.BytesIO(json.dumps({'choices': [{'finish_reason': finish if len(posts) == 1 else 'tool_calls',
                                                     'message': message}]}).encode())
        up = Upstream('http://offline.invalid', context_window=32768, open_request=send)
        def judge(body, log):
            # Auxiliary calls must not remove authenticated initial coder credit.
            log.restored_on_wire = {'aux-only': 'not-coder'}
            return b'{"choices":[{"message":{"content":"WHOLE_FILE"}}]}'
        driver = _single_loop(up.chat, reasoner_chat=judge,
            reasoner_role=Role(name='reasoner', backend='local'), workspace_root=tw.ROOT)
        def execute(source, services, grounding):
            checked.append(source.completion)
            names = [tc['function']['name'] for c in source.completion['choices']
                     for tc in c['message'].get('tool_calls', [])]
            assert any(name in ('write_file', 'write', 'Write') for name in names)
            completion = source.completion
            if retry:
                changed = copy.deepcopy(source.body)
                changed['messages'] = [m for m in changed['messages'] if not m.get(bodykeys.RESTORED_FILES)]
                completion = services.retry(changed, changed.get('tools'))
            return guards.RecoveryResult(completion, guards.RecoveryStatus.RECOVERED)
        definition = replace(guards.RUNAWAY, execute=execute)
        runtime = assistruntime.AssistRuntime.select(level=5)
        driver._ctx.pilot_runtime = replace(runtime, ordered_stages=tuple(
            definition if d.policy.id == definition.policy.id else d for d in runtime.ordered_stages))
        session = _synth()
        session.plan.task, session.workspace_root = tw.TASK, tw.ROOT
        offered = {tw.JAVA: 'authenticated-wire-sha'}
        framed = {'tools': tools, 'messages': [{'role': 'user', 'content': 'whole original source text',
                      bodykeys.RESTORED_FILES: {'offered': offered}}]}
        with assistruntime.bound(driver._ctx.pilot_runtime):
            driver._coder_turn(session, framed, {'messages': []}, step=1, rlog=tw._Log())
        assert checked
        assert session.restored_current == ({} if retry else offered)
        assert 'whole original source text' in json.dumps(posts[0])
        if retry:
            assert 'whole original source text' not in json.dumps(posts[1])
    finally:
        holder.doCleanups()
