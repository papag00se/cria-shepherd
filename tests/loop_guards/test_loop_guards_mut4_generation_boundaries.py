"""Boundary facts of the generation guards that a mutation sweep (MUT4) showed no test pinned: the stream guard's exact thresholds
(window, dead stream, clock, watch stride, whole-file stride), the recovery statuses and refusal classification of a cut turn, the grounded
next-step span, and the binding contract. Every row names the value it pins; none is a change-detector for prose."""
import dataclasses
import random

import pytest

from cria import assistruntime, bodykeys, generationguards as g, loop, prompts
from loop_guards_helpers import Chat, Log, frame, nonrepeating, reply


def _feed(guard, frames, elapsed=0.0, log=None, text=""):
    log, out = log or Log(), []
    for f in frames:
        out.append(guard.feed(f, lambda: elapsed, lambda: text, lambda: "", log))
    return out


def _chars(n):
    return [frame({"content": f"{i} "}) for i in range(n)]       # distinct, so no repeat check can fire


@pytest.mark.parametrize("window,prompt,guessed,frames,aborts_at", [
    (100, 0, False, 100, 92),       # 92% of the measured room: frame 92 aborts, frame 91 does not
    (100, 0, True, 100, None),      # a guessed window is never trusted
    (100, 500, False, 100, None),   # a prompt larger than the window leaves no room to measure
    (101, 100, False, 3, 1),        # one token of room is still a measured room: the first frame exhausts it
])
def test_the_window_guard_aborts_at_exactly_92_percent_of_a_measured_room(window, prompt, guessed, frames, aborts_at):
    out = _feed(g.StreamGuard(g.StreamInput(window, prompt, guessed)), _chars(frames))
    first = next((i + 1 for i, r in enumerate(out) if r.status is g.StreamStatus.ABORT), None)
    assert first == aborts_at
    if aborts_at:
        assert out[first - 1].verdict["window_exhausted"] is True and out[first - 1].verdict["frames"] == aborts_at


@pytest.mark.parametrize("frames,elapsed,aborts", [
    (399, 0.0, False), (400, 0.0, True),            # 400 frames and not one character
    (1, 179.9, False), (1, 180.0, True),            # or 180 seconds of silence
])
def test_a_stream_that_says_nothing_is_dead_at_400_frames_or_180_seconds(frames, elapsed, aborts):
    out = _feed(g.StreamGuard(g.StreamInput(None, 0, True)), [frame()] * frames, elapsed)
    assert (out[-1].status is g.StreamStatus.ABORT) is aborts
    if aborts:
        assert out[-1].verdict["dead_stream"] is True


def test_the_reasoning_watch_runs_every_400_characters_and_only_while_no_action_is_complete():
    calls = []
    watch = lambda text, tokens: calls.append((len(text), tokens))           # returns None: keep going
    guard = g.StreamGuard(g.StreamInput(None, 0, True, watch=watch))
    for n in (399, 400, 401, 799, 800):
        _feed(guard, [frame({"content": "a"})], text="x" * n)
    assert calls == [(400, 100), (800, 200)]                                 # the default completed_action says "not complete"
    done = g.StreamGuard(g.StreamInput(None, 0, True, watch=watch, completed_action=lambda: True))
    _feed(done, [frame({"content": "a"})], text="x" * 5000)
    assert calls == [(400, 100), (800, 200)]
    log = Log()
    hit = g.StreamGuard(g.StreamInput(None, 0, True, watch=lambda t, n: {"hits": 7, "reasoning_tokens": n}))
    result = _feed(hit, [frame({"content": "a"})], text="x" * 400, log=log)[0]
    assert result.status is g.StreamStatus.ABORT and result.verdict == {"hits": 7, "reasoning_tokens": 100}
    assert log.first("rumination.abort")["hits"] == 7 and log.first("rumination.abort")["reasoning_tokens"] == 100


