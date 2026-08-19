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


class TheCapReachesTheCallerTests(unittest.TestCase):
    def test_the_judge_signature_carries_it(self):
        """The claim IS about the parameter — inspect.signature is the right instrument."""
        import inspect
        self.assertIn("capped", inspect.signature(loop._judge_completion).parameters)
        self.assertIn("capped", inspect.signature(loop._satisfaction_verdict).parameters)

    def test_it_is_appended_where_the_cap_is_logged(self):
        """Room already exhausted before the first round ever ran: the caller must be able to READ
        that this happened, not just see it logged. Drive the real loop past the char budget and
        check what lands in the caller's own list."""
        sent = []

        def chat(body, rlog):
            sent.append(body)
            return json.dumps({"choices": [{"message": {"content": '{"satisfied": false}'}}]}).encode()

        capped = []
        with tempfile.TemporaryDirectory() as ws:
            loop._judge_completion(chat, None, "sys", "x" * (verifytools.VERIFY_MAX_CHARS + 5_000),
                                   _Rlog(), phase="test", workspace_root=ws, capped=capped)
        self.assertEqual(capped, [0], "the cap fired before any inspection round could run")
        self.assertNotIn("tools", sent[0], "a capped round must not still offer inspection tools")


class AnUnfinishedLookNamesNoGapTests(unittest.TestCase):
    """Drives the real `judge_satisfaction` end to end. `evidence` alone big enough to blow the char
    budget on round 0 reproduces the cap without needing six live inspection rounds."""

    def _capped_verdict(self, reason="the coder invented reason", proposed_fix=""):
        rlog = _Rlog()

        def chat(body, _rlog):
            return json.dumps({"choices": [{"message": {"content": json.dumps(
                {"satisfied": False, "reason": reason, "proposed_fix": proposed_fix})}}]}).encode()

        with tempfile.TemporaryDirectory() as ws:
            ok, why, fix = loop.judge_satisfaction(
                "build the thing", "x" * (verifytools.VERIFY_MAX_CHARS + 5_000), chat, None, rlog,
                workspace_root=ws)
        return ok, why, fix, rlog

    def test_the_reason_is_withheld_but_the_verdict_stands(self):
        ok, why, _fix, _rlog = self._capped_verdict()
        # the VERDICT is still False — completion fails closed
        self.assertIs(ok, False)
        # but the invented REASON never reaches the coder — the plain instruction does instead
        self.assertEqual(why, prompts.load("unverified_step"))
        self.assertNotIn("the coder invented reason", why)

    def test_it_is_logged_so_the_suppression_is_countable(self):
        _ok, _why, _fix, rlog = self._capped_verdict()
        self.assertIn("loop.satisfaction_gap_withheld", rlog.kinds())

    def test_a_finished_look_still_names_its_gap(self):
        """The mechanism must not go quiet on the judges that DID read what they cite — a named,
        grounded gap is the whole reason the seat exists. No workspace_root here: the inspection
        never runs, so it cannot cap, and the judge's own reason must survive untouched."""
        rlog = _Rlog()

        def chat(body, _rlog):
            return json.dumps({"choices": [{"message": {"content": json.dumps(
                {"satisfied": False, "reason": "no README on disk"})}}]}).encode()

        ok, why, _fix = loop.judge_satisfaction("build the thing", "wrote main.py", chat, None, rlog)
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
