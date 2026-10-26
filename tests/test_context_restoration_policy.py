"""Offline parity and lifecycle checks for the extracted current-text producer."""
import hashlib
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from cria import bodykeys, contextrestoration as policy, filecommands, loop, modelview, prompts


class View:
    surveyed = True
    may_have_changed = False

    def __init__(self, bodies):
        self.bodies = bodies
        self.requests = []

    def isfile(self, path):
        return True if path in self.bodies else None

    def request_current_body(self, path):
        self.requests.append(path)

    def read_bytes(self, path):
        body = self.bodies.get(path)
        if body is None:
            self.request_current_body(path)
        return body

    def files(self):
        return [SimpleNamespace(path=p, mtime=i) for i, p in enumerate(self.bodies)]

    def rel(self, path):
        return path


def history(**changes):
    values = dict(ledger_paths=('a.py',), written_paths=(), whole_reads=(), whole_writes=(),
                  key=lambda p: p.removeprefix('/ws/'), touch={})
    return policy.FileHistory(**(values | changes))


CURRENT_HEADER = ('⟦ctx:current⟧ WORKSPACE TEXT OF FILES YOU READ OR WROTE EARLIER — each file shown here exactly as '
                  'the workspace last reported it (taken from the workspace, not remembered or summarized). '
                  'This block does not establish whether other copies are in the conversation. '
                  'Anchor any edit on file text, not on memory:')
BARE_HEADER = ('⟦ctx:current⟧ FILES YOU READ OR WROTE EARLIER — THIS BLOCK CARRIES NO TEXT FOR THEM; '
               'IT DOES NOT ESTABLISH WHETHER OTHER COPIES ARE IN THE CONVERSATION:')


@pytest.mark.parametrize('changed', [False, True])
def test_render_source_parity(changed):
    """Frozen wire/body oracle: a legacy adapter may delegate to this very source."""
    bodies = {'a.py': b'print("literal")\n', 'missing': None,
              'large': b'x' * 33, 'binary': b'\0' * 20}
    view = View(bodies)
    view.may_have_changed = changed
    with patch.object(filecommands, 'READ_INLINE_MAX', 32):
        actual = policy.render(view, sorted(bodies), {'a.py': 20})
    if changed:
        expected = (BARE_HEADER + '\nNOT AVAILABLE HERE — a.py, binary, large, missing. '
                    'This block holds no current workspace text for these files. Other conversation copies '
                    'are not assessed here. Base edits on file text, not memory; if you have no usable copy, '
                    'read_file it (in line ranges if it is large).', {}, ['a.py', 'binary', 'large', 'missing'])
        assert view.requests == ['a.py', 'binary', 'large', 'missing']
    else:
        expected = (CURRENT_HEADER + '\n----- a.py -----\nprint("literal")\n\n'
                    'NOT SHOWN HERE — large (33 bytes). Each is larger than one read returns, or would pass '
                    'the 32 bytes this block carries; read_file it (in line ranges if it is large) or grep '
                    'for what you need.\nNOT AVAILABLE HERE — missing. This block holds no current workspace '
                    'text for these files. Other conversation copies are not assessed here. Base edits on '
                    'file text, not memory; if you have no usable copy, read_file it (in line ranges if it is large).',
                    {'a.py': hashlib.sha1(b'print("literal")\n').hexdigest()}, ['a.py', 'large', 'missing'])
        assert view.requests == ['missing']
    assert actual == expected


def test_restoration_uses_canonical_binary_admission_for_short_control_text():
    """A control character alone does not make valid short workspace text binary."""
    view = View({'short.txt': b'\0\0'})
    assert policy.render(view, ['short.txt'], {}) == (
        CURRENT_HEADER + '\n----- short.txt -----\n\x00\x00',
        {'short.txt': hashlib.sha1(b'\0\0').hexdigest()}, ['short.txt'])
    assert view.requests == []


def test_producer_source_parity_and_history_authority():
    view = View({'a.py': b'one\ntwo\n', 'b.py': b'b\n', 'c.py': b'c\n'})
    facts = history(ledger_paths=('/ws/a.py', 'b.py'), written_paths=('c.py',),
                    whole_reads=('b.py',), whole_writes=('c.py',))
    result = policy.restore(policy.RestoreInput(lambda: view, lambda: facts))
    sess = SimpleNamespace(workspace_root='/ws', written_files={'c.py': 1}, file_touch={})
    with patch.object(loop.wsview, 'current', return_value=view), \
         patch.object(loop, '_ledger_state', return_value=({'/ws/a.py': {}, 'b.py': {}}, [], facts.key)), \
         patch.object(loop, '_extract_whole_reads', return_value=['b.py']), \
         patch.object(loop, '_write_events_paths', return_value=[(0, 'id', 'c.py')]):
        assert (result.message, result.offered) == loop._restored_text_message(sess, [])
    expected_hash = hashlib.sha1(b'one\ntwo\n').hexdigest()
    assert result.offered == {'a.py': expected_hash}
    assert result.named == ('a.py',)
    assert result.message == {'role': 'user', 'content': CURRENT_HEADER + '\n----- a.py -----\none\ntwo\n',
        bodykeys.RESTORED_FILES: {'offered': {'a.py': expected_hash}, 'named': ['a.py'],
            'content_sha256': hashlib.sha256((CURRENT_HEADER + '\n----- a.py -----\none\ntwo\n').encode()).hexdigest()}}