def test_a_whole_file_repeat_is_caught_on_the_frame_that_brings_the_2048th_new_character():
    unit = nonrepeating(6664, seed=5)
    text = unit * 3
    guard = g.StreamGuard(g.StreamInput(None, 0, True))
    log = Log()
    early, late = _feed(guard, [frame({"content": text[:17944]}), frame({"content": text[17944:]})], log=log)
    assert early.status is g.StreamStatus.CONTINUE
    assert late.status is g.StreamStatus.ABORT and late.verdict == {"degenerate": True, "chars": len(text)}
    assert log.first("rumination.abort")["wide"] is True


def test_a_wire_timeout_event_says_dead_stream_and_wire():
    log = Log()
    g.StreamGuard(g.StreamInput(None, 0, True)).wire_timeout(12.34, "boom", log)
    event = log.first("rumination.abort")
    assert (event["dead_stream"], event["wire"], event["seconds"], event["chunks"]) == (True, True, 12.3, 0)


@pytest.mark.parametrize("text,period", [("", 0), ("a", 1), ("aa", 1), ("ab", 2), ("abab", 2), ("abcab", 3), ("aabaaab", 4), ("aabaabaab", 3)])
def test_smallest_period_is_the_shortest_unit_the_text_is_a_prefix_of_repeating(text, period):
    assert g._smallest_period(text) == period
    rng = random.Random(4)
    for _ in range(300):
        s = "".join(rng.choice("ab") for _ in range(rng.randint(2, 14)))
        assert g._smallest_period(s) == next(p for p in range(1, len(s) + 1) if s[p:] == s[:len(s) - p])


@pytest.mark.parametrize("budget,tokens,markers,rate,arm", [
    (1000, 500, 6, 3, "second_guessing"), (1000, 499, 6, 3, None),    # half the budget is the gate
    (1000, 500, 5, 3, None),                                          # six markers are the floor of density
    (4000, 2000, 6, 3, "second_guessing"),                            # 3.0 per 1k at a rate of 3: equal counts
    (4000, 2000, 6, 3.002, None),                                     # ... and a hair above the measured rate is not dense
    (1, 1, 6, 4000, "second_guessing"),                               # one token, six markers: 6,000 per 1k beats the length arm's label
    (1000, 1000, 0, 3, "length"), (1000, 999, 0, 3, None)])           # the whole budget is the backstop
def test_reasoning_detector_thresholds_are_exact(budget, tokens, markers, rate, arm):
    verdict = g.Detector(budget, rate).check("actually " * markers + "filler " * 50, tokens)
    assert (verdict["arm"] if verdict else None) == arm


def test_budget_fallback_and_token_estimate():
    assert [g.Detector(b).budget for b in (None, 0, -5, 1, 7)] == [g.DEFAULT_REASONING_BUDGET, g.DEFAULT_REASONING_BUDGET, g.DEFAULT_REASONING_BUDGET, 1, 7]
    assert g.Detector.from_reasoning_budget(0).budget == 4096 and g.Detector(1001).budget_gate() == 500
    assert (g.estimate_reasoning_tokens("a" * 8), g.estimate_reasoning_tokens(None), g.count_markers(None)) == (2, 0, 0)


def _unit(size):
    return "".join(chr(97 + (i % 26)) for i in range(size))


@pytest.mark.parametrize("text,stuck", [
    ("0" * 2048, True), ("0" * 2047, False),                          # the window is 2,048 characters
    (_unit(682) * 3 + _unit(682)[:2], True),                          # a unit filling exactly a third of the window repeats three times
])
def test_degenerate_tail_window_and_third_boundaries(text, stuck):
    assert g.degenerate_tail(text) is stuck


@pytest.mark.parametrize("text,stuck", [
    ("ab" * 4096, True), ("ab" * 4095 + "a", False),                  # 8,192 characters is the least that is judged
    (nonrepeating(6664, seed=5) * 2, False),                          # two whole copies are not three, even with nothing in front
    (nonrepeating(6664, seed=5) * 3, True),                           # exactly three copies fill the tail: still a loop
    (nonrepeating(10923, seed=5) * 3, False),                         # three copies that do not fit the 32,768-character tail are not seen
])
def test_degenerate_wide_boundaries(text, stuck):
    assert g.degenerate_wide(text) is stuck


# ---- recovery of a cut or aborted turn, through the loop's own binding -----------------------------------------------------------------

