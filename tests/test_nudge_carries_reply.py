"""nemotron-nano 1786243834, call 0073: the unexecuted-write nudge fired — the ONE right steer of
the run — saying "your last message contained the file's contents as text … send that same content
again as a write tool call". But the re-framed view rebuilds history from the harness body, which
never saw the internal prose turn: 0073's 12 messages contain no assistant prose at all. Ordered
to resend text it could not see, the model re-read the spec file a 7th time and the run died.

Rule 5b: "your last message contained X" requires that message to be in the frame. Both drive
paths now put the coder's own no-tool-call reply in front of the nudge.

EXCEPT when the reply was CUT OFF at the output cap. Then carrying it is the worse lie — "send
that same content again" over a fragment asks for a COMPLETE write of incomplete content, and
guard_truncation cannot catch the result (the tool call would be whole, only its payload short).
Real case: ~/.cria/calls/20260806T180251-…/0095-coder-s1 — mellum2, plan-off, finish_reason
"length", 60,177 chars, zero tool calls, and the log shows loop.truncated → loop.truncated_dropped
→ loop.unexecuted_write on that very turn. The truncated replies are also the two largest ever
carried (15,044 and 33,638 est tokens), so skipping them drops the size risk along with the lie.
"""
import unittest

from cria import loop, prompts
from cria.plan import Plan, PlanItem

FENCED = "Here is the file:\n\n```python\ndef resolve(handle):\n    return handle\n```\n"
PASTED = ("Here is the script:\n\n```python\n" + "\n".join(f"line_{i} = {i}" for i in range(20)) + "\n```\n")


def _completion(text, finish="stop"):
    return {"choices": [{"finish_reason": finish, "message": {"role": "assistant", "content": text}}]}


class WhatReachesTheCoderTests(unittest.TestCase):
    """Behavioral: build the frame the way _work does and assert what the model actually sees."""

    def _frame(self, sess):
        """The tail _work appends when a nudge is pending — reply (if carried), then the nudge."""
        msgs = []
        if sess.nudge_reply:
            msgs.append({"role": "assistant", "content": sess.nudge_reply})
            sess.nudge_reply = ""
        msgs.append({"role": "user", "content": prompts.render("nudge", reason=sess.nudge_reason)})
        return msgs

    def test_a_complete_reply_is_in_front_of_the_nudge(self):
        sess = loop.PlanSession(plan=None)
        sess.nudge_reply = loop._completion_text(_completion(FENCED))
        sess.nudge_reason = prompts.load("unexecuted_write_nudge")
        out = self._frame(sess)
        self.assertEqual(out[0]["role"], "assistant")
        self.assertIn("def resolve(handle)", out[0]["content"])
        self.assertIn("your last message", out[1]["content"])

    def test_the_carried_reply_is_verbatim_never_clipped(self):
        """Clipping it would make the model resend truncated content — the fault, inverted."""
        big = FENCED + "x" * 50_000
        sess = loop.PlanSession(plan=None)
        sess.nudge_reply = loop._completion_text(_completion(big))
        sess.nudge_reason = "n"
        self.assertEqual(self._frame(sess)[0]["content"], big)

    def test_a_truncated_reply_is_not_carried(self):
        """The nudge still ships; the fragment does not ride in front of it."""
        sess = loop.PlanSession(plan=None)
        comp = _completion("```python\ndef resolve(han", finish="length")
        sess.nudge_reply = "" if _is_trunc(comp) else loop._completion_text(comp)
        sess.nudge_reason = prompts.load("unexecuted_write_nudge")
        out = self._frame(sess)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["role"], "user")

    def test_the_reply_is_consumed_once(self):
        """A stale reply must never ride along on a LATER, unrelated nudge."""
        sess = loop.PlanSession(plan=None)
        sess.nudge_reply, sess.nudge_reason = FENCED, "first"
        self._frame(sess)
        sess.nudge_reason = "a different nudge entirely"
        out = self._frame(sess)
        self.assertEqual(len(out), 1)
        self.assertNotIn("def resolve", out[0]["content"])


def _is_trunc(comp):
    from cria import massage
    return massage.is_truncated(comp)


