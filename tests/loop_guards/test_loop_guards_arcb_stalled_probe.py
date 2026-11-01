"""The wheel-spin probe is a ticket: only the reading that answers that exact call (and only once the harness has delivered the
whole reading) settles it into the steer the coder receives."""
import base64
import json

import pytest

from cria import probegate
from loop_guards_gatefixture import bounds_field_for, gate_page
from loop_guards_helpers import Chat
from test_loop_guards_scenario_lb_sessions import RED, SHELL, WRITE, Run, judge, local_view, say  # noqa: F401


def spinning(tmp_path):
    """A plan-off session whose coder rewrote app.py five times; the next drive is cria's own check probe."""
    count, bodies = [0], []

    def rewrite(body, rlog):
        count[0] += 1
        bodies.append(body)
        return say(None, tool_calls=[{"id": f"w{count[0]}", "type": "function", "function": {
            "name": "write_file", "arguments": json.dumps({"path": "app.py", "content": f"x = {count[0]}\n"})}}])
    run = Run(tmp_path, rewrite, judge([], []), tools=(SHELL, WRITE))
    for _ in range(5):
        run.turn()
    probe = run.turn()
    assert probe["tool_calls"][0]["function"]["name"] == "shell" and run.sess.stalled_probe is not None
    return run, bodies

def answer(run, call_id, content):
    call = run.out["choices"][0]["message"]["tool_calls"][0]
    run.body["messages"] += [{"role": "assistant", "content": None, "tool_calls": [call]},
                             {"role": "tool", "tool_call_id": call_id, "content": content}]
    run.out = run.driver.drive(json.loads(json.dumps(run.body)), "sid:k", None, run.log)
    return run.out["choices"][0]["message"]

def envelope(plan, *fields):
    return "\n".join([probegate._transport_marker(plan.transport_id), *fields, probegate._transport_marker(plan.transport_id, end=True)])

@pytest.mark.parametrize("answers_probe", [False, True], ids=["other-call", "probe-call"])
def test_only_the_reading_that_answers_the_probe_call_settles_it(tmp_path, answers_probe):
    """A tool result for some other call is not the reading: the ticket stays owned, the coder is told the check is UNKNOWN and
    hears no steer; the result of the probe call itself settles the ticket and the reading reaches the coder."""
    run, bodies = spinning(tmp_path)
    ticket, plan = run.sess.stalled_probe, run.sess.gate_plan
    probe_id = run.out["choices"][0]["message"]["tool_calls"][0]["id"]
    answer(run, probe_id if answers_probe else "unrelated", gate_page(plan, RED))
    shown = "\n".join(str(m.get("content")) for m in bodies[5]["messages"][-3:])
    assert len(bodies) == 6 and ("undefined name 'x'" in shown) is answers_probe
    assert (run.sess.stalled_probe is None) is answers_probe
    if not answers_probe:
        assert run.sess.stalled_probe is ticket and run.sess.stalled_steer is None and "UNKNOWN" in shown

def test_a_partial_reading_keeps_the_ticket_until_the_whole_reading_has_arrived(tmp_path):
    """The harness yielded before the checks finished: a `running` envelope is polled, never settled; the steer comes only with
    the complete, verified reading."""
    run, bodies = spinning(tmp_path)
    ticket, plan = run.sess.stalled_probe, run.sess.gate_plan
    probe_id = run.out["choices"][0]["message"]["tool_calls"][0]["id"]
    spool = base64.b64encode(f"/tmp/.ctx-gate-{plan.transport_id}.spool".encode()).decode()
    poll = answer(run, probe_id, envelope(plan, "path\t" + spool, "running\t12.3"))
    poll_id = poll["tool_calls"][0]["id"]
    assert poll_id != probe_id and run.sess.stalled_probe is ticket and run.sess.stalled_steer is None and len(bodies) == 5
    answer(run, poll_id, gate_page(plan, RED))
    assert run.sess.stalled_probe is None and len(bodies) == 6
    assert "undefined name 'x'" in "\n".join(str(m.get("content")) for m in bodies[5]["messages"][-3:])
