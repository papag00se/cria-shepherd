"""Notices to the coder state only what was measured (#5b): the output-limit retry, the thrash trigger and the
refusal trigger each describe the event that fired, with its real numbers."""

import copy
import json

import pytest

from cria import bodykeys, denial, generation, loop, prompts
from loop_rest_helpers import Rlog, loop_rest_local_view  # noqa: F401


def call(name, args, cid="c1"): return {"id": cid, "type": "function", "function": {"name": name, "arguments": args}}

def reply(calls, finish="length", content="", tokens=4450):
    return {"choices": [{"index": 0, "finish_reason": finish, "message": {"role": "assistant", "content": content,
                                                                           "tool_calls": calls}}],
            "usage": {"completion_tokens": tokens}}


# A10 call 0018: a COMPLETE one-call edit_file that reached the output limit after a long lead of text.
COMPLETE_EDIT = reply([call("edit_file", json.dumps({"path": "pom.xml", "old_string": "<a>", "new_string": "<b>"}))],
                      content="lead " * 70)
CUT_WRITE = reply([call("write_file", '{"path": "pom.xml", "content": "<project>')])
CUT_EDIT = reply([call("edit_file", '{"path": "pom.xml", "old_string": "<a>')], content="lead", tokens=100)
CUT_SHELL = reply([call("exec_command", '{"cmd": "go test ./')])


def retry_notice(coder):
    """What the model is told on the retry guard_truncation sends."""
    seen = []
    chat = lambda b, r: seen.append(b["messages"][-1]["content"]) or json.dumps(reply([], "stop", "ok")).encode()  # noqa: E731
    loop.guard_truncation(copy.deepcopy(coder), {"messages": [{"role": "user", "content": "go"}]}, chat, Rlog(), step=1)
    return seen[0]


def test_the_limit_notice_describes_the_call_that_was_actually_cut():
    """C14 D1: a COMPLETE one-call edit_file at the limit was told its whole-file write was cut and to build in small pieces."""
    for coder in (COMPLETE_EDIT, generation.safe_completion(copy.deepcopy(COMPLETE_EDIT))):      # raw reply, and after the wire
        text = retry_notice(coder)
        assert all(x in text for x in ("edit_file", "pom.xml", "4450 tokens", "arguments complete", "withheld"))
        assert f"{len(COMPLETE_EDIT['choices'][0]['message']['content'])} characters of text" in text    # measured sizes
        assert not any(f in text for f in ("whole-file", "SMALL pieces", "partway through writing", "WRITE WAS CUT OFF", "brief"))
        assert "cria" not in text.lower()
    # the build-in-pieces advice belongs only to a cut-off whole-file write
    assert "SMALL pieces" in retry_notice(CUT_WRITE) and "SMALL pieces" not in retry_notice(CUT_EDIT)
    assert "cut off at the limit" in retry_notice(CUT_EDIT)


@pytest.mark.parametrize("coder, classification, wording", [
    (CUT_SHELL, "truncated_call", "generation_incomplete_refused"),   # 17 of 17 truncations called a non-write a refused WRITE
    (CUT_WRITE, "truncated_write", "generation_incomplete_refused"),
    (reply([call("write_file", '{"path": "cart.go", "content": "package cart')], "tool_calls"), "selfcut_write", "selfcut_write"),
])
def test_a_refused_call_is_named_by_what_it_was_and_the_event_agrees_with_the_message(coder, classification, wording):
    """The wording that shipped is recorded in the event; a non-write is a refused CALL, a self-cut write keeps its own."""
    rlog, body = Rlog(), {"messages": [{"role": "user", "content": "do it"}]}
    loop.guard_truncation(copy.deepcopy(coder), body, lambda b, r: json.dumps(coder).encode(), rlog, step=1)
    event = rlog.of("loop.truncated_refused")[0]
    assert event["wording"] == wording and event.get("classification", event["wording"]) == classification
    if wording == "generation_incomplete_refused":
        assert prompts.load(wording) in "\n".join(str(m.get("content") or "") for m in body["messages"])


def thrash_text(*steps):
    """Drive the real trackers: 'r' = a red gate round, 'w' = a write the coder sent."""
    gs = loop.GuardState()
    for n, step in enumerate(steps):
        if step == "r":
            loop.track_gate_progress(gs, "ERROR same")
        else:
            body = call("write_file", json.dumps({"path": "a.java", "content": "x"}), f"w{n}")
            loop.guard_track_write_streak(gs, {"choices": [{"message": {"tool_calls": [body]}}]}, Rlog(), messages=[])
    return loop._STEER_TRIGGER["thrash"](gs, None)


