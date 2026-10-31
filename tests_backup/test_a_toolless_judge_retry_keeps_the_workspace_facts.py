"""1792381177/0057→0058: withdrawing tools erased current harness file bytes.

The same question must not fall back from current source to a condensed old read.
These checks inspect actual serialized requests, not a mocked evidence renderer.
"""
import io
import json

import pytest

from cria import assistruntime, loop, wsview
from cria.config import Role
from cria.upstream import Upstream
from test_executable_assist_pilots import Log
from test_whole_task_review_boundaries import driver_fixture


CURRENT = 'native_body_value = "after-write"\n'
HISTORY = 'Earlier source observation: native_body_value = "before-write"\n'


def transport(monkeypatch, upstream, *, cut_first=True, approving=False, flag='satisfied'):
    posts = []
    def receive(request, **options):
        if not request.full_url.endswith('/v1/chat/completions'):
            return io.BytesIO(b'{"tokens":[1],"data":[]}')
        body = json.loads(request.data)
        posts.append(body)
        cut = cut_first and len(posts) == 1
        answer = json.dumps({flag: approving, 'reason': '', 'proposed_fix': ''})
        reply = {'choices': [{'finish_reason': 'length' if cut else 'stop',
                 'message': {'content': None if cut else answer}}]}
        return io.BytesIO(json.dumps(reply).encode())
    monkeypatch.setattr(upstream, '_receive_open', receive)
    return posts


def assert_same_facts_without_inspection(posts):
    # Other real-driver seats (e.g. the missing-deliverable observer) are distinct
    # questions, not retries of this judge. Inspect exactly the judge's two POSTs.
    posts = [post for post in posts if any('You are a JUDGE, not the coder.' in
             str(message.get('content') or '') for message in post['messages'][:1])]
    assert len(posts) == 2
    assert posts[0].get('tools') and not posts[1].get('tools')
    for post in posts:
        assert CURRENT in '\n'.join(m.get('content') or '' for m in post['messages'])
    assert posts[0]['messages'][1:] == posts[1]['messages'][1:]
    assert posts[1].get('chat_template_kwargs', {}).get('enable_thinking') is False


@pytest.mark.parametrize('approving', [False, True])
def test_whole_task_retry_preserves_current_files_in_final_post(tmp_path, monkeypatch, approving):
    (tmp_path / 'source.txt').write_text(CURRENT)
    upstream = Upstream('http://fixture', context_window=49152, capture_dir=None, capture_rendered=False)
    posts = transport(monkeypatch, upstream, approving=approving)
    role = Role(name='reasoner', backend='local', reasoning='on')
    runtime = assistruntime.AssistRuntime.select(level=5, profile='rank4-ablation')
    token = wsview.bind(wsview.DirectView(str(tmp_path)))
    try:
        with assistruntime.bound(runtime):
            result = loop.judge_satisfaction('Finish the requested artifact.', HISTORY,
                upstream.chat, role, Log(), workspace_root=str(tmp_path))
    finally:
        wsview.unbind(token)
    assert result[0] is False
    assert_same_facts_without_inspection(posts)
    assert (tmp_path / 'source.txt').read_text() == CURRENT


@pytest.mark.parametrize('synthetic', [True, False])
def test_real_driver_retry_preserves_current_files_in_final_post(tmp_path, monkeypatch, synthetic):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'source.txt').write_text(CURRENT)
    upstream = Upstream('http://fixture', context_window=49152, capture_dir=None, capture_rendered=False)
    posts = transport(monkeypatch, upstream)
    action = loop._completion_toolcalls([{'id': 'acting', 'type': 'function', 'function': {
        'name': 'write_file', 'arguments': '{"path":"artifact.txt","content":"work"}'}}])
    driver, session, body, frames = driver_fixture(synthetic=synthetic, scheduled=True,
        reasoner=upstream.chat, shell=False, coder=lambda *_: json.dumps(action).encode())
    driver._ctx.pilot_runtime = assistruntime.AssistRuntime.select(level=5, profile='rank4-ablation')
    session.workspace_root = str(tmp_path)
    body['messages'] += [{'role': 'assistant', 'content': HISTORY}]
    token = wsview.bind(wsview.DirectView(str(tmp_path)))
    try:
        driver.drive(body, 'sid:review', None, Log())
    finally:
        wsview.unbind(token)
    assert_same_facts_without_inspection(posts)
    assert session.latest_satisfaction is False and not session.plan.items[0].done
    assert frames and (tmp_path / 'source.txt').read_text() == CURRENT


