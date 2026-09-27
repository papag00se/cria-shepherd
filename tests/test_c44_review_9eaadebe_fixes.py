"""Fixes for independent review 9eaadebe (candidate C44 @ 211169a7).

B1 — the truthful-frame fix only handled a fully BLANK summary; the common shape is prose dropped
but the deterministic appendices (inventory/fetch/checks) survive, so `summary` reads non-blank and
the normal "the handoff below is an ungrounded account" framing still shipped — a false claim over
cria's own re-derived ground truth (#5b). Fixed by a model-invisible marker
(`loop._PROSE_DROPPED_MARKER`) `_harden_compaction_reply` prepends whenever no prose survived, which
`reframe_compaction` consumes and strips before routing to an appendix-aware "retained ground truth"
template instead.

B3 — the retry fired on ANY validator rejection (fidelity UNFAITHFUL, scope NARROWS, an unreadable
answer) but always told the writer "your draft contained a next step" and to "keep every other
fact" — false for a fidelity rejection (#5b), and for an invented-fact draft, an instruction to keep
the invention. Fixed by threading `answers_out` through `validate_compaction_briefing` so the caller
can gate the retry on `answers["retrospective"] == "PLAN"` specifically — the only rejection reason
the retry's own claim to the writer is actually true for.
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from cria import loop
from cria import server as srv
from cria.config import Role


class _Rlog:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))

    def kinds(self):
        return [k for k, _ in self.events]


PRE = ("Another language model started to solve this problem and produced a summary of its thinking "
      "process. You also have access to the state of the tools that were used by that language "
      "model. Use this to build on the work that has already been done and avoid duplicating work. "
      "Here is the summary produced by the other language model, use the information in this "
      "summary to assist with your own analysis:\n")


def _base_messages():
    return [
        {"role": "user", "content": "Add EU zone detection."},
        {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function",
         "function": {"name": "shell", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "ok"},
        {"role": "user", "content": "<<<LOCAL_COMPACT>>> summarize"},
    ]


class _NoRoleProvider:
    """No [roles] configured -> `validate_compaction_briefing` returns False immediately
    ("judge unavailable") without ever calling this. Simulates a real drop where the writer DID
    produce a draft and the deterministic appendices are non-empty."""

    def chat(self, body, rlog):
        return json.dumps({"choices": [{"message": {
            "content": "Chose the foo_gem for EU detection. Next step: add it to the Gemfile."}}]}).encode()


class _NoRoleSrv:
    class cfg:
        class routing:
            roles = {}
    class loop:
        _store = type("S", (), {"get": staticmethod(lambda k: None)})()


class B1AppendixOnlyTruthfulFrameTests(unittest.TestCase):
    """FAILS-BEFORE (confirmed against 211169a7): `summary` is non-blank (the appendix survived),
    so the pre-fix `tmpl = "compaction_reframe_dropped" if not summary.strip() else template` chose
    the NORMAL template, which claims "the handoff below is an ungrounded account" over content that
    is not a handoff at all — cria's own re-derived workspace listing."""

    def test_prose_dropped_but_appendix_present_never_claims_an_account(self):
        comp = {"choices": [{"message": {"role": "assistant", "content":
                             "Chose the foo_gem for EU detection. Next step: add it."}}]}
        with mock.patch.object(
                srv, "_workspace_listing",
                return_value=("FILES ALREADY IN THIS WORKSPACE (on disk right now — do not "
                             "re-create them):\n  README.md\n  orders/")):
            out = srv._harden_compaction_reply(comp, {"messages": _base_messages()},
                                               _NoRoleProvider(), _NoRoleSrv, _Rlog())
        shipped = out["choices"][0]["message"]["content"]
        self.assertTrue(shipped.strip(), "the appendix must still ship — never destroy re-derivable facts")
        self.assertIn(loop._PROSE_DROPPED_MARKER, shipped)   # the marker travels WITH the appendix

        # The harness round-trips this exact text back as the NEXT turn's "another language model"
        # preamble — reframe_compaction must consume the marker, not merely tolerate its presence.
        wrapped = [{"role": "user", "content": PRE + shipped}]
        out2, hit = loop.reframe_compaction(wrapped)
        self.assertTrue(hit)
        final = out2[0]["content"]
        self.assertNotIn(loop._PROSE_DROPPED_MARKER, final)          # stripped before the model reads it
        self.assertNotIn("ungrounded account", final)                # #5b: not a handoff, never claimed as one
        self.assertIn("RETAINED GROUND TRUTH", final)                 # presented as cria's own re-derived fact
        self.assertIn("README.md", final)                            # the real appendix content survives

    def test_a_genuine_accepted_handoff_keeps_the_normal_ungrounded_account_frame(self):
        """Regression guard: the marker must NEVER appear when real prose shipped — only an actual
        drop earns the appendix-aware frame."""
        role = Role(name="compactor", backend="local")

        class _Srv:
            class cfg:
                class routing:
                    roles = {"compactor": role}
            class loop:
                _store = type("S", (), {"get": staticmethod(lambda k: None)})()

        class _AcceptingProvider:
            def chat(self, body, rlog):
                msgs = body.get("messages", [])
                all_text = json.dumps(msgs)
                if "PLAN or RETROSPECTIVE" in all_text:
                    return json.dumps({"choices": [{"message": {"content": "RETROSPECTIVE"}}]}).encode()
                if "NARROWS or PRESERVES" in all_text:
                    return json.dumps({"choices": [{"message": {"content": "PRESERVES"}}]}).encode()
                if "UNFAITHFUL or FAITHFUL" in all_text:
                    return json.dumps({"choices": [{"message": {"content": "FAITHFUL"}}]}).encode()
                return json.dumps({"choices": [{"message": {
                    "content": "What now works: X. What was done last: Y."}}]}).encode()

        comp = {"choices": [{"message": {"role": "assistant",
                            "content": "What now works: X. What was done last: Y."}}]}
        out = srv._harden_compaction_reply(comp, {"messages": _base_messages()},
                                           _AcceptingProvider(), _Srv, _Rlog())
        shipped = out["choices"][0]["message"]["content"]
        self.assertNotIn(loop._PROSE_DROPPED_MARKER, shipped)

        wrapped = [{"role": "user", "content": PRE + shipped}]
        out2, hit = loop.reframe_compaction(wrapped)
        self.assertIn("ungrounded account", out2[0]["content"])   # the normal, TRUE claim for a real account


