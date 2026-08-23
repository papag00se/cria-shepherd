"""The post-compaction orienter was handed the ORIGINAL TASK and asked what had been built.

`_reasoned_reanchor` fires when the harness compacts the coder's history away. It asks a reasoner to
orient the coder: what already exists (so it does not re-create it) and what remains. The summary it
passed was

    summary = _history_root(body.get("messages", []))[0]

and `_history_root` returns the first user message that is not env context. Under a harness that
KEEPS its user messages — Codex does; it drops the work behind them — that message is the task. So
the reasoner received a list of REQUIREMENTS under a prompt saying "the working history was just
compacted into the summary you are given… state what has already been built", and answered the only
way that question can be answered from a task: by reading the requirements back as accomplishments,
and the not-yet-mentioned ones as remaining work.

Walked on cycle 4, feed-pipeline-java x qwen35, where it fired three times. The reasoner said so
itself — "Since the summary is not provided… I am in a bind", "If I output a message claiming I know
what was built, I am hallucinating" — and then guessed anyway. cria injected the guess as a four-item
"Remains to Fix" list whose every item was already written and passing. Call 0365 answered it with
"Let me redesign the solution", deleted `incrementSkip(parsed.reason)`, and broke
`messy_feed_handled`. The cell had been 5/5 at the fifteen-minute floor and finished 4/5.

THE SUMMARY IS THE RE-ANCHORED TURN. `reframe_compaction` tags the harness's compaction message with
CONTINUATION_MARKER before drive ever sees it, in whichever shape the harness rewrites — replaced
root or appended turn. Keying on the marker finds it in both and finds nothing when no compaction
reached this turn, which is the case that must not be asked (#11b): no summary is no grounds to say
what was built, and the canned reanchor says the true thing without claiming to know.

The prompt now also forbids filling a gap IN the summary, since a summary that omits what remains
puts the reasoner back in the same bind on a smaller scale.
"""

import json
import unittest

from cria import loop, prompts


class _Chat:
    """The reasoner transport: takes the request body, returns encoded JSON — and keeps every body it
    was handed, which is how the test reads WHAT the reasoner was shown."""

    def __init__(self, text):
        self.text = text
        self.seen = []

    def __call__(self, body, role):
        self.seen.append(body)
        return json.dumps({"choices": [{"message": {"content": self.text}}]}).encode()


def _summary_turn(text):
    return {"role": "user", "content": loop.CONTINUATION_MARKER + " " + text}


class TheOrienterReadsTheMarkedTurnTests(unittest.TestCase):
    TASK = {"role": "user", "content": "Build a feed parser. Count skipped rows. Add tests."}

    def _reanchor(self, msgs, said="Already built: X. Remains: Y."):
        from tests.test_loop import _Scripted, _done, _Rlog, _single_loop
        from cria.config import Role
        loop_ = _single_loop(_Scripted([_done()]), reasoner_chat=_Chat(said),
                             reasoner_role=Role(name="reasoner", backend="local"))
        return loop_._reasoned_reanchor({"messages": msgs}, _Rlog())

    def test_the_task_alone_is_not_a_summary(self):
        """THE REGRESSION. A conversation with a task and no compaction must not be described."""
        self.assertEqual(self._reanchor([self.TASK]), prompts.load("reanchor"))

    def test_a_real_compaction_is_oriented_from(self):
        self.assertIn("Already built", self._reanchor([self.TASK, _summary_turn("built X")]))

    def test_the_task_is_not_what_the_reasoner_reads(self):
        """It is handed the summary; being handed requirements is what produced the invention."""
        from tests.test_loop import _Scripted, _done, _Rlog, _single_loop
        from cria.config import Role
        chat = _Chat("Already built: X.")
        _single_loop(_Scripted([_done()]), reasoner_chat=chat,
                     reasoner_role=Role(name="reasoner", backend="local"))._reasoned_reanchor(
            {"messages": [self.TASK, _summary_turn("built the parser")]}, _Rlog())
        sent = repr(chat.seen)
        self.assertIn("built the parser", sent)
        self.assertNotIn("Build a feed parser", sent)

    def test_it_reads_the_newest_marked_turn(self):
        """A long session compacts more than once; the stale summary must not win. Two marked turns
        in one history — the reasoner must be shown the SECOND (newest), never the first."""
        from tests.test_loop import _Scripted, _done, _Rlog, _single_loop
        from cria.config import Role
        chat = _Chat("Already built: X.")
        msgs = [self.TASK, _summary_turn("built the parser (first compaction)"),
               {"role": "assistant", "content": "did more work"},
               _summary_turn("built the parser AND the tests (second compaction)")]
        _single_loop(_Scripted([_done()]), reasoner_chat=chat,
                     reasoner_role=Role(name="reasoner", backend="local"))._reasoned_reanchor(
            {"messages": msgs}, _Rlog())
        sent = repr(chat.seen)
        self.assertIn("second compaction", sent)
        self.assertNotIn("first compaction", sent)


