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

    def test_a_satisfied_step_is_REPORTED_and_never_completed(self):
        """It reports; it does not complete. Completing was a second authority that never reads the
        workspace, and on run 1785812224 it marked "write the script", "unit tests" and "the live
        test" verified in under three minutes with two files on disk — 0.0 where plan-off scored
        1.0. The step critic is the only thing here that checks what was actually built (#13)."""
        lp, sess, rlog = self._loop(), _sess(research.RESEARCH_CHECK_EVERY), _Rlog()
        with patch.object(loop, "_extract_fetches", return_value=LEDGER), \
             patch.object(research, "step_reading_verdict", return_value=research.DONE), \
             patch.object(loop.Loop, "_advance") as adv:
            out = lp._research_check(sess, "k", {"messages": []}, 0, 2, rlog)
        self.assertIsNone(out)
        self.assertFalse(adv.called, "the reading check must never complete a step")
        self.assertIn("loop.research_satisfied", [k for k, _ in rlog.events])

    def test_it_runs_once_per_tick_not_once_per_step(self):
        """The driver recurses into the next item without advancing coder_turns, so a modulo test
        alone re-fires for every remaining step inside ONE turn — six steps in three minutes."""
        lp, sess, rlog = self._loop(), _sess(research.RESEARCH_CHECK_EVERY), _Rlog()
        with patch.object(loop, "_extract_fetches", return_value=LEDGER), \
             patch.object(research, "step_reading_verdict", return_value=research.DONE) as v:
            for _ in range(5):
                lp._research_check(sess, "k", {"messages": []}, 0, 2, rlog)
        self.assertEqual(v.call_count, 1)
        sess.coder_turns += research.RESEARCH_CHECK_EVERY      # next tick — it may run again
        with patch.object(loop, "_extract_fetches", return_value=LEDGER), \
             patch.object(research, "step_reading_verdict", return_value=research.DONE) as v2:
            lp._research_check(sess, "k", {"messages": []}, 0, 2, rlog)
        self.assertEqual(v2.call_count, 1)

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


class TheCriticGetsTheReadingFactTests(unittest.TestCase):
    """The check reports; the CRITIC acts. It is the only thing here that reads the workspace, and it
    was refusing research steps forever because nothing told it reading had succeeded — run
    1785804243 held five HTTP 200s that defined nothing and 114 of 195 calls died on step 1."""

    def _verify_prompt(self, sources):
        seen = {}

        def fake_ask(chat_fn, role, system, user, *a, **k):   # _judge_completion's real shape
            seen["user"] = user
            return '{"done": true, "reason": "ok", "proposed_fix": ""}'

        lp = loop.Loop.__new__(loop.Loop)
        lp._ctx = type("C", (), {"reasoner_chat": None, "reasoner_role": None,
                                 "runs_dir": "", "workspace_root": ""})()
        with patch.object(loop, "_judge_completion", side_effect=fake_ask):
            lp._verify("Research the API docs", "did it", "", "", _Rlog(), sources_read=sources)
        return seen.get("user", "")

    def test_the_sources_reach_the_critic(self):
        text = self._verify_prompt(
            [("https://api.handle.me/openapi.json", "/handles/{handle}", "holder(string)")])
        self.assertIn("/handles/{handle}", text)
        self.assertIn("holder(string)", text)
        self.assertIn("ACTUALLY BEEN READ", text)

    def test_nothing_is_said_when_nothing_was_read(self):
        """Silence is the honest state — cria must not imply research happened (#5b)."""
        self.assertNotIn("ACTUALLY BEEN READ", self._verify_prompt([]))

    def test_it_tells_the_critic_this_does_not_finish_a_BUILD_step(self):
        """The bypass scored 0.0 by treating a read as completion of "write the unit tests". The
        critic is told, in the same breath, that this list is background for a build step."""
        text = self._verify_prompt([("u", "/r", "f")])
        self.assertIn("does not make it done", text)