def test_the_thrash_trigger_counts_the_edits_that_landed_between_red_rounds():
    """C14 D2: 'kept editing' was said when no write landed between the last rounds; now the measured count is."""
    assert "2 file edits landed between those rounds, none of them between the last 3 rounds" in thrash_text(*"rwrwrrr")
    idle = thrash_text(*"wwrrrrr")
    assert "no file edit landed between those rounds" in idle and "for 5 rounds" in idle and "kept editing" not in idle


def refused_history():
    msgs = []
    for n, cmd in enumerate(("bundle add countries", "gem install countries", "gem list --local countries",
                             "bundle info countries", "gem environment")):
        msgs += [{"role": "assistant", "tool_calls": [call("exec_command", json.dumps({"cmd": cmd}), f"r{n}")]},
                 {"role": "tool", "tool_call_id": f"r{n}", "content": denial.mark("This call did not run."),
                  bodykeys.RESULT_OUTCOME: denial.REFUSED}]
    cur = {"role": "assistant", "tool_calls": [call("exec_command", json.dumps({"cmd": "which bundler"}), "ok")]}
    return msgs + [cur, {"role": "tool", "tool_call_id": "ok", "content": "ordinary result"}], {"choices": [{"message": cur}]}


def test_the_refusal_trigger_reports_the_measured_count_and_a_call_that_was_really_refused():
    """Five distinct refusals are not 'three'; the quoted call is the last REFUSED one, not the current un-refused call."""
    msgs, current = refused_history()
    rlog, gs = Rlog(), loop.GuardState()
    loop.guard_track_refusals(gs, current, rlog, step=1, messages=msgs)
    assert gs.repeat_count == 5 and rlog.of("loop.refusals")[0]["count"] == 5
    said = loop._STEER_TRIGGER["refusal"](gs, 1)
    assert "5 of its recent calls were refused" in said and "gem environment" in said and "which bundler" not in said
    assert "repeating the SAME action" not in said and "cria" not in said.lower()


def test_the_redirect_never_re_supplies_the_body_of_a_refused_write():
    """ada-handles fabliq 0079: the 3.2 KB file was re-sent under 'choose a DIFFERENT action'; the model only renamed it."""
    body = "x" * 3200
    msgs = [{"role": "assistant", "tool_calls": [call("write_file", json.dumps({"path": "handle_resolver.py", "content": body}), "c1")]},
            {"role": "tool", "tool_call_id": "c1", "content": denial.mark("outside the workspace"),
             bodykeys.RESULT_OUTCOME: denial.REFUSED}]
    n, last = loop._refusals_in_window(msgs)
    assert n == 1 and len(last) < 400 and body not in last and "handle_resolver.py" in last


@pytest.mark.parametrize("ran,says", [(True, "verified by the completion check and the repo's own checks"),
                                      (False, "could not be run here, so nothing has verified")])
def test_the_done_note_claims_verification_only_when_the_repos_checks_ran(ran, says):
    note = loop.satisfaction_done_note("all four endpoints answer", checks_ran=ran)
    assert says in note and note.endswith("all four endpoints answer")
    assert ("verified by the completion check" in note) is ran


@pytest.mark.parametrize("briefing,named", [
    ("The Python script resolver.py has not been written. Unit tests have not been added.", ["resolver.py"]),  # maple 1786218955
    ("Nothing was created yet for the Review.md file.", []),                              # no denial sentence shape: left alone
    ("Never written: test_a.py. The README is fine.", ["tests/test_a.py"]),               # the negation leads; a bare name resolves to the listed path
    ("resolver.py has not been written. resolver.py has not been created.", ["resolver.py"]),   # named once, not twice
    ("ghost.py has not been written.", []),                                              # a file cria cannot see is not contradicted
])
def test_a_briefing_that_denies_a_file_on_disk_is_corrected_additively_and_never_edited(briefing, named):
    """The briefing keeps its words; cria appends what its own listing observed (the real spelling), once, with an event."""
    log = Rlog()
    out = loop._briefing_disk_truth(briefing, "resolver.py\ntests/test_a.py\nREVIEW.md\n", log)
    assert out.startswith(briefing)
    assert (out != briefing) is bool(named) and all(out[len(briefing):].count(n) == 1 for n in named)
    assert ("context.briefing_denies_disk" in log.kinds()) is bool(named)
