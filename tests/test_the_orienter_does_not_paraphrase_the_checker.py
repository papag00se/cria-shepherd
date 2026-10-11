"""P1 (phi4/Java A6 call 0164): the orienter paraphrased the checker into a repair plan.

When the briefing is rejected the continuation holds only re-derived ground truth (listing + the
repo's own check output). The orienter, asked to "state what has been built / what remains", could
only restate the checker in its own words — javac's "class, interface, enum, or record expected"
became "ensure Importer.java contains the appropriate declarations", and the coder wrapped the file
in an extra class (call 0165). Fixture: the real continuation message of call 0164."""

import json
import pathlib
import unittest

from cria import loop, prompts

FIX = pathlib.Path(__file__).parent / "fixtures" / "a6_call0164_continuation_dropped_prose.txt"
PARAPHRASE = ("The latest check results indicate compilation errors due to missing class, interface, "
              "enum, or record declarations. Ensure the file contains the appropriate declarations.")


class _Chat:
    def __init__(self):
        self.calls = 0

    def __call__(self, body, role):
        self.calls += 1
        return json.dumps({"choices": [{"message": {"content": PARAPHRASE}}]}).encode()


def _reanchor(continuation_text):
    from tests.test_loop import _Scripted, _done, _Rlog, _single_loop
    from cria.config import Role
    chat = _Chat()
    lp = _single_loop(_Scripted([_done()]), reasoner_chat=chat,
                      reasoner_role=Role(name="reasoner", backend="local"))
    body = {"messages": [{"role": "user", "content": continuation_text}]}
    return lp._reasoned_reanchor(body, _Rlog()), chat


class TheOrienterSkipsAGroundTruthOnlyContinuation(unittest.TestCase):
    def test_real_a6_continuation_gets_the_canned_reanchor_and_no_reasoner_call(self):
        out, chat = _reanchor(FIX.read_text())
        self.assertEqual(chat.calls, 0)
        self.assertEqual(out, prompts.load("reanchor"))
        self.assertNotIn("declarations", out)

    def test_a_continuation_with_model_prose_is_still_oriented(self):
        out, chat = _reanchor(loop.CONTINUATION_MARKER + " earlier work: the parser was built")
        self.assertEqual(chat.calls, 1)
        self.assertEqual(out, PARAPHRASE)

    def test_both_dropped_templates_carry_the_detection_lead(self):
        for name in ("compaction_reframe_dropped", "compaction_reframe_dropped_facts"):
            with self.subTest(name=name):
                self.assertIn(loop._DROPPED_PROSE_LEAD, prompts.load(name))