def _write(args, name="write_file", finish="tool_calls"):
    return reply("", finish=finish, tool_calls=[{"id": "w", "type": "function", "function": {"name": name, "arguments": args}}])


def _recover(first, *replies, selected, body=None):
    body = body if body is not None else {"messages": [{"role": "user", "content": "task"}], "tools": []}
    chat, log = Chat(*replies), Log()
    return loop._generation_recovery(first, body, chat, log, selected=selected), chat, log, body


TRUNC = g.SelectedGuards(None, g.TRUNCATION)
CUT_W, CUT_E, NO_PATH = '{"path":"a.txt","content":"cut', '{"path":"a.txt","old_string":"o","new_string":"cut', '{"content":"cut'
OK_W = '{"path":"a.txt","content":"whole"}'


@pytest.mark.parametrize("first,retries,status,attempts", [
    (_write(CUT_W), [_write(CUT_W)] * 2 + [reply("ok")], g.RecoveryStatus.RECOVERED, 3),     # recovered on the last allowed retry: not exhausted
    (_write(CUT_W), [_write(CUT_W)], g.RecoveryStatus.EXHAUSTED, 3),                         # the retry budget spent: exhausted exactly at the cap
    (_write(CUT_W), [_write(NO_PATH)], g.RecoveryStatus.REFUSED, 1),                         # no path to name: refused, not exhausted
    (_write('{"cmd":"cut', name="exec_command"), [], g.RecoveryStatus.REFUSED, 0),           # refused before any retry was spent
    (_write('{"input":"*** Begin Patch\\n*** Update File: a.py\\n+x', name="apply_patch"), [reply("ok")], g.RecoveryStatus.RECOVERED, 1),   # a patch names its file in its text
    (reply("fine"), [], g.RecoveryStatus.UNCHANGED, 0),
])
def test_a_cut_turn_ends_recovered_exhausted_or_refused_at_the_retry_cap(first, retries, status, attempts):
    stages, chat, _, _ = _recover(first, *retries, selected=TRUNC)
    assert (stages.truncation.status, stages.truncation.attempts, len(chat.bodies)) == (status, attempts, attempts)


@pytest.mark.parametrize("first,retries,key,note", [
    (_write(CUT_W), [_write(CUT_W)], "selfcut_write", "stopped early mid-write"),
    (_write(CUT_E, name="edit_file"), [_write(CUT_E, name="edit_file")], "selfcut_edit", "stopped early mid-write"),
    (_write(OK_W, finish="length"), [_write(CUT_W, finish="length")], "truncated_write", "actions withheld"),
    (_write(CUT_W), [_write(NO_PATH)], "selfcut_write", "stopped early mid-write"),           # the last cut call names no path but is still a file write
    (_write(CUT_W), [_write('{"cmd":"cut', name="exec_command")], "truncated_call", "ended before the call was complete"),   # ... and one that is no write at all is a plain call
])
def test_the_refusal_names_what_the_last_cut_call_was(first, retries, key, note):
    stages, chat, log, body = _recover(first, *retries, selected=TRUNC)
    assert note in " ".join(stages.completion[bodykeys.NOTES])
    event = log.first("loop.truncated_refused")
    assert event["classification"] == key
    wording = event["wording"]       # a turn the server cut at its limit is told the generic incomplete-reply wording instead
    text = prompts.load(wording) if wording == "generation_incomplete_refused" else prompts.load_map("call_refused")[wording]
    assert (wording == key) is (key != "truncated_write") and body["messages"][-1]["content"].startswith(text)
    if key == "truncated_call":
        assert len(chat.bodies) == 1                                  # a call that names no file is not retried again


def test_a_retry_carries_the_whole_conversation_then_the_notice():
    _, chat, _, _ = _recover(_write(CUT_W), reply("ok"), selected=TRUNC)
    sent = chat.bodies[0]["messages"]
    assert len(sent) == 2 and sent[0] == {"role": "user", "content": "task"} and sent[1]["role"] == "user"


def test_a_refusal_with_no_conversation_to_append_to_does_not_invent_one():
    body = {"tools": []}
    stages, _, _, _ = _recover(_write('{"cmd":"cut', name="exec_command"), selected=TRUNC, body=body)
    assert stages.truncation.status is g.RecoveryStatus.REFUSED and body == {"tools": []}


