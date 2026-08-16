# (was condition="flail" — the quiet-flail steer is removed; see tests/test_flail.py. The
# mechanism under test here is author_steer itself, so any live condition exercises it.)
"""cria acted on a one-word ANSWER while that same completion's REASONING said the opposite.

Measured on the ladder walks and in ~/.cria/calls. Two phases carry the defect and are covered here:

  * the STEP CRITIC — 493 captured calls, 175 unreadable, 7 of those carry a clear NOT-done in the
    thinking (four of them `finish_reason=tool_calls` with empty content: the judge spent its
    inspection rounds looking and never answered).
  * the STEER AUTHOR — verbatim, run ada-handles_fabliq_codex_pon_1785721353 call 0213: "I believe
    the coder is stuck and needs help ... The appropriate response would be to use the directive
    `ON_TRACK`", emitted as the bare word `ON_TRACK`, which asserts the coder needs no help. Ten
    calls in that one run; call 0255's thinking ends with a finished directive.

ONE DIRECTION ONLY in both: a NOT-done, or a directive where none was given. Never an approval, and
never a veto of a rescue.
"""
import json
import os
import tempfile
import types
import unittest

from cria import loop, prompts
from cria.config import Role


class _Rlog:
    phase = ""

    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def kinds(self):
        return [k for k, _ in self.events]


def _comp(content="", reasoning=None, finish="stop", tool_calls=None):
    msg = {"role": "assistant", "content": content}
    if reasoning is not None:
        msg["reasoning_content"] = reasoning
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {"choices": [{"finish_reason": finish, "message": msg}]}


def _scripted(replies):
    seen = []

    def chat(body, rlog):
        seen.append(body)
        return json.dumps(replies[min(len(seen) - 1, len(replies) - 1)]).encode()

    chat.bodies = seen
    return chat


# ---------------------------------------------------------------------------------------------
# THE STEP CRITIC
# ---------------------------------------------------------------------------------------------

# Verbatim from run 20260802T020433/0172-critic — finish_reason=tool_calls, content "". The judge
# inspected for five rounds, answered nothing, and cria handed the coder its generic keep-working
# line instead of this.
# What the RECOVERY reasoner answers when handed CRITIC_REAL. The reading is a reasoner's job now
# (operator, 2026-08-08) — a regex of ruling phrasings was the most fragile matcher in cria, because
# it read a model's unconstrained private prose and turned the answer into a verdict. Scripting its
# reply here keeps these tests on cria's CONTRACT: what it does with the answer it gets.
CRITIC_RECOVERY_ANSWER = (
    'NOT_DONE: the step "Write a live test that runs resolve_handle.py with handle goose" '
    'is not done — there is no test for "goose" in the file.')

CRITIC_REAL = (
    'So the step "Write a live test that runs resolve_handle.py with handle goose" is not done — '
    "there is no test for \"goose\" in the file. The coder has not written this test. The coder's "
    "summary is about fixing existing tests, not adding a new one. So: done = false."
)


def _loop_with(reasoner_chat):
    lp = loop.Loop.__new__(loop.Loop)
    lp._ctx = types.SimpleNamespace(reasoner_chat=reasoner_chat,
                                    reasoner_role=Role(name="reasoner", backend="local"))
    return lp


