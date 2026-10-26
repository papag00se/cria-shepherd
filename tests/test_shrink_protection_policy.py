"""F15 source behavior against captured payloads and isolated text-file commands."""
import ast
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cria import denial, shrinkprotection as policy, toolwire, wholefile, writeproxy
from cria.toolstages import LoweringRequest, OutboundCall, ToolStages


class Log:
    def __init__(self):
        self.events = []
    def emit(self, event, **fields):
        self.events.append((event, fields))


CURRENT = ''.join(f'block {i}:\n    value {i}\n' for i in range(8))
FRAGMENT = 'replacement\n'
REMOVAL = ''.join(f'new line {i}\n' for i in range(12))


class View:
    surveyed = True
    def __init__(self, raw=CURRENT.encode(), exists=True):
        self.raw, self.exists = raw, exists
    def rel(self, path):
        return 'file.txt'
    def isfile(self, path):
        return self.exists
    def read_bytes(self, path):
        return self.raw


def services(answer='OTHER', *, raw=CURRENT.encode(), baseline=('file.txt',)):
    state = policy.ShrinkState()
    session = policy.ShrinkSession(baseline, state)
    return policy.ShrinkServices(Mock(return_value=session), Mock(return_value=View(raw)),
                                 Mock(return_value=answer), Log())


@dataclass(frozen=True)
class Request(LoweringRequest):
    # Candidate integration field: primary later adds this to the shared contract.
    shrink_services: policy.ShrinkServices | None = None


def call(source, content=FRAGMENT, path='file.txt', injected=('write_file', 'edit_file')):
    arguments = {'path': path, 'content': content}
    return OutboundCall({'id': 'c1', 'function': {'name': 'write_file', 'arguments': json.dumps(arguments)}},
                        arguments, Request(frozenset(injected), shrink_services=source), log=source.log)


@pytest.mark.parametrize('answer,allowed', [('WHOLE_FILE', True), ('whole_file: yes', True),
    ('OTHER', False), ('', False), ('WHOLE_FILE_MAYBE', False), ('I think WHOLE_FILE', False)])
def test_fragment_hold_and_affirmative_only_cache(answer, allowed):
    source = services(answer)
    first = policy.check_write(source, 'file.txt', FRAGMENT, 'edit_file')
    again = policy.check_write(source, 'file.txt', FRAGMENT, 'edit_file')
    assert (first is None) == allowed
    assert again == first
    state = source.session.return_value.state
    if allowed:
        source.ask.assert_called_once()
        assert state.approved == {('file.txt', hashlib.sha1(FRAGMENT.encode()).hexdigest()): 'WHOLE_FILE'}
    else:
        assert source.ask.call_count == 2 and state.approved == {}
        assert first['bytes'] == CURRENT.encode() and not first.get('land')
        assert 'edit_file' in first['text'] and 'block 0:' in first['text']
    question = source.ask.call_args.args[0]
    assert FRAGMENT in question and 'file.txt' in question
    assert source.ask.call_args.kwargs == {
        'phase': 'write-shrink', 'max_tokens': wholefile.JUDGE_MAX_TOKENS, 'retry_off': False}
    assert all(fields['assist_id'] == 'shrinking-file-protection' and fields['family_id'] == 'F15'
               for _, fields in source.log.events)


def test_removal_facts_require_original_baseline_but_fragments_do_not():
    for baseline in (None, (), ('created-later.txt',)):
        source = services(baseline=baseline)
        assert policy.check_write(source, 'file.txt', REMOVAL) is None
        assert policy.check_write(source, 'file.txt', FRAGMENT) is not None
        source.ask.assert_called_once()
    source = services()
    finding = policy.check_write(source, 'file.txt', REMOVAL)
    assert finding['land'] is True and finding['bytes'] == CURRENT.encode()
    assert 'removed' in finding['text'] and 'block 0:' in finding['text']
    source.ask.assert_not_called()
    assert source.session.return_value.state.approved == {}


@pytest.mark.parametrize('view', [View(raw=None), View(exists=None), View(exists=False),
                                SimpleNamespace(surveyed=False)])
