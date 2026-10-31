"""Fake-reader/workspace-view contracts for optional step review, never task release."""
import json
from copy import deepcopy
from dataclasses import dataclass, replace
from unittest.mock import patch

import pytest

from cria import loop, stepreview as sp
from cria.config import Role


# Literal prompt contracts stay independent when Loop._verify becomes an
# adapter to this same Source. No old verifier or live renderer is an oracle.
VERIFY_SYSTEM = """You are a JUDGE, not the coder. You have only two READ-ONLY tools: `list_dir` and `read_file`. Use them only when the action log does not already prove a required artifact exists or contains the required content. Never write code, run commands, fetch pages, or perform the next step.

Judge ONE plan step using the coder's REAL action log: `$ ...` is a tool call; `-> ...` is its result. Judge what the coder actually did, not its summary.

Rules:
- Judge only THIS step, not the full task or later steps.
- `done=true` only when evidence positively shows this step's goal was reached.
- For research/investigation, the required facts must actually appear in tool output from the real source. Search results, snippets, guesses, or landing pages are not enough. Once the real source is read, judge by what it actually contains; do not require facts the source demonstrably does not provide.
- For artifact steps, verify existence/content when the log does not prove them; files may be empty or stubbed.
- If this step's own command, test, or runtime behavior fails, `done=false`.
- Exit 0, compile, lint, or syntax success proves only that the command passed, not that runtime behavior works. Printed runtime errors, HTTP 4xx/5xx, stack traces, `Failed`, `Error`, `not found`, or `404` mean runtime failure even with exit 0.
- Ignore failures unrelated to THIS step.
- If THIS step is about tests, require meaningful tests of actual behavior; mocks must not force success.
- Do not invent requirements. Missing evidence means `done=false`.

Output fields:
- `done`: `true` only when THIS step is proven complete; otherwise `false`.
- `reason`: short, specific evidence showing what succeeded, failed, is missing, or remains unproven.
- `proposed_fix`: if `done=false`, NAME what this step still needs — the deliverable, behaviour or file that is missing or wrong — in one line. What must become true, not how to make it true: never a command, a library, an approach, or a filename the step did not name. Choosing the implementation is the coder's job, and a judge that picks one is authoring the work. If `done=true`, use `""`.
- `diagnosis_kind`: when false, exactly one of `missing_file`, `missing_content`, `failed_check`, `unverified_requirement`, or `other`; when true, `""`. A missing whole file and missing content inside an existing file are different types.
- `subject`: the exact step-named workspace path for `missing_file` or `missing_content`; otherwise `""` unless one exact subject is useful.
- `task_quote`: when false, an exact contiguous quote from THIS step stating the requirement at issue; when true, `""`.
- `evidence_source`: when false, exactly one of `workspace_absence`, `workspace_file`, `action_log`, `checks`, or `participation`; when true, `""`.
- `evidence_quote`: when false, an exact contiguous quote from that source, with no paraphrase. Use `""` only for `workspace_absence`; when true, use `""`.

Do not promote a documented risk, caveat, future improvement, or benchmark uncertainty into required work unless THIS step's exact text requires that outcome. If no exact task/evidence pair supports a negative diagnosis, keep `done=false` but leave all diagnosis fields, `reason`, and `proposed_fix` empty.

Output only:
{"done": true|false, "reason": "<specific evidence-based finding or empty>", "proposed_fix": "<missing thing or empty>", "diagnosis_kind": "<typed value or empty>", "subject": "<step-named path or empty>", "task_quote": "<exact step quote or empty>", "evidence_source": "<typed source or empty>", "evidence_quote": "<exact evidence quote or empty>"}"""
BASIC_USER = """STEP: Write report

WHAT THE CODER DID — its tool CALLS and what they returned (real ground truth):
current tool evidence

CODER'S SUMMARY (a claim — trust the tool output above over this):
coder claims done

THE STEP YOU ARE RULING ON IS THE ONE AT THE TOP, RESTATED HERE — any step numbering inside the coder's summary is the CODER's own and is NOT what you judge:
Write report"""
UNVERIFIED = "This step is not yet verified as complete. Keep working: re-check the step's goal against the files on disk, then demonstrate completion by running the repo's own checks and showing their real, unfiltered output."


class Log:
    def __init__(self): self.events = []
    def emit(self, name, **fields): self.events.append((name, fields))


