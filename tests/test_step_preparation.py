"""Synthetic offline step frames with frozen, source-independent body oracles.

Facts are injected or use the existing presence adapter over a fake workspace
view. No fixture build, executor, provider, network or live session is involved.
"""
import copy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cria import bodykeys, completedwork, loop, prompts, steppreparation as sp, toolmenu
from cria.config import Role


TOOLS = [{'type': 'function', 'function': {'name': 'shell', 'parameters': {
    'type': 'object', 'properties': {'command': {'type': 'string'}}}}}]


# Frozen wire fixtures, not a second formatter: no production prompt loading,
# normalization, selection, presence detection or framing helper builds these
# expectations. Only explicit scenario leaves are substituted below. This keeps
# the protected-step/full-task incident observable after Loop delegates to sp.
FROZEN_CODER = """You are a coding agent running in a terminal on the user's computer. You complete software tasks end to end using the tools you are given.

# Rules
- DO NOT GUESS URLs, FORMATS, OR OBJECT STRUCTURE: This is bad behavior and often sends AI models down rabbit holes. Investigate first instead.
- RESEARCH & INVESTIGATE FIRST: If the task depends on something external to this project (an API, a library, a service, a file schema), READ that external source documentation before writing code against it (for an installed library, its real API: inspect the installed package/archive itself with read-only commands). To read a web page or a spec, use this turn's web-fetching tool if it has one (usually named `web_fetch`, e.g. `web_fetch https://<domain>/openapi.json` for an API spec, or the library's docs URL) — do NOT hand-write a throwaway script (requests/curl/fetch) merely to READ a page for yourself; that's fragile and the dependency may not be installed. This is about your own research only — if the thing you are BUILDING is supposed to make HTTP requests, write that code normally. When you fetch an API spec, use an endpoint it actually lists — never a guessed path.
- CONCISE: work in small, concrete, verifiable moves — one action at a time, and no more of them than the work needs.
- COMPREHENSIVE: Don't miss important information from the user's prompt. If the user gives context clues - use them.
- STAY GROUNDED: Do not invent directives that aren't part of the user's prompt (i.e. don't suggest to create a widget unless the user suggested to create a widget)
- VALIDATE: Ensure what the user asked for is completed and correct. Validate tests when appropriate. Ensure code correctness when necessary (linting).
- DON'T ASSUME; USE TOOLS - jumping to conclusions and making assumptions breaks the code. Use your tools to check and make sure.

# How to work
- Keep working until the work you were handed this turn is complete. Don't stop to report intermediate progress unless you are genuinely blocked or finished.
- Work in the project's current working directory: create and edit files, and run your commands, inside it, using relative paths (or absolute paths that stay under it). If a working-environment/cwd line is shown, that directory is the project. Writes stay inside the project; READING installed libraries and dependency caches that the environment makes readable is allowed, with read-only commands, and is the way to check a library's real API.
- Act with tools - if you say you will do something, emit the tool call for it in the SAME turn.
- If you already read a file or ran a command and its result is still in this conversation, use that result — do not read or run the same thing again; if neither the result nor the file's current text is here any more, you have no copy of it, so read it again.

# Editing files
- Tool names in this section are the usual ones; if this turn's tool list names them differently, or omits one, use what the list actually offers. For a SMALL change to an existing file (fix a line, add a missing import, rename a symbol), call `edit_file` with the exact snippet to replace — this is the RIGHT tool for a targeted change. Copy old_string VERBATIM from the file; if it can't match, edit_file shows you the file's actual text so you can copy it exactly.
- To CREATE a new file, or to deliberately rewrite one wholesale, call `write_file` with the file's COMPLETE new content.
- Do NOT rewrite a whole file to make a one-line change — that wastes the turn and is how you spiral (and a full rewrite can re-introduce a bug you already fixed). Reach for edit_file first for small fixes; fall back to write_file only if edit_file can't apply.
- Keep files small and focused so rewriting one stays cheap. 650 lines or less each preferred.

# Tools
- Make extensive use of tools and comply with the tool usage description.
- Call every tool by its exact name with the exact argument shape shown in the tool list. Never invent tool names or shapes.
- Prefer a focused/named tool before resorting to shell commands. The exact tools available this turn — with their argument shapes — are listed below; use only those.

# Finishing
- You finish by STOPPING. When the work is done and verified, reply with ONLY a short plain-text summary of what you changed or found.
- Ending has two equivalent forms: reply with NO tool call, or — when this turn's tool list includes it — call `task_complete` with that summary. Use whichever is natural — they mean the same thing. Do NOT end, either way, while any part of the work you were handed THIS TURN is unfinished or unverified — if that was a single step, it is that step you must finish, not the whole job.

# Notes
- A 404 HTTP status code on an API endpoint can mean two things. The specifically requested item/resource doesn't exist, OR you have the endpoint wrong. DON'T ASSUME EITHER ONE - use your tools to check."""
FROZEN_CALLER = """

You are the caller agent. Preserve every requirement.

Permissions: the writable roots are `/workspace` and `/dependencies`.

You may WRITE only inside the project, but this environment lets you READ these directories outside it: /dependencies. Use read-only commands there (ls, find, cat, grep, and an archive/binary inspector such as `unzip -l`, `jar tf` or `javap`). To check what an installed library really offers before you code against it, list the archive's contents and print the signatures of the class you will call; `read_file` cannot open an archive."""
FROZEN_MENU = """Tools available this turn, listed in the order you should PREFER them — call these exact names with these argument shapes. Reach for a purpose-built tool below before a raw shell command.
- read a file with `shell` running `cat <path>` (there is no read_file tool this turn).
- shell — LAST RESORT, for commands with no dedicated tool above (build, test, git, package installs, mkdir/rm). Per the tool's own argument schema. Do NOT use it to read, write, or list files when a focused tool exists. A focused tool cannot open an archive or compiled binary: inspect those here with a read-only command (e.g. list a jar/zip's entries, print a compiled class's signatures)."""
FROZEN_ACK = "Understood. I've broken this task into a short, ordered plan. I’ll prioritize the current step while still delivering every required part of the full task."
FROZEN_STEP = """You are completing a larger task with an ordered plan. This plan was created by another model — not the user — and may contain mistakes; verify before moving on. @COMPLETED@Prioritize this step (2 of 5):

Write `a.py` while documenting `README.md`.

Once it is complete, continue with directly related work needed to deliver the full user request. Do not let the plan defer required tests, documentation, and verification when the relevant work is in hand."""
FROZEN_REPAIRS = {
    ('a.py',): "[GROUND TRUTH — the filesystem, read just now] The file named in this step already exists on disk: `a.py`. That is a direct read of the disk, so trust it over anything above that says otherwise. The repo's checks are failing right now, so do not start over: read what is there and make the smallest change that clears the failures reported below. Rewriting a file from scratch recreates the problem it already has.",
    ('README.md', 'a.py'): "[GROUND TRUTH — the filesystem, read just now] The files named in this step already exist on disk: `README.md`, `a.py`. That is a direct read of the disk, so trust it over anything above that says otherwise. The repo's checks are failing right now, so do not start over: read what is there and make the smallest change that clears the failures reported below. Rewriting a file from scratch recreates the problem it already has.",
}
FROZEN_REMEDIATION = "A verified completion-remediation action is active. The ordered-plan cursor is suspended for this turn. Act on the typed missing-file finding in the latest instruction: create that exact task-named file now. Its required contents come only from the exact task requirement and current workspace evidence; do not invent a format or implementation. Do not resume the ordered plan until the write has succeeded."
FROZEN_HISTORY = [
    {'role': 'user', 'content': 'Working environment — cwd: /workspace.'},
    {'role': 'user', 'content': 'ORIGINAL TASK: CLI, tests, documentation, and all details.\n' * 100},
    {'role': 'assistant', 'content': 'Quoted prior work is not a current disk fact.'},
    {'role': 'assistant', 'tool_calls': [{'id': 'read', 'type': 'function', 'function': {
        'name': 'read_file', 'arguments': '{"path":"a.py"}'}}]},
    {'role': 'tool', 'tool_call_id': 'read', 'content': 'EXACT FILE/TOOL BYTES\n' * 1000},
]
FROZEN_SPAN = {'start': len(FROZEN_CODER) + 2,
               'text': 'You are the caller agent. Preserve every requirement.'}
