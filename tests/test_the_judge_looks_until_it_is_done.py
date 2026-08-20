"""cria told a coder its finished work did not exist, six times, and it edited a 5/5 down to 4/5.

Cycle 4 cell 10, feed-pipeline-java x qwen35. The suite measured **all five checks passing at the
15-minute milestone**, by running them. The model said `task_complete`. Over the next 62 minutes
cria's satisfaction judge refused that completion six times, and these are its reasons, verbatim
from the log:

    02:36  "the current implementation is sequential"
    02:42  "The Importer.java is the original unmodified code (WORKERS_ENABLED=false,
            no OpenCSV usage, no malformed input handling, ...)"
    02:50  "The code claims tests pass but I cannot verify this without running tests"
    03:04  "The 4x speedup requirement cannot be verified - no baseline comparison exists"
    03:22  "current implementation is ~2.5x faster (0.4s vs 1.0s baseline), task requires 4x"

The verifier had already observed 4 threads spawned, opencsv importing the quoted-comma row, and an
**18.7x** speedup against a 4x bar. Every one of those sentences is a claim about a workspace the
judge had not finished reading — `loop.verify_inspect_capped` fired FIVE times in that session.
cria handed each one to the coder as the named gap, the coder went to work on code that was already
right, and the cell finished at 4/5. **cria took a 5/5 run and made it worse.**

THE MECHANISM: the inspection loop bounds a wandering judge with VERIFY_MAX_ROUNDS and then FORCES
an answer. That is correct — an unbounded judge is its own failure — but the forced answer was
allowed to assert things the judge never read, and the caller could not tell a finished look from an
interrupted one.

THE FIX, at both ends. `_judge_completion` tells its caller when it capped. `judge_satisfaction`
keeps the VERDICT (not satisfied — completion still fails closed, #13) and withholds the invented
REASON, falling back to the plain instruction. And the forced-answer prompt now says: if you did not
manage to read something, say "could not verify X" rather than stating it as fact.

#11b in one line: a mechanism that could not observe the thing it was asked about must not answer as
if it had.

---

**THE CHARACTER CAP IS GONE (operator, 2026-08-19: "get rid of the judge budget, let it go free"),
AND THAT IS NOT A REVERT — IT IS THE CAUSE BEING FIXED UPSTREAM.**

Read the two dates. The size cap landed 2026-08-01 because a judge that could not see enough was
asserting things it had never read. `seed_files` landed 2026-08-18: the judge is now HANDED the
workspace files up front instead of spending inspection rounds fetching them. The cap was a
mitigation for "the judge cannot see enough"; the thing that made it unable to see was fixed
seventeen days later, and the cap went on firing.

What it cost on 2026-08-19, `feed-pipeline-java x qwen35` call 0304 — the judge had already run
`list_dir`, seen there was no REVIEW.md, and said so:

    {"satisfied": false,
     "reason": "REVIEW.md does not exist in the workspace (confirmed via list_dir). The task
                explicitly requires creating this file... All other requirements appear to be met"}

What reached the coder at 0305:

    "This step is not yet verified as complete. Keep working: re-check the step's goal against the
     files on disk..."

A true, verified, actionable absence, replaced by boilerplate. REVIEW.md was never written in that
run's 319 calls, and the cell scored 0 of 5.

Principle 1's corollary decides it: an assist is re-measured against the system it runs in NOW, not
the one it was born in. What survives is the ROUND budget — a judge still cannot look forever — and
the forced-answer prompt that tells it to say "could not verify X" rather than invent. What is gone
is the second, blunter bound that interrupted a judge mid-look and then discarded whatever it said.
"""

import json
import tempfile
import unittest

from cria import loop, prompts, verifytools


class _Rlog:
    def __init__(self):
        self.events = []
        self.phase = None

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def kinds(self):
        return [k for k, _ in self.events]


