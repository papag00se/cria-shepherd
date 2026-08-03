"""The steer author's own prompt forbids this, in these words: "NEVER attribute the failure to an
outside cause — authentication, rate limits, permissions, a broken service — that the working access
disproves; a false cause becomes the coder's belief and every later step builds on it."

That is a request, not an enforcement. Walked on ada-handles_mellum2_codex_poff_1785714194 call 0026,
cria's own voice, delivered verbatim to the coder at 0027 — and the same false claim ended two
earlier runs on this task.
"""
import unittest

from cria import loop


class _Rlog:
    def __init__(self): self.events = []
    def emit(self, kind, **kw): self.events.append((kind, kw))


class _Sess:
    def __init__(self, pages): self.fetched_pages = pages


ANSWERED = {"https://api.handle.me/handles/goose": ("HTTP 200 OK", "/handles/{handle}", "", "")}
ALL_DEAD = {"https://api.handle.me/handles/goose": ("HTTP 503 Service Unavailable", "", "", "")}

# Verbatim from run 1785714194 call 0026.
REAL_BLAME = ("This is stuck. The Ada Handles API does not support /holders/{address} returning "
              "per-holder total_handles — it consistently returns 404. The test assertions require "
              "total_handles > 0, which is impossible given the API. Fix: handle the 404 and return "
              "0 for total_handles.")

OBSERVATION = ("The last request to /holders/<the payment address> returned 404. Compare the value "
               "you put in that path against what the route's parameter description says it wants.")


class BlameTests(unittest.TestCase):
    def _check(self, directive, pages, answer):
        return loop._blames_a_service_that_answered(
            directive, _Sess(pages), [], _Rlog(), lambda system: answer)

    def test_the_real_captured_steer_is_caught(self):
        self.assertTrue(self._check(REAL_BLAME, ANSWERED, "BLAMES"))

    def test_an_observation_about_one_request_is_left_alone(self):
        self.assertFalse(self._check(OBSERVATION, ANSWERED, "GROUNDED"))

    def test_it_abstains_when_NOTHING_answered(self):
        # cria holds no disproof, so it is not cria's call to make. No question is even asked.
        asked = []
        self.assertFalse(loop._blames_a_service_that_answered(
            REAL_BLAME, _Sess(ALL_DEAD), [], _Rlog(),
            lambda system: asked.append(system) or "BLAMES"))
        self.assertEqual(asked, [])

    def test_it_abstains_with_no_reasoner(self):
        self.assertFalse(loop._blames_a_service_that_answered(
            REAL_BLAME, _Sess(ANSWERED), [], _Rlog(), None))

    def test_plain_prose_never_costs_a_call(self):
        asked = []
        self.assertFalse(loop._blames_a_service_that_answered(
            "Read the file before you rewrite it.", _Sess(ANSWERED), [], _Rlog(),
            lambda system: asked.append(system) or "BLAMES"))
        self.assertEqual(asked, [], "the trigger is what makes the question affordable")

    def test_an_unreadable_verdict_keeps_the_steer(self):
        # Dropping a steer is destructive; only a clear BLAMES does it.
        for ans in ("", "maybe", None, "I think it depends"):
            with self.subTest(ans=ans):
                self.assertFalse(self._check(REAL_BLAME, ANSWERED, ans))

    def test_the_drop_is_traced_never_silent(self):
        rlog = _Rlog()
        loop._blames_a_service_that_answered(REAL_BLAME, _Sess(ANSWERED), [], rlog,
                                             lambda system: "BLAMES")
        self.assertIn("loop.steer_blames_service", [k for k, _ in rlog.events])


class WiringTests(unittest.TestCase):
    def test_the_gate_runs_it(self):
        import inspect
        self.assertIn("_blames_a_service_that_answered",
                      inspect.getsource(loop._grounded_steer_or_none))

    def test_both_author_paths_supply_the_session_and_history(self):
        import inspect
        src = inspect.getsource(loop.author_steer)
        self.assertEqual(src.count("sess=gs, messages=body.get"), 2)


if __name__ == "__main__":
    unittest.main()
