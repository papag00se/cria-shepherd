"""Original-public-route fake baselines, NOT claims of production rebinding.

Only planner execute_tool is exercised: provider/cache/storage are process-local
fakes. Coder command execution and final wire delivery require Primary's scaffold.
"""
import base64
import builtins
from contextlib import redirect_stdout
from copy import deepcopy
from io import BytesIO, StringIO
import json
import shlex
import sys
from types import SimpleNamespace

import pytest

from cria import assistruntime, externalization as e, planner_tools as p, writeproxy
from cria.loop import GuardState, LoopStore


def test_original_coder_transport_discloses_utf8_extent_without_execution(monkeypatch):
    # This is composition only, not a harness integration or executed command.
    monkeypatch.setattr(writeproxy, 'SPILL_CONTENT_MAX', 4)
    command = writeproxy._spill_command('./tmp/reference/doc.txt', 'αβγ\nEND', 'POINTER')
    encoded = command.split("<<'__CRIA_SPILL__'\n", 1)[1].split('\n__CRIA_SPILL__', 1)[0]
    note = ('[NOTE: this saved copy holds the first 2 characters of a 7-character document '
            '— the rest could not be delivered in one step. What is below is exact; '
            'what is missing is missing. If the part you need is not here, fetch the '
            'specific section of the page directly rather than assuming it is absent.]')
    assert base64.b64decode(encoded).decode() == 'αβ\n\n' + note
    assert 'POINTER\n' + note in command


# Preparation only: these fixtures are lazy and are not production acceptance
# tests. Main must first announce actual registration/projection/import readiness
# and release BEFORE execution. No fixture fabricates delivery acknowledgments or
# invokes a shell. Actual Root result/correlation adapters are not yet available.


def _public_completion(name, arguments, *, call_id='research-call-A'):
    """Real Chat Completions input for writeproxy.translate_outbound."""
    return {'choices': [{'index': 0, 'message': {
        'role': 'assistant', 'content': None,
        'tool_calls': [{'id': call_id, 'type': 'function', 'function': {
            'name': name, 'arguments': json.dumps(arguments, ensure_ascii=False)}}]}}]}


def _paired_public_history(lowered_completion, payload, *, call_id='research-call-A'):
    """Actual history shape; pairing is NOT proof of storage or retention.

    Main's future result bridge must independently observe both. In particular,
    neither exit zero nor this fixture's result text authorizes a ledger update.
    """
    return [deepcopy(lowered_completion['choices'][0]['message']),
            {'role': 'tool', 'tool_call_id': call_id, 'content': payload}]


def _record_split(raw):
    """``(first record as a dict, the rest of the program's output)`` — the stored fact is a TYPED field of that record."""
    first, _, rest = raw.partition('\n')
    return json.loads(first), rest


def _with_record(record, rest):
    return json.dumps(record, separators=(',', ':')) + '\n' + rest


def _run_actual_emitted_search_parser(command, provider_response, monkeypatch, files, *,
                                      close_error=False, output_sink=None):
    """Run ONLY the actual public lowered parser, in-process with fake IO.

    No shell/command evaluation: extract python3's existing -c argument verbatim.
    A missing/changed parser shape is setup evidence, never a semantic before.
    No reconstructed projection/choice/helper is substituted for emitted code.
    """
    words = shlex.split(command, comments=True)
    index = words.index('python3')
    assert words[index + 1] == '-c', 'actual emitted parser adapter needs updating'
    program = words[index + 2]
    def memory_open(target, mode='r', *args, **kwargs):
        assert mode in ('w', 'wb'), 'parser may only use its existing spill writer'
        if close_error:
            class FailedClose(MemoryFile):
                def __exit__(self, *exc):
                    super().__exit__(*exc)
                    raise OSError('in-memory writer close failed')
            return FailedClose(files, target)
        return MemoryBytesFile(files, target) if mode == 'wb' else MemoryFile(files, target)
    namespace = {'__builtins__': {**vars(builtins), 'open': memory_open}}
    output = StringIO() if output_sink is None else output_sink
    with monkeypatch.context() as io:
        io.setattr(sys, 'stdin', StringIO(json.dumps(provider_response, ensure_ascii=False)))
        io.setattr(p.os, 'makedirs', lambda *a, **kw: None)
        with redirect_stdout(output):
            exec(compile(program, '<actual-public-search-parser>', 'exec'), namespace)
    return output.getvalue()


def _assert_literal_fetch_pointer(text):
    assert text == (
        'HTTP 200 · https://example.test/doc\nThis document is too large to hand back inline '
        '(6 chars) — it was saved IN FULL to /owned/example.test_doc.txt.\n'
        'Read it from there — do NOT re-fetch the url. Find the part you need with grep_files '
        '(pattern=<term>, path=/owned/example.test_doc.txt), then read_file /owned/example.test_doc.txt.')


def _assert_literal_stored_fetch(files):
    # Independent source bytes, not an old/new/capture-self comparison.
    assert files == {'/owned/example.test_doc.txt': 'α\nEND\n'}


@pytest.fixture
def prepared_public_fetch(monkeypatch):
    """Lazy provider/cache/FS facts for BOTH existing public transport routes.

    Only actual file writes performed by the planner's Root branch enter files.
    Coder composed commands are never executed or treated as successful writes.
    Optional admission, rendering and selected callback instrumentation must be
    applied to Main's announced adapters, not hidden inside this factual provider.
    """
    observations = []
    files = {}
    cached_documents = {}
    def fetch(url, user_agent=None):
        observations.append(('fetch', url))
        return SimpleNamespace(status=200, final_url=url, body='α\nEND\n',
                               content_type='text/plain', truncated=False)
    def reduce(body, content_type, final_url, raw=False):
        observations.append(('reduce', body, content_type, final_url))
        return 'α\nEND\n', None
    def cache(url, status, content_type, reduced, parsed, truncated):
        args = (url, status, content_type, reduced, parsed, truncated)
        observations.append(('cache', args))
        cached_documents[url] = (status, content_type, reduced, parsed, truncated)
    monkeypatch.setattr(p.webfetch, '_DOC_CACHE', cached_documents)
    monkeypatch.setattr(p.webfetch, 'fetch', fetch)
    monkeypatch.setattr(p.webfetch, 'reduce_for_cache', reduce)
    monkeypatch.setattr(p.webfetch, '_cache_put', cache)
    monkeypatch.setattr(p.webfetch, 'OVERSIZE_CHARS', 2)
    monkeypatch.setattr(p, 'open', lambda target, *a, **kw: MemoryFile(files, target), raising=False)
    monkeypatch.setattr(p.os, 'makedirs', lambda *a, **kw: None)
    return {'observations': observations, 'files': files, 'cache': cached_documents,
            'completion': _public_completion('web_fetch', {'url': 'https://example.test/doc'}),
            'planner_args': {'url': 'https://example.test/doc'}}