def _call(name, args):
    return {"id": "t1", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


class ASizeCapNoLongerInterruptsTheLookTests(unittest.TestCase):
    """The judge keeps its tools until the ROUND budget is spent, however much it has pulled in."""

    def test_a_huge_prompt_does_not_withdraw_the_tools(self):
        """The exact shape that used to cap on round 0: evidence far past the old 60,000-char bound.
        The judge must still be offered its read-only tools."""
        sent = []

        def chat(body, rlog):
            sent.append(body)
            return json.dumps({"choices": [{"message": {"content": '{"satisfied": false}'}}]}).encode()

        with tempfile.TemporaryDirectory() as ws:
            loop._judge_completion(chat, None, "sys", "x" * 200_000, _Rlog(),
                                   phase="test", workspace_root=ws, verdict_key="satisfied")
        self.assertIn("tools", sent[0], "a big prompt must not cost the judge its eyes")

    def test_the_caller_no_longer_takes_a_capped_list(self):
        """The parameter existed only to carry the size cap to the suppression branch. Both are gone
        — a leftover would be a drift guard pointing at a mechanism that no longer exists."""
        import inspect
        self.assertNotIn("capped", inspect.signature(loop._judge_completion).parameters)

    def test_the_size_bound_is_not_consulted_anywhere_in_the_loop(self):
        """Structural: no input can exercise "this constant is never read"."""
        import inspect
        src = inspect.getsource(loop._judge_completion)
        self.assertNotIn("VERIFY_MAX_CHARS", src)

    def test_the_round_bound_still_holds(self):
        """A judge still cannot look forever — that half was never the problem."""
        rounds = []

        def chat(body, rlog):
            rounds.append(1)
            if len(rounds) <= 50:
                return json.dumps({"choices": [{"message": {"tool_calls": [
                    _call("list_dir", {"path": "."})]}}]}).encode()
            return json.dumps({"choices": [{"message": {"content": "done"}}]}).encode()

        with tempfile.TemporaryDirectory() as ws:
            loop._judge_completion(chat, None, "sys", "usr", _Rlog(), phase="test",
                                   workspace_root=ws, verdict_key="satisfied")
        # +2: the six inspection rounds, the forced-answer round, and the toolless retry the caller
        # makes when a forced answer still is not a parseable verdict.
        self.assertLessEqual(len(rounds), verifytools.VERIFY_MAX_ROUNDS + 2)


class TheJudgesOwnReasonReachesTheCoderTests(unittest.TestCase):
    """The walked regression, asserted: a true absence must arrive as itself."""

    def test_a_verified_absence_is_not_replaced_by_boilerplate(self):
        """Call 0304's real verdict, through a prompt big enough to have tripped the old cap."""
        reason = ("REVIEW.md does not exist in the workspace (confirmed via list_dir). "
                  "The task explicitly requires creating this file.")

        def chat(body, _rlog):
            return json.dumps({"choices": [{"message": {"content": json.dumps(
                {"satisfied": False, "reason": reason, "proposed_fix": ""})}}]}).encode()

        with tempfile.TemporaryDirectory() as ws:
            ok, why, _fix = loop.judge_satisfaction(
                "build the thing", "x" * 200_000, chat, None, _Rlog(), workspace_root=ws)
        self.assertIs(ok, False)                      # completion still fails closed (#13)
        self.assertIn("REVIEW.md does not exist", why)
        self.assertNotEqual(why, prompts.load("unverified_step"))

    def test_a_finished_look_still_names_its_gap(self):
        """Unchanged behaviour, kept as the control."""
        def chat(body, _rlog):
            return json.dumps({"choices": [{"message": {"content": json.dumps(
                {"satisfied": False, "reason": "no README on disk"})}}]}).encode()

        ok, why, _fix = loop.judge_satisfaction("build the thing", "wrote main.py", chat, None, _Rlog())
        self.assertIs(ok, False)
        self.assertEqual(why, "no README on disk")


class TheForcedAnswerMayAbstainTests(unittest.TestCase):
    """The forced-answer prompt reaches the model only after the round cap — drive the real six
    rounds and read what actually lands in the request, not the prompt file in isolation."""

    def _forced_ask(self):
        sent = []

        def chat(body, rlog):
            sent.append(body)
            n = len(sent)
            if n <= verifytools.VERIFY_MAX_ROUNDS:
                return json.dumps({"choices": [{"message": {"tool_calls": [_call("list_dir", {"path": "."})]}}]}).encode()
            return json.dumps({"choices": [{"message": {"content": "no more rounds"}}]}).encode()

        with tempfile.TemporaryDirectory() as ws:
            loop._judge_completion(chat, None, "sys", "usr", _Rlog(), phase="test", workspace_root=ws)
        # the request right after the 6th round carries the forced ask as its last message
        return sent[verifytools.VERIFY_MAX_ROUNDS]["messages"][-1]["content"]

    def test_it_is_told_to_say_it_could_not_verify(self):
        ask = self._forced_ask()
        self.assertIn("could not verify", ask)
        self.assertIn("did not actually read", ask)

    def test_it_still_demands_the_verdict_shape(self):
        self.assertIn('"done": true|false', self._forced_ask())

    def test_the_cap_itself_is_unchanged(self):
        """Bounding a wandering judge is correct and stays. What changed is what a capped judge is
        allowed to assert, not whether it is capped."""
        self.assertEqual(verifytools.VERIFY_MAX_ROUNDS, 6)


if __name__ == "__main__":
    unittest.main()