class StepCriticReadsItsOwnThinkingTests(unittest.TestCase):
    def test_a_verdict_only_the_thinking_holds_is_recovered(self):
        lp = _loop_with(_scripted([_comp("", CRITIC_REAL, finish="tool_calls"), _comp(CRITIC_RECOVERY_ANSWER)]))
        obj, _raw = lp._verdict("sys", "user", _Rlog(), reasoning_off=False)
        self.assertIsNotNone(obj, "the critic's own diagnosis was discarded")
        self.assertIs(obj["done"], False)

    def test_the_recovered_reason_carries_the_DIAGNOSIS_the_coder_needs(self):
        lp = _loop_with(_scripted([_comp("", CRITIC_REAL, finish="tool_calls"), _comp(CRITIC_RECOVERY_ANSWER)]))
        obj, _raw = lp._verdict("sys", "user", _Rlog(), reasoning_off=False)
        self.assertIn("goose", obj["reason"])
        # and it survives into the exact string the coder is re-nudged with
        self.assertIn("goose", loop._verdict_nudge(obj, False))

    def test_it_is_traced_under_the_critic_phase_never_silent(self):
        rlog = _Rlog()
        lp = _loop_with(_scripted([_comp("", CRITIC_REAL, finish="tool_calls"), _comp(CRITIC_RECOVERY_ANSWER)]))
        lp._verdict("sys", "user", rlog, reasoning_off=False)
        self.assertIn("loop.verdict_from_reasoning", rlog.kinds())
        self.assertTrue(any(kw.get("phase", "").startswith("critic")
                            for k, kw in rlog.events if k == "loop.verdict_from_reasoning"))

    def test_a_readable_verdict_is_never_second_guessed_by_the_thinking(self):
        # ONE DIRECTION. Of 264 captured critic approvals, 7 carry a negative somewhere in the
        # thinking; all 7 read as the judge ARGUING ITSELF TO the approval ("maybe the step is not
        # fully satisfied because ... but they used web_fetch with the exact URL, that's sufficient").
        approved = json.dumps({"done": True, "reason": "the CLI exists and runs", "proposed_fix": ""})
        lp = _loop_with(_scripted([_comp(approved, "But wait, the README is not done overall.")]))
        obj, _raw = lp._verdict("sys", "user", _Rlog(), reasoning_off=False)
        self.assertIs(obj["done"], True, "a verdict the judge actually reached must stand")

    def test_no_approval_is_ever_recovered_from_thinking(self):
        for text in ("The step is done — the file exists and the tests pass.",
                     "Everything the step asked for is present. Nothing is missing."):
            with self.subTest(text=text[:40]):
                lp = _loop_with(_scripted([_comp("", text, finish="tool_calls")]))
                obj, _raw = lp._verdict("sys", "user", _Rlog(), reasoning_off=False)
                self.assertIsNone(obj, "a recovered approval would be failing OPEN on completion")

    def test_a_cut_reply_recovers_nothing(self):
        lp = _loop_with(_scripted([_comp("", CRITIC_REAL, finish="length")]))
        obj, _raw = lp._verdict("sys", "user", _Rlog(), reasoning_off=False)
        self.assertIsNone(obj, "a cut trace is not a conclusion")


# ---------------------------------------------------------------------------------------------
# THE STEER AUTHOR
# ---------------------------------------------------------------------------------------------

# Verbatim reasoning_content, run ada-handles_fabliq_codex_pon_1785721353 call 0213. Emitted
# content: the single word ON_TRACK.
STEER_REAL = (
    "We need to decide if the coder is stuck or making progress. The coder has been trying to fix "
    "syntax errors and test failures but hasn't made meaningful progress.\n\n"
    "The coder's attempts have not converged on a working solution - they're stuck in a loop of "
    "trying different approaches without success.\n\n"
    "Given this analysis, I believe the coder is stuck and needs help from the user. The appropriate "
    'response would be to use the directive "ON_TRACK" to indicate that the coder is not making '
    "progress and requires assistance."
)

RECOVERED = ("You keep re-running the same edit against handle_resolver.py while the tests fail the "
             "same way. Read handle_resolver.py now and run the failing test to see the real error.")


