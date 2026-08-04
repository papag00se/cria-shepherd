"""The check must fire on the LIVE path, not only in its own unit tests.

An untriggered guard is indistinguishable from a broken one, and this repo has shipped that bug
before (the `PROBE_EXIT` guard keyed on the NAME of a constant and never fired in production). These
drive Loop._research_check directly with a real PlanSession.
"""
import unittest
from unittest.mock import patch

from cria import loop, research
from cria.plan import Plan, PlanItem


class _Rlog:
    def __init__(self): self.events = []
    def emit(self, kind, **kw): self.events.append((kind, kw))
    phase = ""


def _sess(turns):
    s = loop.PlanSession(plan=Plan(id="p", task="resolve a handle via api.handle.me",
                                   created="now", items=[PlanItem(text="read the api docs"),
                                                         PlanItem(text="write the resolver")]),
                         synthetic=True)
    s.coder_turns = turns
    return s


LEDGER = {"https://api.handle.me/openapi.json": ("200", "/handles/{handle}", "holder(string)")}


class TheCheckFiresOnTheLivePathTests(unittest.TestCase):
    def _loop(self):
        lp = loop.Loop.__new__(loop.Loop)
        lp._ctx = type("C", (), {"reasoner_chat": lambda *a, **k: None, "reasoner_role": None})()
        return lp

    def test_at_the_cadence_a_satisfied_step_is_ADVANCED(self):
        lp, sess, rlog = self._loop(), _sess(research.RESEARCH_CHECK_EVERY), _Rlog()
        with patch.object(loop, "_extract_fetches", return_value=LEDGER), \
             patch.object(research, "step_reading_verdict", return_value=research.DONE), \
             patch.object(loop.Loop, "_advance", return_value={"advanced": True}) as adv:
            out = lp._research_check(sess, "k", {"messages": []}, 0, 2, rlog)
        self.assertEqual(out, {"advanced": True})
        self.assertTrue(adv.called, "a satisfied research step must complete")
        self.assertIn("loop.research_satisfied", [k for k, _ in rlog.events])

    def test_off_cadence_it_does_nothing(self):
        lp, sess, rlog = self._loop(), _sess(research.RESEARCH_CHECK_EVERY - 1), _Rlog()
        with patch.object(research, "step_reading_verdict") as v:
            self.assertIsNone(lp._research_check(sess, "k", {"messages": []}, 0, 2, rlog))
        self.assertFalse(v.called)

    def test_a_step_it_declines_is_left_alone(self):
        lp, sess, rlog = self._loop(), _sess(research.RESEARCH_CHECK_EVERY), _Rlog()
        with patch.object(loop, "_extract_fetches", return_value=LEDGER), \
             patch.object(research, "step_reading_verdict", return_value=research.NOT_RESEARCH), \
             patch.object(loop.Loop, "_advance") as adv:
            self.assertIsNone(lp._research_check(sess, "k", {"messages": []}, 0, 2, rlog))
        self.assertFalse(adv.called)

    def test_it_says_what_it_did_even_when_it_declines(self):
        """Silence is what made this unverifiable in the live run: nothing distinguished 'never ran'
        from 'ran and said no'."""
        lp, sess, rlog = self._loop(), _sess(research.RESEARCH_CHECK_EVERY), _Rlog()
        with patch.object(loop, "_extract_fetches", return_value={}), \
             patch.object(loop.Loop, "_advance"):
            lp._research_check(sess, "k", {"messages": []}, 0, 2, rlog)
        kinds = [k for k, _ in rlog.events]
        self.assertIn("loop.research_check", kinds)


if __name__ == "__main__":
    unittest.main()
