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


def test_compaction_writer_and_validator_receive_prior_handoff_as_evidence(monkeypatch):
    from cria import loop as lp
    seen = []
    def summarize(chat, role, system, ask, rlog, **kwargs):
        seen.append(kwargs["evidence_blocks"])
        return "The coder inspected the source."
    validations = []
    def validate(*args, **kwargs):
        validations.append(kwargs)
        return True
    real_summarize = lp.summarize
    monkeypatch.setattr(lp, "summarize", summarize)
    monkeypatch.setattr(lp, "validate_compaction_briefing", validate)
    distillation = []
    def binder(*args):
        def distill(blocks, count, **kw):
            distillation.append((blocks, count, kw))
            return blocks
        return distill
    monkeypatch.setattr(lp.handoffdistill, "binder", binder)
    ctx = LoopContext(planner=None, coder_chat=None, reasoner_chat=lambda *_: b"{}", runs_dir="")
    driver = Loop(replace(ctx, reasoner_role=Role(name="reasoner", backend="local")))
    driver._compaction_room = lambda *a, **kw: (100, None)
    history = [{"role": "system", "content": "sys"}] + [{"role": "assistant", "content": "work " * 300} for _ in range(50)]
    handoff = "⟦ctx:continuation⟧ A check failed earlier; inspect the file."
    result = driver._self_compact(history, synthetic(), 1, Rlog(), pinned_task="Build the feature.",
                                  root_evidence=(handoff,))
    assert seen and validations and distillation
    blocks, count, opts = distillation[0]
    assert opts == {"history_start": 1, "history_scope": "middle", "task": "Build the feature."}
    assert all(block.startswith("MIDDLE BEING REPLACED") for block in blocks[1:1 + count])
    assert any(block.startswith("NEWER RETAINED EVIDENCE") for block in blocks[1 + count:])
    assert any(handoff in block for block in seen[0])
    assert any(handoff in block for block in validations[0]["transcript_blocks"])
    task_blocks = [block for block in seen[0] if block.startswith("⟦ctx:task⟧\nORIGINAL TASK")]
    assert len(task_blocks) == 1 and "Build the feature." in task_blocks[0] and handoff not in task_blocks[0]
    assert validations[0]["task"] == "Build the feature."
    assert any("The coder inspected the source." in str(m.get("content")) for m in result)

    # Exercise the real summary composer and final wire, not only the callback's arguments.
    from cria.upstream import Upstream
    sent = []
    def chat(body, log):
        wire, _, _ = Upstream("http://unused", context_window=100000)._prep(body, False, log)
        sent.append(json.loads(wire))
        return json.dumps({"choices": [{"message": {"content": "Briefing"}}]}).encode()
    assert real_summarize(chat, None, "summary", "question", Rlog(), evidence_blocks=seen[0]) == "Briefing"
    contents = [m.get("content", "") for m in sent[0]["messages"]]
    assert any(handoff in c for c in contents)
    assert all("cria_annotation_source" not in m for m in sent[0]["messages"])
    assert any(c.startswith("⟦ctx:task⟧\nORIGINAL TASK") and handoff not in c for c in contents)


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

