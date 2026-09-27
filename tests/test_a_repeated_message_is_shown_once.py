"""The same payload rode the coder's prompt twice, 882 times, for 2.1 MB.

Rule 5's first exception is de-duplication: repeated content may appear once with a pointer to the
original. cria had that machinery and pointed it at ONE thing — the fetch ledger — so everything
else repeated freely.

MEASURED by replaying every captured coder prompt (6,614 of them) through the new fold:

    prompts carrying a byte-identical >=200-char user/tool payload twice   882  (13%)
    bytes removed                                                    2,088,194  (~522K tokens)

The largest groups, by what was repeated:

    352  cria's own ⟦ctx:denied⟧ refusal, re-earned verbatim
    216  a source file read twice
    130  a spec/rules file read twice
    126  cria's own ⟦ctx:edit⟧ failure directive
    150  one fetched page delivered twice

NEWEST WINS, the same rule `stub_old_write_args` and `clean_gate_results` already apply: the last
copy describes the world now. The copies here are byte-identical so nothing is lost either way, but
one rule, one direction.

AGGREGATE-LOSSLESS. n pointers plus one full copy — the coder can still see it happened n+1 times,
which is itself the signal when what repeated is a refusal it kept re-earning.

WHAT IS NEVER FOLDED: an assistant turn (the model's own words are never rewritten), a system
message (cria's frame), and any message carrying an anchor marker — an anchor block is the
designated single copy of its content and folding it at a later duplicate would move that content
out of the protected head.
"""

import json
import unittest
import unittest.mock

from cria import dedup, prompts, selfcompact
from cria.loop import _ANCHOR_MARKERS_FOR_DEDUP

NOTE = prompts.load("repeated_message_note").strip()
BIG = "package cartsvc\n\nfunc Total() int {\n\treturn 0\n}\n" + ("// filler\n" * 60)
OTHER = "def total():\n    return 0\n" + ("# filler\n" * 60)


def fold(msgs, **kw):
    kw.setdefault("protect", _ANCHOR_MARKERS_FOR_DEDUP)
    return dedup.fold_repeated_messages(msgs, NOTE, **kw)


def tool(text, i="c1"):
    return {"role": "tool", "tool_call_id": i, "content": text}


class TheNewestCopySurvivesTests(unittest.TestCase):
    def test_an_earlier_identical_payload_becomes_a_pointer(self):
        out, n = fold([tool(BIG, "a"), {"role": "assistant", "content": "thinking"}, tool(BIG, "b")])
        self.assertEqual(n, 1)
        self.assertEqual(out[0]["content"], NOTE)
        self.assertEqual(out[2]["content"], BIG)

    def test_three_copies_leave_one(self):
        out, n = fold([tool(BIG, "a"), tool(BIG, "b"), tool(BIG, "c")])
        self.assertEqual(n, 2)
        self.assertEqual([m["content"] for m in out], [NOTE, NOTE, BIG])

    def test_the_count_survives_as_pointers(self):
        """Aggregate-lossless: the coder can still see it happened three times."""
        out, _ = fold([tool(BIG, "a"), tool(BIG, "b"), tool(BIG, "c")])
        self.assertEqual(sum(1 for m in out if m["content"] == NOTE), 2)

    def test_everything_else_about_the_message_is_kept(self):
        out, _ = fold([tool(BIG, "a"), tool(BIG, "b")])
        self.assertEqual(out[0]["tool_call_id"], "a")
        self.assertEqual(out[0]["role"], "tool")

    def test_a_user_turn_folds_too(self):
        msgs = [{"role": "user", "content": BIG}, {"role": "user", "content": BIG}]
        out, n = fold(msgs)
        self.assertEqual(n, 1)
        self.assertEqual(out[1]["content"], BIG)


