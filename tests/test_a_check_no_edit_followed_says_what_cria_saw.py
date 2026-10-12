"""A check nobody has edited since is not "re-run it" — and the claim is only what cria observed.

ornith1.5_9b / Java B3 (capture 20261012T044734-01a12ff0): the gate at 05:25:08 ran after the last landed
edit and no edit/write landed again for 35 calls, yet every handoff said "Re-run the check rather than
acting on whichever you saw first", and the rumination guard said "Prefer reading the current file or
rerunning the exact failing check" with the flagged source and the check both in the window.

cria's own bookkeeping (the write registry, filled from its outbound completions) knows whether any
edit/write tool call has been forwarded since the gate. It says nothing about the disk: a shell command
may have changed files, and the wording says so."""
import json
import re
import unittest
from types import SimpleNamespace

from cria import bodykeys, loop, prompts, selfcompact, server

MAIN_STALE = (
    "\nWhen this handoff was written you had run {n} of your own commands since that check. If one of "
    "them shows something different — a build that now succeeds, a test that now passes — your own "
    "newer result is the current state and this block is not — and so is anything you have run since "
    "this handoff. Re-run the check rather than acting on whichever you saw first.")

ABS = "/w/src/main/java/pipeline/Importer.java"
FLAG = ("[GROUND TRUTH — the repo's own checks fail] The failures:\n"
        f"$ mvn -q compile — {ABS}:203: cannot find symbol\n"
        "symbol:   variable results\n"
        f"  • {ABS}:203: cannot find symbol")


class _Log:
    def emit(self, *a, **k):
        pass