@dataclass(frozen=True)
class Confirmation:
    confirmed: bool
    observed: bool
    reason: str = ''


class Reads:
    def __init__(self, answers): self.answers, self.calls = list(answers), []
    def __call__(self, request):
        self.calls.append(request)
        return self.answers.pop(0)


def make(answers, **kwargs):
    reader = Reads([sp.StepAnswer(answer, f'raw {i}') for i, answer in enumerate(answers)])
    records, confirmations, diagnoses, applicability = [], [], [], []
    log = Log()
    def normalize(obj, flag, phase): return loop._fill_missing_verdict_flag(obj, flag, log, phase)
    def confirm(request):
        confirmations.append(request)
        return Confirmation(True, True)
    def diagnosis(request):
        diagnoses.append(request)
        return 'accepted judge reason'
    def applies(system):
        applicability.append(system)
        return 'YES'
    services = sp.StepServices(reader, normalize, confirm, diagnosis, records.append,
        loop.VerdictNudge, loop._named_gap, confirm_applies_ask=applies)
    source = sp.StepInput('Write report', 'coder claims done', 'current tool evidence', sp.ProbeEvidence(),
                          services, log, key='session', index=2, total=4, original_task='write report and tests', **kwargs)
    return source, reader, records, confirmations, diagnoses, applicability


@pytest.mark.parametrize('claim,summary', [
    ('All requested report work is complete.', 'All requested report work is complete.'),
    ('<tool_call>{"name":"write_file"}</tool_call>',
     "(the coder's completion message was a malformed tool call, not a summary — judge from the evidence above)"),
    ('｜DSML｜invoke name="write_file"',
     "(the coder's completion message was a malformed tool call, not a summary — judge from the evidence above)"),
])
def test_claim_dialect_detection_uses_pure_syntax_not_upper_pipeline(claim, summary):
    from cria import massage
    source, reader, records, _, _, _ = make([{'done': False, 'reason': 'not yet'}])
    source = replace(source, coder_text=claim)
    with patch.object(massage, 'has_tool_call_leak', side_effect=AssertionError('upper parser backedge')):
        result = sp.StepSelection.opt_in().run(source)
    assert result.status is sp.StepStatus.REJECTED and len(reader.calls) == len(records) == 1
    assert full_read(reader.calls[0]).user == (
        'STEP: Write report\n\n'
        'WHAT THE CODER DID — its tool CALLS and what they returned (real ground truth):\n'
        'current tool evidence\n\n'
        "CODER'S SUMMARY (a claim — trust the tool output above over this):\n" + summary + '\n\n'
        "THE STEP YOU ARE RULING ON IS THE ONE AT THE TOP, RESTATED HERE — any step numbering inside the coder's summary is the CODER's own and is NOT what you judge:\n"
        'Write report')


def test_careful_and_retry_have_separate_authority():
    source, reader, records, _, diagnoses, _ = make([{'done': True, 'reason': 'yes'}])
    result = sp.StepSelection.opt_in().run(source)
    assert result.done and result.readable and result.status is sp.StepStatus.APPROVED
    assert result.effect.action is sp.StepAction.ADVANCE
    assert len(reader.calls) == len(records) == len(diagnoses) == 1
    assert not reader.calls[0].reasoning_off and reader.calls[0].recovery_key == 'done'
    assert reader.calls[0].verdict_key == ''
    source, reader, records, _, diagnoses, _ = make([None, {'done': True, 'reason': 'retry says yes'}], workspace_root='/workspace')
    result = sp.StepSelection.opt_in().run(source)
    assert not result.done and not result.readable and result.status is sp.StepStatus.UNKNOWN
    assert [r.reasoning_off for r in reader.calls] == [False, True]
    assert [r.workspace_root for r in reader.calls] == ['/workspace', '']
    assert len(records) == 1 and records[0].raw == 'raw 1' and not diagnoses
    assert any(event == 'loop.verify_failclosed' for event, _ in source.log.events)
    source, reader, records, _, diagnoses, _ = make([None, {'done': False, 'reason': 'not done'}])
    result = sp.StepSelection.opt_in().run(source)
    assert result.status is sp.StepStatus.REJECTED and result.readable
    assert len(reader.calls) == 2 and len(records) == 1
    assert diagnoses[0].phase == 'critic-retry-diagnosis' and not diagnoses[0].done