def test_a_cut_call_that_names_no_file_is_refused_at_once_with_the_incomplete_arguments_wording_and_each_try_is_numbered():
    _, chat, log, body = _recover(_write('{"cmd":"cut', name="exec_command"), selected=TRUNC)
    assert not chat.bodies and log.first("loop.incomplete_tool_call_dropped") is not None and log.first("loop.truncated") is None
    assert body["messages"][-1]["content"].startswith(prompts.load_map("call_refused")["incomplete_args"])
    _, _, log, _ = _recover(_write(CUT_W), _write(CUT_W), selected=TRUNC)
    assert [f["attempt"] for kind, f in log.events if kind == "loop.truncated"] == [1, 2, 3]


def test_a_withheld_patch_beside_the_cut_call_is_named_with_the_file_its_text_edits():
    patch = {"id": "p", "type": "function", "function": {"name": "apply_patch", "arguments": '{"input":"*** Begin Patch\\n*** Update File: a.py\\n@@\\n+x\\n*** End Patch"}'}}
    cut = {"id": "w", "type": "function", "function": {"name": "write_file", "arguments": CUT_W.replace("a.txt", "b.txt")}}
    _, chat, _, _ = _recover(reply("", tool_calls=[patch, cut]), reply("ok"), selected=TRUNC)
    assert "`apply_patch` on `a.py`" in chat.bodies[0]["messages"][-1]["content"]


RUN = g.SelectedGuards(g.RUNAWAY, None)


def _aborted(**verdict):
    comp = reply("", finish="rumination")
    comp[bodykeys.RUMINATION] = verdict
    return comp


@pytest.mark.parametrize("retries,status,attempts", [
    ([reply("ok")], g.RecoveryStatus.RECOVERED, 1),
    ([_aborted(degenerate=True), _aborted(window_exhausted=True), _aborted(dead_stream=True)], g.RecoveryStatus.EXHAUSTED, 3),
    ([_aborted(dead_stream=True)], g.RecoveryStatus.IDENTICAL, 2),
])
def test_an_aborted_turn_ends_recovered_exhausted_or_identical_and_ships_a_plain_stop(retries, status, attempts):
    stages, _, _, _ = _recover(_aborted(dead_stream=True), *retries, selected=RUN)
    assert (stages.runaway.status, stages.runaway.attempts) == (status, attempts)
    assert stages.completion["choices"][0]["finish_reason"] in ("stop", "length")
    assert bodykeys.RUMINATION not in stages.completion


def test_a_recovered_turn_keeps_its_own_finish_reason_and_calls():
    call = {"id": "c", "type": "function", "function": {"name": "exec_command", "arguments": '{"cmd":"ls"}'}}
    stages, _, _, _ = _recover(_aborted(hits=8, reasoning_tokens=900), reply("", finish="tool_calls", tool_calls=[call]), selected=RUN)
    assert stages.completion["choices"][0]["finish_reason"] == "tool_calls" and stages.completion["choices"][0]["message"]["tool_calls"] == [call]
    assert stages.runaway.status is g.RecoveryStatus.RECOVERED


# ---- the grounded next step: only a line the coder was actually shown, in a file nothing has changed since --------------------------------

def _grounded(*, unedited=True, same=True, span=(5, 10), mutated=False, text="a\nb\nc\n", line=10):
    services = g.GroundedNoticeServices(
        gate_unedited=lambda: unedited, gate_lines=lambda: [("p.py:%d: bad" % line, "p.py", line)],
        reads=lambda msgs: [g.ReadResult(3, "p.py", None, None, text)], read_span=lambda s, e, t: span,
        same_file=lambda a, b: same, mutated_after=lambda msgs, pos, path: mutated)
    return g.grounded_next_step([], services)


