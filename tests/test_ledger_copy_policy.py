from types import SimpleNamespace
from unittest.mock import Mock, patch

from cria import ledgercopies as policy, loop

POINTER = ('(identical fetched-spec content is shown once, IN FULL, in the fetch-record block of this '
           'conversation — it is not repeated here)')


def fixture():
    ledger = 'PAGES YOU HAVE ALREADY FETCHED\n- https://example.test → HTTP 200\n  ' + 'literal fields ' * 30
    anchor = {'role': 'user', 'content': '⟦ctx:facts⟧\n' + ledger}
    duplicate = {'role': 'tool', 'tool_call_id': 'fetch', 'content': ledger}
    return ledger, anchor, duplicate


def test_source_parity_and_anchor_survival():
    ledger, anchor, duplicate = fixture()
    messages = [{'role': 'user', 'content': 'ORIGINAL TASK'}, duplicate, anchor]
    events = Mock()
    result = policy.elide(policy.LedgerCopyInput(messages, lambda: ledger, events))
    fetched_pages = {'https://example.test': ('HTTP 200', '', 'literal fields ' * 30)}
    session = SimpleNamespace(fetched_pages=fetched_pages)
    with patch.object(loop, '_format_fetches', return_value=ledger) as formatter:
        adapted = loop._elide_ledger_copies(messages, session)
        assert result.messages == adapted
        formatter.assert_called_once_with(fetched_pages, 'PAGES YOU HAVE ALREADY FETCHED',
                                          visible=set(), location=False)
    assert adapted[0] is messages[0]
    assert adapted[-1] is anchor
    # Independent full-content oracle: the legacy adapter can now call the same
    # source and its equality above alone would no longer prove lossless elision.
    assert result.messages == [messages[0],
        {'role': 'tool', 'tool_call_id': 'fetch', 'content': 'PAGES YOU HAVE ALREADY FETCHED\n' + POINTER},
        anchor]
    assert result.excised == 1
    assert result.messages[-1] is anchor
    assert result.messages[0] is messages[0]
    assert duplicate['content'] == ledger
    events.emit.assert_called_once_with('context.ledger_dedup', reshape='dedup', excised=1)


def test_no_anchor_or_changed_anchor_cannot_leave_dangling_pointer():
    ledger, anchor, duplicate = fixture()
    for messages in ([duplicate], [duplicate, {**anchor, 'content': '⟦ctx:facts⟧ changed'}]):
        result = policy.elide(policy.LedgerCopyInput(messages, lambda: ledger))
        assert result.messages is messages
        assert result.excised == 0


def test_disabled_replaced_and_other_session_do_not_gather_or_change_facts():
    ledger, anchor, duplicate = fixture()
    messages = [duplicate, anchor]
    gather = Mock(side_effect=AssertionError)
    item = policy.LedgerCopyInput(messages, gather)
    assert policy.DEFINITION.execute(item, enabled=False).messages is messages
    replacement = lambda source: policy.LedgerCopyResult(source.messages)
    assert replacement(item).messages is messages
    gather.assert_not_called()
    other = policy.elide(policy.LedgerCopyInput(messages, lambda: 'other session'))
    assert other.messages is messages
    assert anchor['content'].endswith(ledger)


def test_model_text_headers_and_nonidentical_bytes_stay_literal():
    ledger, anchor, duplicate = fixture()
    assistant = {'role': 'assistant', 'content': ledger}
    changed = {**duplicate, 'content': ledger.replace('literal fields', 'changed fields')}
    messages = [assistant, changed, anchor]
    assert policy.elide(policy.LedgerCopyInput(messages, lambda: ledger)).messages is messages