def test_probe_settlement_preserves_step_not_task_authority():
    source, _, _, _, _, _ = make([{'done': False}])
    source = replace(source, probe=sp.ProbeEvidence(ran=True, blocked=True, repair_text='EXACT CHECKER LINE',
        red_findings='EXACT CHECKER LINE', standing_red=True))
    result = sp.StepSelection.opt_in().run(source)
    assert result.effect.nudge == 'EXACT CHECKER LINE' and result.reason == 'accepted judge reason'
    assert result.effect.verify_failures == 1 and result.effect.critic_failures == 0
    assert not result.effect.consider_critic_rescue
    assert result.effect.preserve_gate_state
    approved, _, _, _, _, _ = make([{'done': True}], workspace_root='/workspace')
    approved = replace(approved, probe=source.probe)
    result = sp.StepSelection.opt_in().run(approved)
    assert result.done and result.effect.action is sp.StepAction.ADVANCE
    assert result.effect.red_gate_advance and result.effect.preserve_gate_state
    unknown, _, _, _, _, _ = make([{'done': False}])
    unknown = replace(unknown, probe=sp.ProbeEvidence(transport_unknown=True, standing_red=True))
    result = sp.StepSelection.opt_in().run(unknown)
    assert result.effect.verify_failures == result.effect.critic_failures == 1
    assert result.effect.consider_critic_rescue
    assert result.effect.nudge == 'accepted judge reason' and result.effect.preserve_gate_state


def test_disabled_pending_and_periodic_never_judge():
    source, reader, records, confirm, diagnoses, applicability = make([])
    with patch.object(sp.groundtruth, 'absent_step_literals', side_effect=AssertionError('detected')):
        assert sp.StepSelection().run(source).status is sp.StepStatus.NOT_SELECTED
        pending = replace(source, probe=sp.ProbeEvidence(pending=True))
        assert sp.StepSelection.opt_in().run(pending).status is sp.StepStatus.PENDING_PROBE
        periodic = replace(source, probe=sp.ProbeEvidence(periodic=True, repair_text='checker output'))
        result = sp.StepSelection.opt_in().run(periodic)
        assert result.status is sp.StepStatus.PERIODIC and not result.done
        assert result.effect.action is sp.StepAction.RENUDGE and result.effect.nudge == 'checker output'
        assert result.effect.verify_failures == result.effect.critic_failures == 0
    assert not reader.calls and not records and not confirm and not diagnoses and not applicability


@pytest.mark.parametrize('applies,expected', [('NO', False), ('YES', True), ('', True), ('UNDECIDABLE', True), (None, True)])
def test_step_confirmation_applicability_fails_toward_the_brake(applies, expected):
    source, reader, records, confirmations, _, _ = make([{'done': True}], workspace_root='/workspace')
    questions = []
    def ask(system): questions.append(system); return applies
    source = replace(source, services=replace(source.services, confirm_applies_ask=None if applies is None else ask))
    result = sp.StepSelection.opt_in().run(source)
    assert result.done and len(reader.calls) == len(records) == 1
    assert bool(confirmations) == expected
    assert len(questions) == (0 if applies is None else 1)


def test_red_gate_skips_applicability_question_but_requires_real_confirmation():
    source, reader, records, _, diagnoses, applicability = make([{'done': True, 'reason': 'claimed done'}], workspace_root='/workspace')
    requests = []
    def confirm(request):
        requests.append(request)
        return Confirmation(False, False, 'workspace not observed')
    source = replace(source, probe=sp.ProbeEvidence(standing_red=True),
                     services=replace(source.services, confirm=confirm))
    result = sp.StepSelection.opt_in().run(source)
    assert not result.done and result.readable and result.confirmation.observed is False
    assert isinstance(result.reason, loop.VerdictNudge) and not diagnoses and not applicability
    assert len(reader.calls) == len(records) == len(requests) == 1
    assert requests[0].original_task == source.original_task
    assert records[0].raw == 'raw 0' and not records[0].done


def test_unknown_reader_never_advances_and_keeps_named_checker_facts():
    source, reader, records, confirmations, diagnoses, _ = make([None, None])
    source = replace(source, probe=sp.ProbeEvidence(red_findings='compiler: exact finding'))
    result = sp.StepSelection.opt_in().run(source)
    assert result.status is sp.StepStatus.UNKNOWN and not result.done and not result.readable
    assert 'compiler: exact finding' in result.reason and len(reader.calls) == 2
    assert records[0].reason == result.reason and not diagnoses and not confirmations


