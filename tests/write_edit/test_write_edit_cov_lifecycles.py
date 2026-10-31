"""Write-path lifecycles: cria.pastedfile (a whole file pasted into chat -> that file's write, or one bounded nudge) with cria.wholefile (the
WHOLE_FILE/OTHER reader); cria.historyarguments (replayed malformed tool arguments are always valid JSON, never silently dropped); cria.toolargs
(the one argument/path parser), cria.toolcontracts (event attribution) and cria.returnedpolicies (notes added to returned tool results)."""
import json
import os
import re
from types import SimpleNamespace
import pytest
from cria import bodykeys, denial, depsurface, editrecovery, historyarguments as ha, payloadboundary, pastedfile as pf, returnedpolicies as rp, toolargs, writeproxy
from cria.assistcontract import Policy
from cria.toolcontracts import ReturnedResult, policy_log
from cria.wholefile import whole_file_ruling
from write_edit_helpers import ENVELOPE, write_edit_workspace_view  # noqa: F401  (autouse: the workspace view is this machine's disk)

BODY = [f'value_{i} = compute({i}) + offset_{i}' for i in range(14)]      # >= FILE_LINES non-blank lines
TOOLS = [{'type': 'function', 'function': {'name': 'write_file', 'parameters': {'type': 'object', 'required': ['path', 'content'],
         'properties': {'path': {'type': 'string'}, 'content': {'type': 'string'}}}}}]

def reply(lines=BODY, name='app.py', close=True):
    return {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant',
            'content': f'Here is the file `{name}`:\n```python\n' + '\n'.join(lines) + ('\n```\nDone.' if close else '')}}]}

class View:
    surveyed = complete = True
    folded = False
    def __init__(self, files=None, dirs=('src',)): self.disk, self.dirs = files or {}, set(dirs)
    def rel(self, p): return None if p.startswith('/') or p.startswith('..') else p
    def abs(self, p): return '/w/' + p
    def isdir(self, p): return p in self.dirs
    def isfile(self, p): return p in self.disk
    def files(self): return [SimpleNamespace(path=p) for p in self.disk]
    def read(self, p): return self.disk.get(p)
    def size(self, p): return len(self.disk[p])

class Log:
    def __init__(self): self.events = []
    def emit(self, kind, **f): self.events.append((kind, f))

def source(view, completion=None, injected=(), seen=True, asked=None, task=''):
    ev = pf.Evidence(lambda c: c['choices'][0]['message']['content'], lambda c: bool(c['choices'][0]['message'].get('tool_calls')), lambda m: list(injected),
                     lambda root: view, lambda m: '/w', lambda m: task, lambda rel, t: rel in t, lambda v, rel, m: seen, lambda v, rel, m: 'UNREAD')
    ask = lambda q, **k: (asked.append(q), 'WHOLE_FILE')[1]
    return pf.RecoveryInput(completion or reply(), TOOLS, [], task, '/w', False, ev, ask, Log())

@pytest.mark.parametrize('name,files,task,want', [
    ('/etc/passwd', {}, '', 'outside_workspace'), ('src', {}, '', 'names_a_directory'), ('app.py', {'app.py': 'x'}, '', ('app.py', True)),
    ('util.py', {'a/util.py': 'x', 'b/util.py': 'y'}, '', 'ambiguous_path'), ('util.py', {'a/util.py': 'x'}, '', ('a/util.py', True)),
    ('new.py', {}, 'write something', 'unnamed_new_file'), ('new.py', {}, 'create new.py', ('new.py', False)),
    ('nodir/new.py', {}, 'create nodir/new.py', 'unknown_parent'), ('src/new.py', {}, 'create src/new.py', ('src/new.py', False)),
])
def test_a_pasted_files_path_is_chosen_from_the_workspace_never_guessed(name, files, task, want):
    """A name resolves only to an existing file, or to a new file the TASK itself names under a known directory."""
    assert pf.resolve_named_file(View(files), name, task, lambda rel, t: rel in t) == want

