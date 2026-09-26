"""C44 follow-up: fixing the lens alone left the dominant failure untouched. Of the 18 real
`harness-compaction-validate-retrospective` rejections in row p28, 13 are a genuinely accurate,
retrospective briefing plus exactly ONE trailing forward sentence the writer prompt already forbids
(line 2 of `selfcompact_summary.txt`: "do not prescribe a repair, file edit, command, implementation,
or next action"). Reading those 13, every one ends the sentence right after "what you were doing
last" — e.g. orders 0173: "...The next step is to fix the import, create the database and apply the
migration, add the new endpoint, and correct the test client." feed-pipeline-java 0050/0086: "The
next step is to complete the CSV-parsing fix..." / "The next concrete step is to add the commons-csv
library...". The OLD closing ask (`compact_closing_ask.txt`) lists "what you were doing last" as its
final category with nothing after it reinforcing "and stop there" — the highest-recency instruction
the writer reads says nothing to override the natural completion "...and next I should X".

Two changes, both at the owner:
1. `compact_closing_ask.txt` (root cause A) now ends by explicitly forbidding a sentence after
   "what you were doing last" — reinforced at the position with the most recency leverage.
2. `server._retry_dropped_plan_briefing` (consequence C safety net, #9: one purposeful extra call)
   fires ONLY when `validate_compaction_briefing` rejects a non-empty writer reply and a validator
   role is configured. It asks the SAME writer, shown its own rejected draft, to redo the SAME
   evidence keeping only retrospective fact (the model re-selects what to keep — cria never edits a
   sentence itself, #2/#5) and re-validates the redo through all three lenses, once, before falling
   back to the deterministic appendices unchanged.
"""

from __future__ import annotations

import json
import unittest

from cria import server as srv
from cria.config import Role


class _Rlog:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))

    def kinds(self):
        return [k for k, _ in self.events]