def test_keyless_negative_reuses_shared_reader_without_recovering_approval():
    negative = {key: '' for key in ('diagnosis_kind', 'subject', 'task_quote', 'evidence_source', 'evidence_quote')}
    source, reader, _, _, _, _ = make([negative])
    assert sp.StepSelection.opt_in().run(source).status is sp.StepStatus.REJECTED
    assert len(reader.calls) == 1
    source, reader, _, _, _, _ = make([{'satisfied': True}, {'satisfied': True}])
    assert sp.StepSelection.opt_in().run(source).status is sp.StepStatus.UNKNOWN
    assert len(reader.calls) == 2


def test_selected_replacement_bypasses_old_detector_and_questions():
    source, reader, records, _, _, _ = make([])
    seen = []
    def replacement(value):
        seen.append(value.step)
        return sp.StepResult(sp.StepStatus.REJECTED, 'replacement', effect=sp.StepEffect(sp.StepAction.RENUDGE, 'replacement'))
    selected = sp.StepSelection.opt_in(replace(sp.DEFINITION, execute=replacement))
    with patch.object(sp.groundtruth, 'absent_step_literals', side_effect=AssertionError('old detector ran')):
        assert selected.run(source).reason == 'replacement'
    assert seen == ['Write report'] and not reader.calls and not records
    assert sp.StepSelection.opt_in(None).run(source).status is sp.StepStatus.NOT_SELECTED


def test_prompt_is_identical_to_existing_step_review_and_preserves_full_evidence(tmp_path):
    """Historical name retained; full frozen request, not Loop._verify parity."""
    (tmp_path / 'report.md').write_text('actual file contents\n')
    source, reader, records, _, _, _ = make([{'done': False}], workspace_root=str(tmp_path),
        coder_tools='  - shell: command', routes='real routes', sources_read=(('https://example.org', 'HTTP 200', 'source'),),
        participation_facts='actual test participation')
    source = replace(source, step="Update report.md with the literal 'needed'", coder_text='<tool_call>write_file{bad}</tool_call>',
                     evidence='BEGIN\n' + 'current facts\n' * 2000 + 'END',
                     probe=sp.ProbeEvidence(digest='PROBE DIGEST', red_findings='EXACT CHECKER LINE'))
    sp.StepSelection.opt_in().run(source)
    user = ("STEP: Update report.md with the literal 'needed'\n\n"
        "WHAT THE CODER DID — its tool CALLS and what they returned (real ground truth):\n"
        + 'BEGIN\n' + 'current facts\n' * 2000 + 'END\n\n'
        'GROUND-TRUTH CHECKS (lint · type-check · tests · git): PROBE DIGEST\n\n'
        'actual test participation\n\n'
        "THE REPO'S OWN CHECKS ARE CURRENTLY FAILING. These checks run over the WHOLE repository, so this is a fact about the repository — it is NOT a verdict on this step, and the output cannot say which step's work produced it:\n"
        'EXACT CHECKER LINE\n\n'
        "The ONLY question you are being asked about these failures is whether THIS step's own goal requires them to be resolved. If they are this step's own work failing — the code this step wrote does not parse, the tests this step wrote fail, the command this step runs errors — that is this step failing, so answer false and name it. If they are in work that a DIFFERENT step of the plan covers, they are not evidence about this step at all: judge this step on its own goal exactly as you would with clean checks. Someone else will decide whether the whole task is finished; do not answer that question here, and do not fix anything yourself.\n\n"
        "CODER'S SUMMARY (a claim — trust the tool output above over this):\n"
        "(the coder's completion message was a malformed tool call, not a summary — judge from the evidence above)\n\n"
        'YOU DO NOT HAVE WEB FETCH/SEARCH or SHELL EXEC TOOLS AVAILABLE TO YOU — the tool list below is NOT yours, and you must never claim to have performed any action from it. It is FOR REFERENCE ONLY: it names the tools THE CODER has, so any action you name for the coder is doable with one of these, BY THE NAME LISTED — e.g. to search a saved file tell it to run `grep -n "<term>" <file>` via its shell/exec tool; to see part of a file, the coder\'s file-reading tool with a line range (its real name is in the list below):\n'
        '  - shell: command\n\n'
        "ON-DISK FACT, gathered by running the check — not a verdict, and not necessarily a failure: the step quotes 'needed', and report.md does not contain it anywhere. Decide for yourself whether this step's goal needs them present. If the step asked for the artifact to USE those exact values, it does not yet.\n\n"
        'WHAT HAS ACTUALLY BEEN READ SO FAR (gathered from the real tool results — each of these returned content, and everything else that was tried did not):\n'
        '- https://example.org\n    routes it defines: HTTP 200\n    response fields it defines: source\n\n'
        "If THIS step's goal was to find something out, judge whether what is listed here answers it. If the step's goal was to BUILD something, this list is background and does not make it done.\n\n"
        "THE STEP YOU ARE RULING ON IS THE ONE AT THE TOP, RESTATED HERE — any step numbering inside the coder's summary is the CODER's own and is NOT what you judge:\n"
        "Update report.md with the literal 'needed'")
    assert full_read(reader.calls[0]).user == user
    assert source.evidence in full_read(reader.calls[0]).user and 'END' in full_read(reader.calls[0]).user
    assert records == [sp.StepRecord(source.step, VERIFY_SYSTEM, user, False, 'accepted judge reason',
                                     'raw 0', 'session', 2, 4)]