def test_a_paste_that_quotes_shown_text_or_changes_nothing_is_refused_before_any_question_is_asked():
    """A reply that re-quotes a fence the coder was shown, or pastes the file already on disk, is no write: withheld with a reason, judge never asked."""
    for view, injected, why in [(View({'app.py': 'x'}), ['\n'.join(BODY)], 'quote_of_shown_text'), (View({'app.py': '\n'.join(BODY) + '\n'}), [], 'unchanged')]:
        asked = []; src = source(view, injected=injected, asked=asked); result = pf.recover(src, pf.State())
        assert result.status is pf.Status.WITHHELD and result.reason == why and not asked and result.completion is src.completion
        assert src.log.events[0][0] == 'loop.text_write_refused'
    asked = []; assert pf.recover(source(View({'app.py': 'old'}), asked=asked), pf.State()).status is pf.Status.PREPARED and len(asked) == 1
    asked = []; menu = source(View({'app.py': 'old'}), asked=asked); bare = pf.RecoveryInput(**{**menu.__dict__, 'tools': [{'type': 'function', 'function': {'name': 'read_file', 'parameters': {}}}]})
    assert pf.recover(bare, pf.State()).status is pf.Status.UNCHANGED and not asked                      # no whole-file write tool on the menu: nothing to promote to

@pytest.mark.parametrize('content,injected,want', [
    ('```python\n' + '\n'.join(BODY) + '\n```', [], True), ('```python\n' + '\n'.join(BODY[:11]) + '\n```', [], False),
    ('```python\n' + '\n'.join(BODY), [], True), ('```python\n' + '\n'.join(BODY) + '\n```', ['\n'.join(BODY)], False),
    ('```\n' + '\n'.join(BODY) + '\n```', [], True), ('no fence ' * 50, [], False)])
def test_unsaved_text_means_a_long_unquoted_fenced_file_even_when_the_reply_was_cut_off(content, injected, want):
    """The nudge fires for a >=12-line fence (closed or truncated) unless it merely repeats shown text."""
    assert pf.unsaved_text(content, injected) is want

def test_unexecuted_write_nudges_are_bounded_by_the_shared_budget_and_carry_the_whole_reply():
    """At most MAX_NUDGES redrives per shared budget (already-spent budget counts); the nudge carries the full reply and names the one file."""
    src = source(View()); budget = SimpleNamespace(unexecuted_nudges=0); state = pf.State()
    nudge = lambda: pf.redrive(pf.NudgeInput(src.completion, [], src.evidence, budget, src.log), state)
    statuses = [nudge().status for _ in range(3)]
    assert statuses == [pf.Status.NUDGE, pf.Status.NUDGE, pf.Status.UNCHANGED] and budget.unexecuted_nudges == 2
    first = pf.redrive(pf.NudgeInput(src.completion, [], src.evidence, SimpleNamespace(unexecuted_nudges=1), src.log), pf.State())
    assert first.status is pf.Status.NUDGE and first.nudge.carried_reply == src.completion['choices'][0]['message']['content'] and '`app.py`' in first.nudge.text
    assert pf.redrive(pf.NudgeInput(src.completion, [], src.evidence, SimpleNamespace(unexecuted_nudges=2), src.log), pf.State()).status is pf.Status.UNCHANGED

def test_a_prepared_write_is_settled_once_and_only_by_its_own_call_ids():
    """Prepared is not a write that ran: forwarding needs the real call ids, an unrelated completion changes nothing, and settlement is one-shot."""
    call = {'id': 'c1', 'type': 'function', 'function': {'name': 'write_file', 'arguments': '{}'}}
    done = {'choices': [{'message': {'tool_calls': [call]}}]}; prep = pf.Prepared('app.py', 'x\n', call, done, ('c1',)); state = pf.State(prepared=prep)
    other = {'choices': [{'message': {'tool_calls': [{**call, 'id': 'zzz'}]}}]}
    assert pf.forwarded(state, prep, other).reason == 'unrelated_completion' and state.prepared is prep
    sent = pf.forwarded(state, prep, done); assert sent.status is pf.Status.FORWARDED and state.prepared is None and 'c1' in state.deliveries
    assert pf.settle(state, sent.delivery, 'nope', ran=True, changed=True).status is pf.Status.UNCHANGED
    first = pf.settle(state, sent.delivery, 'c1', ran=True, changed=False)
    assert first.status is pf.Status.SETTLED and (first.settlement.ran, first.settlement.changed) == (True, False)
    assert pf.settle(state, sent.delivery, 'c1', ran=True, changed=True).status is pf.Status.UNCHANGED and state.settlements['c1'].changed is False
    state2 = pf.State(prepared=prep); empty = {'choices': [{'message': {'content': 'ok'}}]}
    assert pf.forwarded(state2, prep, empty).reason == 'no_forwarded_call' and state2.prepared is None and not state2.deliveries

