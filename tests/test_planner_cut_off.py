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
import inspect
import json
import pathlib
import unittest

from cria import planner, prompts


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
    SRC = inspect.getsource(planner.Planner._gather_and_plan)

    def test_it_only_engages_when_calls_are_actually_present(self):
        self.assertIn('if msg.get(FINISH_KEY) == "length" and calls:', self.SRC)

    def test_only_the_fragment_is_dropped(self):
        self.assertIn("if _last_call_truncated(msg):", self.SRC)
        self.assertIn("calls = calls[:-1]", self.SRC)

    def test_the_surviving_calls_are_still_EXECUTED(self):
        drop = self.SRC.index("calls = calls[:-1]")
        run = self.SRC.index("planner_tools.execute_tool")
        self.assertLess(drop, run, "the round must still happen after the fragment is dropped")

    def test_the_note_rides_WITH_the_results_never_instead_of_them(self):
        results = self.SRC.index('messages.append({"role": "tool", "tool_call_id": cid')
        note = self.SRC.index("if pending_note:")
        self.assertLess(results, note, "results first and whole, then the note")

    def test_it_is_said_once_not_every_round(self):
        self.assertIn("cut_noted = False", self.SRC)
        self.assertIn("and not cut_noted", self.SRC)


class SteerTextTests(unittest.TestCase):
    TEXT = prompts.load_map("planner_steers")["reply_cut_off"]

    def test_it_no_longer_claims_calls_were_discarded(self):
        self.assertNotIn("none of its tool calls were run", self.TEXT)

    def test_it_states_what_is_actually_true(self):
        self.assertIn("cut short", self.TEXT)
        self.assertIn("calls that arrived complete", self.TEXT)

    def test_it_names_no_internals(self):
        self.assertNotIn("cria", self.TEXT.lower())


class MeasurementTests(unittest.TestCase):
    def test_the_5_of_8_split_is_what_the_captures_still_say(self):
        root = pathlib.Path.home()/".cria"/"calls"
        if not root.is_dir():
            self.skipTest("captures not present on this machine")
        complete = fragment = 0
        for r in root.glob("*/*-planner.response.json"):
            try: ch = json.load(r.open())["choices"][0]
            except Exception: continue
            if ch.get("finish_reason") != "length": continue
            if not (ch["message"].get("tool_calls") or []): continue
            if planner._last_call_truncated(ch["message"]): fragment += 1
            else: complete += 1
        if complete + fragment == 0:
            self.skipTest("no cut-off rounds with calls in these captures")
        self.assertGreater(complete, 0,
                           "if NO cut-off round ends on a complete call, refusing the whole round "
                           "would have been right after all — re-derive this guard")