def test_unknown_or_unreadable_views_are_silent(view):
    source = services()
    source.view.return_value = view
    assert policy.check_write(source, 'file.txt', FRAGMENT) is None
    source.ask.assert_not_called()
    assert source.log.events == [] and source.session.return_value.state.approved == {}


def test_no_session_path_or_reasoner_does_not_measure_or_judge(monkeypatch):
    measure = Mock(side_effect=AssertionError('unexpected measurement'))
    monkeypatch.setattr(policy, 'shrink_measure', measure)
    source = services()
    source.session.return_value = None
    assert policy.check_write(source, 'file.txt', FRAGMENT) is None
    assert policy.check_write(services(), '', FRAGMENT) is None
    no_reasoner = replace(services(), ask=None)
    assert policy.check_write(no_reasoner, 'file.txt', REMOVAL) is None
    no_reasoner.session.assert_not_called()
    no_reasoner.view.assert_not_called()
    measure.assert_not_called()


def test_disabled_and_replaced_definition_bypass_all_owned_policy(monkeypatch):
    gather = Mock(side_effect=AssertionError('disabled gathered'))
    assert policy.run_selected(None, gather, 'original command') == 'original command'
    gather.assert_not_called()
    source = services()
    execute = Mock(return_value='replacement command')
    definition = replace(policy.DEFINITION, execute=execute)
    actual_call = call(source)
    assert policy.run_selected(definition, lambda: actual_call, 'original') == 'replacement command'
    execute.assert_called_once_with(actual_call, 'original')
    source.session.assert_not_called()
    source.view.assert_not_called()
    source.ask.assert_not_called()
    # The same definition projects into the existing production mutation stage.
    stages = ToolStages.from_definitions((definition,))
    assert stages.mutation_command(actual_call, 'original') == 'replacement command'
    assert ToolStages.from_definitions(()).mutation_command(actual_call, 'original') == 'original'


def test_real_workspace_reader_supplies_observed_bytes_without_policy_callback(tmp_path):
    from cria import wsview
    from wsfixture import survey
    view = wsview.View(str(tmp_path), 'shrink-source')
    assert wsview.apply_survey(view, survey(f'F\t1\t{len(CURRENT.encode())}\tfile.txt',
                                          root=str(tmp_path), complete=True))
    view.note_read('file.txt', CURRENT)
    source = replace(services(), view=Mock(return_value=view))
    actual = call(source)
    poison = Mock(side_effect=AssertionError('legacy whole-policy callback was invoked'))
    actual = replace(actual, request=replace(actual.request, shrink_check=poison))
    assert policy.DEFINITION.execute(actual, 'original') != 'original'
    poison.assert_not_called()
    assert policy.check_write(source, 'file.txt', FRAGMENT)['bytes'] == view.read_bytes('file.txt') == CURRENT.encode()


@pytest.mark.parametrize('mode', ['wrong-tool', 'no-services', 'no-reasoner'])
def test_unavailable_services_and_nonwrites_never_prepare_or_gather(monkeypatch, mode):
    source = services()
    actual = call(source)
    if mode == 'wrong-tool':
        actual = replace(actual, call={'function': {'name': 'read_file'}})
    elif mode == 'no-services':
        actual = replace(actual, request=replace(actual.request, shrink_services=None))
    else:
        actual = replace(actual, request=replace(actual.request, shrink_services=replace(source, ask=None)))
    prepare = Mock(side_effect=AssertionError('unexpected mutation preparation'))
    monkeypatch.setattr(writeproxy, '_prepare_file_mutation', prepare)
    assert policy.DEFINITION.execute(actual, 'original') == 'original'
    source.session.assert_not_called()
    source.view.assert_not_called()
    source.ask.assert_not_called()
    prepare.assert_not_called()


def test_cache_is_candidate_bound_and_transient_not_cleared_by_compaction_or_current_bytes():
    source = services('WHOLE_FILE')
    policy.check_write(source, 'file.txt', FRAGMENT)
    source.view.return_value.raw = (CURRENT + 'different current bytes\n').encode()
    assert policy.check_write(source, 'file.txt', FRAGMENT) is None
    assert source.ask.call_count == 1  # historical affirmative key is path + candidate, not baseline bytes
    policy.check_write(source, 'file.txt', FRAGMENT + 'changed\n')
    assert source.ask.call_count == 2
    state = source.session.return_value.state
    state.reset()
    policy.check_write(source, 'file.txt', FRAGMENT)
    assert source.ask.call_count == 3
    source.session.return_value = policy.ShrinkSession(('file.txt',), policy.ShrinkState())
    policy.check_write(source, 'file.txt', FRAGMENT)
    assert source.ask.call_count == 4


