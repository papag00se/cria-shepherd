"""The last judge before a run may end must see what the checks measured, not only the claim.

`_confirm_completion` is the approve-path brake: it runs only on a satisfied/done verdict and is
deliberately given claim + reason and NOT the coder's summary, because the summary is confabulation
fuel. Withholding the narrative is right. Withholding cria's own measurements was not.

Walked on L5 handles-cli-node x qwen35: `_offline_fact` — the suite passed, and passed again with
the network taken away — fired seven times and reached 20 coder prompts and **0 of the 24
`satisfaction-confirm` prompts**. The confirmer approved, `loop.gate blocked=false`, the session
ended. The suite it approved has seven tests that all count PASS before a single assertion runs:
the runner calls `fn()` on async bodies and never awaits. Verified in a copy — `npm test` finishes
instantly and identically with and without `unshare -rn`.
"""
import unittest
from unittest import mock

from cria import loop, prompts


class _Plan:
    def __init__(self, fact):
        self.offline_fact = fact


class _Sess:
    def __init__(self, fact):
        self.gate_plan = _Plan(fact)


FACT = "The test command still succeeds with the network switched off."


class TheConfirmerGetsWhatTheChecksMeasured(unittest.TestCase):

    def test_the_offline_fact_is_read_off_the_plan(self):
        self.assertEqual(FACT, loop._cria_measured_facts(_Sess(FACT)))

    def test_silence_when_there_is_no_fact(self):
        self.assertEqual("", loop._cria_measured_facts(_Sess("")))
        self.assertEqual("", loop._cria_measured_facts(object()))
        self.assertEqual("", loop._cria_measured_facts(None))

    def test_a_fact_reaches_the_confirm_prompt(self):
        seen = {}

        def fake_judge(_chat, _role, _system, user, _rlog, **kw):
            seen["user"] = user
            return {"choices": [{"message": {"content": "CONSISTENT"}}]}

        with mock.patch.object(loop, "_judge_completion", fake_judge):
            loop._confirm_completion("do the task", "because", "/w", object(), None,
                                     mock.Mock(), phase="satisfaction-confirm", cria_facts=FACT)
        self.assertIn(FACT, seen.get("user", ""))

    def test_no_fact_adds_nothing_to_the_prompt(self):
        seen = {}

        def fake_judge(_chat, _role, _system, user, _rlog, **kw):
            seen["user"] = user
            return {"choices": [{"message": {"content": "CONSISTENT"}}]}

        with mock.patch.object(loop, "_judge_completion", fake_judge):
            loop._confirm_completion("do the task", "because", "/w", object(), None,
                                     mock.Mock(), phase="satisfaction-confirm")
        self.assertNotIn("ALSO WEIGH THIS", seen.get("user", ""))


if __name__ == "__main__":
    unittest.main()