FROZEN_RAW_BODY = [
    {'role': 'system', 'content': FROZEN_CODER + FROZEN_CALLER + '@MENU@@PRIOR@',
     'cria_caller_span': FROZEN_SPAN},
    *FROZEN_HISTORY,
]
FROZEN_ACTIVE_BODY = [
    {'role': 'system', 'content': FROZEN_CODER + FROZEN_CALLER + '\n\n@MENU@@PRIOR@@ACTIVE@',
     'cria_caller_span': FROZEN_SPAN},
    FROZEN_HISTORY[0], FROZEN_HISTORY[1],
    {'role': 'assistant', 'content': FROZEN_ACK},
    *FROZEN_HISTORY[2:],
    {'role': 'user', 'content': '@ACTIVE@'},
]


def frozen_body(*, active=None, menu=FROZEN_MENU, prior=''):
    """Populate leaves of the two fixed wire fixtures; never inspect an input."""
    body = copy.deepcopy(FROZEN_RAW_BODY if active is None else FROZEN_ACTIVE_BODY)
    # Separators are part of the frozen raw/active fixture contracts.
    menu_block = ('\n\n' + menu if active is None else menu + '\n\n') if menu else ''
    prior_block = ('Already done earlier this session (build on it, don\'t redo):\n' + prior) if prior else ''
    if prior_block:
        prior_block = '\n\n' + prior_block if active is None else prior_block + '\n\n'
    body[0]['content'] = body[0]['content'].replace('@MENU@', menu_block).replace('@PRIOR@', prior_block)
    if active is not None:
        body[0]['content'] = body[0]['content'].replace('@ACTIVE@', active)
        body[-1]['content'] = active
    return body