class WhatIsNeverFoldedTests(unittest.TestCase):
    def test_an_assistant_turn_is_never_rewritten(self):
        msgs = [{"role": "assistant", "content": BIG}, {"role": "assistant", "content": BIG}]
        out, n = fold(msgs)
        self.assertEqual(n, 0)
        self.assertIs(out, msgs)

    def test_a_system_message_is_crias_frame(self):
        msgs = [{"role": "system", "content": BIG}, {"role": "system", "content": BIG}]
        self.assertEqual(fold(msgs)[1], 0)

    def test_an_anchor_keeps_its_full_copy(self):
        """The ⟦ctx:facts⟧ / ⟦ctx:task⟧ block is the designated single copy; folding it at a later
        duplicate would move the content out of the protected head."""
        anchored = f"{selfcompact.FACTS_MARKER} the pages you fetched\n" + BIG
        out, n = fold([{"role": "user", "content": anchored}, tool(anchored)])
        self.assertEqual(n, 0)
        self.assertIn(BIG, out[0]["content"])

    def test_every_anchor_marker_is_protected(self):
        for mark in _ANCHOR_MARKERS_FOR_DEDUP:
            with self.subTest(mark=mark):
                body = f"{mark} header\n" + BIG
                self.assertEqual(fold([tool(body, "a"), tool(body, "b")])[1], 0)

    def test_the_protected_set_tracks_selfcompacts(self):
        """dedup is low-level and imports nothing, so the markers are passed in — mirrored, and this
        is the assertion that keeps the mirror honest."""
        for mark in (selfcompact.FACTS_MARKER, selfcompact.TASK_MARKER, selfcompact.SUMMARY_MARKER):
            self.assertIn(mark, _ANCHOR_MARKERS_FOR_DEDUP)

    def test_short_payloads_are_left_alone(self):
        """Below MIN_UNIT_CHARS a pointer is longer than the thing it points at."""
        msgs = [tool("ok", "a"), tool("ok", "b")]
        self.assertEqual(fold(msgs)[1], 0)

    def test_different_payloads_are_never_merged(self):
        msgs = [tool(BIG, "a"), tool(OTHER, "b")]
        out, n = fold(msgs)
        self.assertEqual(n, 0)
        self.assertIs(out, msgs, "identity when nothing matches — no needless copy")

    def test_a_payload_that_merely_CONTAINS_another_is_not_a_repeat(self):
        """Whole-message equality only. A file that grew by one line is a different file."""
        self.assertEqual(fold([tool(BIG, "a"), tool(BIG + "\n// one more\n", "b")])[1], 0)

    def test_non_string_content_is_ignored(self):
        msgs = [tool([{"type": "text", "text": BIG}], "a"), tool([{"type": "text", "text": BIG}], "b")]
        self.assertEqual(fold(msgs)[1], 0)

    def test_an_empty_list_is_fine(self):
        self.assertEqual(fold([]), ([], 0))


def call(cmd, tid):
    return {"role": "assistant", "tool_calls": [{"id": tid, "type": "function",
            "function": {"name": "exec_command", "arguments": json.dumps({"cmd": cmd})}}]}


class DifferentCommandsAreNeverPairedTests(unittest.TestCase):
    """C42, walked on cart-billing-go x nemotron-elastic 20260925T094032, coder prompt 0160: `grep
    -n "type Cart"` and `grep -n "type Item"` both matched nothing. Both got the identical
    `search_found_nothing` note appended by writeproxy, so after `volatile_key` scrubs the per-call
    envelope (Chunk ID, Wall time, token count) the two tool results were byte-identical \u2014 despite
    answering two entirely different questions. The fold pointed the Cart result at the Item result's
    body: a pointer promising "the full copy below" that did not contain the Cart answer at all, and
    the coder was left unable to confirm Cart was undefined."""

    def _empty_search_envelope(self, chunk_id):
        return (f"Chunk ID: {chunk_id}\nWall time: 0.0000 seconds\nProcess exited with code 1\n"
                "Original token count: 0\nOutput:\n\n\n" + prompts.load("search_found_nothing"))

    def test_two_different_empty_searches_are_not_folded(self):
        msgs = [call('grep -n "type Cart" cart.go', "t1"), tool(self._empty_search_envelope("6a780e"), "t1"),
                call('grep -n "type Item" cart.go', "t2"), tool(self._empty_search_envelope("aa3750"), "t2")]
        out, n = fold(msgs)
        self.assertEqual(n, 0, "two different commands must never fold into one pointer")
        self.assertNotEqual(out[1]["content"], NOTE)
        self.assertNotEqual(out[3]["content"], NOTE)

    def test_the_same_command_rerun_still_folds(self):
        """The fix must not blind the fold to a REAL repeat: the same command, run twice, is still
        one fact said twice."""
        env_a = self._empty_search_envelope("6a780e")
        env_b = self._empty_search_envelope("ffffff")  # only the per-run Chunk ID differs
        msgs = [call('grep -n "type Cart" cart.go', "t1"), tool(env_a, "t1"),
                call('grep -n "type Cart" cart.go', "t2"), tool(env_b, "t2")]
        out, n = fold(msgs)
        self.assertEqual(n, 1)
        self.assertEqual(out[1]["content"], NOTE)
        self.assertEqual(out[3]["content"], env_b)

    def test_a_user_message_with_no_command_still_folds_on_content(self):
        """Only `tool` results carry a command; a `user` turn keeps the old content-only behavior."""
        msgs = [{"role": "user", "content": BIG}, {"role": "user", "content": BIG}]
        out, n = fold(msgs)
        self.assertEqual(n, 1)