@pytest.mark.parametrize('answer,want', [('WHOLE_FILE', 'WHOLE_FILE'), ('whole_file.', 'WHOLE_FILE'), ('**OTHER**: an excerpt', 'OTHER'),
                                          ('The answer is WHOLE_FILE', 'THE ANSWER IS WHOLE_FILE'), ('', '')])
def test_the_whole_file_ruling_reads_only_the_first_word(answer, want):
    """A verdict buried in prose is not a ruling (it stays unparsed, never WHOLE_FILE), so a wordy judge cannot authorize a write."""
    assert whole_file_ruling(answer) == want

def history(*raws):
    return [{'role': 'assistant', 'tool_calls': [{'id': str(i), 'function': {'name': 'write_file', 'arguments': raw}} for i, raw in enumerate(raws)]}]

def sent(messages): return [c['function']['arguments'] for c in messages[0]['tool_calls']]

def test_replayed_malformed_arguments_are_recovered_or_enveloped_losslessly_and_valid_ones_stay_byte_for_byte():
    """Valid JSON (even scalars/{}) is never touched; malformed text becomes a recovered object, or {"_unparsed": original} when recovery is off,
    absent, or recovers nothing; the event says which. History must stay valid JSON on the wire without losing the model's text."""
    raw_newline, trailing, garbage = '{"path":"a.py","content":"raw\nnewline"}', '{"a": 1} trailing', 'not json at all'
    log = []; emit = SimpleNamespace(emit=lambda kind, **f: log.append((kind, f)))
    out = ha.prepare_history(history('null', '{}', '[1]', raw_newline, trailing, garbage), emit, definition=ha.DEFINITION)
    assert sent(out)[:3] == ['null', '{}', '[1]'] and json.loads(sent(out)[3]) == {'path': 'a.py', 'content': 'raw\nnewline'} and json.loads(sent(out)[4]) == {'a': 1}
    assert json.loads(sent(out)[5]) == {'_unparsed': garbage} and log == [('massage.history_args_repaired', {'count': 3, 'assist_id': ha.DEFINITION.policy.id, 'family_id': 'F06'})]
    for kwargs in ({'definition': None}, {'definition': ha.DEFINITION, 'recover': False}):
        log.clear(); off = ha.prepare_history(history(raw_newline, garbage), emit, **kwargs)
        assert [json.loads(a) for a in sent(off)] == [{'_unparsed': raw_newline}, {'_unparsed': garbage}] and log == [('upstream.history_args_enveloped', {'count': 2})]
    assert ha.recover_arguments(ha.HistoricalArguments(('{} trailing', trailing, garbage))).values == (None, {'a': 1}, None)     # {} conveys none of the call
    empty = ha.HistoricalDefinition(ha.DEFINITION.policy, lambda src: ha.RecoveredArguments(tuple({} for _ in src.values)))
    assert json.loads(sent(ha.prepare_history(history(garbage), definition=empty))[0]) == {'_unparsed': garbage}      # {} says nothing of the original
    short = ha.HistoricalDefinition(ha.DEFINITION.policy, lambda src: ha.RecoveredArguments(()))
    with pytest.raises(ValueError): ha.prepare_history(history(garbage), definition=short)

@pytest.mark.parametrize('args,want_args,want_path', [
    ('{"path": "a\nb"}', {'path': 'a\nb'}, 'a\nb'), ('{"content": "x\ny"}', {'content': 'x\ny'}, None),      # a raw control char in a string value is tolerated
    ('nope', {}, None), ('[1]', {}, None), (None, {}, None), ({'file_path': 'p', 'path': 'q'}, {'file_path': 'p', 'path': 'q'}, 'q'),
    ('{"path": "", "file": "x.py"}', {'path': '', 'file': 'x.py'}, 'x.py'), ({'file': 'a', 'file_path': 'b'}, {'file': 'a', 'file_path': 'b'}, 'b'), ('{"filename": "z"}', {'filename': 'z'}, 'z')])