def frozen_step(summary='', repair=''):
    completed = 'Completed so far:\n' + summary + '\n\n' if summary else ''
    return FROZEN_STEP.replace('@COMPLETED@', completed) + ('\n\n' + repair if repair else '')


def adapters():
    return sp.BaseServices(loop._strip_cria_file_ops, loop._msg_text_content,
                           loop.reframe_preamble, loop._is_serialized_plan_cursor)


def messages():
    persona = 'You are the caller agent. Preserve every requirement.'
    return [
        {'role': 'system', 'content': 'Harness boilerplate, not the coder system.'},
        {'role': 'developer', 'content': persona,
         bodykeys.CALLER_INSTRUCTIONS: True, bodykeys.CALLER_PERSONA: persona},
        {'role': 'developer', 'content': 'Permissions: the writable roots are `/workspace` and `/dependencies`.',
         bodykeys.CALLER_INSTRUCTIONS: True},
        {'role': 'user', 'content': '<environment_context>\n<cwd>/workspace</cwd>\n</environment_context>'},
        {'role': 'user', 'content': 'ORIGINAL TASK: CLI, tests, documentation, and all details.\n' * 100},
        {'role': 'assistant', 'content': 'Quoted prior work is not a current disk fact.'},
        {'role': 'assistant', 'tool_calls': [{'id': 'read', 'type': 'function', 'function': {
            'name': 'read_file', 'arguments': '{"path":"a.py"}'}}]},
        {'role': 'tool', 'tool_call_id': 'read', 'content': 'EXACT FILE/TOOL BYTES\n' * 1000},
    ]


def make(*, red=False, files=('a.py',), summary='', prior='', tools=True, source_messages=None):
    incoming = messages() if source_messages is None else source_messages
    base_input = sp.BaseInput(incoming, adapters(), tools=TOOLS if tools else None,
                              workspace_root='/workspace', prior_work=prior)
    base = sp.assemble_base(base_input)
    calls = []
    def present(step, root):
        calls.append((step, root))
        return files
    source = sp.StepInput(base, 'Write `a.py` while documenting `README.md`.', summary, 2, 5,
                          present, gate_red=red, planner_enabled=True)
    return source, base_input, calls