@pytest.mark.parametrize("kwargs,named", [
    (dict(span=(5, 10)), True), (dict(span=(10, 20)), True),                   # both ends of the shown span are shown
    (dict(span=(11, 20)), False), (dict(span=(1, 9)), False),
    (dict(span=(1, None), text="\n".join("l%d" % i for i in range(12))), True),   # an open-ended read shows as many lines as the text has
    (dict(span=(1, None), text="\n".join("l%d" % i for i in range(9))), False),
    (dict(mutated=True), False), (dict(same=False), False), (dict(unedited=False), False)])
def test_the_grounded_step_names_a_finding_only_when_its_line_was_shown_and_the_file_is_unchanged(kwargs, named):
    assert bool(_grounded(**kwargs)) is named
    assert g.grounded_next_step([], None) == ""


def test_the_grounded_step_skips_a_read_with_no_span_and_a_read_of_another_file():
    services = g.GroundedNoticeServices(
        gate_unedited=lambda: True, gate_lines=lambda: [("p.py:3: bad", "p.py", 3)],
        reads=lambda msgs: [g.ReadResult(1, "q.py", None, None, "x"), g.ReadResult(2, "p.py", None, None, "x"), g.ReadResult(3, "p.py", None, None, "x\ny\nz")],
        read_span=lambda s, e, t: None if t == "x" else (1, 3), same_file=lambda a, b: a == b, mutated_after=lambda *a: False)
    assert "p.py" in g.grounded_next_step([], services)      # only the third read can ground it


# ---- the binding contract -----------------------------------------------------------------------------------------------------------

def test_selected_guards_refuse_a_miswired_definition_and_build_a_detector_only_when_selected_and_applicable():
    other = dataclasses.replace(g.RUNAWAY, policy=dataclasses.replace(g.RUNAWAY.policy, id="x"))
    for bad in (other, g.TRUNCATION, dataclasses.replace(g.RUNAWAY, execute=None)):
        with pytest.raises(ValueError, match="Invalid generation executable contract: generation-runaway-guard"):
            g.SelectedGuards(bad, None)
    with pytest.raises(ValueError, match="Unknown generation executable contract: x"):
        g.SelectedGuards.from_definitions([other])
    with pytest.raises(ValueError, match="Duplicate generation executable: generation-runaway-guard"):
        g.SelectedGuards.from_definitions([g.RUNAWAY, g.RUNAWAY])
    assert g.SelectedGuards.from_definitions([g.RUNAWAY, g.TRUNCATION]) == g.SelectedGuards(g.RUNAWAY, g.TRUNCATION)
    assert g.SelectedGuards(g.RUNAWAY, None).detector(lambda: 100).budget == 100
    nothing = lambda: pytest.fail("a reserve was gathered for a detector that cannot be built")
    assert g.SelectedGuards(g.RUNAWAY, None).detector(nothing, applicable=False) is None
    assert g.SelectedGuards(None, g.TRUNCATION).detector(nothing) is None


def test_both_generation_guards_are_selected_from_rung_4_and_neither_below():
    ids = {g.RUNAWAY.policy.id, g.TRUNCATION.policy.id}
    assert ids <= set(assistruntime.AssistRuntime.select(level=4).selected)
    assert not ids & set(assistruntime.AssistRuntime.select(level=3).selected)


def _execute_runaway(first, *replies, role=None, body=None):
    chat, log = Chat(*replies), Log()
    body = body if body is not None else {"messages": [{"role": "user", "content": "task"}], "tools": []}
    services = loop._ObservedCoderRetries(chat, loop._parse_completion, loop._add_note, log, role)
    return g.recover_runaway(g.RecoveryInput(first, body), services), chat


@pytest.mark.parametrize("kwargs", [None, {"keep": 1, "enable_thinking": True}])
def test_the_reasoning_off_retry_builds_its_own_template_kwargs_and_keeps_the_callers_other_ones(kwargs):
    from types import SimpleNamespace
    body = {"messages": [{"role": "user", "content": "task"}], "tools": [], **({"chat_template_kwargs": kwargs} if kwargs else {})}
    _, chat = _execute_runaway(_aborted(dead_stream=True), reply("ok"), role=SimpleNamespace(reasoning="on", think_protocol="chat_template"), body=body)
    sent = chat.bodies[0]["chat_template_kwargs"]
    assert sent["enable_thinking"] is False and sent.get("keep") == (1 if kwargs else None)
