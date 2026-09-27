"""Fixes for independent review 9eaadebe (candidate C44 @ 211169a7).

B1 — the truthful-frame fix only handled a fully BLANK summary; the common shape is prose dropped
but the deterministic appendices (inventory/fetch/checks) survive, so `summary` reads non-blank and
the normal "the handoff below is an ungrounded account" framing still shipped — a false claim over
cria's own re-derived ground truth (#5b). Fixed by a model-invisible marker
(`loop._PROSE_DROPPED_MARKER`) `_harden_compaction_reply` prepends whenever no prose survived, which
`reframe_compaction` consumes and strips before routing to an appendix-aware "retained ground truth"
template instead.

C44a (strategy reset, real-model replay): the lens rewording, the closing-ask change, and the
plan-dropped retry (B3's own fix, and `answers_out`) were REVERTED — Part A of the real-model replay
showed the reworded lens producing a false-accept regression (7 of 13 hand-labelled plan-bearing
drafts wrongly accepted) with no live evidence the retry ever helped. Only the deterministic
truthfulness fixes below this point remain; B3's tests are gone with the code they tested.
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

        # The harness round-trips this exact text back as the NEXT turn's "another language model"
        # preamble. FAILS-BEFORE (behaviourally, not via AttributeError — every assertion below
        # exists on the pre-fix base too): on 211169a7, `summary` reads non-blank (the appendix
        # survived) so the OLD blank-only check chose the NORMAL template, and the very first
        # assertion below fails with a real AssertionError ("ungrounded account" unexpectedly found).
        wrapped = [{"role": "user", "content": PRE + shipped}]
        out2, hit = loop.reframe_compaction(wrapped)
        self.assertTrue(hit)
        final = out2[0]["content"]
        self.assertNotIn("ungrounded account", final)                # #5b: not a handoff, never claimed as one
        self.assertIn("RE-DERIVED AT THE TIME OF THAT COMPACTION", final)                 # presented as cria's own re-derived fact
        self.assertIn("README.md", final)                            # the real appendix content survives
        self.assertNotIn("prose-dropped", final)                     # the internal marker itself never ships

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
        self.assertNotIn("prose-dropped", shipped)   # the marker never appears when real prose shipped

        wrapped = [{"role": "user", "content": PRE + shipped}]
        out2, hit = loop.reframe_compaction(wrapped)
        self.assertIn("ungrounded account", out2[0]["content"])   # the normal, TRUE claim for a real account



if __name__ == "__main__":
    unittest.main()