def test_recovered_repair_rationale_belongs_to_real_source_not_model_prompts():
    assert sp.DEFINITION.execute is sp.prepare_step
    rationale = ' '.join((sp.DEFINITION.execute.__doc__ or '').split())
    run_id = 'ada-handles_mellum2_codex_pon_1785625253'
    for fact in (run_id, '33 consecutive author-step prompts',
                 '15 prompts carried gate findings, not successful corrections',
                 'archived run statistics were not newly revalidated',
                 'instruction must not outlive its artifact while findings are intermittent',
                 'Keep the original step untouched',
                 'presence does not establish authoring intent'):
        assert fact in rationale
    assert '15 successful corrections' not in rationale
    source, _, _ = make(red=True)
    result = sp.StepSelection.opt_in().prepare(source)
    for historical in (run_id, '33 consecutive author-step prompts', 'not newly revalidated'):
        assert historical not in str(result.messages)


@pytest.mark.parametrize('red,files', [(False, ()), (None, ('a.py',)), (True, ()),
                                       (True, ('a.py',)), (True, ('README.md', 'a.py'))])
@pytest.mark.parametrize('summary', ['', 'Step one is complete.\nExact earlier details.'])
@pytest.mark.parametrize('tools', [False, True])
def test_full_frame_parity(red, files, summary, tools):
    source, base_input, calls = make(red=red, files=files, summary=summary,
                                   prior='Earlier completed work; still historical.', tools=tools)
    before = copy.deepcopy(base_input.messages)
    repair = FROZEN_REPAIRS[tuple(files)] if red is True and files else ''
    expected = frozen_body(active=frozen_step(summary, repair),
                           prior='Earlier completed work; still historical.',
                           menu=FROZEN_MENU if tools else '')
    result = sp.StepSelection.opt_in().prepare(source)
    assert result.messages == expected and base_input.messages == before
    assert result.status is sp.StepStatus.PREPARED
    assert calls == ([(source.step, source.base.workspace_root)] if red is True else [])
    assert result.messages[0]['content'].endswith(result.prompt)
    assert result.messages[-1] == {'role': 'user', 'content': result.prompt}
    original = base_input.messages[4]['content']
    task_position = next(i for i, m in enumerate(result.messages) if m.get('content') == original)
    assert result.messages[task_position + 1] == {'role': 'assistant', 'content': prompts.load('plan_ack')}
    assert result.messages[task_position - 1]['content'] != prompts.load('plan_ack')  # not after env preamble
    span = result.messages[0][bodykeys.CALLER_SPAN]
    assert result.messages[0]['content'][span['start']:span['start'] + len(span['text'])] == span['text']
    assert any(m.get('content') == base_input.messages[-1]['content'] for m in result.messages)


@pytest.mark.parametrize('prior', ['', 'Earlier work, including every quote and detail.'])
@pytest.mark.parametrize('tools', [False, True])
def test_generic_base_is_original_raw_task_frame_without_optional_policy(prior, tools):
    source, data, calls = make(prior=prior, tools=tools)
    expected = frozen_body(prior=prior, menu=FROZEN_MENU if tools else '')
    assert source.base.messages == expected
    result = sp.StepSelection().prepare(source)
    assert result.messages is source.base.messages and not calls
    assert all(m.get('content') != prompts.load('plan_ack') for m in result.messages)
    assert 'Prioritize this step (' not in str(result.messages)


def test_empty_and_rootless_histories_keep_original_role_and_prompt_order():
    for incoming in ([], [{'role': 'assistant', 'content': 'Existing assistant prose'}],
                     [{'role': 'user', 'content': '<environment_context>env only</environment_context>'}]):
        source, data, _ = make(source_messages=incoming, tools=False)
        expected = [
            {'role': 'system', 'content': FROZEN_CODER + '\n\n' + frozen_step()},
            *copy.deepcopy(incoming),
            {'role': 'user', 'content': frozen_step()},
        ]
        assert sp.StepSelection.opt_in().prepare(source).messages == expected


def test_disabled_and_replaced_policy_never_runs_original_detection():
    source, _, calls = make(red=True)
    with patch.object(sp, 'prepare_step', side_effect=AssertionError('old policy execution')), \
         patch.object(sp.prompts, 'render', side_effect=AssertionError('own prompt rendering')):
        for disabled in (sp.StepSelection(), sp.StepSelection.opt_in(None)):
            result = disabled.prepare(source)
            assert result.status is sp.StepStatus.NOT_SELECTED and result.messages is source.base.messages
        replacement = replace(sp.DEFINITION, execute=lambda request: sp.StepResult(
            sp.StepStatus.PREPARED, [{'role': 'user', 'content': 'replacement owns this frame'}]))
        result = sp.StepSelection.opt_in(replacement).prepare(source)
        assert result.messages == [{'role': 'user', 'content': 'replacement owns this frame'}]
    assert not calls


