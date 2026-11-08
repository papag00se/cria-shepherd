"""A prior long rollup remains historical evidence rather than being refolded by the new handoff."""
import json

import pytest

from cria import assistruntime, selfcompact
from cria.config import Role
from cria.loop import Loop, LoopContext

from loop_main_helpers import Rlog, loop_main_local_view, synthetic  # noqa: F401
from test_loop_main_compaction import ACCEPT

OLD = "Earlier work: " + "resolver internals were built and verified. " * 700            # ~31K chars: past the refold share


def compact(refold_verdict, refold_text, tmp_path):
    phases = []

    def reasoner(body, rlog):
        phases.append(rlog.phase)
        system = body["messages"][0]["content"]
        answers = {**ACCEPT, "PLAN or RETROSPECTIVE": refold_verdict if "refold" in rlog.phase else "RETROSPECTIVE"}
        if rlog.phase.startswith("self-compact-refold"):
            text = refold_text
        else:
            text = next((v for k, v in answers.items() if k in system), "Then the CLI was wired up.")
        return json.dumps({"choices": [{"message": {"content": text}}]}).encode()
    driver = Loop(LoopContext(planner=None, coder_chat=None, reasoner_chat=reasoner, runs_dir="", workspace_root=str(tmp_path),
                              reasoner_role=Role(name="reasoner", backend="local")))
    driver._compaction_room = lambda rlog, chat_fn, frame_tokens, *, facts_text="": (100, None)
    sess = synthetic("build it")
    sess.compact_state = selfcompact.CompactState(summary=OLD, covered=2, attempted=2)
    view = [{"role": "system", "content": "sys"}, {"role": "user", "content": "build it"},
            {"role": "user", "content": "⟦ctx:rollup⟧ " + OLD}] \
        + [{"role": "assistant", "content": f"turn {i} " + "y" * 1000} for i in range(60)]
    out = driver._self_compact(view, sess, 1, Rlog())
    return out, sess, phases


@pytest.mark.parametrize("verdict,text", [("RETROSPECTIVE", "CONDENSED: resolver built and verified."),
                                          ("PLAN", "CONDENSED: resolver built and verified."),
                                          ("RETROSPECTIVE", "")])
def test_prior_rollup_is_preserved_as_history_not_refolded_without_a_topic_judge(verdict, text, tmp_path):
    out, sess, phases = compact(verdict, text, tmp_path)
    rollup = next(m["content"] for m in out if "⟦ctx:rollup⟧" in str(m.get("content")))
    assert OLD in rollup and "CONDENSED" not in rollup
    assert not phases


def test_a_rung_without_the_compaction_policy_ships_the_history_untouched_and_asks_nobody(tmp_path):
    asked = []
    rung3 = assistruntime.AssistRuntime.select(level=3)
    driver = Loop(LoopContext(planner=None, coder_chat=None, reasoner_chat=lambda b, r: asked.append(b),
                              runs_dir="", reasoner_role=Role(name="reasoner", backend="local"), pilot_runtime=rung3))
    view = [{"role": "system", "content": "sys"}] + [{"role": "assistant", "content": "y" * 1000} for _ in range(60)]
    with assistruntime.bound(rung3):
        assert driver._self_compact(view, synthetic("build it"), 1, Rlog()) is view and not asked
