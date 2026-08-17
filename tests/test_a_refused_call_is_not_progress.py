"""An install loop erased the evidence of itself, and the repetition guard never fired once.

Cycle 4 cell 13, `shipping-rates-rb × ternary-bonsai` — 10% useful, and **34 of its 54 calls spent
trying to obtain a gem**. Six identical refused `gem install` attempts across 25 calls, and the
redirect never came.

`_is_progress` reads the command TEXT: writing a `Gemfile`, `mkdir -p vendor/bundle` — both carry
mutator words, so both answer "this changed the workspace", and a change on new ground FLUSHES the
repetition window. Writing a Gemfile and making vendor directories is exactly what an install loop
does between attempts, so the loop kept resetting the hunt for itself. Call 0051 rewrote the Gemfile
with bytes identical to call 0033 and still counted as progress on new ground. The walk replayed the
run's real 53-call sequence through `guard_track_repetition` with the live constants and it fires
**zero times**.

The words were true; the outcome was not. A call cria refused wrote nothing — and cria is what
refused it, so this is a fact cria holds, not a judgement it has to make (#8). What resets the hunt
now is a change that actually happened.

THE PROTECTED CASE IS UNTOUCHED, and it is the reason the reset exists at all: a healthy
edit→test→edit→test cycle must never trip on its repeated test runs. Those writes really do change
bytes and cria never refused them, so they reset exactly as before.
"""

import json
import unittest

from cria import loop


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, name, **k):
        self.events.append((name, k))

    def first(self, name):
        return next((k for n, k in self.events if n == name), None)


def call(cid, name, cmd):
    return {"id": cid, "function": {"name": name, "arguments": json.dumps({"command": cmd})}}


def write(cid, path, content="x"):
    return {"id": cid, "function": {"name": "write_file",
                                    "arguments": json.dumps({"path": path, "content": content})}}


def completion(tc):
    return {"choices": [{"message": {"tool_calls": [tc]}}]}


DENIAL = ("⟦ctx:denied⟧ Installing into the shared system or user environment is not permitted "
          "here — an install must land inside the project directory.")


def history(pairs):
    """pairs: (tool_call, result_text) — the assistant turn and what came back."""
    msgs = []
    for tc, result in pairs:
        msgs.append({"role": "assistant", "tool_calls": [tc]})
        msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
    return msgs