@pytest.mark.parametrize('answers', [
    [None, None], [None, {'done': True}], [None, {'done': False}],
    [{'done': False}], [{'done': True}],
])
def test_source_matches_legacy_careful_retry_outcomes_and_counts(answers):
    """Historical name retained; independent reads, effects, records and events."""
    before = deepcopy(answers)
    source, reader, records, confirmations, diagnoses, applicability = make(answers)
    result = sp.StepSelection.opt_in().run(source)
    assert answers == before
    expected_reads = [sp.StepRead(VERIFY_SYSTEM, BASIC_USER, False)]
    events = []
    if len(answers) == 2:
        expected_reads.append(sp.StepRead(VERIFY_SYSTEM, BASIC_USER, True))
        events.append(('loop.verify_retry', {'level': 'info', 'reason': 'no parseable verdict; retry reasoning-off'}))
    unknown = len(answers) == 2 and (answers[-1] is None or answers[-1]['done'])
    if len(answers) == 2 and answers[-1] is not None and answers[-1]['done']:
        events.append(('loop.verify_failclosed', {'level': 'info'}))
    done = len(answers) == 1 and answers[0]['done']
    status = sp.StepStatus.UNKNOWN if unknown else sp.StepStatus.APPROVED if done else sp.StepStatus.REJECTED
    reason = UNVERIFIED if unknown else 'accepted judge reason'
    effect = (sp.StepEffect(sp.StepAction.ADVANCE) if done else
              sp.StepEffect(sp.StepAction.RENUDGE, reason, verify_failures=1,
                            critic_failures=1, consider_critic_rescue=True))
    assert result == sp.StepResult(status, reason, effect=effect, readable=not unknown, review_done=done)
    assert [full_read(r) for r in reader.calls] == expected_reads and not reader.answers
    assert not confirmations and not applicability and source.log.events == events
    assert records == [sp.StepRecord('Write report', VERIFY_SYSTEM, BASIC_USER, done, reason,
                                     f'raw {len(answers) - 1}', 'session', 2, 4)]
    assert diagnoses == ([] if unknown else [sp.StepDiagnosis(
        before[-1], done, '', BASIC_USER, 'Write report', 'write report and tests',
        'current tool evidence', '', '', '',
        'critic-retry-diagnosis' if len(answers) == 2 else 'critic-diagnosis')])


def test_best_effort_verifier_persistence_cannot_change_a_step_verdict():
    source, reader, _, _, _, _ = make([{'done': True}])
    def persist(record): raise OSError('owned artifact directory unavailable')
    source = replace(source, services=replace(source.services, persist=persist))
    result = sp.StepSelection.opt_in().run(source)
    assert result.done and len(reader.calls) == 1


