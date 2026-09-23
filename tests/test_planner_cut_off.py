"""A planner reply cut off at the output cap: what was unfinished decides the handling.

The first version of this guard refused the whole round. Checked against every captured cut-off
round that carried tool calls (n=8), that was wrong twice over:

  * the LAST call's arguments parse as valid JSON in 5 of the 8 and are a fragment ("{") in 3 — so
    "the list is unfinished" is true less than half the time, and refusing threw away real research;
  * on a cut-off round with NO calls at all it still fired, telling the model "none of its tool
    calls were run" when there were none. That is cria asserting something untrue (principle 5b),
    and it shipped — run 20260801T221447 calls 0002 and 0006 both made zero calls and got it.

Now: drop only a trailing call that does not parse, keep and run the rest, and say the reply was cut
short — once, and only when calls were actually present.
"""
import json
import os
from pathlib import Path
import tempfile
import unittest

from cria import planner, prompts


class _Rlog:
    phase = ""

    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def kinds(self):
        return [k for k, _ in self.events]


class _ScriptedPlanner:
    """Feeds one scripted completion per planner call, in order."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.bodies = []

    def chat(self, body, rlog):
        self.bodies.append(body)
        return json.dumps(self.replies[len(self.bodies) - 1]).encode()


def _cwd_with_file(name="a.py", content="print('hello')\n"):
    cwd = tempfile.mkdtemp()
    with open(os.path.join(cwd, name), "w") as f:
        f.write(content)
    return cwd


def _env(cwd):
    return [{"role": "user", "content": f"<environment_context><cwd>{cwd}</cwd></environment_context>"},
            {"role": "user", "content": "build the thing"}]


def _submit_round(*steps):
    return {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": None,
        "tool_calls": [{"id": "p1", "type": "function", "function": {"name": "submit_plan",
            "arguments": json.dumps({"steps": list(steps) or ["write the thing"]})}}]}}]}


class FragmentDetectionTests(unittest.TestCase):
    def _msg(self, raw):
        return {"tool_calls": [{"function": {"name": "read_file", "arguments": raw}}]}

    def test_a_complete_call_is_not_a_fragment(self):
        self.assertFalse(planner._last_call_truncated(self._msg('{"path":"a.py"}')))

    def test_a_truncated_call_IS(self):
        self.assertTrue(planner._last_call_truncated(self._msg("{")))
        self.assertTrue(planner._last_call_truncated(self._msg('{"path":"a.p')))

    def test_a_legitimately_empty_argument_object_is_not(self):
        # _tool_calls parses leniently and turns BOTH into {}, so the check must read the raw string.
        self.assertFalse(planner._last_call_truncated(self._msg("{}")))

    def test_no_calls_at_all_is_not_a_fragment(self):
        self.assertFalse(planner._last_call_truncated({"tool_calls": []}))
        self.assertFalse(planner._last_call_truncated({}))


class HandlingTests(unittest.TestCase):
    """Driven for real: a gather round cut off at the output cap, with a trailing tool call that
    is a JSON fragment (the measured shape — 3 of 8 captured cut-off rounds end mid-object)."""

    def _cut_off_round(self, *paths):
        return {"choices": [{"finish_reason": "length", "message": {"role": "assistant", "content": None,
            "tool_calls": [{"id": f"c{i}", "type": "function", "function": {
                "name": "read_file", "arguments": json.dumps({"path": p})}}
                for i, p in enumerate(paths)] + [
                {"id": "frag", "type": "function", "function": {
                    "name": "read_file", "arguments": '{"path": "b.p'}}]}}]}

    def test_only_the_fragment_is_dropped_and_the_rest_still_runs(self):
        """One valid call plus one fragment in the same cut-off round: the fragment must not be
        executed (only one plan.gather fires) and the valid call's REAL content must still reach
        the planner's next turn — dropping is per-call, not per-round."""
        cwd = _cwd_with_file()
        sp = _ScriptedPlanner([self._cut_off_round("a.py"),
                               {"choices": [{"finish_reason": "stop", "message": {
                                   "role": "assistant", "content": "done looking"}}]},
                               _submit_round()])
        rlog = _Rlog()
        plan = planner.Planner(sp).plan_for(_env(cwd), rlog)
        self.assertIsNotNone(plan)
        self.assertEqual(rlog.kinds().count("plan.gather"), 1,
                         "only the surviving (non-fragment) call may execute")
        self.assertIn("plan.gather_partial_call_dropped", rlog.kinds())
        # the surviving call's real result reached the next round's prompt, whole
        joined = " ".join(str(m.get("content") or "") for m in sp.bodies[1]["messages"])
        self.assertIn("print('hello')", joined)

    def test_the_note_rides_WITH_the_results_never_instead_of_them(self):
        """The results come first and whole, the cut-short note follows — never the reverse."""
        cwd = _cwd_with_file()
        sp = _ScriptedPlanner([self._cut_off_round("a.py"),
                               {"choices": [{"finish_reason": "stop", "message": {
                                   "role": "assistant", "content": "done looking"}}]},
                               _submit_round()])
        planner.Planner(sp).plan_for(_env(cwd), _Rlog())
        msgs = sp.bodies[1]["messages"]
        tool_result = next(i for i, m in enumerate(msgs) if m.get("role") == "tool")
        note = next(i for i, m in enumerate(msgs)
                    if m.get("role") == "user" and "cut short" in (m.get("content") or ""))
        self.assertLess(tool_result, note, "the tool result must precede the cut-off note")

    def test_it_is_said_once_not_every_round(self):
        """Two consecutive cut-off rounds must not double the note — attempt 2 is silent about it."""
        cwd = _cwd_with_file()
        with open(os.path.join(cwd, "b_real.py"), "w") as f:
            f.write("print('world')\n")
        sp = _ScriptedPlanner([self._cut_off_round("a.py"), self._cut_off_round("b_real.py"),
                               {"choices": [{"finish_reason": "stop", "message": {
                                   "role": "assistant", "content": "done looking"}}]},
                               _submit_round()])
        rlog = _Rlog()
        planner.Planner(sp).plan_for(_env(cwd), rlog)
        self.assertEqual(rlog.kinds().count("plan.gather_cut_off"), 1)

    def test_it_only_engages_when_calls_are_actually_present(self):
        """The walked regression: a cut-off round with ZERO tool calls must not claim any call was
        dropped or cut short — cria has nothing true to say about a round that made no calls."""
        cwd = _cwd_with_file()
        sp = _ScriptedPlanner([
            {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": None,
                "tool_calls": [{"id": "c1", "type": "function", "function": {
                    "name": "read_file", "arguments": json.dumps({"path": "a.py"})}}]}}]},
            {"choices": [{"finish_reason": "length", "message": {"role": "assistant",
                "content": "I have reviewed enough of the codebase to draft a plan now."}}]},
            _submit_round()])
        rlog = _Rlog()
        plan = planner.Planner(sp).plan_for(_env(cwd), rlog)
        self.assertIsNotNone(plan)
        self.assertNotIn("plan.gather_cut_off", rlog.kinds())
        self.assertNotIn("plan.gather_partial_call_dropped", rlog.kinds())