@pytest.mark.parametrize('change', ['off', 'synthetic', 'suspended'])
def test_nonplanned_or_suspended_frames_never_detect_artifacts_or_render_steps(change):
    source, _, calls = make(red=True)
    if change == 'off': source = replace(source, planner_enabled=False)
    elif change == 'synthetic': source = replace(source, synthetic=True)
    else: source = replace(source, base=replace(source.base, cursor_suspended=True))
    with patch.object(sp.prompts, 'render', side_effect=AssertionError('own prompt rendering')):
        result = sp.StepSelection.opt_in().prepare(source)
    assert result.status is sp.StepStatus.NOT_APPLICABLE
    assert result.messages is source.base.messages and not calls


@pytest.mark.parametrize('files,status', [(None, sp.RepairStatus.UNKNOWN), ([], sp.RepairStatus.NO_PRESENT_ARTIFACT)])
def test_unknown_or_absent_presence_does_not_claim_absence_or_add_repair(files, status):
    source, _, calls = make(red=True, files=files)
    result = sp.StepSelection.opt_in().prepare(source)
    assert result.repair is status and not result.files
    assert '[GROUND TRUTH' not in result.prompt and source.step in result.prompt
    assert len(calls) == 1


def test_presence_is_rederived_not_cached_or_promoted_to_approval():
    source, _, _ = make(red=True)
    answers = iter([['a.py'], None, [], ['README.md']])
    source = replace(source, present_artifacts=lambda step, root: next(answers))
    selected = sp.StepSelection.opt_in()
    first = selected.prepare(source)
    assert first.files == ('a.py',) and 'smallest change' in first.prompt
    stale = selected.prepare(source)
    assert stale.repair is sp.RepairStatus.UNKNOWN and '[GROUND TRUTH' not in stale.prompt
    assert selected.prepare(source).repair is sp.RepairStatus.NO_PRESENT_ARTIFACT
    fresh = selected.prepare(source)
    assert fresh.files == ('README.md',) and '`a.py`' not in fresh.prompt.split('[GROUND TRUTH')[1]
    assert not hasattr(first, 'approved') and not hasattr(first, 'done')
    assert source.gate_red is True  # neither existence nor this frame clears the gate


def test_standing_red_is_not_silently_changed_to_green_when_gate_is_not_fresh():
    source, data, _ = make(red=True)
    session = SimpleNamespace(last_gate_red=True, gate_fresh=False)
    expected = frozen_body(active=frozen_step(repair=FROZEN_REPAIRS[('a.py',)]))
    assert sp.StepSelection.opt_in().prepare(source).messages == expected
    assert session.last_gate_red and not session.gate_fresh


def test_real_shared_presence_adapter_only_counts_exact_true_from_fake_view():
    source, _, _ = make(red=True)
    source = replace(source, step='a.py b.py c.py a.py', present_artifacts=loop.step_artifacts_on_disk)
    seen = []
    def isfile(path):
        seen.append(path)
        return {'/workspace/a.py': True, '/workspace/b.py': None, '/workspace/c.py': False}[path]
    with patch.object(loop.wsview, 'current', return_value=SimpleNamespace(isfile=isfile)):
        result = sp.StepSelection.opt_in().prepare(source)
    assert result.files == ('a.py',) and seen == ['/workspace/a.py', '/workspace/b.py', '/workspace/c.py']
    assert 'already exists' in result.prompt


def test_contradictory_step_is_retained_and_presence_note_only_overrides_file_claim():
    source, _, _ = make(red=True, files=['a.py', 'README.md'])
    source = replace(source, step='a.py and README.md are not in the workspace; no README.md exists.')
    result = sp.StepSelection.opt_in().prepare(source)
    assert source.step in result.prompt
    assert 'trust it over anything above that says otherwise' in result.prompt
    assert 'do not start over' in result.prompt
    assert 'Once it is complete, continue with directly related work' in result.prompt
    assert result.prompt.index(source.step) < result.prompt.index('[GROUND TRUTH')
    assert 'asks you to WRITE' not in result.prompt


