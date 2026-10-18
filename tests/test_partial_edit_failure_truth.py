"""Failed target mutations cannot be represented as pre-write refusals."""
import io
import json
from types import SimpleNamespace

import pytest
from cria import assistruntime, denial, loop, writeproxy, wsview
from test_generation_driver_policy import setup_driver
from test_loop import _Rlog
from test_executor_resource_ownership import execute, instrument
from test_writeproxy import _call, _CMD_SHELL, _history_from, _lowered_cmd
from wsfixture import survey


@pytest.fixture(params=['hardlink_edit', 'atomic_edit', 'atomic_write'])
def failure(tmp_path, monkeypatch, request):
    workspace, scratch = tmp_path / 'workspace', tmp_path / 'scratch'
    workspace.mkdir(); scratch.mkdir()
    target, alias = workspace / 'a.txt', workspace / 'b.txt'
    old, new = 'old content\n' * 80, 'updated content\n' * 80
    target.write_text(old)
    if request.param == 'hardlink_edit':
        alias.hardlink_to(target)
    else:
        alias.write_text(old)
    (workspace / 'c.txt').write_text('unrelated cached body')
    session = str(tmp_path)
    view = wsview.View(str(workspace), session)
    assert wsview.apply_survey(view, survey(
        f'F\t1\t{len(old)}\ta.txt\nF\t1\t{len(old)}\tb.txt\nF\t1\t21\tc.txt', root=str(workspace)))
    view.note_read('a.txt', old)
    view.note_read('b.txt', old)
    view.note_read('c.txt', 'unrelated cached body')
    monkeypatch.setitem(writeproxy._SURVEY_SEQ, session, 0)
    fault = '''import io, os, errno
_original_open=io.open
class _FailingWriter:
    def __init__(self, stream): self.stream=stream
    def __getattr__(self, name): return getattr(self.stream, name)
    def __enter__(self): self.stream.__enter__(); return self
    def __exit__(self,*args): return self.stream.__exit__(*args)
    def write(self, data):
        self.stream.write(data[:17]); self.stream.flush()
        raise OSError(errno.ENOSPC,'injected after truncate and actual prefix write')
def _fault_open(file, mode='r', *args, **kwargs):
    stream=_original_open(file,mode,*args,**kwargs)
    if not isinstance(file,int) and os.path.realpath(os.fspath(file))==os.path.realpath('a.txt') and ('w' in mode or '+' in mode):
        return _FailingWriter(stream)
    return stream
io.open=_fault_open
'''
    if request.param != 'hardlink_edit':
        fault = '''import os, errno
_original_replace=os.replace
def _uncertain_replace(*args, **kwargs):
    _original_replace(*args, **kwargs)
    raise OSError(errno.EIO,'injected after actual atomic replacement')
os.replace=_uncertain_replace
'''
    token = wsview.bind(view)
    runtime = assistruntime.AssistRuntime.select(level=5, profile='rank4-ablation')
    try:
        with assistruntime.bound(runtime):
            name = 'write_file' if request.param == 'atomic_write' else 'edit_file'
            arguments = ({'path': 'a.txt', 'content': new} if name == 'write_file' else
                         {'path': 'a.txt', 'old_string': old, 'new_string': new})
            completion = writeproxy.translate_outbound(_call(name, arguments),
                _CMD_SHELL, injected={name}, session=session, workspace_root=str(workspace))
            command = instrument(_lowered_cmd(completion), fault)
            call = completion['choices'][0]['message']['tool_calls'][0]
            args = json.loads(call['function']['arguments']); args['cmd'] = command
            call['function']['arguments'] = json.dumps(args)
            result = execute(command, workspace, scratch)
            # Faults happen AFTER actual target writes, never a mocked pre-write refusal.
            if request.param == 'hardlink_edit':
                assert target.read_text() == alias.read_text() == new[:17]
                assert target.stat().st_nlink == 2
            else:
                assert target.read_text() == new
                assert alias.read_text() == old
            history = _history_from(completion) + [{'role': 'tool', 'tool_call_id': 'c1',
                'content': f'Process exited with code {result.returncode}\nOutput:\n' + result.stdout + result.stderr}]
            represented = writeproxy.represent_inbound(history, workspace_root=str(workspace), sess_key=session)
    finally:
        wsview.unbind(token)
    return SimpleNamespace(native=result.stdout+result.stderr, history=history, represented=represented,
                           view=view, workspace=workspace, session=session, old=old)


def test_partial_failure_does_not_claim_that_the_edit_never_ran(failure):
    assert not denial.is_denied(failure.native)
    assert writeproxy.EDIT_MUTATION_UNKNOWN in failure.native
    assert 'Nothing was changed' not in failure.native
    assert not writeproxy._failed_edit_ids(failure.history)


def test_partial_failure_invalidates_target_and_unresolved_alias_facts(failure):
    assert failure.view.read_bytes('a.txt') is None
    assert failure.view.read_bytes('b.txt') is None
    assert failure.view.may_have_changed
    # A later request cannot re-promote a same-sized prior cache as current.
    next_view = wsview.View(str(failure.workspace), failure.session)
    assert wsview.apply_survey(next_view, survey(
        f'F\t1\t{len(failure.old)}\ta.txt\nF\t1\t{len(failure.old)}\tb.txt', root=str(failure.workspace)))
    assert next_view.read_bytes('a.txt') is None
    assert next_view.read_bytes('b.txt') is None


def test_next_actual_coder_post_cannot_recredit_the_old_cached_body(failure, monkeypatch):
    driver, session, body = setup_driver()
    session.workspace_root = str(failure.workspace)
    session.read_files = {'a.txt': (len(failure.old), '80 lines'), 'b.txt': (len(failure.old), '80 lines')}
    session.restored_current = {'a.txt': 'prior-call-credit'}
    body['messages'] += failure.represented
    driver._ctx.pilot_runtime = assistruntime.AssistRuntime.select(level=5, profile='rank4-ablation')
    posts = []
    def send(request, **options):
        if not request.full_url.endswith('/v1/chat/completions'):
            return io.BytesIO(b'{"tokens":[1],"data":[]}')
        posts.append(json.loads(request.data))
        return io.BytesIO(json.dumps(loop._completion_toolcalls([{'id': 'next', 'type': 'function',
            'function': {'name': 'read_file', 'arguments': '{"path":"next.txt"}'}}])).encode())
    monkeypatch.setattr(driver._ctx.coder_chat.__self__, '_receive_open', send)
    token = wsview.bind(failure.view)
    try:
        driver.drive(body, 'driver-fixture', None, _Rlog())
    finally:
        wsview.unbind(token)
    assert len(posts) == 1
    assert session.restored_current == {}
    restored = [m['content'] for m in posts[0]['messages'] if str(m.get('content')).startswith('⟦ctx:current⟧')]
    assert all(failure.old not in text for text in restored)


def test_partial_failure_cannot_label_the_proposed_bytes_as_never_on_disk(failure):
    text = json.dumps(failure.represented, ensure_ascii=False)
    assert '⟦ctx:rejected-candidate⟧' not in text
    assert 'these bytes never reached disk' not in text
