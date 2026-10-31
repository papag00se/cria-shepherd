"""Scenario: the coder pastes a whole file into chat instead of calling write_file. Real Loop.drive (plan-off) over a real workspace dir,
fake coder and reasoner models: the reply is promoted to that file's write, the transport admits it, and the next request (carrying the
write's result) settles the delivery."""
import json
from types import SimpleNamespace

from cria import config
from cria.classify import Classification
from cria.loop import LoopStore

from loop_main_helpers import Chat, Rlog, body, completion, plan_off_loop, loop_main_local_view  # noqa: F401

CODING = Classification("task", "coding", "fixture")
WRITE = {"type": "function", "function": {"name": "write_file", "parameters": {
    "type": "object", "required": ["path", "content"], "properties": {"path": {"type": "string"}, "content": {"type": "string"}}}}}
SHELL = {"type": "function", "function": {"name": "shell", "parameters": {"type": "object", "properties": {"command": {"type": "array"}}}}}
LINES = [f"value_{i} = compute({i}) + offset_{i}" for i in range(14)]
TASK = "create app.py computing the values"


def test_a_file_pasted_into_chat_becomes_that_files_write_and_its_result_settles_the_delivery(tmp_path):
    asked = []

    def reasoner(b, r):
        asked.append("\n".join(m["content"] for m in b["messages"]))
        return json.dumps(completion("WHOLE_FILE")).encode()

    pasted = completion("Here is the file `app.py`:\n```python\n" + "\n".join(LINES) + "\n```\nDone.")
    store, rlog, held = LoopStore(), Rlog(), []
    loop = plan_off_loop(Chat(pasted, completion(None, ("shell", {"command": ["true"]}))), store=store, reasoner=reasoner,
                         workspace_root=str(tmp_path), reasoner_role=config.Role(name="reasoner", backend="local"), assists=True)
    out = loop.drive(body(TASK, tools=[WRITE, SHELL]), "sid:p", CODING, rlog, pasted_delivery=held.append)
    call = out["choices"][0]["message"]["tool_calls"][0]
    content = json.loads(call["function"]["arguments"])["content"]
    assert call["function"]["name"] == "write_file" and content == "\n".join(LINES) + "\n"
    assert asked and "app.py" in asked[0] and "massage.text_write_recovered" in rlog.kinds()
    sess = store.get("sid:p")
    assert not sess.pasted_deliveries                                  # nothing is delivered until the transport admits the write
    held[0](out, {call["id"]: SimpleNamespace(path=str(tmp_path / "app.py"), content=content)})
    assert list(sess.pasted_deliveries) == [call["id"]]
    messages = [{"role": "user", "content": TASK}, {"role": "assistant", "tool_calls": [call]},
                {"role": "tool", "tool_call_id": call["id"], "content": "ok"}]
    nxt = loop.drive({**body(TASK, tools=[WRITE, SHELL]), "messages": messages}, "sid:p", CODING, rlog)
    assert nxt["choices"][0]["message"]["tool_calls"] and not sess.pasted_deliveries
    assert sess.pasted_settlements[call["id"]].delivery.prepared.path == "app.py"


def test_a_paste_the_judge_cannot_rule_on_is_redriven_with_its_own_words_and_the_file_named(tmp_path):
    """No answer from the whole-file judge means nothing is promoted: the coder is re-driven once with the reply it wrote and
    the measured fact that no write call was made (the phi4 A1 pasted-class run)."""
    pasted = completion("Here is the file `app.py`:\n```python\n" + "\n".join(LINES) + "\n```\nDone.")
    coder, rlog = Chat(pasted, completion(None, ("shell", {"command": ["true"]}))), Rlog()
    loop = plan_off_loop(coder, store=LoopStore(), reasoner=lambda b, r: json.dumps(completion("")).encode(), workspace_root=str(tmp_path),
                         reasoner_role=config.Role(name="reasoner", backend="local"), assists=True)
    out = loop.drive(body(TASK, tools=[WRITE, SHELL]), "sid:u", CODING, rlog)
    assert len(coder.bodies) == 2 and out["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "shell"
    carried, nudge = coder.bodies[1]["messages"][-2:]
    assert carried == {"role": "assistant", "content": pasted["choices"][0]["message"]["content"]}
    assert nudge["role"] == "user" and "`app.py` as text, but no write tool call was made" in nudge["content"]
    assert "loop.unexecuted_write" in rlog.kinds() and "massage.text_write_recovered" not in rlog.kinds()
