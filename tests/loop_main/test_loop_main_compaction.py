"""Compaction wiring through the Loop: what the judge and the rollup are told once the transcript has been folded."""
import json
from dataclasses import replace

from cria.config import Role
from cria.loop import Loop, LoopContext, _satisfaction_evidence, _work_log

from loop_main_helpers import Rlog, synthetic, loop_main_local_view  # noqa: F401

ACCEPT = {"PLAN or RETROSPECTIVE": "RETROSPECTIVE", "NARROWS or PRESERVES": "PRESERVES", "CHANGED or NOT CHANGED": "NONE",
          "GREEN or EARLIER or NOT GREEN": "NONE", "UNFAITHFUL or FAITHFUL": "FAITHFUL"}


def test_judge_evidence_after_a_harness_compaction_carries_the_summary_as_the_record_of_the_work():
    """A harness compaction replaces the tool history with prose, so the work log alone is EMPTY and the judge
    hallucinated 'no work done' over a built workspace. The summary rides whole; an uncompacted history is just the log."""
    summary = "⟦ctx:continuation⟧ Earlier you built resolve_handle.py, a test suite, and a README."
    folded = [{"role": "system", "content": "sys"}, {"role": "user", "content": summary}, {"role": "assistant", "content": ""}]
    assert not _work_log(folded).strip()
    assert summary in _satisfaction_evidence(folded) and "RETAINED EARLIER CONTEXT" in _satisfaction_evidence(folded)
    plain = [{"role": "assistant", "tool_calls": [{"id": "a", "function": {"name": "write_file", "arguments": '{"path":"h.py"}'}}]},
             {"role": "tool", "tool_call_id": "a", "content": "wrote h.py"}]
    assert _satisfaction_evidence(plain) == _work_log(plain)


def test_a_rollup_that_launders_a_tests_pass_claim_carries_crias_measured_red_check_beside_it():
    """The summary writer claimed 'all 7 tests now pass'; cria's own last gate was red. The claim is kept (never deleted)
    and the exact checker line plus a dated 'had reported failures' note ride in the same briefing."""
    def reasoner(body, rlog):
        system = body["messages"][0]["content"]
        text = next((v for k, v in ACCEPT.items() if k in system), "all 7 tests now pass")
        return json.dumps({"choices": [{"message": {"content": text}}]}).encode()
    ctx = LoopContext(planner=None, coder_chat=None, reasoner_chat=reasoner, runs_dir="")
    loop = Loop(replace(ctx, reasoner_role=Role(name="reasoner", backend="local")))
    loop._compaction_room = lambda rlog, chat_fn, frame_tokens, *, facts_text="": (100, None)   # a room 50 turns overflow
    sess = synthetic()
    sess.last_gate_red, sess.last_gate_flag = True, "⟦ctx:checks⟧ test_x.py:1: AssertionError: 400 != 200"
    view = [{"role": "system", "content": "sys"}] + [{"role": "assistant", "content": "y" * 1000} for _ in range(50)]
    rollup = next(m["content"] for m in loop._self_compact(view, sess, 1, Rlog()) if "⟦ctx:rollup⟧" in str(m.get("content")))
    assert "all 7 tests now pass" in rollup and sess.last_gate_flag in rollup
    assert "had reported failures" in rollup and "A later result from the same check supersedes" in rollup
    assert "currently FAIL" not in rollup