class SteerAuthorReadsItsOwnThinkingTests(unittest.TestCase):
    """The author declined with ON_TRACK; its thinking says stuck. Only silence can become a steer."""

    def _author(self, replies, *, workspace=True):
        d = tempfile.mkdtemp() if workspace else ""
        if d:
            with open(os.path.join(d, "handle_resolver.py"), "w") as f:
                # 6 real lines: the authored-directive test cites "line 4", and the false-citation
                # guard's bare-line arm now (correctly) withholds a line number past every listed
                # file's real length — the fixture must be tall enough for the citation to be true.
                f.write("x = 1\ny = 2\nz = 3\na = 4\nb = 5\nc = 6\n")
        chat = _scripted(replies)
        gs = types.SimpleNamespace(gate_stall=3, recent_writes=["handle_resolver.py"], spin_path="",
                                   steered_checks_text="", fetched_pages={})
        rlog = _Rlog()
        steer = loop.author_steer(chat, Role(name="reasoner", backend="local"), d, gs,
                                  {"messages": [{"role": "user", "content": "task"}]}, rlog,
                                  condition="thrash")
        return steer, chat.bodies, rlog

    def test_the_directive_behind_a_bare_ON_TRACK_is_recovered(self):
        steer, bodies, rlog = self._author([_comp("ON_TRACK", STEER_REAL), _comp(RECOVERED)])
        self.assertIsNotNone(steer, "the author's own diagnosis was thrown away")
        self.assertIn("handle_resolver.py", steer)
        self.assertIn("loop.steer_from_reasoning", rlog.kinds())
        self.assertGreaterEqual(len(bodies), 2, "the focused question was never asked")

    def test_it_works_on_the_toolless_path_too(self):
        steer, _bodies, _rlog = self._author([_comp("ON_TRACK", STEER_REAL), _comp(RECOVERED)],
                                             workspace=False)
        self.assertIsNotNone(steer)
        self.assertIn("handle_resolver.py", steer)

    def test_an_empty_answer_with_a_diagnosis_behind_it_is_recovered(self):
        # Run 20260802T001204 call 0033: content "", the whole diagnosis in reasoning_content.
        steer, _bodies, _rlog = self._author([_comp("", STEER_REAL), _comp(RECOVERED)])
        self.assertIsNotNone(steer)

    def test_the_question_carries_the_thinking_and_asks_for_the_directive(self):
        _steer, bodies, _rlog = self._author([_comp("ON_TRACK", STEER_REAL), _comp(RECOVERED)])
        asked = bodies[-1]["messages"][0]["content"]
        self.assertIn("stuck in a loop of trying different approaches", asked)   # its OWN thinking
        self.assertIn("ON_TRACK", asked)                                          # positive sentinel

    # ---- ONE DIRECTION ONLY ------------------------------------------------------------------

    def test_a_real_on_track_answer_stays_a_veto(self):
        # The trigger over-fires by design; the QUESTION decides, and when it re-confirms ON_TRACK
        # nothing is injected. Five of ten sampled hits are exactly this shape.
        steer, bodies, _rlog = self._author([_comp("ON_TRACK", STEER_REAL), _comp("ON_TRACK")])
        self.assertEqual(len(bodies), 2, "the question must actually have been asked")
        self.assertIsNone(steer)

    def test_an_authored_directive_is_never_overwritten(self):
        given = "You are re-fetching the same page; read handle_resolver.py and fix line 4."
        steer, bodies, _rlog = self._author([_comp(given, STEER_REAL)])
        self.assertIn("line 4", steer)
        self.assertEqual(len(bodies), 1, "a directive already exists — no recovery call is owed")

    def test_thinking_with_no_stuck_language_costs_nothing(self):
        calm = "Each turn advances and the coder is clearly converging on the fix."
        steer, bodies, _rlog = self._author([_comp("ON_TRACK", calm)])
        self.assertIsNone(steer)
        self.assertEqual(len(bodies), 1, "the pre-filter must keep the common path free")

    def test_a_cut_author_reply_recovers_nothing(self):
        steer, bodies, _rlog = self._author([_comp("ON_TRACK", STEER_REAL, finish="length")])
        self.assertIsNone(steer)
        self.assertEqual(len(bodies), 1)
        # …and the refusal lives in the recovery itself, not only in the tooled branch's own guard,
        # so the toolless path (where summarize returns "" on a cut reply) is covered too.
        asked = []
        self.assertIsNone(loop._steer_from_reasoning(
            _comp("ON_TRACK", STEER_REAL, finish="length"), "ON_TRACK",
            lambda s: asked.append(s) or "anything", _Rlog()))
        self.assertEqual(asked, [], "a cut trace must not even be asked about")

    def test_a_recovered_directive_still_passes_the_grounding_chokepoint(self):
        # _grounded_steer_or_none is enforced for the recovery exactly as for a normal steer.
        invented = ("You should fetch https://totally-invented.example.org/v9/handles and parse the "
                    "JSON it returns.")
        steer, _bodies, rlog = self._author([_comp("ON_TRACK", STEER_REAL), _comp(invented)])
        self.assertIsNone(steer)
        self.assertIn("loop.steer_ungrounded", rlog.kinds())


class RecoveryPromptTests(unittest.TestCase):
    def test_the_veto_sentinel_stays_a_POSITIVE_token(self):
        # Principle 21: a sentinel a weak model emits to veto its own rescue must never be reachable
        # by negating its own reasoning.
        p = prompts.load("steer_reasoning_recover")
        self.assertIn("ON_TRACK", p)
        self.assertNotIn("NOT_STUCK", p)

    def test_it_fences_the_recovering_model_out_of_doing_the_work(self):
        p = prompts.load("steer_reasoning_recover").lower()
        self.assertIn("no tools", p)
        self.assertIn("must appear in the thinking below", p)

    def test_the_whole_thinking_reaches_the_recovering_model(self):
        """It used to carry the last 4,000 characters, on the theory that a conclusion is what a
        model writes LAST. That is cria judging relevance for the model, and #5 leaves no room:
        never truncated, for any reader. The reader here IS a model — it selects for itself."""
        head = "First I considered whether the endpoint returns the holder at all. "
        long = (head + "x " * 4000 + "It is looping, so we must write a directive. "
                "Thus we will output: read the file and run the failing test.")
        sent = {}

        def ask(prompt):
            sent["prompt"] = prompt
            return "read the file and run the failing test"

        comp = {"choices": [{"message": {"content": "ON_TRACK", "reasoning_content": long}}]}
        loop._steer_from_reasoning(comp, "ON_TRACK", ask, _Rlog())
        self.assertIn(head.strip(), sent["prompt"])          # the HEAD survives too
        self.assertIn("Thus we will output", sent["prompt"])  # and so does the tail
        self.assertNotIn("…", sent["prompt"])

if __name__ == "__main__":
    unittest.main()