def test_provider_failure_does_not_cache_or_fabricate_hold():
    source = services()
    source.ask.side_effect = RuntimeError('reader unavailable')
    with pytest.raises(RuntimeError, match='reader unavailable'):
        policy.check_write(source, 'file.txt', FRAGMENT)
    assert source.session.return_value.state.approved == {} and source.log.events == []


@pytest.mark.parametrize('land,stale,fail', [(False, False, False), (False, True, False),
    (True, False, False), (True, True, False), (True, False, True)])
def test_byte_settlement_runs_stale_writes_and_only_emits_successful_current_facts(tmp_path, land, stale, fail):
    target = tmp_path / 'file.txt'
    target.write_text(CURRENT)
    source = services()
    candidate = REMOVAL if land else FRAGMENT
    args = json.dumps({'path': str(target), 'content': candidate})
    rcpt = denial.receipt_for('c1', 'write_file', args)
    with denial.receipt_scope(rcpt):             # composed for THIS call, as the compiler does: the program prints its records
        command = 'false' if fail else writeproxy._write_command(str(target), candidate)
        wrapped = policy.DEFINITION.execute(call(source, candidate, str(target)), command)
    assert wrapped != command
    if stale:
        target.write_text('disk has changed since survey')
    run = subprocess.run(['bash', '-c', wrapped], capture_output=True, text=True, timeout=10)
    if not land and not stale:
        from tests.resultshape import leading_frame
        kind, lead = leading_frame(run.stdout, rcpt)
        assert run.returncode != 0 and kind == denial.REFUSED and run.stdout[len(lead):].startswith('⟦ctx:denied⟧')
        assert target.read_text() == CURRENT
    elif fail:
        assert run.returncode != 0 and target.read_text() == CURRENT
        assert '"rm":' not in run.stdout
    else:
        assert run.returncode == 0 and target.read_text() == candidate
        assert ('"rm":' in run.stdout) == (land and not stale)       # the measured facts: a typed field of the landed record
    # Real result representation must preserve either denial or landed facts.
    full_command = toolwire._sentinel('write_file', args, rcpt) + '\n' + wrapped
    tc = {'id': 'c1', 'type': 'function', 'function': {'name': 'exec_command', 'arguments': json.dumps({'cmd': full_command})}}
    history = [{'role': 'assistant', 'tool_calls': [tc]},
               {'role': 'tool', 'tool_call_id': 'c1', 'content': run.stdout + run.stderr}]
    represented = writeproxy.represent_inbound(history, workspace_root=str(tmp_path))[-1]['content']
    if land and not stale and not fail:
        assert 'removed at least' in represented and 'block 0:' in represented
    if not land and not stale:
        assert 'Wrote' not in represented


def captured(fixture, suffix):
    root = Path(__file__).parent / 'fixtures'
    comp = json.loads((root / fixture).read_text())
    for tc in comp['choices'][0]['message']['tool_calls']:
        arguments = json.loads(tc['function']['arguments'])
        if tc['function']['name'] == 'write_file' and arguments['path'].endswith(suffix):
            return arguments['content']
    raise AssertionError(suffix)