@pytest.fixture
def prepared_public_search():
    """Literal provider response for Main's forthcoming parsed search seam.

    This value is data only. No command is evaluated, no invented parser is used,
    and no fake final-delivery/store receipt is synthesized from this response.
    """
    return {
        'completion': _public_completion('web_search', {'query': 'Q'}),
        'provider_response': {'web': {'results': [
            {'title': 'Title', 'url': 'https://example.test', 'description': 'α tail'}]}},
        'planner_body': 'Search results for: Q\n1. Title\n  https://example.test\n  α tail\n',
        'planner_full': 'Search results for: Q\n1. Title\n  https://example.test\n  α tail\n',
        # Coder's full storage is a distinct existing projection, without the
        # planner formatter's query/title numbering. Keep the oracle explicit.
        'coder_full': '1 results:\nTitle\n  https://example.test\n  α tail',
    }


def _externalization_runtime(definition=None, *, absent=False):
    from dataclasses import replace
    runtime = assistruntime.AssistRuntime.select(level=2,
        disabled=(e.DEFINITION.policy.id,) if absent else ())
    if definition is not None:
        runtime = replace(runtime, ordered_stages=tuple(
            definition if d.policy.id == definition.policy.id else d for d in runtime.ordered_stages))
    assert runtime.externalization is (None if absent else definition or e.DEFINITION)
    return runtime


def _actual_owner():
    # Existing Store, no persistence path, synthetic plan, or mirror state.
    store = LoopStore()
    owner = store.get_guard('sid:externalization-before', create=True)
    assert isinstance(owner, GuardState)
    assert store.get_guard('sid:externalization-before') is owner
    assert store.get('sid:externalization-before') is None
    return store, owner


def _public_lower(completion, owner, observe=None):
    shell = {'name': 'exec_command', 'schema': {
        'type': 'object', 'properties': {'cmd': {'type': 'string'}}, 'required': ['cmd']}}
    lowered = writeproxy.translate_outbound(deepcopy(completion), shell,
        injected={'web_fetch', 'web_search'}, brave_key='fake-key',
        externalization_owner=owner, observe_externalization=observe)
    call = lowered['choices'][0]['message']['tool_calls'][0]
    assert call['id'] == 'research-call-A'
    assert call['function']['name'] == 'exec_command'
    arguments = json.loads(call['function']['arguments'])
    return lowered, arguments['cmd']


@pytest.mark.parametrize('response,expected', [
    ({'web': {'results': [{'title': 'Title', 'url': 'https://example.test',
                          'description': 'α tail'}]}},
     '1 results:\nTitle\n  https://example.test\n  α tail\n'),
    ({'web': {'results': []}}, 'no results\n'),
    ({'error': 'bad key'}, 'search API error: "bad key"\n'),
])
def test_public_search_absence_full_inline_without_optional_write(monkeypatch, response, expected):
    runtime = _externalization_runtime(absent=True)
    store, owner = _actual_owner()
    with assistruntime.bound(runtime):
        _, command = _public_lower(_public_completion('web_search', {'query': 'Q'}), owner)
    files = {}
    output = _run_actual_emitted_search_parser(command, response, monkeypatch, files)
    assert output == expected
    assert files == {}
    assert owner.externalization_state is None
    assert owner.externalization_offers is None
    assert store.get_guard('sid:externalization-before') is owner


def test_public_search_embeds_exact_selected_program_not_canonical(monkeypatch, prepared_public_search):
    from dataclasses import replace
    original = e.DEFINITION
    programs, executions, observations = [], [], []
    program = e.SearchProgram(repr('SELECTED α PROGRAM'))
    def selected_program(budget):
        programs.append((budget, program))
        return program
    def execute(source, state):
        executions.append((source, state))
        return original.execute(source, state)
    replacement = replace(original, execute=execute, search_program=selected_program)
    runtime = _externalization_runtime(replacement)
    store, owner = _actual_owner()
    def forbidden(*a, **kw):
        pytest.fail('canonical externalization callback used')
    monkeypatch.setattr(e, 'DEFINITION', replace(original, execute=forbidden, search_program=forbidden))
    monkeypatch.setattr(e, 'search_program', forbidden)
    with assistruntime.bound(runtime):
        _, command = _public_lower(prepared_public_search['completion'], owner,
                                    lambda *args: observations.append(args))
    files = {}
    output = _run_actual_emitted_search_parser(command,
        prepared_public_search['provider_response'], monkeypatch, files)
    assert 'SELECTED α PROGRAM\n' in output
    assert program.expression in shlex.split(command, comments=True)[
        shlex.split(command, comments=True).index('python3') + 2]
    assert len(programs) == 1 and programs[0][1] is program
    assert len(executions) == 1
    source, state = executions[0]
    assert isinstance(source, e.Input)
    assert state is owner.externalization_state
    assert observations  # Construction only; never counted as stored/retained.
    assert list(files.values()) == ['1 results:\nTitle\n  https://example.test\n  α tail']
    assert all(path.startswith('./tmp/reference/') for path in files)
    assert store.get_guard('sid:externalization-before') is owner


def test_public_fetch_absence_preserves_mandatory_provider_cache_without_spill(prepared_public_fetch):
    runtime = _externalization_runtime(absent=True)
    _, owner = _actual_owner()
    with assistruntime.bound(runtime):
        _, command = _public_lower(prepared_public_fetch['completion'], owner)
    assert '__CRIA_SPILL__' not in command
    assert 'α\nEND\n' in command
    assert [event[0] for event in prepared_public_fetch['observations']] == ['fetch', 'reduce', 'cache']
    assert prepared_public_fetch['cache'] == {
        'https://example.test/doc': (200, 'text/plain', 'α\nEND\n', None, False)}
    assert prepared_public_fetch['files'] == {}
    assert owner.externalization_state is None


