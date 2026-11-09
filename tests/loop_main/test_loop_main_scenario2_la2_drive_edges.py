"""Scenario2 (LA2): drive() edges around the transport handoff - a
delivery that lands after the conversation's session was dropped, and a model-server refusal in a conversation that has no stable key.
Real Loop.drive (plan-off) over a real workspace; only the models are fakes."""
import json
from types import SimpleNamespace

import pytest

from cria import config
from cria.classify import Classification
from cria.loop import LoopStore
from cria.upstream import UpstreamProtocolError

from loop_main_helpers import Chat, Rlog, acting, body, completion, drive_after_initial_inventory, plan_off_loop, loop_main_local_view  # noqa: F401
from test_loop_main_scenario_pasted_file import CODING, LINES, SHELL, TASK, WRITE


def pasted_drive(tmp_path, key):
    reasoner = lambda b, r: json.dumps(completion("WHOLE_FILE")).encode()          # noqa: E731
    pasted = completion("Here is the file `app.py`:\n```python\n" + "\n".join(LINES) + "\n```\nDone.")
    store, held = LoopStore(), []
    loop = plan_off_loop(Chat(pasted, acting()), store=store, reasoner=reasoner, workspace_root=str(tmp_path),
                         reasoner_role=config.Role(name="reasoner", backend="local"), assists=True)
    out = drive_after_initial_inventory(loop, body(TASK, tools=[WRITE, SHELL]), key, CODING, Rlog(), pasted_delivery=held.append)
    call = out["choices"][0]["message"]["tool_calls"][0]
    admitted = {call["id"]: SimpleNamespace(path=str(tmp_path / "app.py"), content=json.loads(call["function"]["arguments"])["content"])}
    return store, store.get(key), held[0], out, call, admitted


def test_a_delivery_after_the_session_was_dropped_releases_its_transient_reply_state_and_keeps_the_store_empty(tmp_path):
    store, sess, deliver, out, call, admitted = pasted_drive(tmp_path, "sid:gone")
    sess.living_effects, sess.living_raw_reply = object(), out
    store.drop("sid:gone")
    deliver(out, admitted)
    assert sess.living_effects is None and sess.living_raw_reply is None and sess.living_pending is None
    assert store.get("sid:gone") is None
    store2, live, deliver2, out2, call2, admitted2 = pasted_drive(tmp_path, "sid:kept")
    live.living_effects = marker = object()
    deliver2(out2, admitted2)
    assert live.living_effects is marker                       # a live owner keeps what the retention step did not consume


def test_a_protocol_refusal_in_a_conversation_without_a_stable_key_is_not_retried_and_leaves_no_session():
    refusal = UpstreamProtocolError("invalid literal tool output", {"type": "protocol", "message": "bad"})

    class Refusing(Chat):
        def __call__(self, b, rlog):
            self.bodies.append(b)
            raise refusal
    coder, rlog = Refusing(acting()), Rlog()
    store = LoopStore()
    with pytest.raises(UpstreamProtocolError) as raised:
        plan_off_loop(coder, store=store).drive(body(), "task:abc", CODING, rlog)
    assert raised.value is refusal and len(coder.bodies) == 1 and "loop.protocol_refused" not in rlog.kinds()
    assert store.get("task:abc") is None
