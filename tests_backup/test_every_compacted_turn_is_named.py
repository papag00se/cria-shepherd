"""A compacted turn is named, not counted away.

`_drop_oldest` replaces the turns it drops with a note. The note's budget was spent
first-come-first-served, newest-dropped first — and `digest_reduce` returns code and prose
UNCHANGED by design, after the word-stripper was caught inverting a negation. So one dropped
`write_file` payload asked for its share and handed back its whole self, took the entire note
budget, and every older turn was disclosed as:

    (+64 further compacted turn(s) whose content could not be summarized here.)

Measured across the capture corpus: **6,725 turns** across 965 prompts left with no digest at all,
219 prompts dropping ten or more. The coder was told a number and nothing else, and the starvation
landed on the OLDEST turns, which is where the task history lives.

Every turn now gets a line before any turn gets a paragraph: the reserve for the remaining stubs is
measured exactly (a guessed reserve refused a real digest by six tokens) and a digest may spend only
what is left after it.
"""
import unittest

from cria import contextfloor as cf
from cria.contextfloor import est_tokens


def _session(huge_lines=400, steps=19):
    msgs = [{"role": "system", "content": "sys"},
            {"role": "assistant", "content": "here is the whole file\n" + ("x = 1\n" * huge_lines)}]
    msgs += [{"role": "assistant", "content": f"step {i}: I will now check the {i}th thing carefully"}
             for i in range(steps)]
    msgs.append({"role": "user", "content": "y" * 12000})
    return msgs


class EveryCompactedTurnIsNamed(unittest.TestCase):

    def _note(self, msgs, budget=2600):
        out, dropped = cf._drop_oldest(msgs, msg_budget=budget)
        self.assertGreater(dropped, 0, "the floor must actually have dropped something")
        return next(m for m in out if cf._COMPACTED_MARK in str(m.get("content") or ""))["content"]

    def test_one_huge_turn_does_not_starve_the_others(self):
        note = self._note(_session())
        named = [i for i in range(19) if f"step {i}:" in note]
        self.assertEqual(19, len(named),
                         "every dropped turn is named; the huge one may not spend the whole note")

    def test_nothing_is_disclosed_as_merely_counted(self):
        self.assertNotIn("could not be summarized", self._note(_session()))

    def test_the_note_still_costs_less_than_what_it_replaces(self):
        msgs = _session()
        dropped_text = "".join(cf._msg_text(m) for m in msgs[1:-1])
        self.assertLess(est_tokens(self._note(msgs)), est_tokens(dropped_text),
                        "naming every turn must not cost more than carrying them")

    def test_a_turn_that_fits_is_still_summarized_not_stubbed(self):
        """The reserve must not refuse a digest there is room for."""
        blob = ("<html><body>" + "".join(
            f"<div class='row r{i}'><p>Failure {i}: the resolver returned None</p></div>"
            for i in range(60))
            + "</body></html>")
        msgs = [{"role": "system", "content": "sys"},
                {"role": "assistant", "content": "fetch the page",
                 "tool_calls": [{"id": "c1", "function": {"name": "web_fetch", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "c1", "content": blob},
                {"role": "user", "content": "x" * 12000}]
        self.assertIn("resolver returned None", self._note(msgs, budget=2400))


if __name__ == "__main__":
    unittest.main()