class SteerTextTests(unittest.TestCase):
    TEXT = prompts.load_map("planner_steers")["reply_cut_off"]

    def test_it_no_longer_claims_calls_were_discarded(self):
        self.assertNotIn("none of its tool calls were run", self.TEXT)

    def test_it_states_what_is_actually_true(self):
        self.assertIn("cut short", self.TEXT)
        self.assertIn("calls that arrived complete", self.TEXT)

    def test_it_names_no_internals(self):
        self.assertNotIn("cria", self.TEXT.lower())


class CaptureShapeTests(unittest.TestCase):
    """Fixed terminal forms from preserved C13 responses, not a changing live-capture census."""

    FIXTURE = Path(__file__).parent / "fixtures" / "planner-cut-off-terminal-forms.json"

    def test_cutoff_terminal_calls_classify_by_arguments_not_finish_reason(self):
        """Both capture-shaped forms are output-cap cutoffs; valid terminal JSON survives.

        Keeping the terminal envelopes in-repo makes this semantic regression independent of later
        capture retention: ``finish_reason=length`` alone cannot say whether the final call is a
        fragment.
        """
        cases = json.loads(self.FIXTURE.read_text(encoding="utf-8"))["responses"]
        complete = cases["complete_terminal_call_at_cutoff"]["choices"][0]
        fragment = cases["fragment_terminal_call_at_cutoff"]["choices"][0]
        self.assertEqual(complete["finish_reason"], "length")
        self.assertEqual(fragment["finish_reason"], "length")
        self.assertFalse(planner._last_call_truncated(complete["message"]))
        self.assertTrue(planner._last_call_truncated(fragment["message"]))