def test_imported_capture_payloads_preserve_fragment_removal_distinction():
    root = Path(__file__).resolve().parents[1]
    seed = root / 'suite/tasks/feed-pipeline-java/seed'
    pom = (seed / 'pom.xml').read_text()
    java = (seed / 'src/main/java/pipeline/Importer.java').read_text()
    assert policy.shrink_measure(pom, captured('phi4_java_a4/0009-reply.json', 'pom.xml'))['fragment']
    assert policy.shrink_measure(java, captured('phi4_java_a3/0011-reply.json', 'Importer.java'))['fragment']
    removal = policy.shrink_measure(java, captured('phi4_java_a9/0010-reply.json', 'Importer.java'))
    assert not removal['fragment'] and removal['cand_lines'] * 2 > removal['current_lines']
    assert any('summarize' in line for _, line in removal['openers'])
    for name in ('lookup.js', 'Gemfile'):
        fixtures = root / 'tests/fixtures/h2_corpus'
        current, candidate = [(fixtures / f'{name}.{kind}').read_text() for kind in ('current', 'rewrite')]
        source = services(raw=current.encode())
        finding = policy.check_write(source, 'file.txt', candidate)
        assert finding['land'] is True
        source.ask.assert_not_called()


def test_multiset_units_indentation_bounds_and_small_or_additive_writes():
    measured = policy.shrink_measure('x\n' * 10, 'x\nx\n')
    assert measured['current_lines'] == 10 and measured['distinct'] == 1
    assert measured['removed_at_least'] == 8 and not measured['fragment']
    assert policy.shrink_measure('a\nb\nc\n', FRAGMENT) is None
    assert policy.shrink_measure(CURRENT, CURRENT + 'added\n') is None
    assert policy.shrink_measure(CURRENT, CURRENT.replace('value 0', 'changed')) is None
    many = ''.join(f'outer{i}\n    nested{i}\n        detail{i}\n' for i in range(20))
    measured = policy.shrink_measure(many, FRAGMENT)
    assert len(measured['openers']) == policy.SHRINK_OPENERS_MAX
    assert measured['openers_total'] == 40
    assert all(text.startswith('outer') for _, text in measured['openers'])
    assert [no for no, _ in measured['openers']] == sorted(no for no, _ in measured['openers'])


@pytest.mark.parametrize('answer,verdict', [('`WHOLE_FILE` yes', 'WHOLE_FILE'), ('OTHER.', 'OTHER'),
    ('NOT_WHOLE_FILE', 'NOT_WHOLE_FILE'), ('WHOLE_FILE_MAYBE', 'WHOLE_FILE_MAYBE'),
    ('mentions WHOLE_FILE', 'MENTIONS WHOLE_FILE'), ('', '')])
def test_shared_reader_is_the_actual_imported_parser_and_question_pipeline(answer, verdict):
    assert policy.judge_whole_file is wholefile.judge_whole_file
    ask = Mock(return_value=answer)
    assert wholefile.judge_whole_file(ask, 'complete caller-specific question', phase='text-write') == verdict
    ask.assert_called_once_with('complete caller-specific question', phase='text-write',
                               max_tokens=wholefile.JUDGE_MAX_TOKENS, retry_off=False)


def test_real_closed_reader_retains_role_temperature_budget_and_single_empty_call():
    from cria import loop
    from cria.config import Role
    seen = []
    def chat(body, log):
        seen.append(body)
        return json.dumps({'choices': [{'message': {'content': ''}}]}).encode()
    source = services()
    def ask(question, **options):
        return loop.ask_closed(chat, Role(name='reasoner', backend='local'), question, source.log, **options)
    source = replace(source, ask=ask)
    assert policy.check_write(source, 'file.txt', FRAGMENT) is not None
    assert len(seen) == 1 and seen[0]['temperature'] == 0.0
    assert seen[0]['max_tokens'] == wholefile.JUDGE_MAX_TOKENS
    assert source.session.return_value.state.approved == {}


def test_metadata_references_actual_source_hooks_tests_and_prompts():
    assert policy.DEFINITION.execute is policy.shrinking_replacement
    assert policy.DEFINITION.policy.id == 'shrinking-file-protection'
    assert policy.DEFINITION.policy.family_id == 'F15'
    assert policy.DEFINITION.policy.migrated is False
    root = Path(__file__).resolve().parents[1]
    for ref in policy.DEFINITION.policy.hooks + policy.DEFINITION.policy.regressions:
        body = ast.parse((root / ref.path).read_text()).body
        for name in ref.symbol.split('.'):
            node = next(n for n in body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name)
            body = node.body
    for prompt in policy.DEFINITION.policy.prompts:
        assert (root / 'cria/prompts' / (prompt + '.txt')).is_file()
