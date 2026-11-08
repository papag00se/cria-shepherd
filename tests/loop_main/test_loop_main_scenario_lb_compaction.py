"""A plan-off session retains history and receives only a topic-classified next action."""
import json

import pytest

from cria.config import Role
from cria.loop import Loop, LoopContext, LoopStore

from loop_main_helpers import Chat, Rlog, SHELL, acting, loop_main_local_view, synthetic  # noqa: F401


@pytest.mark.parametrize("verdict,accepted", [("ON_TASK", True), ("OFF_TOPIC", False)])
def test_the_coder_keeps_history_and_only_gets_an_on_topic_action(verdict, accepted):
    calls = []
    def reasoner(body, rlog):
        calls.append(body)
        return json.dumps({"choices": [{"message": {"content": "Inspect app.py."}}]}).encode()
    class Judge:
        def judge_compaction_topic(self, task, response, *, rlog):
            return verdict
    coder = Chat(acting())
    driver = Loop(LoopContext(planner=None, coder_chat=coder, reasoner_chat=reasoner, runs_dir="", self_compact=True,
                              system1=Judge(), reasoner_role=Role(name="reasoner", backend="local")), LoopStore())
    driver._compaction_room = lambda rlog, chat_fn, frame_tokens, *, facts_text="": (100, None)
    driver._put_session("sid:k", synthetic("build it"))
    history = [{"role": "user", "content": "build it"}] + [{"role": "assistant", "content": f"turn {i} " + "y" * 1000} for i in range(50)]
    out = driver.drive({"messages": history, "tools": [SHELL], "stream": True}, "sid:k", None, Rlog())
    assert out["choices"][0]["message"]["tool_calls"]
    assert len(calls) == (1 if accepted else 2)
    sent = coder.bodies[-1]["messages"]
    assert sum(str(m.get("content", "")).startswith("turn ") for m in sent) == 50
    assert any("Inspect app.py." in str(m.get("content")) for m in sent) is accepted