@pytest.mark.parametrize('name', ['web_fetch', 'web_search'])
def test_public_planner_absence_inlines_full_without_optional_storage(
        monkeypatch, prepared_public_fetch, prepared_public_search, name):
    runtime = _externalization_runtime(absent=True)
    _, owner = _actual_owner()
    monkeypatch.setattr(p, '_SEARCH_INLINE_CHARS', 1)
    monkeypatch.setattr(p, 'gate_search', lambda *a: None)
    monkeypatch.setattr(p, 'brave_search', lambda *a: prepared_public_search['provider_response']['web']['results'])
    monkeypatch.setattr(p, 'format_results', lambda *a: prepared_public_search['planner_body'])
    arguments = {'url': 'https://example.test/doc'} if name == 'web_fetch' else {'query': 'Q'}
    with assistruntime.bound(runtime):
        result = p.execute_tool(name, arguments, '/workspace', 'fake-key', [], None,
            scratch='/owned', facts=None, externalization_owner=owner, operation='research-call-A')
    assert result.text == ('HTTP 200 · https://example.test/doc\nα\nEND\n'
                           if name == 'web_fetch' else prepared_public_search['planner_full'])
    assert prepared_public_fetch['files'] == {}
    assert owner.externalization_state is None


@pytest.fixture
def research_ledgers(monkeypatch):
    # Isolate the EXISTING authoritative ledgers; no parallel production store.
    monkeypatch.setattr(p.webfetch, '_SEARCH_SPILLED', {})
    monkeypatch.setattr(p.webfetch, '_FETCH_SPILLED', {})
    monkeypatch.setattr(p.webfetch, '_FETCH_SEEN', {})
    monkeypatch.setattr(p.webfetch, '_FETCH_STREAK', {})
    monkeypatch.setattr(p.webfetch, '_SEARCH_SEEN', {})
    monkeypatch.setattr(p.webfetch, '_SEARCH_ALLOWED', {})
    return p.webfetch


def _lower_search(owner, runtime, *, observe=None):
    with assistruntime.bound(runtime):
        completion, command = _public_lower(_public_completion('web_search', {'query': 'Q'}),
                                            owner, observe)
    return completion, command, owner.externalization_offers['research-call-A']


def _ledger(owner, facts):
    # _public_lower does not supply a session; use captured record services below
    # for identity tests, and explicit session lowering for actual ledger tests.
    return facts.spilled_path('sid:externalization-before', 'Q')


def _session_lower_search(owner, runtime):
    shell = {'name': 'exec_command', 'schema': {'type': 'object',
        'properties': {'cmd': {'type': 'string'}}, 'required': ['cmd']}}
    with assistruntime.bound(runtime):
        completion = writeproxy.translate_outbound(_public_completion('web_search', {'query': 'Q'}),
            shell, injected={'web_search'}, brave_key='fake-key',
            session='sid:externalization-before', externalization_owner=owner)
    command = json.loads(completion['choices'][0]['message']['tool_calls'][0]['function']['arguments'])['cmd']
    return completion, command, owner.externalization_offers['research-call-A']


@pytest.mark.parametrize('over_by', [0, 1])
def test_public_actual_parser_canonical_program_inclusive_utf8_literal_boundary(
        monkeypatch, prepared_public_search, over_by):
    brief = ('1 results:\nTitle\n  https://example.test\n'
        'web_search "Q" — every result\'s full description is in ./tmp/reference/search-q-c3156e00.txt. '
        'Only the descriptions naming something callable are shown above; read the file '
        'when none of these is what you were looking for.')
    pointer = ('web_search "Q" — results saved to ./tmp/reference/search-q-c3156e00.txt '
        '(each result is title / url / description). They are NOT inlined here (search snippets '
        'are mostly noise). Read them there: grep for a term (grep -n "<keyword>" '
        './tmp/reference/search-q-c3156e00.txt), or read the first lines with read_file '
        'start_line/end_line to see the top results and their URLs.')
    monkeypatch.setattr(writeproxy.content_reduce_mod, 'INLINE_RESULT_MAX_BYTES',
                        len(brief.encode('utf-8')) - over_by)
    _, owner = _actual_owner()
    _, command, _ = _lower_search(owner, _externalization_runtime())
    files = {}
    raw = _run_actual_emitted_search_parser(command, prepared_public_search['provider_response'], monkeypatch, files)
    assert _record_split(raw)[1] == (pointer if over_by else brief) + '\n'
    assert files == {'./tmp/reference/search-q-c3156e00.txt':
                     '1 results:\nTitle\n  https://example.test\n  α tail'}


@pytest.mark.parametrize('defect', ['equal-owner-clone', 'lost-final-envelope'])
def test_public_storage_without_original_owner_retained_envelope_cannot_commit(
        monkeypatch, prepared_public_search, research_ledgers, defect):
    from copy import copy
    _, owner = _actual_owner()
    lowered, command, offer = _session_lower_search(owner, _externalization_runtime())
    raw = _run_actual_emitted_search_parser(command, prepared_public_search['provider_response'], monkeypatch, {})
    messages = _paired_public_history(lowered, raw)
    if defect == 'equal-owner-clone':
        clone = copy(owner)
        assert clone == owner and clone is not owner
        writeproxy.retain_externalizations(clone, lowered)
        writeproxy.observe_externalization_results(clone, messages)
    else:
        writeproxy.retain_externalizations(owner, {'choices': [{'message': {'role': 'assistant',
                                                    'content': 'held', 'tool_calls': []}}]})
        writeproxy.observe_externalization_results(owner, messages)
    assert not offer.retained
    assert _ledger(owner, research_ledgers) == ''
    writeproxy.retain_externalizations(owner, lowered)
    writeproxy.observe_externalization_results(owner, messages)
    assert _ledger(owner, research_ledgers) == offer.delivery.result.spill.target


@pytest.mark.parametrize('order', ['stored-first', 'retained-first'])
def test_public_search_joint_real_writer_and_retention_commit_once(
        monkeypatch, prepared_public_search, research_ledgers, order):
    import hashlib
    runtime = _externalization_runtime()
    _, owner = _actual_owner()
    lowered, command, offer = _session_lower_search(owner, runtime)
    files = {}
    raw = _run_actual_emitted_search_parser(command, prepared_public_search['provider_response'], monkeypatch, files)
    record, _ = _record_split(raw)
    assert raw.count('"st":') == 1                      # ONE stored fact, a typed field of the program's first record
    fact = record['rep']['st']
    expected = '1 results:\nTitle\n  https://example.test\n  α tail'
    assert files == {offer.delivery.result.spill.target: expected}
    assert fact == {'operation': offer.operation, 'target': offer.delivery.result.spill.target,
                    'byte_count': len(expected.encode('utf-8')),
                    'sha256': hashlib.sha256(expected.encode('utf-8')).hexdigest()}
    messages = _paired_public_history(lowered, raw)
    assert _ledger(owner, research_ledgers) == ''
    if order == 'stored-first':
        writeproxy.observe_externalization_results(owner, messages)
        assert _ledger(owner, research_ledgers) == ''
    writeproxy.retain_externalizations(owner, lowered)
    assert _ledger(owner, research_ledgers) == ''
    writeproxy.observe_externalization_results(owner, messages)
    assert _ledger(owner, research_ledgers) == offer.delivery.result.spill.target
    writeproxy.observe_externalization_results(owner, messages)
    assert research_ledgers.spilled_search_files('sid:externalization-before') == {
        offer.delivery.result.spill.target: 'Q'}
    represented = writeproxy.represent_inbound(messages, sess_key='sid:externalization-before')
    assert '"st":' not in str(represented)