def forward(s, name, args, cid):
    coder = {"choices": [{"message": {"tool_calls": [
        {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}}]}
    loop.guard_track_refusals(s, coder, _Log(), step=1, messages=[])
    loop.guard_track_write_streak(s, coder, _Log(), step=1, messages=[])


def session(calls_before=2, calls_after=3, flag=FLAG):
    s = loop.PlanSession(plan=[])
    for i in range(calls_before):
        forward(s, "read_file", {"path": "a.java"}, f"b{i}")
    loop.track_gate_progress(s, flag, [])
    for i in range(calls_after):
        forward(s, "read_file", {"path": "a.java"}, f"a{i}")
    return s


def note(s):
    srv = SimpleNamespace(loop=SimpleNamespace(_store={"k": s}))
    return server._last_checks_note(srv, "k")


class TheHandoffClaimsOnlyWhatCriaObserved(unittest.TestCase):
    def test_no_edit_since_the_gate_gets_the_conditional(self):
        n = note(session())
        self.assertIn("none of your file edit/write tool calls had landed", n)
        self.assertIn("Unless you changed files some other way", n)
        self.assertNotIn("Re-run the check", n)
        self.assertNotRegex(n.lower(), r"\bcria\b")

    def test_an_edit_landing_after_the_gate_restores_todays_wording_exactly(self):
        s = session()
        forward(s, "write_file", {"path": "src/A.java", "content": "x"}, "w1")
        n = note(s)
        self.assertIn(MAIN_STALE.format(n=4).strip(), n)
        self.assertNotIn("none of your file", n)

    def test_a_native_apply_patch_counts_as_an_edit(self):
        s = session()
        forward(s, "apply_patch", {"input": "*** Begin Patch\n*** Update File: src/A.java\n@@\n-a\n+b\n*** End Patch"}, "p1")
        self.assertIn("Re-run the check", note(s))

    def test_an_edit_before_the_gate_does_not_count(self):
        s = loop.PlanSession(plan=[])
        forward(s, "edit_file", {"path": "src/A.java", "old_string": "a", "new_string": "b"}, "e0")
        loop.track_gate_progress(s, FLAG, [])
        for i in range(3):
            forward(s, "read_file", {"path": "a.java"}, f"r{i}")
        self.assertTrue(loop.gate_unedited(s))
        self.assertNotIn("Re-run the check", note(s))

    def test_a_write_known_not_to_have_run_does_not_count(self):
        s = session()
        forward(s, "write_file", {"path": "src/A.java", "content": "x"}, "w1")
        s.refused_write_ids = {"w1"}
        self.assertTrue(loop.gate_unedited(s))

    def test_a_shell_redirect_counts_as_a_write(self):
        s = session()
        forward(s, "exec_command", {"cmd": "echo hi > src/A.java"}, "sh1")
        self.assertFalse(loop.gate_unedited(s))

    def test_cria_cannot_tell_without_live_bookkeeping(self):
        s = session()
        s.gate_write_mark = None                      # e.g. a session restored without the registry
        self.assertIn("Re-run the check", note(s))
        t = loop.PlanSession(plan=[])                 # the write tracker never ran (assists off)
        t.action_seq = 1
        loop.track_gate_progress(t, FLAG, [])
        t.action_seq = 6
        self.assertFalse(loop.gate_unedited(t))
        self.assertIn("Re-run the check", note(t))
        s2 = session(); s2.write_call_ids = []        # a registry that lost entries
        s2.gate_write_mark = 3
        self.assertFalse(loop.gate_unedited(s2))

    def test_the_newer_own_run_fact_is_kept(self):
        s = session()
        s.own_check_runs = [(s.last_gate_seq + 1, ["mvn -q compile"], 0)]
        n = note(s)
        self.assertIn("none of your file edit/write tool calls", n)
        self.assertIn("`mvn -q compile`", n)

    def test_a_young_check_gets_neither(self):
        n = note(session(calls_after=1))
        self.assertNotIn("Re-run", n)
        self.assertNotIn("none of your file", n)

    def test_the_writer_input_decides_with_the_same_value(self):
        s = session()
        known = selfcompact.checks_input(FLAG, loop.gate_age(s))
        self.assertIn("none of the coder's file edit/write tool calls had landed", known)
        forward(s, "write_file", {"path": "src/A.java", "content": "x"}, "w1")
        edited = selfcompact.checks_input(FLAG, loop.gate_age(s))
        self.assertEqual(edited, selfcompact.checks_input(FLAG, int(loop.gate_age(s))))
        self.assertNotIn("none of the coder's", edited)
        self.assertIn("so the transcript may hold a newer one", edited)


def read_msgs(path, start=None, end=None, body="203: int x = results.size();\n204: y\n", cid="r1"):
    args = {"path": path}
    if start:
        args["start_line"], args["end_line"] = start, end
    return [{"role": "assistant", "tool_calls": [{"id": cid, "type": "function", "function": {
                "name": "read_file", "arguments": json.dumps(args)}}]},
            {"role": "tool", "tool_call_id": cid, "content": body}]


REL = "src/main/java/pipeline/Importer.java"
MAIN_GUARD = '[RUMINATION GUARD] Your last reasoning pass hit {{HITS}} second-guessing phrases ("actually", "wait", "let me reconsider", etc.) after ~{{TOKENS}} reasoning tokens and was aborted before it produced any output.\n\nNone of that reasoning survived, but the task and tool evidence above did. Continue from that evidence and take the smallest grounded next step as a single tool call. Prefer reading the current file or rerunning the exact failing check over reconstructing or replacing a file from memory. If what you are circling is an unread external fact, obtain it with a tool before proposing a change.'
MAIN_GUARD_LENGTH = '[REASONING GUARD] Your last turn was stopped: it spent about {{TOKENS}} tokens reasoning and had not produced a tool call or an answer, so it was cut here — on this side of the model — before it ran out of room on its own.\n\nNone of that reasoning survived, but the task and tool evidence above did. Continue from that evidence and take the smallest grounded next step as a single tool call. Prefer reading the current file or rerunning the exact failing check over reconstructing or replacing a file from memory. If the missing fact concerns an external library or service, obtain it with a tool before proposing a change.'
MAIN_STEP = "Prefer reading the current file or rerunning the exact failing check over reconstructing or replacing a file from memory."


class TheRuminationStepIsGroundedOnlyWhenItIsTrue(unittest.TestCase):
    def setUp(self):
        self.s = session()
        self.s.workspace_root = "/w"

    def step(self, msgs):
        return loop.grounded_rumination_step(self.s, msgs)

    def test_fires_on_a_read_of_that_path_covering_the_line(self):
        out = self.step(read_msgs(REL, 180, 230, body="\n".join(f"{i}: l{i}" for i in range(180, 231))))
        self.assertIn(f"$ mvn -q compile — {ABS}:203: cannot find symbol", out)   # the checker's own line, verbatim
        self.assertIn(f"`{REL}`", out)
        self.assertIn("line 203", out)
        self.assertNotRegex(out.lower(), r"\bcria\b")

    def test_a_whole_read_counts_when_it_returned_that_many_lines(self):
        out = self.step(read_msgs(REL, body="\n".join(f"l{i}" for i in range(1, 260))))
        self.assertTrue(out)
        self.assertEqual(self.step(read_msgs(REL, body="\n".join(f"l{i}" for i in range(1, 50)))), "")

    def test_an_unrelated_file_carrying_the_same_line_is_not_that_file(self):
        self.assertEqual(self.step(read_msgs("src/main/java/pipeline/Unrelated.java", 180, 230,
                                             body="\n".join(f"{i}: int x = results.size();" for i in range(180, 231)))), "")
        # …nor the check's own text quoted in some other tool result
        self.assertEqual(self.step(read_msgs("pom.xml", 1, 3, body=f"1: {ABS}:203: cannot find symbol\n2: a\n3: b")), "")

    def test_a_window_that_misses_the_line_does_not_count(self):
        self.assertEqual(self.step(read_msgs(REL, 1, 20, body="\n".join(f"{i}: l" for i in range(1, 21)))), "")

    def test_a_write_to_the_path_after_the_read_defeats_it(self):
        msgs = read_msgs(REL, 180, 230, body="\n".join(f"{i}: l" for i in range(180, 231)))
        msgs.append({"role": "assistant", "tool_calls": [{"id": "p", "type": "function", "function": {
            "name": "apply_patch", "arguments": json.dumps({"input": f"*** Begin Patch\n*** Update File: {REL}\n@@\n-a\n+b\n*** End Patch"})}}]})
        self.assertEqual(self.step(msgs), "")

    def test_an_edit_since_the_gate_or_a_green_gate_defeats_it(self):
        msgs = read_msgs(REL, 180, 230, body="\n".join(f"{i}: l" for i in range(180, 231)))
        forward(self.s, "write_file", {"path": "other.txt", "content": "x"}, "w")
        self.assertEqual(self.step(msgs), "")
        t = session(flag="")
        t.workspace_root = "/w"
        self.assertEqual(loop.grounded_rumination_step(t, msgs), "")

    def test_no_file_line_in_the_check_means_default(self):
        s = session(flag="[GROUND TRUTH] tests failed: 2 failed")
        self.assertEqual(loop.grounded_rumination_step(s, read_msgs(REL, 1, 400, body="1: a")), "")

    def _guard(self, gs, msgs, arm=None):
        ruminating = {"choices": [{"index": 0, "finish_reason": "rumination", "message": {"role": "assistant", "content": ""}}],
                      bodykeys.RUMINATION: {"hits": 9, "reasoning_tokens": 8000, **({"arm": arm} if arm else {})}}
        sent = []

        def chat(body, rlog):
            sent.append(body)
            return json.dumps({"choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}]}).encode()
        loop.guard_rumination(ruminating, {"messages": msgs, "tools": []}, chat, _Log(), gs=gs)
        return sent[0]["messages"][-1]["content"]

    def test_the_guard_swaps_only_the_clause(self):
        msgs = read_msgs(REL, 180, 230, body="\n".join(f"{i}: l" for i in range(180, 231)))
        for arm in (None, "length"):
            text = self._guard(self.s, msgs, arm)
            self.assertNotIn(MAIN_STEP, text)
            self.assertIn("smallest grounded step is an edit", text)
            self.assertIn("If what you are circling", text) if arm is None else None

    def test_default_guard_text_is_byte_identical(self):
        main, main_len = MAIN_GUARD, MAIN_GUARD_LENGTH   # verbatim from origin/main before the clause became a fragment
        self.assertEqual(prompts.render("rumination_guard", hits=9, tokens=8000), prompts.fill(main, hits=9, tokens=8000))
        self.assertEqual(prompts.render("rumination_guard_length", tokens=8000), prompts.fill(main_len, tokens=8000))
        msgs = read_msgs(REL, 1, 3, body="1: a")            # nothing grounds → the guard sends the default
        self.assertEqual(self._guard(self.s, msgs), prompts.fill(main, hits=9, tokens=8000))
        self.assertEqual(self._guard(None, msgs), prompts.fill(main, hits=9, tokens=8000))


if __name__ == "__main__":
    unittest.main()