def test_remediation_uses_generic_active_directive_without_running_step_policy():
    source, data, calls = make(red=True)
    cursor = {'role': 'user', 'content': sp.StepSelection.opt_in().prepare(source).prompt}
    calls.clear()
    data = replace(data, messages=data.messages + [cursor], suspend_cursor=True)
    base = sp.assemble_base(data)
    source = replace(source, base=base)
    assert sp.StepSelection.opt_in().prepare(source).status is sp.StepStatus.NOT_APPLICABLE
    assert not calls
    actual = sp.with_directive(base, prompts.load('completion_remediation'), prompts.load('plan_ack'))
    expected = frozen_body(active=FROZEN_REMEDIATION)
    assert actual == expected and cursor not in actual
    assert sp.assemble_base(data).messages == frozen_body()


@pytest.mark.parametrize('retained', [False, True])
def test_passive_carry_survives_planner_off_and_rewrites(retained):
    history = ([{'role': 'assistant', 'content': f'{completedwork.BRIEFING_OPEN}\nPrior exact work\n{completedwork.BRIEFING_CLOSE}'}]
               if retained else [])
    carried = completedwork.read_history(history)
    for rewrite in (None, '', 'Harness continuation with full original scope'):
        carry = carried.followup(rewrite)
        source, data, calls = make(prior=carry.coder_prior_work, source_messages=history + [{'role': 'user', 'content': 'New task'}])
        result = sp.StepSelection.opt_in().prepare(replace(source, planner_enabled=False))
        expected = 'Prior exact work' if retained else (rewrite or '')
        prior_block = ('\n\nAlready done earlier this session (build on it, don\'t redo):\n' + expected
                       if expected else '')
        assert result.messages == [
            {'role': 'system', 'content': FROZEN_CODER + '\n\n' + FROZEN_MENU + prior_block},
            *copy.deepcopy(history), {'role': 'user', 'content': 'New task'},
        ]
        assert carry.coder_prior_work == expected
        assert carry.planner_prior_work == ('Prior exact work' if retained and rewrite is None else '')
        if expected:
            assert result.messages[0]['content'].count(expected) == 1
        else:
            assert 'Prior exact work' not in result.messages[0]['content']
        assert not calls and 'Prioritize this step (' not in str(result.messages)


def test_full_coder_body_sampling_and_budget_parity_without_provider_calls():
    source, data, _ = make(red=True, summary='Previous progress')
    expected_messages = frozen_body(active=frozen_step('Previous progress', FROZEN_REPAIRS[('a.py',)]))
    actual = {'stream': False, 'tools': data.tools, 'messages': sp.StepSelection.opt_in().prepare(source).messages}
    expected = {'stream': False, 'tools': copy.deepcopy(TOOLS), 'messages': expected_messages}
    role = Role(name='coder', backend='local', temperature=0.7, reasoning='on')
    role.apply(actual)
    role.apply(expected)
    assert actual == expected


def test_shared_gate_cleanup_receives_actual_plan_and_keeps_exact_result_lines():
    source, data, _ = make()
    gate = object()
    data = replace(data, gate_plan=gate)
    calls = []
    exact = {'role': 'tool', 'tool_call_id': 'gate', 'content': 'EXACT CHECKER LINES\nfile.py:3: error\n'}
    def clean(messages, plan):
        calls.append(plan)
        assert plan is gate
        return [*messages, exact]
    with patch.object(sp.probegate, 'clean_gate_results', side_effect=clean):
        actual = sp.StepSelection.opt_in().prepare(replace(source, base=sp.assemble_base(data))).messages
    expected = frozen_body(active=frozen_step())
    expected.insert(-1, exact)
    assert actual == expected and calls == [gate]
    assert exact in actual


