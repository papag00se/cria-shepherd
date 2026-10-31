"""Stalled work through the real Loop driver: what the coder is sent, what only a retained reply acknowledges, and the
call clock the detector reads, with the assist selected, absent or failing."""
import json
from dataclasses import replace

import pytest
from cria import assistruntime, bodykeys, denial, loop, stalledwork as sw, upstream
from loop_orientation_helpers import KEY, Log, driver, local_workspace_view, tool_reply, transport  # noqa: F401

REFUSED_NOTE = "refused (not run)"

def call(cid, name="read_file", **args):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args or {"path": "next.txt"})}}

def refused_history(n=3):
    out = []
    for i in range(n):
        out += [{"role": "assistant", "content": None, "tool_calls": [call(f"x{i}")]},
                {"role": "tool", "tool_call_id": f"x{i}", "content": REFUSED_NOTE, bodykeys.RESULT_OUTCOME: denial.REFUSED}]
    return out

def select(*, disabled=False, definition=sw.DEFINITION):
    others = tuple(d for d in assistruntime.DEFINITIONS if d.policy.id != sw.DEFINITION.policy.id)
    return assistruntime.AssistRuntime.select(level=5, registrations=others + (definition,),
                                              disabled=(sw.DEFINITION.policy.id,) if disabled else ())

def rig(monkeypatch, replies, *, disabled=False, history=(), definition=sw.DEFINITION):
    drv, sess, body = driver()
    drv._ctx.pilot_runtime = select(disabled=disabled, definition=definition)
    drv._ctx.assists = True
    body["messages"] += list(history)
    send, posted = transport(replies)
    monkeypatch.setattr(drv._ctx.coder_chat.__self__, "_receive_open", send)
    return drv, sess, body, posted

def carried(text, request):
    return any(text in str(m.get("content")) for m in request["messages"])

def test_a_refusal_steer_is_acknowledged_only_by_the_reply_the_coder_actually_returned(monkeypatch):
    """Three refused calls arm the refusal guard once the next reply is forwarded; with no shell and no reasoner the measured
    floor goes to the coder. A provider failure delivers nothing, so the same steer is offered again and is credited once,
    by the retained reply."""
    drv, sess, body, posted = rig(monkeypatch, [tool_reply("first"), upstream.UpstreamError("down"), tool_reply("after")],
                                  history=refused_history())
    drv.drive(body, KEY, None, Log())
    assert sess.redirect_due and sess.repeat_count == 3 and sess.stalled_steer is None and sess.action_seq == 1
    with pytest.raises(upstream.UpstreamError):
        drv.drive(body, KEY, None, Log())
    steer = sess.stalled_steer
    assert steer is not None and steer.trigger is sw.Trigger.REFUSAL and "3 of your recent calls were refused" in steer.text
    assert carried(steer.text, posted[1]) and sess.stalled_delivered is None and sess.action_seq == 1
    out = drv.drive(body, KEY, None, Log())
    assert out["choices"][0]["message"]["tool_calls"][0]["id"] == "after"
    assert carried(steer.text, posted[2]) and sess.stalled_steer is None and sess.stalled_delivered is steer
    assert sess.action_seq == 2

def write_reply(cid, path="a.py"):
    return {"choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant", "content": None, "tool_calls": [
        call(cid, "write_file", path=path, content="source\n")]}}]}

@pytest.mark.parametrize("disabled", [False, True], ids=["selected", "absent"])
def test_with_the_assist_absent_nothing_is_armed_but_the_call_clock_and_write_facts_still_advance(monkeypatch, disabled):
    """The detector is optional; the call clock and the write registry are the loop's own. A refused window arms the guard only
    when it is selected, while the forwarded write is registered either way."""
    drv, sess, body, posted = rig(monkeypatch, [write_reply("w1"), tool_reply("n")], disabled=disabled, history=refused_history())
    first = drv.drive(body, KEY, None, Log())
    assert sess.redirect_due is (not disabled) and sess.spin_probe_due is False
    assert sess.action_seq == 1 and sess.write_tracking and sess.write_call_ids == ["w1"]
    assert (sess.blocked_fired_seq == -10000) is disabled
    assert not sess.recent_writes                                    # a refused-window completion never feeds the wheel-spin streak
    body["messages"] += [first["choices"][0]["message"], {"role": "tool", "tool_call_id": "w1", "content": "Wrote a.py",
                                                          bodykeys.RESULT_OUTCOME: denial.LANDED}]
    drv.drive(body, KEY, None, Log())                                # the next drive carries the write's result home, steer pending or not
    assert sess.write_result_ids == {"w1"} and sess.write_call_ids == ["w1"]