@pytest.mark.parametrize('defect', ['missing', 'cut', 'malformed', 'wrong-operation',
    'wrong-target', 'invalid-count', 'invalid-digest', 'wrong-call-id', 'wrong-arguments'])
def test_public_search_invalid_raw_fact_or_pair_stays_pending_for_original(
        monkeypatch, prepared_public_search, research_ledgers, defect):
    runtime = _externalization_runtime()
    _, owner = _actual_owner()
    lowered, command, offer = _session_lower_search(owner, runtime)
    files = {}
    raw = _run_actual_emitted_search_parser(command, prepared_public_search['provider_response'], monkeypatch, files)
    writeproxy.retain_externalizations(owner, lowered)
    messages = _paired_public_history(lowered, raw)
    bad = deepcopy(messages)
    record, rest = _record_split(raw)
    if defect in ('missing', 'cut', 'malformed'):
        if defect == 'missing':
            record.pop('rep')                                   # the producer declared no stored fact
            bad[-1]['content'] = _with_record(record, rest)
        elif defect == 'cut':
            bad[-1]['content'] = raw[:len(raw.partition('\n')[0]) // 2]
        else:
            record['rep']['st'] = 'not a fact'
            bad[-1]['content'] = _with_record(record, rest)
    elif defect in ('wrong-call-id', 'wrong-arguments'):
        if defect == 'wrong-call-id':
            bad[-1]['tool_call_id'] = 'foreign-call'
        else:
            bad[0]['tool_calls'][0]['function']['arguments'] += ' '
    else:
        key, value = {'wrong-operation': ('operation', 'foreign'), 'wrong-target': ('target', 'foreign'),
            'invalid-count': ('byte_count', True), 'invalid-digest': ('sha256', 'a' * 63)}[defect]
        record['rep']['st'][key] = value
        bad[-1]['content'] = _with_record(record, rest)
    writeproxy.observe_externalization_results(owner, bad)
    assert _ledger(owner, research_ledgers) == ''
    writeproxy.observe_externalization_results(owner, messages)
    assert _ledger(owner, research_ledgers) == offer.delivery.result.spill.target


@pytest.mark.parametrize('terminal', ['failure', 'cancel', 'reset', 'drop', 'evict', 'upgrade'])
def test_public_search_terminal_or_successor_owner_cannot_commit_late(
        monkeypatch, prepared_public_search, research_ledgers, terminal):
    from cria.loop import PlanSession
    from cria.plan import Plan
    store, owner = _actual_owner()
    lowered, command, offer = _session_lower_search(owner, _externalization_runtime())
    raw = _run_actual_emitted_search_parser(command, prepared_public_search['provider_response'], monkeypatch, {})
    writeproxy.retain_externalizations(owner, lowered)
    if terminal == 'failure':
        writeproxy.observe_externalization_results(owner, _paired_public_history(lowered,
            # A terminal failure needs a complete exec envelope, not a status
            # phrase concatenated directly onto the producer's opaque stdout.
            'Process exited with code 1\nOutput:\n' + raw))
    elif terminal == 'cancel':
        offer.delivery.cancel()
    elif terminal == 'reset':
        offer.delivery.reset()
    elif terminal == 'drop':
        store.drop('sid:externalization-before')
    elif terminal == 'evict':
        import cria.loop as loop_module
        monkeypatch.setattr(loop_module, '_MAX_SESSIONS', 1)
        store.get_guard('sid:successor', create=True)
    else:
        store.put('sid:externalization-before', PlanSession(plan=Plan(
            id='successor', task='task', created='fixed', items=[])))
    writeproxy.observe_externalization_results(owner, _paired_public_history(lowered, raw))
    assert _ledger(owner, research_ledgers) == ''


@pytest.mark.parametrize('header', ['', 'Process exited with code 0\nOutput:\n',
    'Process exited with code 0\r\nOutput:\r\n',
    'Chunk ID: ab\nWall time: 1s\nProcess running with session ID 7\nOutput:\n',
    'Chunk ID: ab\nWall time: 1s\nOutput:\n'])
def test_public_search_quoted_exit_does_not_override_the_producers_stored_fact(
        monkeypatch, prepared_public_search, research_ledgers, header):
    _, owner = _actual_owner()
    lowered, command, offer = _session_lower_search(owner, _externalization_runtime())
    raw = _run_actual_emitted_search_parser(command, prepared_public_search['provider_response'], monkeypatch, {})
    writeproxy.retain_externalizations(owner, lowered)
    messages = _paired_public_history(lowered, header + raw + '\nProcess exited with code 19\nOutput:\nlog tail\n')
    writeproxy.observe_externalization_results(owner, messages)
    assert _ledger(owner, research_ledgers) == offer.delivery.result.spill.target


def test_public_search_quoted_header_does_not_poison_later_actual_storage(
        monkeypatch, prepared_public_search, research_ledgers):
    _, owner = _actual_owner()
    lowered, command, offer = _session_lower_search(owner, _externalization_runtime())
    raw = _run_actual_emitted_search_parser(command, prepared_public_search['provider_response'], monkeypatch, {})
    writeproxy.retain_externalizations(owner, lowered)
    quoted = 'build.log:\nProcess exited with code 1\nOutput:\n' + raw
    writeproxy.observe_externalization_results(owner, _paired_public_history(lowered, quoted))
    assert _ledger(owner, research_ledgers) == ''  # no first producer record at stdout offset zero
    writeproxy.observe_externalization_results(owner, _paired_public_history(lowered, raw))
    assert _ledger(owner, research_ledgers) == offer.delivery.result.spill.target


def test_public_search_writer_close_failure_cannot_emit_storage_fact(
        monkeypatch, prepared_public_search, research_ledgers):
    _, owner = _actual_owner()
    lowered, command, _ = _session_lower_search(owner, _externalization_runtime())
    output = StringIO()
    with pytest.raises(OSError, match='writer close failed'):
        _run_actual_emitted_search_parser(command, prepared_public_search['provider_response'],
                                          monkeypatch, {}, close_error=True, output_sink=output)
    assert '"st":' not in output.getvalue()
    writeproxy.retain_externalizations(owner, lowered)
    writeproxy.observe_externalization_results(owner, _paired_public_history(lowered, 'no storage fact'))
    assert _ledger(owner, research_ledgers) == ''


def test_public_search_retry_exact_services_and_definition_across_body_b(
        monkeypatch, prepared_public_search, research_ledgers):
    from dataclasses import replace
    original = e.DEFINITION
    executed, records = [], []
    def execute(value, state):
        executed.append(value)
        return original.execute(value, state)
    def settle(state, result, outcome, *, stored):
        committed = original.settle(state, result, outcome, stored=stored)
        if committed:
            records.append(result.spill)
        return committed
    selected = replace(original, execute=execute, settle=settle)
    runtime = _externalization_runtime(selected)
    _, owner = _actual_owner()
    lowered, command, offer = _session_lower_search(owner, runtime)
    again, same_command, same_offer = _session_lower_search(owner, runtime)
    assert same_offer is offer and same_command == command and again == lowered
    assert len(executed) == 1
    assert offer.source is executed[0]
    assert offer.delivery.owner is selected
    with assistruntime.bound(_externalization_runtime(absent=True)):
        raw = _run_actual_emitted_search_parser(command, prepared_public_search['provider_response'], monkeypatch, {})
        writeproxy.retain_externalizations(owner, lowered)
        writeproxy.observe_externalization_results(owner, _paired_public_history(lowered, raw))
    assert records == [offer.delivery.result.spill]
    assert _ledger(owner, research_ledgers) == offer.delivery.result.spill.target


@pytest.mark.parametrize('replacement', ['absent', 'different-definition'])
def test_public_search_reselection_does_not_reuse_previous_command_or_authority(
        monkeypatch, prepared_public_search, research_ledgers, replacement):
    from dataclasses import replace
    _, owner = _actual_owner()
    old_completion, old_command, old = _session_lower_search(owner, _externalization_runtime())
    raw = _run_actual_emitted_search_parser(old_command, prepared_public_search['provider_response'], monkeypatch, {})
    runtime = (_externalization_runtime(absent=True) if replacement == 'absent' else
        _externalization_runtime(replace(e.DEFINITION, search_program=lambda n: e.SearchProgram(repr('NEW PROGRAM')))))
    with assistruntime.bound(runtime):
        new, command = _public_lower(_public_completion('web_search', {'query': 'Q'}), owner)
    assert command != old_command
    writeproxy.retain_externalizations(owner, old_completion)
    writeproxy.observe_externalization_results(owner, _paired_public_history(old_completion, raw))
    assert _ledger(owner, research_ledgers) == ''
    if replacement == 'different-definition':
        assert 'NEW PROGRAM' in _run_actual_emitted_search_parser(command,
            prepared_public_search['provider_response'], monkeypatch, {})


class FakeLog:
    def __init__(self):
        self.events = []
    def emit(self, event, **fields):
        self.events.append((event, fields))


def _fake_handler(store, runtime):
    from cria.server import CriaHandler
    handler = object.__new__(CriaHandler)
    cfg = SimpleNamespace(
        routing=SimpleNamespace(simple_tools=True, context_fixes=False, done_refusals=False,
                                assists_enabled=False, engagement_level=2),
        indicators=SimpleNamespace(enabled=False, connect=False, stats=False, assists=False),
        safety=SimpleNamespace(external_dir_permission='write'),
        tools=SimpleNamespace(focus=False, cheatsheet=False))
    stats = SimpleNamespace(calls=0, observe=lambda *a: None)
    handler.server = SimpleNamespace(loop_store=store, loop=None, cfg=cfg, pilot_runtime=runtime,
                                    stats_store=SimpleNamespace(get=lambda key: stats))
    handler.headers = {'X-Cria-Session-Id': 'externalization-before'}
    handler._shell_tool = {'name': 'exec_command', 'schema': {'type': 'object',
        'properties': {'cmd': {'type': 'string'}}, 'required': ['cmd']}}
    handler._synthetic = {'web_search', 'web_fetch'}
    handler._brave_key = 'fake-key'
    return handler


@pytest.mark.parametrize('transport', ['buffered', 'responses', 'direct-proxy-stream'])
def test_real_server_retention_routes_and_raw_ingest_before_representation(
        monkeypatch, prepared_public_search, research_ledgers, transport):
    from cria import server as server_module
    runtime = _externalization_runtime()
    store, owner = _actual_owner()
    handler = _fake_handler(store, runtime)
    log = FakeLog()
    upstream = _public_completion('web_search', {'query': 'Q'})
    upstream.update(id='reply-A', model='fake-model', object='chat.completion')
    upstream['choices'][0]['finish_reason'] = 'tool_calls'
    provider = SimpleNamespace(chat=lambda *args: json.dumps(upstream),
        stream_chat=lambda *args: iter(server_module.completion_to_sse(upstream)))
    handler._classify = lambda *args: None
    handler._route = lambda *args: (provider, SimpleNamespace(note=''))
    handler._apply_route_role = lambda body, *args: body
    handler._engages_loop = lambda *args: False
    body = {'model': 'fake-model', 'messages': [{'role': 'user', 'content': 'Research Q'}],
            'tools': [{'type': 'function', 'function': {'name': 'web_search', 'parameters': {
                'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']}}}]}
    finalized = []
    handler._defer_pasted_delivery(lambda completion, lowered: finalized.append((completion, lowered)))
    if transport == 'buffered':
        with assistruntime.bound(runtime):
            lowered, _ = handler._produce_completion(deepcopy(body), log, 'sid:externalization-before')
        assert finalized and finalized[0][0] is lowered  # F16 callback remains disjoint.
    elif transport == 'responses':
        sent = []
        handler._send_raw_json = sent.append
        handler._send_json = lambda code, obj: pytest.fail(str((code, obj)))
        with assistruntime.bound(runtime):
            handler._respond_responses_buffered(deepcopy(body), 'sid:externalization-before', log)
        assert sent and json.loads(sent[0])['output'][0]['type'] == 'function_call'
        assert finalized
        lowered = finalized[0][0]
    else:
        # Actual massage_stream still runs; bypass only unrelated UI decoration.
        monkeypatch.setattr(server_module, 'wrap_stream', lambda stream, indic: stream)
        with assistruntime.bound(runtime):
            chunks = list(handler._produce_stream(deepcopy(body), log))
        assert chunks and b'research-call-A' in b''.join(chunks)
        assert not finalized  # This path genuinely does not call _finalize.
        pending = owner.externalization_offers['research-call-A']
        lowered = {'choices': [{'message': {'role': 'assistant', 'tool_calls': [{
            'id': pending.call_id, 'type': 'function', 'function': {
                'name': 'exec_command', 'arguments': pending.lowered_arguments}}]}}]}
    offer = owner.externalization_offers['research-call-A']
    assert offer.retained
    assert _ledger(owner, research_ledgers) == ''
    command = json.loads(offer.lowered_arguments)['cmd']
    raw = _run_actual_emitted_search_parser(command, prepared_public_search['provider_response'], monkeypatch, {})
    incoming = {'messages': _paired_public_history(lowered, raw),
        'tools': [{'type': 'function', 'function': {'name': 'exec_command', 'parameters': {
            'type': 'object', 'properties': {'cmd': {'type': 'string'}}, 'required': ['cmd']}}}]}
    original_representation = server_module.represent_inbound
    observed = []
    def representation(messages, *args, **kwargs):
        assert '"st":' in str(messages)
        assert _ledger(owner, research_ledgers) == offer.delivery.result.spill.target
        observed.append(True)
        return original_representation(messages, *args, **kwargs)
    monkeypatch.setattr(server_module, 'represent_inbound', representation)
    monkeypatch.setattr(server_module.brave, 'api_key', lambda: 'fake-key')
    with assistruntime.bound(runtime):
        handler._setup_translation(incoming, 'sid:externalization-before', log)
    assert observed == [True]
    assert '"st":' not in str(incoming['messages'])


