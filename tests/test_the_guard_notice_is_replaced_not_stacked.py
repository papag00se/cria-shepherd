"""Three retries meant three copies of the same paragraph, and a longer prompt each time.

`shipping-rates-rb x ternary-bonsai` 1787111689 ended with four consecutive dead turns. The role in
each call header climbed — `coder-s1` → `focus1` → `focus2` → `focus3` — and every climb triggered a
full prompt re-render. Diffed, the system prompt and tool list at focus2 and focus3 are
**byte-identical**: the only thing that changed between them was one more stacked copy of

    [OUTPUT GUARD] Your last turn ran for a long time and produced nothing at all — no answer, no
    reasoning, and no readable tool call. It was stopped so the rest of the turn is not lost to it.

By the last attempt the model was reading that instruction three times over.

Repetition is not emphasis (#3). And for the two aborts that are ABOUT running out of room —
`window_exhausted` and `dead_stream` — appending makes the next attempt *more* likely to fail the
same way, which is the opposite of what a retry is for.

The notice is replaced now, not stacked: one copy, current, describing the abort that just happened.
"""

import unittest

from cria import bodykeys, loop


# Each abort has its own opening marker — that difference is deliberate (#5b), so the test asks
# about "a guard notice" rather than about one phrase.
_NOTICE_MARKS = ("[OUTPUT GUARD]", "[OUTPUT LOOP]", "[RUMINATION GUARD]")


def _is_notice(m):
    return any(mark in str(m.get("content", "")) for mark in _NOTICE_MARKS)


class _Rlog:
    phase = "coder"

    def emit(self, *a, **k):
        pass


def ruminating(kind="rumination"):
    comp = {"choices": [{"message": {"role": "assistant", "content": ""},
                         "finish_reason": "rumination"}]}
    comp[bodykeys.RUMINATION] = {kind: True} if kind != "rumination" else {"hits": 3,
                                                                          "reasoning_tokens": 2048}
    return comp


class OneNoticeAtATimeTests(unittest.TestCase):
    def _run(self, kind="rumination"):
        """Drive the guard through every retry, capturing the conversation each attempt was sent."""
        sent = []

        def chat(body, rlog):
            import json
            sent.append(list(body.get("messages") or []))
            return json.dumps(ruminating(kind)).encode()

        body = {"messages": [{"role": "user", "content": "task"}], "tools": []}
        loop.guard_rumination(ruminating(kind), body, chat, _Rlog())
        return sent

    def test_the_notice_never_accumulates(self):
        for kind in ("rumination", "dead_stream", "window_exhausted", "degenerate"):
            with self.subTest(abort=kind):
                for conv in self._run(kind):
                    guards = [m for m in conv if _is_notice(m)]
                    self.assertEqual(len(guards), 1,
                                     f"{len(guards)} stacked notices on a {kind} retry")

    def test_the_prompt_does_not_grow_with_each_attempt(self):
        """The failure this is about: for an abort that IS running out of room, a longer prompt is
        the wrong direction."""
        sizes = [sum(len(str(m.get("content", ""))) for m in conv) for conv in self._run("dead_stream")]
        self.assertGreater(len(sizes), 1, "the guard did not retry at all")
        self.assertEqual(len(set(sizes)), 1, f"prompt sizes across retries: {sizes}")

    def test_every_attempt_still_carries_a_notice(self):
        """Replacing must not mean dropping — the model is told why its turn was stopped, every time."""
        for conv in self._run():
            self.assertTrue(any(_is_notice(m) for m in conv))

    def test_the_original_conversation_is_preserved(self):
        for conv in self._run():
            self.assertEqual(conv[0], {"role": "user", "content": "task"})


class TheAbortStillNamesItselfTests(unittest.TestCase):
    def test_each_abort_gets_its_own_words(self):
        """Unchanged, and load-bearing: a dead stream produced nothing, so telling it to stop
        second-guessing would name a behaviour that did not happen (#5b)."""
        from cria import prompts
        bodies = {k: prompts.load(k) for k in
                  ("rumination_guard_window", "rumination_guard_dead_stream",
                   "rumination_guard_degenerate")}
        self.assertEqual(len(set(bodies.values())), 3)


if __name__ == "__main__":
    unittest.main()