class TheTruncationGuardIsWiredAtBothSitesTests(unittest.TestCase):
    """The shape of the real mellum2 case: a fenced file cut off mid-token at the output cap."""

    CUT_OFF = ('Here is the resolver:\n\n```python\nimport requests, argparse\n\n'
               'def resolve_handle(handle: str) -> dict:\n'
               '    r = requests.get(f"https://api.handle.me/handles/{handle}")\n'
               '    r.raise_for_status()\n    return r.json()\n\n'
               'def main():\n    p = argparse.ArgumentParser()\n    p.add_argument("handle")\n'
               '    args = p.parse_args()\n    data = resolve_handle(args.handle)\n'
               '    print(data["resolved_addresses"]["ada"])\n    print(data["holder"])\n\n'
               'if __name__ == "__main__":\n    ma')

    def test_the_real_shape_trips_unexecuted_write(self):
        """Precondition: the guard is load-bearing because the nudge really does fire here."""
        self.assertTrue(loop.unexecuted_write(self.CUT_OFF, []))

    def test_the_single_item_driver_does_not_carry_a_truncated_reply(self):
        """Drive the REAL `_gate_single_done` (the plan-off half) with a paste that fires the
        nudge, once whole and once cut off at the output cap — a source-text grep for
        `massage.is_truncated(comp)` can tell the call is spelled somewhere in the function; it
        cannot tell whether the frame the coder is re-driven with actually honours it."""
        for finish, want_carried in (("stop", True), ("length", False)):
            with self.subTest(finish=finish):
                captured = {}

                def fake_coder_turn(sess, framed, body, step, rlog):
                    captured["messages"] = framed["messages"]
                    return {"choices": [{"message": {"role": "assistant", "tool_calls": [
                        {"id": "c1", "type": "function",
                         "function": {"name": "write_file", "arguments": "{}"}}]}}]}

                lp = loop.Loop.__new__(loop.Loop)
                lp._coder_turn = fake_coder_turn
                sess = loop.PlanSession(plan=Plan(id="x", task="t", created="c",
                                                  items=[PlanItem("write the script")]))
                comp = {"choices": [{"finish_reason": finish,
                                     "message": {"role": "assistant", "content": PASTED}}]}
                framed = {"messages": [{"role": "user", "content": "do it"}]}
                lp._gate_single_done(sess, comp, framed, {"messages": []}, "k1", _RlogB())
                msgs = captured["messages"]
                carried = any(m["role"] == "assistant" and m.get("content") == PASTED for m in msgs)
                self.assertEqual(carried, want_carried)

    def test_the_multi_item_driver_does_not_carry_a_truncated_reply(self):
        """Same claim, the plan-ON half (`_work_item`). `guard_intervene`/`guard_periodic_gate`
        are stubbed to a no-op so the drive reaches the unexecuted-write branch directly."""
        for finish, want_carried in (("stop", True), ("length", False)):
            with self.subTest(finish=finish):
                captured = {}
                calls = []

                def fake_coder_turn(sess, framed, body, step, rlog):
                    calls.append(1)
                    if len(calls) == 1:   # the pasted-file turn that trips the nudge
                        return {"choices": [{"finish_reason": finish,
                                             "message": {"role": "assistant", "content": PASTED}}]}
                    # the re-driven attempt: capture its frame, then stop the recursion
                    captured["messages"] = framed["messages"]
                    return {"choices": [{"message": {"role": "assistant", "tool_calls": [
                        {"id": "c1", "type": "function",
                         "function": {"name": "write_file", "arguments": "{}"}}]}}]}

                saved = (loop.guard_intervene, loop.guard_periodic_gate)
                loop.guard_intervene = lambda *a, **k: None
                loop.guard_periodic_gate = lambda *a, **k: None
                try:
                    lp = loop.Loop.__new__(loop.Loop)
                    lp._ctx = _MultiCtx()
                    lp._coder_turn = fake_coder_turn
                    item = PlanItem("write the script")
                    sess = loop.PlanSession(plan=Plan(id="x", task="t", created="c", items=[item]))
                    body = {"messages": [{"role": "user", "content": "do it"}], "tools": []}
                    lp._work_item(sess, "k1", body, _RlogB(), item, 1)
                finally:
                    loop.guard_intervene, loop.guard_periodic_gate = saved
                msgs = captured["messages"]
                carried = any(m["role"] == "assistant" and m.get("content") == PASTED for m in msgs)
                self.assertEqual(carried, want_carried)


class _RlogB:
    def emit(self, *a, **k):
        pass


class _MultiCtx:
    reasoner_chat = None
    reasoner_role = None
    coder_role = None
    self_compact = False
    focus_trim = False
    satisfaction_check_start = 10 ** 9
    satisfaction_check_every = 0
    workspace_root = None
    assists = True          # the engagement ladder's top rung; this double drives the full loop


class TheSessionFieldTests(unittest.TestCase):
    def test_it_defaults_empty_so_no_reply_rides_by_accident(self):
        import dataclasses
        f = {x.name: x for x in dataclasses.fields(loop.PlanSession)}
        self.assertIn("nudge_reply", f)
        self.assertEqual(f["nudge_reply"].default, "")

    def test_the_nudge_text_still_references_the_last_message(self):
        """If the prompt stops referencing the reply, the carrying mechanism should be revisited."""
        self.assertIn("your last message", prompts.load("unexecuted_write_nudge"))


if __name__ == "__main__":
    unittest.main()
