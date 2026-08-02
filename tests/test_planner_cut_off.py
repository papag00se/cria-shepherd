"""A planner reply cut off at the output cap is not a finished turn.

Measured over every captured planner round (n=333): finish=length occurs in 8, and ALL SEVEN rounds
emitting more than 12 distinct calls are among them. Healthy rounds sit at median and p90 of ONE
distinct call. Run 20260801T213731 (zaya1, 0/4) produced 95, 100, 92 and 93 calls in four
consecutive cut-off rounds and never reached the coder.
"""
import inspect
import json
import pathlib
import unittest

from cria import planner, prompts


class CutOffTests(unittest.TestCase):
    def test_the_finish_reason_is_carried_out_of_reason(self):
        src = inspect.getsource(planner.Planner._reason)
        self.assertIn("FINISH_KEY", src)
        self.assertIn("finish_reason", src)

    def test_a_cut_off_round_is_refused_and_re_asked_once(self):
        src = inspect.getsource(planner.Planner._gather_and_plan)
        self.assertIn('msg.get(FINISH_KEY) == "length" and not cut_retried', src)
        self.assertIn("cut_retried = True", src)
        self.assertIn("plan.gather_cut_off", src)

    def test_the_refusal_happens_BEFORE_any_call_is_executed(self):
        src = inspect.getsource(planner.Planner._gather_and_plan)
        cut = src.index("gather_cut_off")
        exec_at = src.index("planner_tools.execute_tool")
        self.assertLess(cut, exec_at, "the partial list must never be executed")

    def test_it_is_bounded_so_a_model_that_always_overruns_still_progresses(self):
        src = inspect.getsource(planner.Planner._gather_and_plan)
        self.assertIn("cut_retried = False", src)

    def test_the_private_key_never_reaches_the_wire(self):
        # The gather composes its own assistant dict; the private key must not be in it.
        src = inspect.getsource(planner.Planner._gather_and_plan)
        self.assertIn('messages.append({"role": "assistant", "content": msg.get("content") or None, '
                      '"tool_calls": msg["tool_calls"]})', src)
        self.assertNotIn('messages.append(msg)', src)

    def test_the_steer_is_plain_and_names_no_internals(self):
        t = prompts.load_map("planner_steers")["reply_cut_off"]
        self.assertNotIn("cria", t.lower())
        self.assertIn("cut off", t)
        self.assertIn("none of its tool calls were run", t)


class MeasurementTests(unittest.TestCase):
    def test_the_measured_runaway_rounds_all_carry_finish_length(self):
        root = pathlib.Path.home()/".cria"/"calls"
        if not root.is_dir():
            self.skipTest("captures not present on this machine")
        runaway_not_cut = []
        for r in root.glob("*/*-planner.response.json"):
            try: ch = json.load(r.open())["choices"][0]
            except Exception: continue
            tc = ch["message"].get("tool_calls") or []
            n = len({(t["function"]["name"], t["function"].get("arguments", "")) for t in tc})
            if n > 12 and ch.get("finish_reason") != "length":
                runaway_not_cut.append(str(r))
        self.assertEqual(runaway_not_cut, [],
                         "every runaway round should be a cut-off round; if this fails the "
                         "finish_reason signal is no longer sufficient and needs re-measuring")
