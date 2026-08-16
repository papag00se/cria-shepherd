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

import unittest

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


class ItIsWiredIntoTheOutboundViewTests(unittest.TestCase):
    def test_the_coder_view_folds_repeats(self):
        import inspect

        from cria import loop
        src = inspect.getsource(loop._elide_ledger_copies)
        self.assertIn("fold_repeated_messages", src)
        self.assertIn("_ANCHOR_MARKERS_FOR_DEDUP", src)
        self.assertIn("context.repeat_dedup", src)

    def test_both_driver_paths_reach_it(self):
        """plan-ON and plan-off both go through _elide_ledger_copies; a fix on one path only is the
        recurring shape of this codebase's regressions."""
        import inspect

        from cria import loop
        src = inspect.getsource(loop)
        self.assertGreaterEqual(src.count("_elide_ledger_copies("), 3)  # def + both call sites

    def test_the_note_never_names_the_shim(self):
        import re
        self.assertIsNone(re.search(r"\bcria\b", NOTE, re.I))


if __name__ == "__main__":
    unittest.main()