@pytest.mark.parametrize('flag', ['done', 'satisfied'])
def test_shared_critic_retains_facts_but_withdraws_tools(tmp_path, monkeypatch, flag):
    (tmp_path / 'source.txt').write_text(CURRENT)
    upstream = Upstream('http://fixture', context_window=49152, capture_dir=None, capture_rendered=False)
    posts = transport(monkeypatch, upstream, cut_first=False, flag=flag)
    token = wsview.bind(wsview.DirectView(str(tmp_path)))
    try:
        obj, _ = loop._critic_verdict('Judge the supplied work.', 'Original question.',
            upstream.chat, Role(name='reasoner', backend='local', reasoning='on'), Log(),
            reasoning_off=True, workspace_root=str(tmp_path),
            verdict_key=flag if flag == 'satisfied' else '', evidence_blocks=[HISTORY])
    finally:
        wsview.unbind(token)
    assert obj[flag] is False and len(posts) == 1
    assert not posts[0].get('tools')
    assert CURRENT in '\n'.join(m.get('content') or '' for m in posts[0]['messages'])
    assert posts[0]['messages'][-1]['content'] == 'Original question.'


def test_unavailable_body_stays_named_on_retry_without_a_tool_grant(tmp_path, monkeypatch):
    (tmp_path / 'source.txt').write_text(CURRENT)
    (tmp_path / 'unavailable.txt').write_text('never delivered to the workspace view')
    class PartialView(wsview.DirectView):
        def read(self, path):
            return None if str(path).endswith('unavailable.txt') else super().read(path)
    upstream = Upstream('http://fixture', context_window=49152, capture_dir=None, capture_rendered=False)
    posts = transport(monkeypatch, upstream)
    token = wsview.bind(PartialView(str(tmp_path)))
    try:
        with assistruntime.bound(assistruntime.AssistRuntime.select(level=5, profile='rank4-ablation')):
            result = loop.judge_satisfaction('Finish the requested artifact.', HISTORY,
                upstream.chat, Role(name='reasoner', backend='local', reasoning='on'), Log(),
                workspace_root=str(tmp_path))
    finally:
        wsview.unbind(token)
    assert result[0] is False
    assert_same_facts_without_inspection(posts)
    text = '\n'.join(m.get('content') or '' for m in posts[1]['messages'])
    assert 'unavailable.txt' in text and 'never delivered to the workspace view' not in text
    assert 'NOT evidence any is absent or empty' in text
    assert 'if read_file is offered in this request' in text


@pytest.mark.parametrize('root_present', [False, True])
def test_unsurveyed_or_missing_workspace_does_not_invent_facts_or_tools(tmp_path, monkeypatch, root_present):
    upstream = Upstream('http://fixture', context_window=49152, capture_dir=None, capture_rendered=False)
    posts = transport(monkeypatch, upstream, cut_first=False)
    root = str(tmp_path) if root_present else ''
    token = wsview.bind(wsview.View(root))
    try:
        with assistruntime.bound(assistruntime.AssistRuntime.select(level=5, profile='rank4-ablation')):
            result = loop.judge_satisfaction('Finish the requested artifact.', HISTORY,
                upstream.chat, Role(name='reasoner', backend='local', reasoning='on'), Log(),
                workspace_root=root)
    finally:
        wsview.unbind(token)
    assert result[0] is False and len(posts) == 1
    assert not posts[0].get('tools')
    text = '\n'.join(m.get('content') or '' for m in posts[0]['messages'])
    assert 'THE COMPLETE CONTENTS' not in text and CURRENT not in text
    assert HISTORY.strip() in text
