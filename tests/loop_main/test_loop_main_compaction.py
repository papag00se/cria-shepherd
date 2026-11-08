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


def test_compaction_writer_receives_prior_handoff_as_evidence_at_the_wire():
    from cria.upstream import Upstream
    sent = []
    def chat(body, log):
        wire, _, _ = Upstream("http://unused", context_window=100000)._prep(body, False, log)
        sent.append(json.loads(wire))
        return json.dumps({"choices": [{"message": {"content": "Inspect the source."}}]}).encode()
    class Judge:
        def judge_compaction_topic(self, task, response, *, rlog):
            assert task == "Build the feature." and response == "Inspect the source."
            return "ON_TASK"
    ctx = LoopContext(planner=None, coder_chat=None, reasoner_chat=chat, runs_dir="", system1=Judge())
    driver = Loop(replace(ctx, reasoner_role=Role(name="reasoner", backend="local")))
    driver._compaction_room = lambda *a, **kw: (100, None)
    history = [{"role": "system", "content": "sys"}] + [{"role": "assistant", "content": "work " * 300} for _ in range(50)]
    handoff = "⟦ctx:continuation⟧ A check failed earlier; inspect the file."
    result = driver._self_compact(history, synthetic(), 1, Rlog(), pinned_task="Build the feature.", root_evidence=(handoff,))
    contents = [m.get("content", "") for m in sent[0]["messages"]]
    assert any(handoff in c for c in contents)
    assert any("Build the feature." in c and handoff not in c for c in contents)
    assert all("cria_annotation_source" not in m for m in sent[0]["messages"])
    assert result[:len(history)] == history and "Inspect the source." in result[-1]["content"]


def test_rolling_selector_preserves_call_identity_and_source_status():
    from cria import bodykeys
    def reasoner(body, rlog):
        content = json.dumps({"c": [5]}) if rlog.phase == "history-selection" else ""
        return json.dumps({"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}).encode()
    ctx = LoopContext(planner=None, coder_chat=None, reasoner_chat=reasoner, runs_dir="")
    driver = Loop(replace(ctx, reasoner_role=Role(name="reasoner", backend="local")))
    driver._compaction_room = lambda *a, **kw: (100, None)
    history = ([{"role": "user", "content": "Fix tests."}]
        + [{"role": "assistant", "content": "filler " * 300} for _ in range(30)]
        + [{"role": "assistant", "tool_calls": [{"id": "c", "type": "function", "function": {"name": "exec_command", "arguments": '{"cmd":"npm test"}'}}]},
           {"role": "tool", "tool_call_id": "c", "content": "Chunk ID: aa\nWall time: 1 seconds\nProcess exited with code 1\nOutput:\nSyntaxError: broken\n"},
           {"role": "user", "content": "Now run the integration tests."}])
    result = driver._self_compact(history, synthetic(), 1, Rlog(), force=True, pinned_task="Fix tests.")
    selected = [m for m in result if isinstance(m.get(bodykeys.HISTORY_SELECTION), bodykeys.HistorySelectionOrigin)]
    assert len(selected) == 1
    assert "call ID c" in selected[0]["content"] and "Process exited with code 1" in selected[0]["content"]
    assert "SyntaxError: broken" in selected[0]["content"] and "npm test" in selected[0]["content"]
    assert result.index(selected[0]) < result.index(history[-1])
    assert [m for m in result if m not in selected] == history


def test_rolling_preserves_a_measured_red_check_without_an_unjudged_completion_claim():
    """The exact checker line and dated observation survive when no topic judge is available."""
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
    result = loop._self_compact(view, sess, 1, Rlog())
    assert result[:len(view)] == view
    evidence = "\n".join(str(m.get("content")) for m in result)
    assert sess.last_gate_flag in evidence and "had reported failures" in evidence
    assert "A later result from the same check supersedes" in evidence
    assert "all 7 tests now pass" not in evidence and "currently FAIL" not in evidence

