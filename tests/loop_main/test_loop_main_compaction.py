"""Compaction wiring through the Loop: what the judge and the rollup are told once the transcript has been folded."""
import json
from dataclasses import replace

from cria.config import Role
from cria.loop import Loop, LoopContext, _HandoffOrigin, _satisfaction_evidence, _work_log

from loop_main_helpers import Rlog, synthetic, loop_main_local_view  # noqa: F401

ACCEPT = {"PLAN or RETROSPECTIVE": "RETROSPECTIVE", "NARROWS or PRESERVES": "PRESERVES", "CHANGED or NOT CHANGED": "NONE",
          "GREEN or EARLIER or NOT GREEN": "NONE"}


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
    view[1]["content"] = "pytest collected 7 tests"                       # the figure the writer's sentence rests on is in the record
    rollup = next(m["content"] for m in loop._self_compact(view, sess, 1, Rlog()) if "⟦ctx:rollup⟧" in str(m.get("content")))
    assert "all 7 tests now pass" in rollup and sess.last_gate_flag in rollup
    assert "had reported failures" in rollup and "A later result from the same check supersedes" in rollup
    assert "currently FAIL" not in rollup


def test_a_change_claim_is_not_refused_for_want_of_writes_when_a_harness_handoff_carries_them():
    """ornith1.5_9b / Python orders-api, scratch E2E c7 (2026-11-01; 4 of 11 refused briefings): the coder wrote db.py, app.py and test_http.py in
    calls 6-12, Codex compacted, and every later briefing naming those files was refused `UNWRITTEN` because the handoff that carries the writes is a
    root message OUTSIDE the span the write record reads, so a span with no write calls looked like the whole session. A session that holds a harness
    handoff has no provable whole span: the lens abstains. Without a handoff the same briefing over the same view is still refused."""
    def reasoner(body, rlog):
        system = body["messages"][0]["content"]
        text = ("orders/db.py | CHANGED" if "CHANGED or NOT CHANGED" in system
                else next((v for k, v in ACCEPT.items() if k in system), "Edited orders/db.py to add a status column."))
        return json.dumps({"choices": [{"message": {"content": text}}]}).encode()
    ctx = LoopContext(planner=None, coder_chat=None, reasoner_chat=reasoner, runs_dir="")
    loop = Loop(replace(ctx, reasoner_role=Role(name="reasoner", backend="local")))
    loop._compaction_room = lambda rlog, chat_fn, frame_tokens, *, facts_text="": (100, None)
    view = [{"role": "system", "content": "sys"}] + [{"role": "assistant", "content": "y" * 1000} for _ in range(50)]
    rolled = lambda sess: any("⟦ctx:rollup⟧" in str(m.get("content")) for m in loop._self_compact(list(view), sess, 1, Rlog()))
    plain, handed = synthetic(), synthetic()
    handed.handoff_origin = _HandoffOrigin(reply="earlier handoff", ledger="", dropped=False)
    assert not rolled(plain)             # nothing in this span wrote orders/db.py: refused, as before
    assert rolled(handed)                # the handoff outside the span carries the write: no verdict is possible