def test_shared_reader_rejects_truncation_and_uses_step_key():
    bodies = []
    replies = [
        {'choices': [{'finish_reason': 'length', 'message': {'content': '{"done": true}'}}]},
        {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"done": false, "reason": "not verified"}'}}]},
    ]
    role = Role(name='reasoner', backend='local')
    log = Log()
    def chat(body, rlog): bodies.append(body); return json.dumps(replies.pop(0)).encode()
    source, _, records, _, _, _ = make([])
    def shared(request):
        obj, raw = loop._critic_verdict(request.system, request.user, chat, role, log,
            evidence_blocks=list(request.evidence_blocks), reasoning_off=request.reasoning_off, workspace_root=request.workspace_root,
            verdict_key=request.verdict_key)
        return sp.StepAnswer(obj, raw)
    source = replace(source, log=log, services=replace(source.services, read=shared))
    result = sp.StepSelection.opt_in().run(source)
    assert result.status is sp.StepStatus.REJECTED and not result.done
    assert len(bodies) == 2 and len(records) == 1
    assert any(event == 'loop.verify_truncated' for event, _ in log.events)
    assert 'not verified' in records[0].raw


@pytest.mark.parametrize('confirmed,observed,expected,action', [
    (True, True, sp.StepStatus.APPROVED, sp.StepAction.ADVANCE),
    (True, False, sp.StepStatus.UNOBSERVED, sp.StepAction.OBSERVE_WORKSPACE),
    (False, False, sp.StepStatus.REJECTED, sp.StepAction.KEEP_WORKING),
])
def test_scheduled_positive_needs_its_own_observed_confirmation(confirmed, observed, expected, action):
    source, reader, records, _, _, _ = make([{'done': True}], workspace_root='/workspace')
    source = replace(source, trigger=sp.StepTrigger.SCHEDULED,
        services=replace(source.services, confirm=lambda request: Confirmation(confirmed, observed, 'confirmation reason')))
    result = sp.StepSelection.opt_in().run(source)
    assert result.status is expected and result.effect.action is action
    assert result.done == (confirmed and observed)
    assert result.review_done == confirmed and result.effect.verify_failures == result.effect.critic_failures == 0
    assert len(reader.calls) == len(records) == 1
    assert 'coder claims done' not in full_read(reader.calls[0]).user


def test_scheduled_skip_or_missing_workspace_does_not_grant_new_authority():
    for root in ('', '/workspace'):
        source, reader, _, confirmations, _, _ = make([{'done': True}], workspace_root=root)
        source = replace(source, trigger=sp.StepTrigger.SCHEDULED,
            services=replace(source.services, confirm_applies_ask=lambda system: 'NO'))
        result = sp.StepSelection.opt_in().run(source)
        assert result.status is sp.StepStatus.UNOBSERVED and result.review_done and not result.done
        assert result.effect.action is sp.StepAction.KEEP_WORKING
        assert not confirmations and len(reader.calls) == 1


def test_observation_discards_positive_and_rejudges_fresh_facts():
    source, reader, records, _, _, _ = make([{'done': True}, {'done': False}], workspace_root='/workspace')
    source = replace(source, trigger=sp.StepTrigger.SCHEDULED,
        services=replace(source.services, confirm=lambda request: Confirmation(True, False)))
    first = sp.StepSelection.opt_in().run(source)
    assert first.status is sp.StepStatus.UNOBSERVED and first.effect.action is sp.StepAction.OBSERVE_WORKSPACE
    pending = replace(source, probe=sp.ProbeEvidence(pending=True))
    assert sp.StepSelection.opt_in().run(pending).status is sp.StepStatus.PENDING_PROBE
    assert len(reader.calls) == 1
    settled = replace(source, evidence='FRESH WORKSPACE OBSERVATION')
    second = sp.StepSelection.opt_in().run(settled)
    assert second.status is sp.StepStatus.REJECTED and not second.done
    assert second.effect.action is sp.StepAction.KEEP_WORKING
    assert len(reader.calls) == len(records) == 2 and 'FRESH WORKSPACE OBSERVATION' in full_read(reader.calls[1]).user
    assert not second.effect.verify_failures and not second.effect.critic_failures


@pytest.mark.parametrize('answers', [[{'done': False}], [None, None]])
def test_scheduled_negative_or_unknown_never_counts_as_a_coder_failure(answers):
    source, _, _, _, _, _ = make(answers)
    source = replace(source, trigger=sp.StepTrigger.SCHEDULED,
        probe=sp.ProbeEvidence(ran=True, blocked=True, repair_text='real checker line', red_findings='real checker line'))
    result = sp.StepSelection.opt_in().run(source)
    assert not result.done and not result.review_done
    assert result.effect.action is sp.StepAction.KEEP_WORKING and not result.effect.nudge
    assert not result.effect.verify_failures and not result.effect.critic_failures
    assert not result.effect.consider_critic_rescue