def test_tool_arguments_parse_leniently_and_the_target_path_comes_from_the_first_present_alias(args, want_args, want_path):
    """parse_args never raises (control chars tolerated, non-objects -> {}); tool_path prefers path > file_path > file > filename and skips empty values."""
    assert toolargs.parse_args(args) == want_args and toolargs.tool_path(args) == want_path

@pytest.mark.parametrize('name,whole', [('write_file', True), ('create_file', True), ('text_editor', True), ('edit_file', False), ('apply_patch', False), ('str_replace_editor', False)])
def test_only_whole_file_writes_supersede_earlier_writes_and_non_writes_have_no_target(name, whole):
    """An edit is a change to a file, not a version of it: write_target reports replaces_whole_file only for whole-file writes."""
    call = {'function': {'name': name, 'arguments': '{"file_path": "m.py"}'}}
    assert toolargs.write_target(call) == ('m.py', whole) and toolargs.write_path(call) == 'm.py'
    assert toolargs.write_target({'function': {'name': 'read_file', 'arguments': '{"path": "m.py"}'}}) == ('', False)

def test_policy_log_stamps_assist_and_family_unless_a_nested_policy_already_attributed_the_event():
    """Events carry the emitting policy's identity by default; a nested source-owned policy keeps its own; no log stays no log."""
    seen = []; target = SimpleNamespace(emit=lambda kind, **f: seen.append((kind, f)))
    log = policy_log(target, Policy('outer', 'stage', 2, family_id='F01'))
    log.emit('a'); log.emit('b', assist_id='inner', family_id='F99')
    assert seen == [('a', {'assist_id': 'outer', 'family_id': 'F01'}), ('b', {'assist_id': 'inner', 'family_id': 'F99'})] and policy_log(None, Policy('x', 'y', 1)) is None

@pytest.fixture
def go_deps(tmp_path, monkeypatch):
    """Five declared Go dependencies whose module cache holds 600 functions each; session-global note state is fresh per test."""
    home, ws = tmp_path / 'home', tmp_path / 'ws'; ws.mkdir()
    monkeypatch.setattr(os.path, 'expanduser', lambda p: str(home) + p[1:] if p.startswith('~') else p)
    for name in ('_ANCHOR', '_WITHHELD', '_ABSTAINED'): monkeypatch.setattr(depsurface, name, {})
    (ws / 'go.mod').write_text('module example.com/cart\n\ngo 1.21\n\n' + ''.join(f'require example.invalid/p{i} v1.0.0\n' for i in range(5)))
    for i in range(5):
        d = home / f'go/pkg/mod/example.invalid/p{i}@v1.0.0'; d.mkdir(parents=True)
        (d / 'd.go').write_text('package d\n\n' + ''.join(f'func Fn{j}Of{i}(v string) int {{\n\treturn 1\n}}\n\n' for j in range(600)))
    return ws

def dependency_notes(ws, window):
    out = writeproxy.represent_inbound([{'role': 'tool', 'tool_call_id': 'c1', 'content': 'build ok'}], workspace_root=str(ws), sess_key=f'w{window}', tools_present=True, window=window)
    text = out[0]['content']; return text.count('DECLARED IN'), len(re.findall(r'^func ', text, re.M)), 'will NOT appear' in text

def test_dependency_note_budgets_are_shares_of_the_coders_window_and_what_does_not_fit_is_pointed_at_not_promised(go_deps, monkeypatch):
    """A small window shrinks each surface AND the per-request total (one note, the rest named as withheld with a real read command); the reference window
    (unknown) fits three new notes per request; a large window shows more members. Never gathered beyond _MAX_NOTES_PER_REQUEST new coordinates."""
    small, ref, large = dependency_notes(go_deps, 4096), dependency_notes(go_deps, None), dependency_notes(go_deps, 98304)
    gathered = []; real = depsurface.gather
    monkeypatch.setattr(depsurface, 'gather', lambda eco, pkg, ver, *a, **k: (gathered.append(pkg), real(eco, pkg, ver, *a, **k))[1])
    dependency_notes(go_deps, 4096); dependency_notes(go_deps, 4096)                                       # same session again: withheld coordinates are never re-gathered
    assert len(gathered) == len(set(gathered)) == 2
    assert small[0] == 1 and small[2] and ref[0] == large[0] == 3 and not ref[2] and not large[2]
    assert small[1] < ref[1] < large[1]