def test_visible_usage_keeps_the_original_raw_base_budget_without_step_detection():
    from cria import modelview
    source, data, calls = make(red=True, prior='Earlier complete work')
    plan = loop.Plan(id='usage', task='Original task', created='', items=[])
    session = loop.PlanSession(plan=plan, summary='Progress', prior_work=data.prior_work,
                               workspace_root=data.workspace_root)
    store = loop.LoopStore()
    store.put('sid:usage', session)
    ctx = loop.LoopContext(planner=None, coder_chat=None, reasoner_chat=None, runs_dir='')
    before = loop.Loop(ctx, store).visible_context_tokens({'messages': data.messages, 'tools': data.tools}, 'sid:usage')
    assert before == modelview.visible_tokens(frozen_body(prior='Earlier complete work'), TOOLS)
    assert not calls


def test_candidate_does_not_call_old_whole_framing_policies():
    source, data, _ = make(red=True)
    # Tripwires also work after these aliases retire; their existence is not the contract.
    with patch.object(loop, '_frame_for_item', create=True, side_effect=AssertionError('whole old frame')), \
         patch.object(loop, '_item_prompt', create=True, side_effect=AssertionError('whole old prompt')), \
         patch.object(loop, '_repair_note', create=True, side_effect=AssertionError('whole old repair')):
        assert sp.StepSelection.opt_in().prepare(replace(source, base=sp.assemble_base(data))).files == ('a.py',)


def test_two_sessions_and_task_reset_have_no_shared_presence_or_summary():
    def run(label):
        source, data, _ = make(red=True, files=[label + '.py'], summary=label + ' progress')
        data = replace(data, workspace_root='/' + label)
        def present(step, root):
            assert root == '/' + label
            return [label + '.py']
        source = replace(source, step=f'Inspect `{label}.py`', base=sp.assemble_base(data), present_artifacts=present)
        return sp.StepSelection.opt_in().prepare(source)
    with ThreadPoolExecutor(max_workers=2) as pool:
        left, right = list(pool.map(run, ['left', 'right']))
    assert left.files == ('left.py',) and right.files == ('right.py',)
    assert 'right progress' not in left.prompt and 'left progress' not in right.prompt
    reset, _, calls = make(red=None, files=['left.py'], summary='')
    result = sp.StepSelection.opt_in().prepare(replace(reset, step='A new task without file assertions'))
    assert not result.files and not calls and 'Completed so far:' not in result.prompt


def selected_menu_note(policies, *, configured=True):
    # Production adapter contract: use the task's existing selection, no root
    # lookup/default. A declined replacement result cannot supply instructions.
    def note(tools):
        result = policies.instructions(toolmenu.InstructionInput(tools, messages=None,
                                                                 configured=configured))
        return result.note if result.applied else None
    return note


@pytest.mark.parametrize('planned', [False, True])
def test_explicit_selected_menu_replacement_preserves_original_embedding_slot(planned):
    source, data, artifact_calls = make(prior='Earlier work')
    seen = []
    def replacement(request, rlog=None):
        seen.append(request)
        return toolmenu.InstructionResult('SELECTED MENU NOTE', None, applied=True)
    definition = replace(toolmenu.INSTRUCTION_DEFINITION, execute=replacement)
    policies = toolmenu.selected_policies((definition,))
    data = replace(data, services=replace(data.services, menu_note=selected_menu_note(policies)))
    with patch.object(toolmenu, 'current_policies', side_effect=AssertionError('global selection')):
        base = sp.assemble_base(data)
        result = (sp.StepSelection.opt_in().prepare(replace(source, base=base)) if planned
                  else sp.StepSelection().prepare(replace(source, base=base)))
    expected = frozen_body(active=frozen_step() if planned else None,
                           prior='Earlier work', menu='SELECTED MENU NOTE')
    assert result.messages == expected
    assert len(seen) == 1 and seen[0].tools is data.tools and seen[0].messages is None
    assert seen[0].configured and result.messages[0]['content'].count('SELECTED MENU NOTE') == 1
    assert not artifact_calls


