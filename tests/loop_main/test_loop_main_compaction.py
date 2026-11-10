"""Compaction wiring through the Loop: what the judge and the rollup are told once the transcript has been folded."""

from cria.loop import _satisfaction_evidence, _work_log

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