def test_disabled_and_unsurveyed_do_not_gather_or_demand():
    workspace, facts = Mock(side_effect=AssertionError), Mock(side_effect=AssertionError)
    assert policy.restore(policy.RestoreInput(workspace, facts), enabled=False).message is None
    workspace.assert_not_called()
    facts.assert_not_called()
    view = View({'a.py': None})
    view.surveyed = False
    assert policy.restore(policy.RestoreInput(lambda: view, facts)).message is None
    facts.assert_not_called()
    assert view.requests == []


def test_mutation_invalidates_bytes_and_retry_restores_new_body():
    view = View({'a.py': b'old\n'})
    view.may_have_changed = True
    source = policy.RestoreInput(lambda: view, history)
    withheld = policy.restore(source)
    assert withheld.offered == {}
    assert withheld.named == ('a.py',)
    assert 'old\n' not in withheld.message['content']
    assert view.requests == ['a.py']
    view.bodies['a.py'] = b'new exact\r\n'
    view.may_have_changed = False
    result = policy.restore(source)
    assert 'new exact\r\n' in result.message['content']
    assert result.offered == {'a.py': hashlib.sha1(b'new exact\r\n').hexdigest()}


def test_missing_unreadable_unknown_and_budget_never_invent_read_credit():
    view = View({'a.py': None, 'large': b'x' * (filecommands.READ_INLINE_MAX + 1)})
    result = policy.restore(policy.RestoreInput(lambda: view, lambda: history(
        ledger_paths=('a.py', 'large', 'unknown'))))
    assert result.offered == {}
    assert set(result.named) == {'a.py', 'large'}
    assert view.requests == ['a.py']
    assert 'unknown' not in result.message['content']


def test_context_loss_credit_and_session_isolation():
    view = View({'a.py': b'body\n'})
    result = policy.restore(policy.RestoreInput(lambda: view, history))
    first, other = policy.ReadCredit({}), policy.ReadCredit({'other': 'hash'})
    label = prompts.load_map('fetched_facts_sections')['read_restored']
    anchor = {'role': 'user', 'content': label}
    sent = policy.settle_wire(modelview.DeliveryInput([result.message, anchor], result.offered))
    first.settle(sent.delivered)
    assert first.current == result.offered
    first.begin()  # failed/aborted next call cannot retain an earlier delivery
    assert first.current == {}
    reduced = policy.settle_wire(modelview.DeliveryInput([anchor], result.offered))
    first.settle(reduced.delivered)
    assert first.current == {}
    assert other.current == {'other': 'hash'}
    assert label not in reduced.messages[0]['content']
    assert policy.restore(policy.RestoreInput(lambda: view, lambda: history(whole_reads=('a.py',)))).message is None
    # Once the actual read disappears from history it becomes a candidate again.
    assert policy.restore(policy.RestoreInput(lambda: view, history)).offered == result.offered


def test_selection_replacement_needs_no_original_driver_policy():
    source = policy.RestoreInput(Mock(side_effect=AssertionError), Mock(side_effect=AssertionError))
    replacement = SimpleNamespace(execute=lambda source: policy.RestoreResult(None, {'replacement': 'hash'}))
    assert replacement.execute(source).offered == {'replacement': 'hash'}
    assert policy.DEFINITION.execute(source, enabled=False).offered == {}


def test_real_history_parsers_preserve_refused_unknown_reads_and_totals():
    import json
    from cria import denial, wsview
    from tests.wsfixture import survey
    view = wsview.View('/ws', 'policy-history')
    assert wsview.apply_survey(view, survey('F\t1\t5\ta.py', root='/ws'))
    view.note_written('/ws/a.py', 'body\n')
    sess = SimpleNamespace(workspace_root='/ws', read_files={'a.py': (5, '1 lines')},
                           written_files={}, file_touch={}, read_ledger_seen=set())
    call = {'role': 'assistant', 'tool_calls': [{'id': 'r', 'type': 'function',
            'function': {'name': 'read_file', 'arguments': json.dumps({'path': 'a.py'})}}]}
    original_totals = dict(sess.read_files)
    for messages in ([call], [call, {'role': 'tool', 'tool_call_id': 'r',
                                     'content': denial.mark('could not read file'),
                                     bodykeys.RESULT_OUTCOME: denial.REFUSED}]):
        def facts():
            ledger, _, key = loop._ledger_state(sess, messages)
            return policy.FileHistory(tuple(ledger), tuple(sess.written_files),
                tuple(loop._extract_whole_reads(messages, view)),
                tuple(p for _, _, p in loop._write_events_paths(messages)), key, sess.file_touch)
        result = policy.restore(policy.RestoreInput(lambda: view, facts))
        assert result.offered == {'a.py': hashlib.sha1(b'body\n').hexdigest()}
        assert sess.read_files == original_totals
