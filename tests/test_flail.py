"""The quiet-flail steer is GONE. This file records why, so it does not come back.

Operator, 2026-08-13: *"I don't like that word list thing. It should be removed. The whole steer."*

WHAT IT WAS. cria kept the coder's last four private reasoning blocks and searched them for struggle
vocabulary — `fail`, `error`, `wrong`, `still`, `again`, `tried`, `mistake`, and twenty more. Two of
four matching spent a reasoner call asking "is this coder stuck?", and any directive that came back
was injected as ⟦ctx:steer⟧.

WHY THE INSTRUMENT WAS WRONG, not merely mistuned:

  * It read words the coder did not choose. Quoting the pinned task back to itself scored as
    struggling — two of the nine fires the walk could check matched only on task-copied spans.
  * It fired on healthy work: a 53% arm rate on one task, and half the fires that reached the
    reasoner came back ON_TRACK. Nine of nine fires that could be checked were on coders making
    real progress.
  * When it fired wrongly the author still had to say something. qwen35/node 0030 — cria's own
    trigger text: "Its recent private reasoning (below) looks like it may be circling on a failure,
    while no check is currently steering it." The directive that came out: "fix the CLI to output
    \"Invalid handle\" when the handle doesn't contain a dot, as the tests expect" — a requirement
    nobody had asked for, which the coder then built.
  * Tuning it is the tell (#4, and #9's corollary). A rule that needs an exception list should have
    been a question, and the word list IS the exception list.

REMOVED, NOT REPLACED. The obvious replacement — "no bytes changed on disk across N drives" — has
never been measured as a stuck signal, and a genuinely stuck coder often does keep varying its
actions. Swapping one unmeasured trigger for another is how four revisions of a similar rule each
cost a run (#15). The safe direction is REMOVE (#1).

WHAT STILL CATCHES A REAL STALL, none of it vocabulary-based: the completion gate running the repo's
own checks, the repetition guard fingerprinting tool calls and arguments, the wheel-spin probe
reading the file's real bytes, the periodic satisfaction check, and the coder's own checks.
"""

import inspect
import unittest

from cria import loop


class TheWordListIsGoneTests(unittest.TestCase):
    def test_no_struggle_vocabulary_remains(self):
        self.assertFalse(hasattr(loop, "_STRUGGLE_RE"))

    def test_no_trigger_remains(self):
        for name in ("_flail_candidate", "author_flail_steer", "_minus_task_spans",
                     "_record_reasoning"):
            with self.subTest(name=name):
                self.assertFalse(hasattr(loop, name))

    def test_no_constants_remain(self):
        for name in ("FLAIL_WINDOW", "FLAIL_MIN_STRUGGLING", "FLAIL_COOLDOWN",
                     "MAX_FLAIL_STEERS_PER_STEP"):
            with self.subTest(name=name):
                self.assertFalse(hasattr(loop, name))

    def test_the_driver_no_longer_calls_it(self):
        self.assertFalse(hasattr(loop.Loop, "_flail_steer_if_circling"))

    def test_the_reasoning_window_is_gone_too(self):
        """Nothing else ever read it; keeping a field written and never read is dead weight.

        The removal left a tail: `author_steer` kept a `reasoning_window=` parameter and a five-line
        prompt section fed by it, so every real steer carried the header, the authority-list entry
        telling the author how to weigh it, and the words "(not captured for this trigger)". No
        production caller had passed one since the producer was deleted."""
        self.assertNotIn("recent_reasoning", inspect.getsource(loop))
        # CODE only — the comment above author_steer quotes the removed parameter on purpose, to
        # record what it was and why it went.
        code = [ln for ln in inspect.getsource(loop).splitlines()
                if not ln.lstrip().startswith("#")]
        self.assertFalse([ln for ln in code if "reasoning_window" in ln])
        from cria import prompts
        self.assertNotIn("{{REASONING}}", prompts.load("steer_diagnose_user"))

    def test_the_trigger_has_no_prompt_line_left(self):
        """A condition with no trigger would render an empty steer preamble."""
        self.assertNotIn('"flail"', inspect.getsource(loop))


class WhatSurvivesTests(unittest.TestCase):
    def test_reasoning_of_stays(self):
        """The answer-contradicts-thinking rescue and the captures both read it."""
        self.assertEqual(loop._reasoning_of(
            {"choices": [{"message": {"reasoning_content": "hi"}}]}), "hi")

    def test_it_still_falls_back_to_content(self):
        """Principle 19: a model that inlines its thinking must not be invisible."""
        self.assertEqual(loop._reasoning_of(
            {"choices": [{"message": {"content": "inlined thinking"}}]}), "inlined thinking")

    def test_the_reasoning_channel_wins_when_both_are_present(self):
        self.assertEqual(loop._reasoning_of(
            {"choices": [{"message": {"reasoning_content": "R", "content": "C"}}]}), "R")

    def test_the_structural_rescue_is_untouched(self):
        """Its trigger is a verdict the reply's own thinking denies — a fact, not a vocabulary."""
        self.assertTrue(callable(loop._steer_from_reasoning))

    def test_the_other_stall_detectors_are_untouched(self):
        for name in ("guard_probe_steer", "track_gate_progress", "author_steer"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(loop, name))
