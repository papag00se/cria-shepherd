"""The focus assist selection reaches the coder: through the real Loop.drive (plan-off) a duplicate-pair collapse is in the body the coder is sent only
when the stage is selected. Only the model boundary is a fake."""
import json

import pytest

from cria import assistruntime as ar
from cria.classify import Classification
from cria.loop import LoopStore

from loop_main_helpers import Chat, Rlog, body, completion, plan_off_loop, loop_main_local_view  # noqa: F401

READ = {"type": "function", "function": {"name": "read_file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}}


def read_turn(cid):
    return [{"role": "assistant", "content": "", "tool_calls": [{"id": cid, "type": "function", "function": {"name": "read_file", "arguments": json.dumps({"path": "spec.md"})}}]},
            {"role": "tool", "tool_call_id": cid, "content": "the spec\nsame every time"}]


@pytest.mark.parametrize("runtime,collapsed", [(dict(level=5), True), (dict(level=0), False), (dict(level=5, disabled=("focus-duplicate-pairs",)), False)])
def test_the_coder_is_sent_the_collapsed_history_only_when_the_duplicate_stage_is_selected(runtime, collapsed):
    """Real Loop.drive: three identical reads of one spec reach the coder as the last one (plus the counted note) or as all three, per the selection."""
    coder, log = Chat(completion(None, ("read_file", {"path": "other.md"}))), Rlog()
    loop = plan_off_loop(coder, store=LoopStore(), pilot_runtime=ar.AssistRuntime.select(**runtime), focus_trim=True)
    request = body("read the spec", tools=[READ])
    request["messages"] += read_turn("a") + read_turn("b") + read_turn("c")
    loop.drive(request, "sid:f", Classification("task", "coding", "fixture"), log)
    sent = coder.bodies[0]["messages"]
    called = [tc["id"] for m in sent for tc in m.get("tool_calls") or []]
    assert called == (["c"] if collapsed else ["a", "b", "c"])
    assert ("context.focus_trim" in log.kinds()) is collapsed
    assert any("3 times" in str(m["content"]) for m in sent) is collapsed