def shell_turns(root, *pairs):
    msgs = []
    for i, (cmd, out) in enumerate(pairs):
        msgs += [{'role': 'assistant', 'tool_calls': [{'id': f'c{i}', 'type': 'function', 'function': {'name': 'exec_command', 'arguments': json.dumps({'cmd': cmd})}}]},
                 {'role': 'tool', 'tool_call_id': f'c{i}', 'content': ENVELOPE.format(rc=1) + out}]
    return [m['content'] for m in writeproxy.represent_inbound(msgs, workspace_root=str(root)) if m['role'] == 'tool']

def test_a_missing_dependency_is_noted_on_the_latest_failing_result_only_and_never_for_the_projects_own_file(tmp_path):
    """ruby run 39x `cannot load such file` and the note was repeated 39 times / never for the model's own command: label the LAST occurrence once;
    a require that resolves to the project's own lib file is not a missing gem."""
    miss = "a.rb:1:in 'require': cannot load such file -- unaccent (LoadError)\n"; (tmp_path / 'lib').mkdir(); (tmp_path / 'lib/europe.rb').write_text('x\n')
    first, last = shell_turns(tmp_path, ('ruby -Ilib a.rb', miss), ('ruby -Ilib b.rb', miss))
    assert 'not installed anywhere' not in first and 'unaccent' in last and 'not installed anywhere' in last
    own, = shell_turns(tmp_path, ('ruby a.rb', "a.rb:1:in 'require': cannot load such file -- europe (LoadError)\n"))
    assert own.endswith('(LoadError)\n') and 'Note:' not in own

def test_edit_recovery_and_environment_advice_act_only_on_proven_unapplied_edits_and_non_mutation_results():
    """An edit-miss report is rewritten into a directive only when cria PROVED the edit unapplied; a PEP 668 refusal gets its remedy unless the failing call was a write/edit."""
    report = editrecovery.EDITFAIL + '{}'; tool = {'role': 'tool', 'tool_call_id': '1', 'content': report}
    assert rp.edit_failure(ReturnedResult(tool, report, '', [], mutation_failure=True)) is None and rp.edit_failure(ReturnedResult({**tool, bodykeys.RESULT_OUTCOME: denial.UNAPPLIED}, report, '', [])) is None
    fixed = rp.edit_failure(ReturnedResult({**tool, bodykeys.RESULT_OUTCOME: denial.UNAPPLIED}, report, '', [], mutation_failure=True))
    assert fixed['content'] != report and 'NOT APPLIED' in fixed['content']
    pip = {'role': 'tool', 'tool_call_id': '1', 'content': 'error: externally-managed-environment\n'}
    assert 'PEP 668' in rp.environment_advice(ReturnedResult(pip, pip['content'], 'pip install x', []))['content']
    assert rp.environment_advice(ReturnedResult(pip, pip['content'], 'pip install x', [], mutation_failure=True)) is None

@pytest.mark.parametrize('boundary,content,want', [
    (None, 'tool bytes + cria note', 'tool bytes + cria note'),                                  # nothing ever appended: the whole content
    ('verified', 'tool bytes\n\nnote', 'tool bytes'),                                            # stamped length+digest still true: cut there
    ('tampered', 'tool BYTES\n\nnote', None), ('past-end', 'tool', None), ('malformed', 'tool bytes\n\nnote', None)])
def test_the_tools_own_payload_is_what_a_stamped_boundary_still_verifies_else_unknown(boundary, content, want):
    """A reader that counts or quotes only the tool's bytes gets them when length AND digest still hold, and abstains (None) once the content changed."""
    stamp = {'verified': (10, payloadboundary.digest('tool bytes')), 'tampered': (10, payloadboundary.digest('tool bytes')),
             'past-end': (99, payloadboundary.digest('tool')), 'malformed': [10]}.get(boundary)
    assert payloadboundary.payload_of({bodykeys.PAYLOAD_BOUNDARY: stamp} if boundary else {}, content) == want