class ItIsWiredIntoTheOutboundViewTests(unittest.TestCase):
    def test_the_coder_view_folds_repeats(self):
        """Drive the real function: two byte-identical big payloads must fold to one NOTE pointer
        plus the live copy, and the fold must be reported (context.repeat_dedup) so a caller can see
        it happened."""
        from cria import loop

        class _RLog:
            def __init__(self):
                self.events = []

            def emit(self, kind, **kw):
                self.events.append((kind, kw))

        rlog = _RLog()
        out = loop._elide_ledger_copies([tool(BIG, "a"), tool(BIG, "b")], None, rlog)
        self.assertEqual(out[0]["content"], NOTE)
        self.assertEqual(out[1]["content"], BIG)
        self.assertTrue(any(k == "context.repeat_dedup" for k, _ in rlog.events))

    def test_both_driver_paths_reach_it(self):
        """plan-ON and plan-off both go through _elide_ledger_copies; a fix on one path only is the
        recurring shape of this codebase's regressions. Spy on the real function and drive both
        halves for real — a driver that dropped its call would leave that half of the pair empty."""
        from cria import loop
        from cria.loop import Loop, LoopContext, PlanSession
        from cria.plan import Plan, PlanItem

        class _RLog:
            def emit(self, *a, **kw):
                pass

        class _Planner:
            def __init__(self, plan):
                self._plan = plan

            def plan_for(self, messages, rlog, prior_work="", rewrite_summary=""):
                return self._plan

        def _plan(n):
            return Plan(id="x", task="build it", created="2026-01-01T00:00:00+00:00",
                        items=[PlanItem(f"step {i+1}") for i in range(n)])

        shell = {"type": "function", "function": {"name": "shell",
                 "parameters": {"type": "object", "properties": {"command": {"type": "array"}}}}}

        def coder(body, rlog):
            return json.dumps({"choices": [{"message": {"role": "assistant", "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "shell", "arguments": "{}"}}]}}]}).encode()

        body = {"messages": [{"role": "user", "content": "resolve a handle"}],
                "tools": [shell], "stream": True}
        pages = {"https://api.handle.me/openapi.json": (200, "/handles/{handle}")}

        calls = []

        def spy(msgs, sess, rlog=None):
            calls.append(len(msgs))
            return msgs

        with unittest.mock.patch.object(loop, "_elide_ledger_copies", spy):
            ctx = LoopContext(planner=_Planner(_plan(2)), coder_chat=coder, reasoner_chat=coder,
                              runs_dir="")
            sess = PlanSession(plan=_plan(2))
            sess.fetched_pages = pages
            Loop(ctx)._work_item(sess, "k", body, _RLog(), sess.plan.items[0], 1)

            ctx2 = LoopContext(planner=_Planner(_plan(1)), coder_chat=coder, reasoner_chat=coder,
                               planner_enabled=False, runs_dir="")
            sess2 = PlanSession(plan=_plan(1), synthetic=True)
            sess2.fetched_pages = pages
            Loop(ctx2)._drive_single_item(sess2, body, "sid:x", _RLog())

        self.assertEqual(len(calls), 2, "both plan-ON and plan-off must reach the elide step")

    def test_the_note_never_names_the_shim(self):
        import re
        self.assertIsNone(re.search(r"\bcria\b", NOTE, re.I))

    def test_the_note_asserts_the_content_is_INTACT(self):
        """A fold is a reduction the reader can see, so rule 5 requires it be LABELLED as lossless.
        The note said only that the content 'is shown once, IN FULL, further down this conversation'
        — true, and read as damage.

        Walked on shipping-rates-rb x ternary-bonsai-2 (session 01a0b68a, call 0013). The coder had
        successfully run a connectivity probe; the fold replaced the older copy, and it reasoned:
        'The earlier curl test output was cut off ("a repeat — identical content is shown once, in
        full, further down this conversation" — that's weird, looks like a glitch). Let me try again
        with a clean command.' It re-ran a command that had already answered, and the turn was lost.

        This pins the CONTRACT, not the spelling: whatever the wording, the note must state that
        nothing was removed. 'Shown once' describes cria's bookkeeping; a reader needs to know its
        evidence survived.
        """
        lowered = NOTE.lower()
        self.assertTrue(
            any(w in lowered for w in ("nothing was shortened", "nothing was cut", "nothing was lost",
                                       "not shortened", "not cut", "not truncated")),
            f"the fold note must tell the reader its content is intact; got: {NOTE!r}",
        )


if __name__ == "__main__":
    unittest.main()