@pytest.mark.parametrize('mode', ['absent', 'empty-selection', 'empty-note', 'none-note', 'not-applied', 'config-off'])
def test_explicit_menu_absence_or_empty_result_never_uses_defaults(mode):
    source, data, _ = make()
    seen = []
    def replacement(request, rlog=None):
        seen.append(request)
        if mode == 'not-applied':
            return toolmenu.InstructionResult('MUST NOT BE EMBEDDED', None, applied=False)
        return toolmenu.InstructionResult('' if mode == 'empty-note' else None, None, applied=True)
    definition = replace(toolmenu.INSTRUCTION_DEFINITION, execute=replacement)
    policies = toolmenu.selected_policies(() if mode == 'empty-selection' else (definition,))
    adapter = (None if mode == 'absent' else
               selected_menu_note(policies, configured=mode != 'config-off'))
    data = replace(data, services=replace(data.services, menu_note=adapter))
    with patch.object(toolmenu, 'cheatsheet', side_effect=AssertionError('default renderer')), \
         patch.object(toolmenu, 'current_policies', side_effect=AssertionError('global selection')):
        base = sp.assemble_base(data)
        result = sp.StepSelection.opt_in().prepare(replace(source, base=base))
    assert result.status is sp.StepStatus.PREPARED
    assert toolmenu.prompts.load_map('cheatsheet')['header'] not in result.messages[0]['content']
    assert 'MUST NOT BE EMBEDDED' not in result.messages[0]['content']
    assert len(seen) == (0 if mode in ('absent', 'empty-selection', 'config-off') else 1)


def test_coder_note_keeps_its_historical_config_gate_not_the_server_gate():
    _, data, _ = make()
    seen = []
    def replacement(request, rlog=None):
        seen.append(request.configured)
        return toolmenu.InstructionResult('BOUND CODER NOTE', None, applied=True)
    policies = toolmenu.selected_policies((replace(toolmenu.INSTRUCTION_DEFINITION, execute=replacement),))
    # tools.cheatsheet=False gates the server's merge, NOT the existing coder
    # note slot. Supply configured=True here instead of inheriting that flag.
    server = policies.instructions(toolmenu.InstructionInput(data.tools, data.messages, configured=False))
    assert not server.applied and not seen
    data = replace(data, services=replace(data.services, menu_note=selected_menu_note(policies, configured=True)))
    assert 'BOUND CODER NOTE' in sp.assemble_base(data).messages[0]['content']
    assert seen == [True]


def test_explicit_absence_does_not_retain_an_upstream_folded_default_note():
    _, data, _ = make()
    hint = toolmenu.cheatsheet(data.tools)
    incoming = copy.deepcopy(data.messages)
    incoming[1]['content'] += '\n\n' + hint
    data = replace(data, messages=incoming, services=replace(data.services, menu_note=None))
    with patch.object(toolmenu, 'cheatsheet', side_effect=AssertionError('default renderer')):
        base = sp.assemble_base(data)
    assert hint not in base.messages[0]['content']
    span = base.messages[0][bodykeys.CALLER_SPAN]
    assert base.messages[0]['content'][span['start']:span['start'] + len(span['text'])] == span['text']


def test_explicit_menu_absence_does_not_disable_required_remediation():
    source, data, calls = make(red=True)
    data = replace(data, suspend_cursor=True, services=replace(data.services, menu_note=None))
    base = sp.assemble_base(data)
    assert sp.StepSelection().prepare(replace(source, base=base)).messages is base.messages
    actual = sp.with_directive(base, prompts.load('completion_remediation'), prompts.load('plan_ack'))
    expected = frozen_body(active=FROZEN_REMEDIATION, menu='')
    assert actual == expected and not calls


def test_omitted_menu_adapter_retains_unbound_library_compatibility():
    source, data, _ = make()
    assert data.services.menu_note is not None
    expected = frozen_body()
    assert sp.assemble_base(data).messages == expected


def test_consent_scope_and_source_definition_contract():
    with pytest.raises(ValueError): sp.StepSelection(definition=sp.DEFINITION)
    with pytest.raises(ValueError): sp.StepSelection(enabled=1)
    for changed in (replace(sp.DEFINITION, policy=replace(sp.DEFINITION.policy, scope='runtime')),
                    replace(sp.DEFINITION, execute=None)):
        with pytest.raises(ValueError): sp.StepSelection.opt_in(changed)
    assert sp.DEFINITION.policy.family_id == 'F50' and sp.DEFINITION.policy.scope == 'experimental'
    assert not sp.DEFINITION.policy.migrated