@pytest.mark.parametrize('writer_failure,changed_owner', [(False, False), (True, False), (False, True)])
def test_actual_planner_gather_insertion_joins_checked_writer_current_owner(
        monkeypatch, prepared_public_fetch, writer_failure, changed_owner):
    from cria import planner as planner_module
    from cria.planningcontracts import PlanOutcome
    from datetime import datetime, timezone
    runtime = _externalization_runtime()
    store, owner = _actual_owner()
    plan = planner_module.Planner(SimpleNamespace(), clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
    log = FakeLog()
    responses = iter([{'role': 'assistant', 'tool_calls': [{
        'id': 'gather-A', 'type': 'function', 'function': {'name': 'web_fetch',
            'arguments': '{"url":"https://example.test/doc"}'}}]}, {'role': 'assistant', 'content': 'draft'}])
    transcript = []
    def reason(messages, *args, **kwargs):
        transcript[:] = deepcopy(messages)
        return next(responses)
    monkeypatch.setattr(plan, '_reason', reason)
    monkeypatch.setattr(plan, '_draft_plan', lambda messages, *a, **kw: transcript.__setitem__(slice(None), deepcopy(messages)) or ['done'])
    monkeypatch.setattr(planner_module.tempfile, 'mkdtemp', lambda **kw: '/owned')
    monkeypatch.setattr(planner_module.shutil, 'rmtree', lambda *a, **kw: None)
    if writer_failure:
        class FailedClose(MemoryFile):
            def __exit__(self, *exc):
                super().__exit__(*exc)
                raise OSError('actual writer close failed')
        monkeypatch.setattr(p, 'open', lambda target, *a, **kw: FailedClose(prepared_public_fetch['files'], target), raising=False)
    outcome = PlanOutcome()
    outcome.externalization_owner = owner
    outcome.current_externalization_owner = (lambda: GuardState()) if changed_owner else (
        lambda: store.get_guard('sid:externalization-before'))
    with assistruntime.bound(runtime):
        assert plan._gather_and_plan('Research', '', log, outcome=outcome) == ['done']
    tool_result = next(message for message in transcript if message['role'] == 'tool')
    assert tool_result['tool_call_id'] == 'gather-A'
    guidance = ('\n[this page answered, but no endpoints or field names could be read from it '
        '— that is a fact about the REQUEST, not about what the API returns. Nothing you have read '
        'so far DEFINES a route, so any endpoint in your plan would be a guess: find and read '
        'the document that defines them before planning against one.]')
    if writer_failure:
        assert tool_result['content'] == 'HTTP 200 · https://example.test/doc\nα\nEND\n' + guidance
    else:
        assert tool_result['content'].endswith(guidance)
        _assert_literal_fetch_pointer(tool_result['content'][:-len(guidance)])
        _assert_literal_stored_fetch(prepared_public_fetch['files'])
    commits = [fields for event, fields in log.events if event == 'plan.research_spill']
    assert len(commits) == (0 if writer_failure or changed_owner else 1)


@pytest.mark.parametrize('phase,field', [('final', 'name'), ('final', 'type'),
                                         ('inbound', 'name'), ('inbound', 'type')])
def test_actual_server_rejects_same_id_arguments_with_different_transport_identity(
        monkeypatch, prepared_public_search, research_ledgers, phase, field):
    from cria import server as server_module
    runtime = _externalization_runtime()
    store, owner = _actual_owner()
    handler = _fake_handler(store, runtime)
    log = FakeLog()
    with assistruntime.bound(runtime):
        lowered = handler._translate_out(_public_completion('web_search', {'query': 'Q'}),
                                         'sid:externalization-before', log)
    offer = owner.externalization_offers['research-call-A']
    raw = _run_actual_emitted_search_parser(json.loads(offer.lowered_arguments)['cmd'],
                prepared_public_search['provider_response'], monkeypatch, {})
    def change(completion):
        call = completion['choices'][0]['message']['tool_calls'][0]
        if field == 'name':
            call['function']['name'] = 'foreign_tool'
        else:
            call['type'] = 'foreign-type'
    if phase == 'final':
        change(lowered)
    with assistruntime.bound(runtime):
        retained = handler._finalize(lowered, 'sid:externalization-before', log)
    if phase == 'inbound':
        retained = deepcopy(retained)
        change(retained)
    body = {'messages': _paired_public_history(retained, raw), 'tools': []}
    monkeypatch.setattr(server_module.brave, 'api_key', lambda: 'fake-key')
    with assistruntime.bound(runtime):
        handler._setup_translation(body, 'sid:externalization-before', log)
    assert _ledger(owner, research_ledgers) == ''
    if phase == 'final':
        assert not offer.retained


def test_root_canonical_fallback_fault_is_detected_and_restored(
        monkeypatch, prepared_public_search):
    from dataclasses import replace
    original = writeproxy._externalize_coder
    def oracle():
        _, owner = _actual_owner()
        with assistruntime.bound(_externalization_runtime(absent=True)):
            _, command = _public_lower(prepared_public_search['completion'], owner)
        files = {}
        text = _run_actual_emitted_search_parser(command,
            prepared_public_search['provider_response'], monkeypatch, files)
        assert text == '1 results:\nTitle\n  https://example.test\n  α tail\n'
        assert files == {}
    oracle()
    def faulty(source):
        return original(replace(source, request=replace(source.request,
            externalization_definition=e.DEFINITION)))
    with monkeypatch.context() as fault:
        fault.setattr(writeproxy, '_externalize_coder', faulty)
        with pytest.raises(AssertionError):
            oracle()
    oracle()


@pytest.fixture
def planner_reused_cid_facts(monkeypatch, prepared_public_fetch):
    """Two independently fetched bodies; mandatory B facts exist before policy."""
    observations = prepared_public_fetch['observations']
    def fetch(url, user_agent=None):
        body = 'β\nEND\n' if url.endswith('/other') else 'α\nEND\n'
        observations.append(('fetch', url, body))
        return SimpleNamespace(status=200, final_url=url, body=body,
                               content_type='text/plain', truncated=False)
    def reduce(body, content_type, final_url, raw=False):
        observations.append(('reduce', body, content_type, final_url))
        return body, None
    writes = []
    actual_memory_open = p.open
    def opened(target, *args, **kwargs):
        writes.append(target)
        return actual_memory_open(target, *args, **kwargs)
    monkeypatch.setattr(p.webfetch, 'fetch', fetch)
    monkeypatch.setattr(p.webfetch, 'reduce_for_cache', reduce)
    monkeypatch.setattr(p, 'open', opened)
    monkeypatch.setattr(p, '_SEARCH_INLINE_CHARS', 1)
    monkeypatch.setattr(p, 'gate_search', lambda *a: None)
    monkeypatch.setattr(p, 'brave_search', lambda *a: [
        {'title': 'Title', 'url': 'https://example.test', 'description': 'β tail'}])
    search_body = 'Search results for: B\n1. Title\n  https://example.test\n  β tail\n'
    def format_results(query, results):
        observations.append(('search', query, results))
        return search_body
    monkeypatch.setattr(p, 'format_results', format_results)
    return prepared_public_fetch, writes, search_body


def _literal_planner_b(second_name):
    if second_name == 'web_fetch':
        return ('HTTP 200 · https://example.test/other\nThis document is too large to hand back inline '
            '(6 chars) — it was saved IN FULL to /owned/example.test_other.txt.\n'
            'Read it from there — do NOT re-fetch the url. Find the part you need with grep_files '
            '(pattern=<term>, path=/owned/example.test_other.txt), then read_file /owned/example.test_other.txt.')
    return ('Search results for: B — 63 characters of titles and snippets, saved IN FULL to '
        '/owned/search-b.txt. The titles are below; to read a snippet in full: '
        'Find the part you need with grep_files (pattern=<term>, path=/owned/search-b.txt), '
        'then read_file /owned/search-b.txt. Do NOT re-run this search.\nSearch results for: B\n1. Title')


@pytest.mark.parametrize('cid', ['same-model-cid', '', None])
@pytest.mark.parametrize('second_name', ['web_fetch', 'web_search'])
def test_public_planner_reused_or_absent_cid_never_aliases_different_facts(
        planner_reused_cid_facts, cid, second_name):
    facts, writes, search_body = planner_reused_cid_facts
    _, owner = _actual_owner()
    runtime, log = _externalization_runtime(), FakeLog()
    args_a = {'url': 'https://example.test/doc'}
    args_b = {'url': 'https://example.test/other'} if second_name == 'web_fetch' else {'query': 'B'}
    with assistruntime.bound(runtime):
        first = p.execute_tool('web_fetch', args_a, '/workspace', 'fake-key', [], log,
            scratch='/owned', facts=None, externalization_owner=owner, operation=cid)
        assert p.retain_tool_result(first, owner)
        second = p.execute_tool(second_name, args_b, '/workspace', 'fake-key', [], log,
            scratch='/owned', facts=None, externalization_owner=owner, operation=cid)
        # Observe genuine mandatory B data before checking optional output, so a
        # missing/new API or unfetched B can never masquerade as the incident.
        if second_name == 'web_fetch':
            assert facts['cache']['https://example.test/other'][2] == 'β\nEND\n'
        else:
            assert any(event[0:2] == ('search', 'B') for event in facts['observations'])
        assert second.text == _literal_planner_b(second_name)
        assert second.externalization is not first.externalization
        assert p.retain_tool_result(second, owner)
        if cid == 'same-model-cid':
            retry = p.execute_tool(second_name, args_b, '/workspace', 'fake-key', [], log,
                scratch='/owned', facts=None, externalization_owner=owner, operation=cid)
            assert retry is second
            assert retry.externalization is second.externalization
            assert not p.retain_tool_result(retry, owner)
    target_b = '/owned/example.test_other.txt' if second_name == 'web_fetch' else '/owned/search-b.txt'
    assert facts['files'] == {'/owned/example.test_doc.txt': 'α\nEND\n',
        target_b: 'β\nEND\n' if second_name == 'web_fetch' else search_body}
    assert writes == ['/owned/example.test_doc.txt', target_b]
    assert [fields['path'] for event, fields in log.events if event == 'plan.research_spill'] == [
        '/owned/example.test_doc.txt', target_b]


@pytest.mark.parametrize('cid', ['same-model-cid', '', None])
@pytest.mark.parametrize('second_name', ['web_fetch', 'web_search'])
def test_actual_gather_rounds_preserve_real_b_facts_despite_reused_or_missing_cid(
        monkeypatch, planner_reused_cid_facts, cid, second_name):
    from cria import planner as planner_module
    from cria.planningcontracts import PlanOutcome
    from datetime import datetime, timezone
    facts, writes, search_body = planner_reused_cid_facts
    runtime, log = _externalization_runtime(), FakeLog()
    store, owner = _actual_owner()
    plan = planner_module.Planner(SimpleNamespace(), search_key='fake-key',
        clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
    def call(name, arguments):
        result = {'type': 'function', 'function': {'name': name, 'arguments': json.dumps(arguments)}}
        if cid is not None:
            result['id'] = cid
        return result
    first_call = call('web_fetch', {'url': 'https://example.test/doc'})
    second_call = call(second_name, {'url': 'https://example.test/other'}
                       if second_name == 'web_fetch' else {'query': 'B'})
    replies = iter([{'role': 'assistant', 'tool_calls': [first_call]},
                    {'role': 'assistant', 'tool_calls': [second_call]},
                    {'role': 'assistant', 'content': 'draft'}])
    transcript = []
    monkeypatch.setattr(plan, '_reason', lambda *a, **kw: next(replies))
    monkeypatch.setattr(plan, '_draft_plan', lambda messages, *a, **kw:
        transcript.__setitem__(slice(None), deepcopy(messages)) or ['done'])
    monkeypatch.setattr(planner_module.tempfile, 'mkdtemp', lambda **kw: '/owned')
    monkeypatch.setattr(planner_module.shutil, 'rmtree', lambda *a, **kw: None)
    outcome = PlanOutcome()
    outcome.externalization_owner = owner
    outcome.current_externalization_owner = lambda: store.get_guard('sid:externalization-before')
    with assistruntime.bound(runtime):
        assert plan._gather_and_plan('Research', '', log, outcome=outcome) == ['done']
    outputs = [message for message in transcript if message['role'] == 'tool']
    assert len(outputs) == 2
    if second_name == 'web_fetch':
        assert facts['cache']['https://example.test/other'][2] == 'β\nEND\n'
    else:
        assert any(event[0:2] == ('search', 'B') for event in facts['observations'])
    guidance = ('\n[this page answered, but no endpoints or field names could be read from it '
        '— that is a fact about the REQUEST, not about what the API returns. Nothing you have read '
        'so far DEFINES a route, so any endpoint in your plan would be a guess: find and read '
        'the document that defines them before planning against one.]') if second_name == 'web_fetch' else (
        '\n[these results are titles and snippets — POINTERS, not the source. Nothing you have read '
        'so far DEFINES a route, so any endpoint in your plan would be a guess: web_fetch the '
        'document that defines them (a spec, docs page, or the API root) and read it before planning against one.]')
    assert outputs[1]['content'] == _literal_planner_b(second_name) + guidance
    target_b = '/owned/example.test_other.txt' if second_name == 'web_fetch' else '/owned/search-b.txt'
    assert facts['files'] == {'/owned/example.test_doc.txt': 'α\nEND\n',
        target_b: 'β\nEND\n' if second_name == 'web_fetch' else search_body}
    assert writes == ['/owned/example.test_doc.txt', target_b]
    assert [fields['path'] for event, fields in log.events if event == 'plan.research_spill'] == [
        '/owned/example.test_doc.txt', target_b]


class MemoryBytesFile(BytesIO):
    def __init__(self, files, target):
        super().__init__()
        self.files, self.target = files, target

    def close(self):
        self.files[self.target] = self.getvalue()
        super().close()


class MemoryFile(StringIO):
    def __init__(self, files, target):
        super().__init__()
        self.files, self.target = files, target

    def close(self):
        self.files[self.target] = self.getvalue()
        super().close()


def test_original_public_fetch_route_literal_and_source_candidate(monkeypatch):
    files = {}
    monkeypatch.setattr(p, 'open', lambda target, *a, **kw: MemoryFile(files, target), raising=False)
    monkeypatch.setattr(p.os, 'makedirs', lambda *a, **kw: None)
    monkeypatch.setattr(p.webfetch, 'OVERSIZE_CHARS', 2)
    monkeypatch.setattr(p.webfetch, 'fetch', lambda url: SimpleNamespace(
        status=200, final_url=url, body='α\nEND\n', content_type='text/plain', truncated=False))
    monkeypatch.setattr(p.webfetch, 'reduce_for_cache', lambda *a: ('α\nEND\n', None))
    monkeypatch.setattr(p.webfetch, '_cache_put', lambda *a: None)
    original = p.execute_tool('web_fetch', {'url': 'https://example.test/doc'}, '/workspace', '', [], None,
                              scratch='/owned', facts=None)
    expected = ('HTTP 200 · https://example.test/doc\nThis document is too large to hand back inline '
                '(6 chars) — it was saved IN FULL to /owned/example.test_doc.txt.\n'
                'Read it from there — do NOT re-fetch the url. Find the part you need with grep_files '
                '(pattern=<term>, path=/owned/example.test_doc.txt), then read_file /owned/example.test_doc.txt.')
    assert original.text == expected
    assert files == {'/owned/example.test_doc.txt': 'α\nEND\n'}
    candidate = e.planner_fetch(status=200, url='https://example.test/doc', reduced='α\nEND\n',
                               parsed=None, content_type='text/plain', root='/owned', remedy=p.spill_remedy,
                               services=e.PlannerFetchServices(p.webfetch.OVERSIZE_CHARS,
                                   p.webfetch.spill_content, p.webfetch._spill_name, p.webfetch.spill_outline))
    assert candidate.pointer == expected
    assert candidate.content == 'α\nEND\n'


def test_original_public_search_route_literal_and_source_candidate(monkeypatch):
    files = {}
    monkeypatch.setattr(p.os, 'makedirs', lambda *a, **kw: None)
    body = 'Search results for: Q\n1. Title\n  https://example.test\n  α tail\n'
    monkeypatch.setattr(p, 'open', lambda target, *a, **kw: MemoryFile(files, target), raising=False)
    monkeypatch.setattr(p, '_SEARCH_INLINE_CHARS', 1)
    monkeypatch.setattr(p, 'gate_search', lambda *a: None)
    monkeypatch.setattr(p, 'brave_search', lambda *a: [{'title': 'Title'}])
    monkeypatch.setattr(p, 'format_results', lambda *a: body)
    original = p.execute_tool('web_search', {'query': 'Q'}, '/workspace', 'fake-key', [], None,
                              scratch='/owned', facts=None)
    expected = ('Search results for: Q — 63 characters of titles and snippets, saved IN FULL to '
                '/owned/search-q.txt. The titles are below; to read a snippet in full: '
                'Find the part you need with grep_files (pattern=<term>, path=/owned/search-q.txt), '
                'then read_file /owned/search-q.txt. Do NOT re-run this search.\n'
                'Search results for: Q\n1. Title')
    assert original.text == expected
    assert files == {'/owned/search-q.txt': body}
    candidate = e.planner_search('Q', body, scratch='/owned', inline_chars=1, remedy=p.spill_remedy)
    assert candidate.pointer == expected
    assert candidate.content == body