class _FidelityRejectingProvider:
    """The retrospective lens accepts (the draft names no next step); the fidelity lens rejects it
    (an invented claim contradicted by the evidence) — the shape a plan-dropped retry cannot fix and
    must not claim to be fixing."""

    def __init__(self):
        self.calls: list[dict] = []

    def chat(self, body, rlog):
        self.calls.append(body)
        all_text = json.dumps(body.get("messages", []))
        sys_text = "\n".join(str(m.get("content", "")) for m in body.get("messages", [])
                             if m.get("role") == "system")
        if "REJECTED DRAFT" in sys_text:
            raise AssertionError("the plan-dropped retry must never fire on a fidelity rejection")
        if "PLAN or RETROSPECTIVE" in all_text:
            return json.dumps({"choices": [{"message": {"content": "RETROSPECTIVE"}}]}).encode()
        if "NARROWS or PRESERVES" in all_text:
            return json.dumps({"choices": [{"message": {"content": "PRESERVES"}}]}).encode()
        if "UNFAITHFUL or FAITHFUL" in all_text:
            return json.dumps({"choices": [{"message": {"content": "UNFAITHFUL"}}]}).encode()
        return json.dumps({"choices": [{"message": {
            "content": "Chose the foo_gem for EU detection. I was reading lib/x.rb last."}}]}).encode()


class B3RetryOnlyOnRetrospectiveRejectionTests(unittest.TestCase):
    """FAILS-BEFORE (confirmed against 211169a7): the retry fired unconditionally on ANY rejection,
    so `_FidelityRejectingProvider.chat` above raises `AssertionError` on the base — the retry DID
    reach the writer with the (false) claim "it contained a next step" for a fidelity rejection."""

    def test_a_fidelity_rejection_never_triggers_the_plan_dropped_retry(self):
        role = Role(name="compactor", backend="local")

        class _Srv:
            class cfg:
                class routing:
                    roles = {"compactor": role}
            class loop:
                _store = type("S", (), {"get": staticmethod(lambda k: None)})()

        provider = _FidelityRejectingProvider()
        rlog = _Rlog()
        comp = {"choices": [{"message": {"role": "assistant",
                            "content": "Chose the foo_gem for EU detection. I was reading lib/x.rb last."}}]}

        out = srv._harden_compaction_reply(comp, {"messages": _base_messages()}, provider,
                                           _Srv, rlog)
        shipped = out["choices"][0]["message"]["content"]
        self.assertNotIn("route.compaction_plan_retry", rlog.kinds())
        self.assertNotIn("Chose the foo_gem", shipped)   # the fidelity-rejected draft did not ship
        answers = next((f["answers"] for k, f in rlog.events if k == "context.compaction_validation"), {})
        self.assertEqual(answers.get("fidelity"), "UNFAITHFUL")

    def test_validate_compaction_briefing_exposes_which_lens_rejected(self):
        def chat(body, rlog):
            all_text = json.dumps(body.get("messages", []))
            if "PLAN or RETROSPECTIVE" in all_text:
                return json.dumps({"choices": [{"message": {"content": "RETROSPECTIVE"}}]}).encode()
            if "NARROWS or PRESERVES" in all_text:
                return json.dumps({"choices": [{"message": {"content": "PRESERVES"}}]}).encode()
            return json.dumps({"choices": [{"message": {"content": "UNFAITHFUL"}}]}).encode()

        role = Role(name="reasoner", backend="local")
        answers: dict = {}
        accepted = loop.validate_compaction_briefing(
            chat, role, "a candidate briefing", files="", checks="", transcript_blocks=[],
            rlog=_Rlog(), answers_out=answers)
        self.assertFalse(accepted)
        self.assertEqual(answers["retrospective"], "RETROSPECTIVE")
        self.assertEqual(answers["fidelity"], "UNFAITHFUL")


if __name__ == "__main__":
    unittest.main()
