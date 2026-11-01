"""Completed-work memory (F76): a briefing is written only after the task is actually released, embedded only while that release
still stands, and never authorizes anything itself."""
import copy
import json
from dataclasses import replace

import pytest
from cria import assistruntime, completedwork as cw, loop
from cria.config import Role
from cria.plan import Plan, PlanItem
from loop_orientation_helpers import Log, local_workspace_view  # noqa: F401

MEMORY = "Built cli.py; the recorded checker passed."
TOOLS = [{"type": "function", "function": {"name": "write_file", "parameters": {
    "type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
         {"type": "function", "function": {"name": "exec_command", "parameters": {
             "type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}}}]

def completion(text, finish="stop", **message):
    return {"choices": [{"finish_reason": finish, "message": {"role": "assistant", "content": text, **message}}]}

def finished(summaries=(MEMORY,)):
    """An already settled one-step plan whose completion gate is fresh and green; the reasoner is the summary transport."""
    calls, answers = [], iter(summaries)

    def reasoner(body, log):
        calls.append(copy.deepcopy(body))
        answer = next(answers)
        if isinstance(answer, BaseException):
            raise answer
        return json.dumps(completion(answer)).encode()

    def coder(body, log):
        raise AssertionError("a settled completed plan must not redrive the coder")
    runtime = assistruntime.AssistRuntime.select(experimental_planning=True)
    ctx = loop.LoopContext(planner=None, planner_enabled=True, pilot_runtime=runtime, coder_chat=coder, reasoner_chat=reasoner,
                           reasoner_role=None, compactor_role=Role(name="compactor", backend="local", reasoning="off"),
                           runs_dir="", self_compact=False, focus_trim=False, assists=False)
    plan = Plan(id="finished", task="Build the CLI.", created="now", items=[PlanItem("Build CLI", True)], status="in_progress")
    session = loop.PlanSession(plan=plan, gate_fresh=True, last_gate_ran=True)
    driver = loop.Loop(ctx, loop.LoopStore())
    driver._store.put("sid:done", session)
    return driver, session, {"messages": [{"role": "user", "content": plan.task}], "tools": copy.deepcopy(TOOLS)}, calls

def test_a_released_task_closes_with_the_briefing_the_reasoner_wrote():
    driver, session, body, calls = finished()
    body["messages"] += [{"role": "assistant", "tool_calls": [{"id": "t", "type": "function", "function": {
                              "name": "exec_command", "arguments": '{"cmd":"pytest -q"}'}}]},
                         {"role": "tool", "tool_call_id": "t", "content": "REAL CHECKER OUTPUT 4 passed"}]
    out = driver.drive(body, "sid:done", None, Log())
    text = out["choices"][0]["message"]["content"]
    assert len(calls) == 1 and "plan complete — all 1 steps verified." in text
    assert "REAL CHECKER OUTPUT 4 passed" in calls[0]["messages"][-1]["content"]        # the summary is grounded in the real work log
    assert cw.read_history([{"role": "assistant", "content": text}]).text == MEMORY
    assert session.phase is loop.Phase.DONE and session.plan.status == "done" and driver._store.get("sid:done") is None

def judged(verdict):
    """A reasoner that rules on the whole task by phase and otherwise writes the briefing."""
    seen = []

    def reasoner(body, log):
        seen.append(log.phase)
        if log.phase.startswith("satisfaction"):
            return json.dumps(completion(json.dumps({"satisfied": verdict, "reason": "ruled", "proposed_fix": "add README"}))).encode()
        if log.phase.startswith("test-"):
            return json.dumps(completion("NOT_REQUIRED")).encode()
        return json.dumps(completion(MEMORY)).encode()
    return reasoner, seen

@pytest.mark.parametrize("verdict", [False, True])
def test_a_task_the_whole_task_review_refuses_is_never_summarised_and_one_it_releases_is(verdict):
    """The briefing is memory, not authority: the review's ruling decides whether the session closes, and only a release is
    summarised (a rejected task keeps the coder working with no summary call and no briefing in what it is sent)."""
    from cria import livingplan, planner, stepreview
    driver, session, body, calls = finished()
    off = tuple(d.policy.id for d in planner.DEFINITIONS) + (livingplan.DEFINITION.policy.id, stepreview.DEFINITION.policy.id)
    driver._ctx.pilot_runtime = assistruntime.AssistRuntime.select(experimental_planning=True, disabled=off)
    reasoner, seen = judged(verdict)
    driver._ctx.reasoner_chat, driver._ctx.assists = reasoner, True
    driver._ctx.satisfaction_check_start = driver._ctx.satisfaction_check_every = 1      # the scheduled whole-task review
    body["tools"] = body["tools"][:1]                                                    # no shell: the review is the only release
    session.plan.items[0].done = False
    driver._ctx.coder_chat = lambda b, log: json.dumps({"choices": [{"finish_reason": "tool_calls", "message": {
        "role": "assistant", "content": None, "tool_calls": [{"id": "keep", "type": "function", "function": {
            "name": "exec_command", "arguments": '{"cmd":"pwd"}'}}]}}]}).encode()
    out = driver.drive(body, "sid:done", None, Log())
    message = out["choices"][0]["message"]
    summarised = any(not p.startswith(("satisfaction", "test-")) for p in seen)
    assert summarised is verdict
    assert (cw.BRIEFING_OPEN in str(message.get("content"))) is verdict
    assert bool(message.get("tool_calls")) is not verdict

@pytest.mark.parametrize("changed", ["task", "action", "gate"])
def test_a_release_that_stops_standing_while_the_summary_is_written_embeds_no_briefing(changed):
    """The summary call takes real time: if the task, the call clock or the gate moved meanwhile, the briefing describes a
    release that no longer holds, so it is generated (the cost was paid) but never embedded."""
    from cria import probegate
    from cria.proberun import ProbeReport
    driver, session, body, calls = finished()

    def reasoner(request, log):
        calls.append(request)
        if changed == "task":
            session.plan.task = "A different task was installed before output."
        elif changed == "action":
            session.action_seq += 1                    # a newly retained real action
        else:
            loop.record_gate_state(session, probegate.GateOutcome(ran=True, report=ProbeReport(project_type=["python"], selected=[], results=[])),
                                   "cli.py:4: AssertionError", Log())
        return json.dumps(completion(MEMORY)).encode()
    driver._ctx.reasoner_chat = reasoner
    out = driver.drive(body, "sid:done", None, Log())
    assert len(calls) == 1 and cw.BRIEFING_OPEN not in json.dumps(out, ensure_ascii=False)

class Interrupted(BaseException):
    """The harness hung up mid-request (not an Exception: nothing in the summary path may swallow it)."""

def test_an_interrupted_summary_keeps_the_finishing_session_and_the_retry_writes_fresh_memory():
    driver, session, body, calls = finished([MEMORY])
    first = driver._ctx.reasoner_chat

    def reasoner(request, log):
        if not calls:
            calls.append(request)
            raise Interrupted()
        return first(request, log)
    driver._ctx.reasoner_chat = reasoner
    with pytest.raises(Interrupted):
        driver.drive(body, "sid:done", None, Log())
    assert driver._store.get("sid:done") is session
    out = driver.drive(body, "sid:done", None, Log())
    text = out["choices"][0]["message"]["content"]
    assert len(calls) == 2 and cw.read_history([{"role": "assistant", "content": text}]).text == MEMORY
    assert driver._store.get("sid:done") is None

@pytest.mark.parametrize("carrier,expected", [
    (f"{cw.BRIEFING_OPEN}\nHistorical cli.py work\n{cw.BRIEFING_CLOSE}", "Historical cli.py work"),
    (f"Quoted {cw.BRIEFING_OPEN}contamination{cw.BRIEFING_CLOSE}\n{cw.BRIEFING_OPEN}\nActual carried work\n{cw.BRIEFING_CLOSE}",
     "Actual carried work"),
    (f"{cw.BRIEFING_CLOSE}\n{cw.BRIEFING_OPEN}\nUnclosed claim", ""),
    (f"{cw.BRIEFING_OPEN}\n \n{cw.BRIEFING_CLOSE}", ""),
], ids=["plain", "inline-quote-before-real-envelope", "closer-before-opener", "emptied"])
def test_a_planner_off_follow_up_reads_the_carried_briefing_from_history_and_asks_for_no_new_one(monkeypatch, carrier, expected):
    """With planning off nothing generates a briefing, but a follow-up still starts from the one the transcript carries (read by
    the same passive parser, quoted or malformed envelopes ignored); it survives a restart and no summary is requested."""
    from types import SimpleNamespace
    from loop_orientation_helpers import KEY, driver, tool_reply, transport
    drv, old, body = driver()
    drv._store.drop(KEY)
    send, posted = transport([tool_reply("followup-action")])
    monkeypatch.setattr(drv._ctx.coder_chat.__self__, "_receive_open", send)
    drv._ctx.reasoner_chat = lambda *a, **k: pytest.fail("a planner-off follow-up asked the reasoner")
    body["messages"] += [{"role": "assistant", "content": carrier}, {"role": "user", "content": "Add one new CLI option."}]
    out = drv.drive(body, KEY, SimpleNamespace(engagement="task", task_type="coding", cached=False), Log())
    session = drv._store.get(KEY)
    assert out["choices"][0]["message"]["tool_calls"][0]["id"] == "followup-action" and len(posted) == 1
    assert session is not old and session.synthetic and session.plan_off and session.prior_work == expected
    restored = loop._session_from_dict(loop._session_to_dict(session))
    assert restored.prior_work == expected and restored.plan_off

CHECKLIST = "1. [done] Build CLI\n2. [done] Write tests"
CLOSING = f"{loop.indicators.MARKER}plan complete — all 2 steps verified."

def briefing_source(answers, *, summary="", prior="Earlier work, quoted exactly."):
    """The real shared summarize transport over scripted provider replies; a plan of two done steps and a large work log."""
    calls, replies = [], iter(answers)

    def chat(body, log):
        calls.append(copy.deepcopy(body))
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, bytes) else json.dumps(reply).encode()

    def ask(question, log):
        return loop.summarize(chat, question.role, question.system, question.user, log, phase=question.phase, retry_off=question.retry_off)
    plan = Plan(id="completed-plan", task="Build the CLI and retain every requested detail.", created="2026-10-14", status="done",
                items=[PlanItem("Build CLI", True), PlanItem("Write tests", True)])
    messages = [{"role": "user", "content": plan.task},
                {"role": "assistant", "tool_calls": [{"id": "write", "type": "function", "function": {
                    "name": "write_file", "arguments": json.dumps({"path": "cli.py", "content": "CURRENT FILE BYTES\n" * 2000})}}]},
                {"role": "tool", "tool_call_id": "write", "content": "Wrote cli.py\nCURRENT FILE CONTENT\n" * 2000},
                {"role": "assistant", "tool_calls": [{"id": "test", "type": "function", "function": {
                    "name": "shell", "arguments": json.dumps({"command": "pytest -q"})}}]},
                {"role": "tool", "tool_call_id": "test", "content": "REAL CHECKER OUTPUT\n4 passed\n"}]
    source = cw.BriefingInput(cw.CompletionScope("sid:one", 7), plan, messages, cw.Services(loop._work_log, ask), Log(),
                              release_authorized=True, planner_enabled=True, summary=summary, prior_work=prior,
                              compactor_role=Role(name="compactor", backend="local", reasoning="on", temperature=0.6),
                              reasoner_role=Role(name="reasoner", backend="local", reasoning="off", temperature=0.0))
    return source, calls

LONG = "Historical claim: \"the tests passed\"; a claim is not a checker result.\n" * 2000 + "LAST DETAIL"

@pytest.mark.parametrize("answers,summary,status,text,asked", [
    ([completion("Complete summary with exact files and checks.")], "", cw.BriefingStatus.GENERATED, "Complete summary with exact files and checks.", 1),
    ([completion(LONG)], "", cw.BriefingStatus.GENERATED, LONG, 1),                                        # never clipped
    ([completion(""), completion("Recovered summary.")], "", cw.BriefingStatus.GENERATED, "Recovered summary.", 2),
    ([completion(""), completion("")], "Running per-step summary", cw.BriefingStatus.RUNNING_SUMMARY, "Running per-step summary", 2),
    ([completion(""), completion("")], "", cw.BriefingStatus.CHECKLIST, CHECKLIST, 2),
    ([b"{not json", b"{not json"], "Known steps.", cw.BriefingStatus.RUNNING_SUMMARY, "Known steps.", 2),
    ([{"choices": []}, {"choices": []}], "Known steps.", cw.BriefingStatus.RUNNING_SUMMARY, "Known steps.", 2),
    ([completion(None, refusal="Cannot summarize")] * 2, "Known steps.", cw.BriefingStatus.RUNNING_SUMMARY, "Known steps.", 2),
    ([completion("partial summary", finish="length")] * 2, "Known steps.", cw.BriefingStatus.RUNNING_SUMMARY, "Known steps.", 2),
    ([completion("aborted summary", finish="rumination")] * 2, "Known steps.", cw.BriefingStatus.RUNNING_SUMMARY, "Known steps.", 2),
    ([RuntimeError("provider unavailable")] * 2, "Known steps.", cw.BriefingStatus.RUNNING_SUMMARY, "Known steps.", 2),
    ([completion('<|tool_call>call:X{<|"|>y<|"|>}')] * 2, "Known steps.", cw.BriefingStatus.RUNNING_SUMMARY, "Known steps.", 2),
])
def test_the_briefing_is_the_shared_summary_or_the_evidence_already_held_and_its_inputs_arrive_whole(answers, summary, status, text, asked):
    """Real summarize transport: an empty/unreadable/refused/cut reply gets ONE reasoning-off retry and then falls back to what the
    session already held (running summary, else the checklist) - never a claim of its own. The request carries the task, the prior
    work and every byte of the work log, summary-density hint and full token budget included."""
    source, calls = briefing_source(answers, summary=summary)
    before = copy.deepcopy((source.plan, source.messages))
    selected = cw.BriefingSelection.opt_in()
    result = selected.generate(source)
    closing = selected.embed(CLOSING, source, result)
    assert result.status is status and result.text == text and len(calls) == asked and (source.plan, source.messages) == before
    assert closing.text == (CLOSING + f"\n\n{cw.BRIEFING_OPEN}\n{text}\n{cw.BRIEFING_CLOSE}") and cw.read_history(
        [{"role": "assistant", "content": closing.text}]).text == text
    user = calls[0]["messages"][-1]["content"]
    assert source.plan.task in user and source.prior_work in user and "tools" not in calls[0]
    assert "CURRENT FILE BYTES\\n" * 2000 in user and "Wrote cli.py\nCURRENT FILE CONTENT\n" * 2000 in user and "REAL CHECKER OUTPUT" in user
    assert calls[0]["max_tokens"] == loop.SUMMARIZE_MAX_TOKENS and calls[0]["cria_density_kind"] == "summary"
    if asked == 2:
        assert calls[0]["chat_template_kwargs"] == {"enable_thinking": True} and calls[1]["chat_template_kwargs"] == {"enable_thinking": False}
    kind = "loop.compacted" if status is cw.BriefingStatus.GENERATED else "loop.compact_empty"
    assert source.log.events[-1][0] == kind

@pytest.mark.parametrize("change", ["session", "epoch", "task", "plan", "step", "status"])
def test_a_reset_fork_or_changed_plan_cannot_embed_an_earlier_summary_and_an_unreleased_task_embeds_nothing(change):
    """A summary belongs to one session, evidence epoch and plan state; whatever moved, it is not carried. The summary text itself
    ({"satisfied": true}) authorizes nothing: embedding needs the driver's own release."""
    source, calls = briefing_source([completion('{"satisfied": true, "done": true}')])
    selected = cw.BriefingSelection.opt_in()
    result = selected.generate(source)
    plan = copy.deepcopy(source.plan)
    moved = {"session": replace(source, scope=replace(source.scope, session_key="sid:fork")),
             "epoch": replace(source, scope=replace(source.scope, evidence_epoch=8))}.get(change)
    if moved is None:
        {"task": lambda: setattr(plan, "task", "New task"), "plan": lambda: setattr(plan, "id", "new-plan"),
         "step": lambda: setattr(plan.items[0], "text", "Different work"), "status": lambda: setattr(plan, "status", "in_progress")}[change]()
        moved = replace(source, plan=plan)
    closing = selected.embed("unchanged", moved, result)
    assert closing.status is cw.EmbeddingStatus.STALE and closing.text == "unchanged" and len(calls) == 1
    unreleased = replace(source, release_authorized=False)
    assert selected.embed("unchanged", unreleased, result).status is cw.EmbeddingStatus.NOT_APPLICABLE
    assert selected.generate(unreleased).status is cw.BriefingStatus.NOT_APPLICABLE and len(calls) == 1

def test_a_harness_rewrite_keeps_the_harness_summary_for_the_planner_and_stacks_no_briefing_onto_it():
    carried = cw.read_history([{"role": "assistant", "content": f"{cw.BRIEFING_OPEN}\nPrior work\n{cw.BRIEFING_CLOSE}"}])
    assert carried.followup() == cw.FollowupContext("Prior work", "Prior work")
    assert carried.followup("") == cw.FollowupContext("", "Prior work")           # an empty rewrite: the planner gets none, the coder keeps it
    assert carried.followup("Harness summary.").planner_prior_work == "" and cw.read_history([]).followup("") == cw.FollowupContext("", "")

def held(verdict_reasoner):
    """A finished-looking task whose release is a HELD claim waiting on the repo's own checks, whose green reading is in the history."""
    import base64, hashlib
    from cria import probegate, probediscovery
    driver, session, body, calls = finished()
    driver._ctx.reasoner_chat = verdict_reasoner
    session.plan.items[0].done = False
    session.done_probe, session.pending_done_parts, session.pending_done = True, ("The requested CLI work is complete.",), "The held claim."
    session.probe_call_id = "held-release-check"
    candidate = probediscovery.ProbeCandidate(probediscovery.ProbeKind.Test, ["pytest", "-q"], "", 90, 80, probediscovery.ProbeCost.Cheap,
                                              False, False, False, "fixture")
    plan = session.gate_plan = probegate.GatePlan(workspace="/offline", candidates=[candidate], transport_required=True,
                                                  script=probegate._gate_sentinel(["pytest -q"]))
    raw = f"{probegate.SECTION_PREFIX}probe-0{probegate.SECTION_SUFFIX}\n2 passed\nEXIT:0\n"
    data, offset, sections = raw.encode(), 0, {}
    for line in data.splitlines(keepends=True):
        if line.strip().startswith(probegate.SECTION_PREFIX.encode()):
            sections[line.strip()[len(probegate.SECTION_PREFIX):-len(probegate.SECTION_SUFFIX)].decode()] = offset
        offset += len(line)
    b64 = lambda raw_bytes: base64.b64encode(raw_bytes).decode()                                  # noqa: E731
    page = "\n".join([probegate._transport_marker(plan.transport_id), "path\t" + b64(f"/tmp/.cria-gate-{plan.transport_id}.spool".encode()),
                      "offset\t0", f"total\t{len(data)}", "sha256\t" + hashlib.sha256(data).hexdigest(),
                      "bounds\t" + b64(json.dumps(dict(checker_end=len(data), report_end=len(data), total=len(data), sections=sections)).encode()),
                      "data\t" + b64(data), probegate._transport_marker(plan.transport_id, end=True)])
    body["messages"] += [{"role": "assistant", "tool_calls": [{"id": "held-release-check", "type": "function", "function": {
                              "name": "exec_command", "arguments": json.dumps({"cmd": plan.script})}}]},
                         {"role": "tool", "tool_call_id": "held-release-check", "content": page}]
    return driver, session, body, calls

class FlakyLog(Log):
    """A run log whose write fails once at the moment the summary has just been produced (before any closing exists)."""
    def emit(self, kind, **fields):
        if kind == "loop.compacted" and not getattr(self, "failed", False):
            self.failed = True
            raise OSError("log write failed")
        super().emit(kind, **fields)

def test_a_held_claim_released_by_a_green_probe_is_briefed_and_a_failure_before_the_closing_replays_with_fresh_memory():
    """The held-probe release exit: the repo's own green reading settles the held claim, the whole-task review releases it and the
    briefing is written from that release. If anything fails after the summary but before the closing exists, the original held
    claim and its reading survive for a checked replay, and the replay writes new memory (the abandoned one is never reused)."""
    reasoner, _ = judged(True)
    summaries = []

    def numbered(body, log):
        if log.phase.startswith(("satisfaction", "test-")):
            return reasoner(body, log)
        summaries.append(log.phase)
        return json.dumps(completion("Abandoned first memory." if len(summaries) == 1 else MEMORY)).encode()
    driver, session, body, calls = held(numbered)
    parts, plan = session.pending_done_parts, session.gate_plan
    log = FlakyLog()
    with pytest.raises(OSError):
        driver.drive(body, "sid:done", None, log)
    assert driver._store.get("sid:done") is session and plan.transport_complete and not plan.transport_error
    assert session.done_probe and session.pending_done_parts is parts and session.pending_done == "The held claim."
    assert session.probe_call_id == "held-release-check" and session.last_gate_ran and not session.last_gate_red
    out = driver.drive(body, "sid:done", None, log)
    message = out["choices"][0]["message"]
    assert len(summaries) == 2 and cw.read_history([message]).text == MEMORY and "Abandoned" not in message["content"]
    assert not message.get("tool_calls") and driver._store.get("sid:done") is None


@pytest.mark.parametrize("kwargs,message", [
    (dict(enabled=1), "explicit experimental consent"), (dict(enabled="yes"), "explicit experimental consent"),
    (dict(enabled=False, definition=cw.DEFINITION), "explicit experimental consent"),       # a replacement without consent is still no consent
    (dict(enabled=True, definition=object()), "Incompatible"),
    (dict(enabled=True, definition=replace(cw.DEFINITION, execute=None)), "Incompatible"),
    (dict(enabled=True, definition=replace(cw.DEFINITION, embed="x")), "Incompatible"),
    (dict(enabled=True, definition=replace(cw.DEFINITION, policy=replace(cw.DEFINITION.policy, id="other"))), "Incompatible")])
def test_completed_work_generation_needs_explicit_consent_and_only_a_compatible_replacement(kwargs, message):
    """Planning-off policy: consent is exactly the bool True (never truthy), and a replacement briefing must carry the same policy and callables."""
    with pytest.raises(ValueError, match=message):
        cw.BriefingSelection(**kwargs)
    assert cw.BriefingSelection().enabled is False and cw.BriefingSelection.opt_in().enabled is True
    assert cw.BriefingSelection(True, replace(cw.DEFINITION)).enabled is True