def test_actual_membership_and_consent_are_independent_and_absence_is_lazy():
    from cria import planner
    def poison():
        raise AssertionError('unselected STEP gathered facts or constructed services')
    for selected in (sp.StepSelection.from_definitions((sp.DEFINITION,)),
                     sp.StepSelection.from_definitions((), enabled=True),
                     sp.StepSelection.from_definitions(planner.DEFINITIONS, enabled=True)):
        result = selected.run(poison)
        assert result.status is sp.StepStatus.NOT_SELECTED
        assert result.effect.action is sp.StepAction.CONTINUE_UNREVIEWED
        assert not result.done and not result.readable and not result.review_done
        assert result.confirmation is None and not result.reason and not result.effect.nudge
        assert not result.effect.verify_failures and not result.effect.critic_failures


def test_factory_and_lazy_run_keep_exact_selected_objects_once():
    source, reader, records, _, _, _ = make([])
    seen, factories = [], []
    expected = sp.StepResult(sp.StepStatus.REJECTED, 'selected',
        effect=sp.StepEffect(sp.StepAction.RENUDGE, 'selected'))
    def execute(actual):
        seen.append(actual)
        return expected
    definition = replace(sp.DEFINITION, execute=execute)
    selected = sp.StepSelection.from_definitions((definition,), enabled=True)
    def build():
        factories.append('build')
        return source
    result = selected.run(build)
    assert selected.definition is definition and result is expected
    assert factories == ['build'] and len(seen) == 1 and seen[0] is source
    assert not reader.calls and not records


@pytest.mark.parametrize('returned', [None, True, {'status': 'approved'},
    sp.StepResult('approved'), sp.StepResult(sp.StepStatus.REJECTED, effect=None),
    sp.StepResult(sp.StepStatus.REJECTED, effect=sp.StepEffect('advance')),
    sp.StepResult(sp.StepStatus.APPROVED, readable='yes'),
    sp.StepResult(sp.StepStatus.REJECTED, reason=None),
    sp.StepResult(sp.StepStatus.REJECTED, effect=sp.StepEffect(nudge=None)),
    sp.StepResult(sp.StepStatus.REJECTED, effect=sp.StepEffect(verify_failures=True)),
    sp.StepResult(sp.StepStatus.REJECTED, effect=sp.StepEffect(critic_failures=-1)),
    sp.StepResult(sp.StepStatus.REJECTED, effect=sp.StepEffect(red_gate_advance=1))])
def test_invalid_selected_result_is_rejected_after_actual_input_delivery(returned):
    source, _, _, _, _, _ = make([])
    seen = []
    def execute(actual):
        seen.append(actual)
        return returned
    definition = replace(sp.DEFINITION, execute=execute)
    with pytest.raises(TypeError):
        sp.StepSelection.from_definitions((definition,), enabled=True).run(lambda: source)
    assert len(seen) == 1 and seen[0] is source


def test_factory_rejects_duplicate_or_mutable_selection_without_filling_defaults():
    with pytest.raises(ValueError):
        sp.StepSelection.from_definitions((sp.DEFINITION, sp.DEFINITION), enabled=True)
    with pytest.raises(ValueError):
        sp.StepSelection.from_definitions([sp.DEFINITION], enabled=True)
    with pytest.raises(ValueError):
        sp.StepSelection.from_definitions((), enabled=1)


def test_bad_consent_scope_or_contract_is_rejected():
    with pytest.raises(ValueError): sp.StepSelection(False, sp.DEFINITION)
    with pytest.raises(ValueError): sp.StepSelection.opt_in(replace(sp.DEFINITION, policy=replace(sp.DEFINITION.policy, scope='runtime')))
    assert sp.DEFINITION.policy.family_id == 'F50' and sp.DEFINITION.policy.scope == 'experimental'
    assert sp.DEFINITION.policy.hooks and sp.DEFINITION.policy.regressions and not sp.DEFINITION.policy.migrated


def full_read(request):
    if not request.evidence_blocks:
        return request
    first, rest = request.user.split("\n\n", 1)
    return replace(request, user=first+"\n\n"+"".join(request.evidence_blocks)+"\n\n"+rest, evidence_blocks=())