class TheRefusedCallDoesNotResetTests(unittest.TestCase):
    def test_the_install_loop_no_longer_erases_itself(self):
        """THE CELL, in miniature. The real run made six refused install attempts across 25 calls,
        writing a Gemfile and mkdir-ing vendor directories between them — which is what an install
        loop does — and each of those flushed the window.

        What is asserted is the flush, because that is what was fixed. Whether the redirect then
        FIRES depends on `_actions_match` deciding those attempts are the same action, and on the
        real run's attempts (`gem install`, `--user-dir`, `gem install bundler`, `bundle install`,
        a hand-rolled `curl`) it would not — that is a second, unmeasured half, recorded in the
        ledger rather than guessed at here."""
        gs = loop.GuardState()
        rlog = _Rlog()
        msgs = []
        GEMFILE = 'source "https://rubygems.org"\ngem "eu_countries"\n'
        seq = [(call("1", "exec_command", "gem install eu_countries 2>&1 | tail -5"), DENIAL),
               (write("2", "Gemfile", GEMFILE), "Wrote Gemfile"),      # real progress — must reset
               (call("3", "exec_command", "gem install eu_countries 2>&1 | tail -10"), DENIAL),
               (call("4", "exec_command", "mkdir -p vendor/bundle && gem install eu_countries"),
                DENIAL),                                              # used to flush: `mkdir`
               (write("5", "Gemfile", GEMFILE), "Wrote Gemfile"),      # used to flush: identical bytes
               (call("6", "exec_command", "gem install eu_countries 2>&1 | tail -5"), DENIAL)]
        for tc, result in seq:
            loop.guard_track_repetition(gs, completion(tc), rlog, messages=msgs)
            msgs += [{"role": "assistant", "tool_calls": [tc]},
                     {"role": "tool", "tool_call_id": tc["id"], "content": result}]
        installs = [e for e in gs.recent_actions if e[1][0] == "act"]
        self.assertEqual(len(installs), 3,
                         "the install attempts were flushed out of the window by the loop's own "
                         "housekeeping")   # 1 is flushed by call 2, which is real progress; 3/4/6 stay

    def test_the_first_real_write_still_resets(self):
        """The protected case, in the same sequence: the Gemfile did not exist and now does."""
        gs = loop.GuardState()
        rlog = _Rlog()
        msgs = []
        for tc, result in ((call("1", "exec_command", "gem install eu_countries"), DENIAL),
                           (write("2", "Gemfile", 'gem "eu_countries"'), "Wrote Gemfile")):
            loop.guard_track_repetition(gs, completion(tc), rlog, messages=msgs)
            msgs += [{"role": "assistant", "tool_calls": [tc]},
                     {"role": "tool", "tool_call_id": tc["id"], "content": result}]
        self.assertEqual([e[1][0] for e in gs.recent_actions], ["write"])

    def test_an_install_into_a_shared_environment_is_not_workspace_progress(self):
        for cmd in ("gem install eu_countries",
                    "mkdir -p vendor/bundle && gem install eu_countries",
                    "npm install -g typescript",
                    "pip install requests"):
            with self.subTest(command=cmd):
                sig = loop._action_signature("exec_command", json.dumps({"command": cmd}))
                self.assertFalse(loop._is_progress(sig, json.dumps({"command": cmd})), cmd)

    def test_a_local_install_is_not_swept_in(self):
        """An install that lands INSIDE the project is a different thing, and this rule must not
        touch it. Asserted at the owner: `_is_progress` never called a bare install progress in the
        first place (there is no mutator word and no redirect in `npm install`), so asserting it
        does would pin something that was never true."""
        from cria import dirguard
        for cmd in ("bundle3.2 install --path vendor/bundle",
                    "npm install",
                    "python3 -m venv .venv && .venv/bin/pip install requests"):
            with self.subTest(command=cmd):
                self.assertFalse(dirguard.installs_outside_workspace(cmd), cmd)

    def test_a_refused_write_does_not_flush_the_window(self):
        gs = loop.GuardState()
        gs.recent_actions = []
        rlog = _Rlog()
        probe = call("9", "exec_command", "gem install countries")
        msgs = history([(write("2", "Gemfile"), DENIAL)])
        loop.guard_track_repetition(gs, completion(probe), rlog, messages=msgs)
        loop.guard_track_repetition(gs, completion(write("2b", "Gemfile")), rlog, messages=msgs)
        self.assertTrue([e for e in gs.recent_actions if e[1][0] != "write"],
                        "the refused write flushed the non-write history it must not touch")

    def test_the_signature_match_tolerates_flag_jitter(self):
        """`tail -5` vs `tail -10` vs `--user-dir` is the same action; the tracker already knows
        that, and the refusal lookup has to use the same comparison or it answers about bytes."""
        a = loop._action_signature("exec_command",
                                   json.dumps({"command": "gem install eu_countries 2>&1 | tail -5"}))
        b = loop._action_signature("exec_command",
                                   json.dumps({"command": "gem install eu_countries 2>&1 | tail -10"}))
        self.assertTrue(loop._actions_match(a, b))


class TheHealthyCycleStillResetsTests(unittest.TestCase):
    """The reason the reset exists. These writes really change bytes and cria never refused them."""

    def test_edit_test_edit_test_does_not_trip(self):
        gs = loop.GuardState()
        rlog = _Rlog()
        msgs = []
        for i in range(4):
            for tc in (write(f"w{i}", "cart.go", f"package main // rev {i}"),
                       call(f"t{i}", "exec_command", "go test ./...")):
                loop.guard_track_repetition(gs, completion(tc), rlog, messages=msgs)
                msgs += [{"role": "assistant", "tool_calls": [tc]},
                         {"role": "tool", "tool_call_id": tc["id"], "content": "ok\nEXIT:0"}]
        self.assertFalse(gs.redirect_due or gs.redirect_probe,
                         "a healthy edit/test cycle was read as a repetition loop")

    def test_a_call_with_no_history_is_judged_as_before(self):
        self.assertEqual(loop._denied_signatures(None), [])
        self.assertEqual(loop._denied_signatures([]), [])

    def test_a_successful_result_is_not_a_denial(self):
        msgs = history([(write("1", "Gemfile"), "Wrote Gemfile")])
        self.assertEqual(loop._denied_signatures(msgs), [])


class ItIsCriaSOwnFactNotAJudgementTests(unittest.TestCase):
    def test_the_denial_is_recognised_by_its_owner(self):
        """#23: `denial.is_denied` is what decides this everywhere else too."""
        import inspect
        self.assertIn("denial.is_denied", inspect.getsource(loop._denied_signatures))

    def test_the_messages_reach_the_tracker(self):
        import inspect
        self.assertIn("messages=body.get(\"messages\")",
                      inspect.getsource(loop.Loop._coder_turn))


if __name__ == "__main__":
    unittest.main()