@pytest.mark.parametrize("disabled", [False, True], ids=["selected", "absent"])
def test_the_call_clock_dates_the_coders_own_check_and_a_genuine_act_satisfies_act_first_with_or_without_the_assist(monkeypatch, disabled):
    """Required facts do not depend on the detector: the first retained act satisfies act-first (no extra leg-0 call) and a later
    own check run is dated by the same clock that the freshness of the checks is judged on."""
    done = {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "done"}}]}
    drv, sess, body, posted = rig(monkeypatch, [tool_reply("own-check"), done, tool_reply("unneeded")], disabled=disabled)
    body["tools"].append({"type": "function", "function": {"name": "exec_command", "parameters": {
        "type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}}})
    sess.last_gate_flag, sess.last_gate_seq = "$ pytest -q\nprior exact failure", 0
    first = drv.drive(body, KEY, None, Log())
    own = {"id": "own-check", "type": "function", "function": {"name": "exec_command", "arguments": '{"cmd":"pytest -q"}'}}
    message = {**first["choices"][0]["message"], "tool_calls": [own]}
    body["messages"] += [message, {"role": "tool", "tool_call_id": "own-check", "content": "Process exited with code 0\nOutput:\nok"}]
    drv.drive(body, KEY, None, Log())
    assert len(posted) == 2 and not sess.leg0_nudged and sess.action_seq == 1
    assert sess.own_check_runs == [(1, ["pytest -q"], 0)] and "pytest -q" in loop.newer_own_run(sess)

@pytest.mark.parametrize("start,blocked,end,fired", [(49, 38, 51, 50), (24, 14, 26, 26)])
def test_a_multi_call_reply_is_dated_from_where_its_batch_began(monkeypatch, start, blocked, end, fired):
    """One reply carrying two calls advances the clock by two; the refusal cooldown is measured from the batch's first call
    (still cooling in the first row, expired by the second call in the second), never from its end."""
    batch = tool_reply("b1")
    batch["choices"][0]["message"]["tool_calls"].append(call("b2"))
    drv, sess, body, posted = rig(monkeypatch, [batch], history=refused_history())
    sess.action_seq, sess.blocked_fired_seq = start, blocked
    log = Log()
    out = drv.drive(body, KEY, None, log)
    assert len(out["choices"][0]["message"]["tool_calls"]) == 2
    assert sess.action_seq == end and sess.blocked_fired_seq == fired and sess.redirect_due and sess.repeat_count == 3
    assert [f["count"] for k, f in log.events if k == "loop.refusals"] == [3]

def test_an_observation_that_fails_after_the_coder_replied_leaves_the_steer_pending_and_retried(monkeypatch):
    """A failure while observing the reply that carried the steer publishes no delivery and loses no retry: the clock stays,
    the identical steer is offered again, and only the retained retry credits it."""
    seen = []

    def observe(source, view, *, enabled=True):
        seen.append(source)
        if len(seen) == 2:
            raise RuntimeError("observer failed after the coder replied")
        return sw.observe(source, view, enabled=enabled)
    drv, sess, body, posted = rig(monkeypatch, [tool_reply("first"), tool_reply("failed-return"), tool_reply("retry")],
                                  history=refused_history(), definition=replace(sw.DEFINITION, execute=observe))
    drv.drive(body, KEY, None, Log())                                # arms the refusal guard
    with pytest.raises(RuntimeError, match="observer failed"):
        drv.drive(body, KEY, None, Log())
    steer = sess.stalled_steer
    assert steer is not None and carried(steer.text, posted[1]) and sess.stalled_delivered is None and sess.action_seq == 1
    out = drv.drive(body, KEY, None, Log())
    assert out["choices"][0]["message"]["tool_calls"][0]["id"] == "retry"
    assert sess.stalled_steer is None and sess.stalled_delivered is steer and carried(steer.text, posted[2]) and sess.action_seq == 2

def test_an_empty_refusal_ledger_supersedes_stale_legacy_names_when_a_directive_is_vetted():
    """The structured refusal ledger is authoritative: once it exists and holds nothing, a name remembered from the legacy set is
    not an active refusal (no question is spent on it); with no ledger the legacy names are still consulted."""
    from cria import groundedaction as ga, refusalledger
    asked = []
    ask = lambda *a: asked.append(a) or "SUPPORTED"                                    # noqa: E731
    facts = ga.ActionEvidence(refusal_events=refusalledger.RefusalLedger(), refused_names=frozenset({"bad-package"}))
    engine = loop._grounded_actions()
    result = ga.DEFINITION.vet(engine, ga.CandidateInput("Remove bad-package", "", Log(), ask, facts, []))
    assert result.directive == "Remove bad-package" and not asked
    result = ga.DEFINITION.vet(engine, ga.CandidateInput("Remove bad-package", "", Log(), ask, replace(facts, refusal_events=None), []))
    assert result.directive == "Remove bad-package" and len(asked) == 1

def test_a_selected_stage_cannot_forge_the_call_clock_or_grow_the_reply_it_observed(monkeypatch):
    """The clock is the loop's own: it advances by the calls the coder's reply held when it was forwarded, whatever the assist's
    observation writes to its view or does to the reply afterwards."""
    retained = []

    def observe(source, view, *, enabled=True):
        out = sw.observe(source, view, enabled=enabled)
        retained[0]["choices"][0]["message"]["tool_calls"].append(call("callback-added"))
        view.action_seq = 999
        return out
    drv, sess, body, posted = rig(monkeypatch, [tool_reply("only")], definition=replace(sw.DEFINITION, execute=observe))
    original = drv._drive_single_item

    def remember(*args, **kwargs):
        retained.append(original(*args, **kwargs))
        return retained[0]
    monkeypatch.setattr(drv, "_drive_single_item", remember)
    drv.drive(body, KEY, None, Log())
    assert len(retained[0]["choices"][0]["message"]["tool_calls"]) == 2 and sess.action_seq == 1
    assert sess.recent_write_ids == ["only"]
