"""A plan-off session whose history outgrows the coder's room is folded by the briefing writer, and only a briefing that survives its four
validators becomes the coder's context: the root task stays verbatim, the briefing follows it, the newest turns stay whole."""
import json

import pytest

from cria.config import Role
from cria.loop import Loop, LoopContext, LoopStore

from loop_main_helpers import Chat, Rlog, SHELL, acting, loop_main_local_view, synthetic  # noqa: F401
from test_loop_main_compaction import ACCEPT


@pytest.mark.parametrize("fidelity,folded", [("FAITHFUL", True), ("UNFAITHFUL", False)])
def test_the_coder_gets_a_rollup_only_when_the_briefing_is_validated(fidelity, folded):
    phases = []

    def reasoner(body, rlog):
        phases.append(rlog.phase)
        system = body["messages"][0]["content"]
        answers = {**ACCEPT, "UNFAITHFUL or FAITHFUL": fidelity}
        return json.dumps({"choices": [{"message": {"content": next((v for k, v in answers.items() if k in system),
                                                                    "Built the resolver; app.py exists.")}}]}).encode()
    coder = Chat(acting())
    driver = Loop(LoopContext(planner=None, coder_chat=coder, reasoner_chat=reasoner, runs_dir="", self_compact=True,
                              reasoner_role=Role(name="reasoner", backend="local")), LoopStore())
    driver._compaction_room = lambda rlog, chat_fn, frame_tokens, *, facts_text="": (100, None)    # a room 50 turns overflow
    driver._put_session("sid:k", synthetic("build it"))
    history = [{"role": "user", "content": "build it"}] + [{"role": "assistant", "content": f"turn {i} " + "y" * 1000} for i in range(50)]
    out = driver.drive({"messages": history, "tools": [SHELL], "stream": True}, "sid:k", None, Rlog())
    assert out["choices"][0]["message"]["tool_calls"]                                             # the coder still acts either way
    assert phases[0] == "self-compact" and sum(p.startswith("compaction-validate") for p in phases) == 4
    sent = coder.bodies[-1]["messages"]
    rollup = [m for m in sent if "⟦ctx:rollup⟧" in str(m.get("content"))]
    assert bool(rollup) is folded
    if folded:
        assert sent[1]["content"] == "build it" and "Built the resolver; app.py exists." in rollup[0]["content"]
        assert sent.index(rollup[0]) < len(sent) - 3 and sent[-1]["content"].startswith("turn 49 ") and len(sent) < 50
    else:
        assert sum(str(m["content"]).startswith("turn ") for m in sent) > 30                       # nothing was thrown away unvalidated
