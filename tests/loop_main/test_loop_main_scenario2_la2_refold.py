"""Scenario2 (LA2): a long plan-off session whose accumulated rollup has itself outgrown its share of the window is folded ONCE more -
and only a refold that survives the validators replaces it; a rejected or empty one leaves the longer, truthful text standing.
Real Loop._self_compact over a real CompactState; only the reasoner is scripted (by the phase it is called under)."""
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
        answers = {**ACCEPT, "UNFAITHFUL or FAITHFUL": refold_verdict if "refold" in rlog.phase else "FAITHFUL"}
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
    view = [{"role": "system", "content": "sys"}, {"role": "user", "content": "build it"}] \
        + [{"role": "assistant", "content": f"turn {i} " + "y" * 1000} for i in range(60)]
    out = driver._self_compact(view, sess, 1, Rlog())
    return out, sess, phases


@pytest.mark.parametrize("verdict,text,refolded", [("FAITHFUL", "CONDENSED: resolver built and verified.", True),
                                                   ("UNFAITHFUL", "CONDENSED: resolver built and verified.", False),
                                                   ("FAITHFUL", "", False)])
def test_the_accumulated_rollup_is_refolded_only_when_the_refold_is_written_and_validated(verdict, text, refolded, tmp_path):
    out, sess, phases = compact(verdict, text, tmp_path)
    rollup = next(m["content"] for m in out if "⟦ctx:rollup⟧" in str(m.get("content")))
    assert "self-compact-refold" in phases
    if refolded:      # the refold condenses the old text AND the new increment into one entry
        assert sess.compact_state.summary == text and text in rollup and "Earlier work" not in rollup
    else:             # too long beats gone: the old text stands, the new increment appended
        assert sess.compact_state.summary == OLD + "\n\nThen the CLI was wired up."
        assert "Earlier work: resolver internals" in rollup and "CONDENSED" not in rollup


def test_a_rung_without_the_compaction_policy_ships_the_history_untouched_and_asks_nobody(tmp_path):
    asked = []
    driver = Loop(LoopContext(planner=None, coder_chat=None, reasoner_chat=lambda b, r: asked.append(b),
                              runs_dir="", reasoner_role=Role(name="reasoner", backend="local"),
                              pilot_runtime=assistruntime.AssistRuntime.select(level=3)))
    view = [{"role": "system", "content": "sys"}] + [{"role": "assistant", "content": "y" * 1000} for _ in range(60)]
    assert driver._self_compact(view, synthetic("build it"), 1, Rlog()) is view and not asked