class ThePromptForbidsInventingTests(unittest.TestCase):
    BODY = prompts.load("reanchor_reasoned")

    def test_it_may_say_only_what_it_was_given(self):
        """The seat is now given the summary AND the workspace listing — the same fix its sibling,
        the self-compaction briefing writer, already had. The rule names both sources, because a
        file the disk listing names IS grounded and refusing it would punish the seat for using the
        fact cria just handed it."""
        self.assertIn("Say ONLY what the summary and the file listing beneath it state", self.BODY)
        self.assertIn("neither the summary nor the file listing already names", self.BODY)

    def test_a_missing_answer_is_disclosed_not_guessed(self):
        self.assertIn("Never fill either gap with a guess", self.BODY)

    def test_it_says_why_the_guess_is_harmful(self):
        """The reason is the measured outcome, so the rule reads as a consequence, not a style note."""
        self.assertIn("already done", self.BODY)

    def test_it_still_asks_for_the_orientation(self):
        """The mechanism's whole value — a weak model disowning its own work — is unchanged."""
        for phrase in ("what has already been built", "INSPECT the existing files"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.BODY)

    def test_it_may_not_name_a_new_artifact_or_say_start_over(self):
        """Walked on cycle 4 cell 24 (`rust-toml-cli x nemotron-elastic`). Handed the task instead of
        a summary, the orienter answered "Start a new binary Cargo project named `toml-dotted-key`" —
        a name the task never used, over a crate already on disk called `dotkey-toml`. The coder
        obeyed and rewrote Cargo.toml without its `[package]` header and with `[bin]` for `[[bin]]`,
        undoing two fixes it had earned 35 calls earlier. cria contradicted itself in the same
        prompt: the continuation block beside the steer said "Do NOT recreate files or restart work
        that is already done" and listed the real files."""
        for phrase in ("never name a project", "never tell the coder to start over"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.BODY.lower())

    def test_the_prompt_never_names_the_shim(self):
        import re
        self.assertIsNone(re.search(r"\bcria\b", self.BODY, re.I))


class TheCannedTextIsTheAbstentionTests(unittest.TestCase):
    def test_it_claims_no_knowledge_of_what_was_built(self):
        """What cria says when it cannot orient must not itself assert an orientation."""
        canned = prompts.load("reanchor")
        self.assertNotIn("already built", canned)
        self.assertNotIn("remains", canned)



class TheOrienterIsGivenTheDiskTests(unittest.TestCase):
    """The one seat asked point-blank "state what has already been built" was shown no workspace.

    Its sibling — the self-compaction briefing writer — was given this exact fix, and its comment
    says why: *"This inventory was already gathered on the line below, but only to CORRECT the
    briefing after the fact. The writer never saw it and invented files that never existed. Same
    fact, given before the question."* This seat never got it, while `sess.workspace_root` was in
    scope at the call site.

    Measured over 136 real answers: 22 (16%) name a file path absent from their input, and replaying
    both of the seat's guards over the 126 non-empty ones discards 36 — **29%** of a full model call
    each, thrown away on the seat withheld the fact it invents.

    The listing is also what makes the answer useful: the prompt's own instruction is "tell it to
    INSPECT the existing files on disk", which cria can simply show.
    """

    def _seat(self, tree, answer):
        import json
        import types
        from cria import wsview
        from cria.config import Role

        class _Chat:
            def __init__(self):
                self.seen = []

            def __call__(self, body, rlog):
                self.seen.append(body)
                return json.dumps({"choices": [{"message": {"role": "assistant",
                                                            "content": answer}}]}).encode()

        from tests.test_loop import _Rlog
        chat = _Chat()
        lp = loop.Loop.__new__(loop.Loop)
        lp._ctx = types.SimpleNamespace(reasoner_chat=chat,
                                        reasoner_role=Role(name="reasoner", backend="local"))
        view = wsview.View("/ws", "s")
        view._ingest_tree(tree, complete=True)
        self.addCleanup(wsview.unbind, wsview.bind(view))
        body = {"messages": [{"role": "user",
                              "content": loop.CONTINUATION_MARKER + " earlier work: the gem was added"}]}
        return lp._reasoned_reanchor(body, _Rlog(), "/ws"), json.dumps(chat.seen)

    TREE = "D\t\nD\tlib\nD\tlib/shipping\nF\t5\t300\tlib/shipping/rates.rb\n"

    def test_the_listing_reaches_the_seat(self):
        _out, sent = self._seat(self.TREE, "anything")
        self.assertIn("rates.rb", sent)

    def test_a_file_the_listing_names_is_not_refused_as_invented(self):
        """The guard is grounded against BOTH sources — refusing a name cria just handed over would
        be the guard punishing the seat for using it."""
        out, _ = self._seat(self.TREE,
                            "You have built lib/shipping/rates.rb. Remaining: the EU zone lookup. "
                            "Inspect the files on disk before creating anything.")
        self.assertTrue(out.startswith("You have built"), out[:80])

    def test_a_file_neither_source_names_is_still_refused(self):
        out, _ = self._seat(self.TREE,
                            "You have built lib/shipping.rb. Remaining: nothing. Inspect first.")
        self.assertEqual(out, prompts.load("reanchor"))


if __name__ == "__main__":
    unittest.main()
