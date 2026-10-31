"""Composed internal calls must give the context floor something legal to reduce.

The Java L5 run sent the same 185,158-character two-message compactor body four times.  Both messages
were protected, so the floor reported over_budget without changing it.  Historical evidence now
rides in separate turns between a small first-user introduction and the final active question.
"""
import unittest

from cria import contextfloor, selfcompact


class ComposedInternalEvidenceFitTests(unittest.TestCase):
    def _history(self):
        return [{"role": "user", "content": "task"}] + [
            {"role": "assistant" if i % 2 == 0 else "tool",
             "content": (f"historical block {i} " + chr(65 + i % 20) * 12000),
             **({"tool_call_id": f"t{i}"} if i % 2 else {})}
            for i in range(20)
        ]

    def test_compaction_evidence_is_not_one_irreducible_message(self):
        messages = [
            {"role": "system", "content": "write a briefing"},
            *selfcompact.compaction_request_messages(self._history()),
        ]
        self.assertGreater(len(messages), 10)
        self.assertEqual(messages[-1]["content"],
                         __import__("cria.prompts", fromlist=["load"]).load("compact_closing_ask"))

        fitted, _tools, report = contextfloor.fit(
            messages, None, window=12000, reserve=1000, safety=1.0)
        self.assertFalse(report.over_budget)
        self.assertGreater(report.turns_dropped + report.protected_dropped, 0)
        joined = "\n".join(str(m.get("content") or "") for m in fitted)
        self.assertIn("compacted to fit the context window", joined)
        self.assertIn("Write the briefing now", joined)

    def test_without_pressure_every_evidence_block_is_byte_preserved(self):
        parts = selfcompact.compaction_request_parts(self._history())
        messages = selfcompact.compaction_request_messages(self._history())
        carried = [m["content"] for m in messages[1:-1]]
        self.assertEqual(carried, parts)


if __name__ == "__main__":
    unittest.main()