def _base_messages():
    return [
        {"role": "user", "content": "Make these two changes to the orders service: add a status "
                                    "field, and add integration tests."},
        {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function",
         "function": {"name": "shell", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "ok"},
        {"role": "user", "content": "<<<LOCAL_COMPACT>>> Summarize the thread for continuation."},
    ]


REJECTED_DRAFT = ("What now works: the GET /orders/<id> route returns order details. What is "
                  "broken: the status field has not been added. What I was doing last: I read "
                  "orders/db.py to confirm the schema. The next step is to add the status column "
                  "and write a migration.")
CLEAN_REDO = ("What now works: the GET /orders/<id> route returns order details. What is broken: "
             "the status field has not been added. What I was doing last: I read orders/db.py to "
             "confirm the schema.")


class _Provider:
    """Distinguishes the writer retry call (its system message quotes the rejected draft) from a
    validator lens call (its evidence blocks carry the exact candidate under test) purely by body
    content — the same shape `provider.chat` bodies actually take."""

    def __init__(self, retry_writer_text=CLEAN_REDO):
        self.calls: list[dict] = []
        self.retry_writer_text = retry_writer_text

    def chat(self, body, rlog):
        self.calls.append(body)
        sys_msgs = [m for m in body.get("messages", []) if m.get("role") == "system"]
        sys_text = "\n".join(str(m.get("content", "")) for m in sys_msgs)
        if "REJECTED DRAFT" in sys_text:
            # this is the plan-dropped retry writer call
            return json.dumps({"choices": [{"message": {
                "role": "assistant", "content": self.retry_writer_text}}]}).encode()
        # a validator lens call: judge the CANDIDATE it was actually given
        all_text = json.dumps(body.get("messages", []))
        if "PLAN or RETROSPECTIVE" in all_text:
            verdict = "PLAN" if "The next step is to add the status column" in all_text else "RETROSPECTIVE"
            return json.dumps({"choices": [{"message": {"content": verdict}}]}).encode()
        if "NARROWS or PRESERVES" in all_text:
            return json.dumps({"choices": [{"message": {"content": "PRESERVES"}}]}).encode()
        if "UNFAITHFUL or FAITHFUL" in all_text:
            return json.dumps({"choices": [{"message": {"content": "FAITHFUL"}}]}).encode()
        raise AssertionError(f"unexpected call: {all_text[:200]}")


class _Srv:
    def __init__(self, role):
        class cfg:
            class routing:
                roles = {"compactor": role} if role is not None else {}
        self.cfg = cfg
        class loop:
            _store = type("S", (), {"get": staticmethod(lambda k: None)})()
        self.loop = loop


class PlanDroppedRetryTests(unittest.TestCase):
    def test_a_rejected_plan_bearing_draft_is_retried_and_the_clean_redo_ships(self):
        provider = _Provider(retry_writer_text=CLEAN_REDO)
        role = Role(name="compactor", backend="local")
        server = _Srv(role)
        rlog = _Rlog()
        comp = {"choices": [{"message": {"role": "assistant", "content": REJECTED_DRAFT}}]}

        out = srv._harden_compaction_reply(comp, {"messages": _base_messages()}, provider=provider,
                                           server=server, rlog=rlog)
        final_text = out["choices"][0]["message"]["content"]

        self.assertIn("route.compaction_plan_retry", rlog.kinds())
        self.assertIn("What I was doing last", final_text)
        self.assertNotIn("The next step is to add the status column", final_text)
        # the retried writer call happened, quoting the REJECTED draft
        retry_calls = [c for c in provider.calls
                      if any("REJECTED DRAFT" in str(m.get("content", ""))
                             for m in c.get("messages", []) if m.get("role") == "system")]
        self.assertEqual(len(retry_calls), 1, "the retry fires exactly once")
        self.assertIn(REJECTED_DRAFT, json.dumps(retry_calls[0]["messages"]))

    def test_a_still_plan_bearing_redo_falls_back_to_appendices_only(self):
        """The retry is not a license to keep trying: if the redo STILL contains forward material,
        this falls back to today's safe minimum exactly as an outright rejection always has."""
        provider = _Provider(retry_writer_text=REJECTED_DRAFT)  # writer repeats the same plan sentence
        role = Role(name="compactor", backend="local")
        server = _Srv(role)
        rlog = _Rlog()
        comp = {"choices": [{"message": {"role": "assistant", "content": REJECTED_DRAFT}}]}

        out = srv._harden_compaction_reply(comp, {"messages": _base_messages()}, provider=provider,
                                           server=server, rlog=rlog)
        final_text = out["choices"][0]["message"]["content"]
        self.assertNotIn("The next step is to add the status column", final_text)
        self.assertNotIn("What I was doing last", final_text)  # the whole prose is gone, not patched

    def test_no_validator_role_configured_never_spends_the_retry_call(self):
        """#4: no fallback behind an unavailable reasoner. Without a role, a redo could never be
        validated either, so the retry call would be spent for nothing."""
        provider = _Provider()
        server = _Srv(role=None)
        rlog = _Rlog()
        comp = {"choices": [{"message": {"role": "assistant", "content": REJECTED_DRAFT}}]}

        srv._harden_compaction_reply(comp, {"messages": _base_messages()}, provider=provider,
                                     server=server, rlog=rlog)
        self.assertEqual(provider.calls, [], "no role means no validator and no retry call at all")

    def test_a_cleanly_accepted_first_draft_never_triggers_a_retry(self):
        provider = _Provider()
        role = Role(name="compactor", backend="local")
        server = _Srv(role)
        rlog = _Rlog()
        comp = {"choices": [{"message": {"role": "assistant", "content": CLEAN_REDO}}]}

        out = srv._harden_compaction_reply(comp, {"messages": _base_messages()}, provider=provider,
                                           server=server, rlog=rlog)
        self.assertNotIn("route.compaction_plan_retry", rlog.kinds())
        self.assertIn("What I was doing last", out["choices"][0]["message"]["content"])


if __name__ == "__main__":
    unittest.main()
