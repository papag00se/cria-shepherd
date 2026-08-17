"""cria handed a judge the corpse of an aborted compactor as "the coder's action log".

Cycle 4 cell 23, `handles-cli-node × nemotron-elastic`, twice — calls 0073→0075 and 0089→0091. The
compactor's turn was killed by the rumination guard mid-reasoning, so there was no content;
`coerce_text_answer` recovered `reasoning_content`, and `summarize` returned it. What reached the
satisfaction judge in the slot where the coder's tool log belongs was the compactor talking to itself:

    We need to continue the process. The user wants a condensed log of all distinct actions and
    outcomes. We must output only the log, in same order actions happened… Then attempts to exec
    command node __tests__/lookup.end2end.test.js again, error. Then attempts to exec command node
    __tests__/lookup.end2end.test.js again, error.  (×40, then cut)

Not one real command, exit code, or error string from the session survived into it. The judge then
ruminated too and produced a list of invented actions citing `/workspace/README.md`, a path that does
not exist; `satisfaction-recover` reported that failure to the coder as a completion finding.

THE RULE ALREADY EXISTS, ONE FUNCTION OVER. `_steer_from_reasoning` refuses exactly this case, in
these words: *"A STREAM CRIA ITSELF KILLED IS NOT AN ANSWER… This ran anyway, and then cria narrated
the corpse as a decision."* It was missing from `summarize`, which is the primitive every summariser
shares — the compactor, the briefing writer, the steer author, the judges.

Failing the pass is not a loss: it fires the reasoning-off retry, which is where a summary belongs
anyway — straight into content, with no reasoning to salvage. That is the same recovery the truncation
and tool-call-answer rejections beside it already use.
"""

import json
import unittest

from cria import bodykeys, loop


class _Rlog:
    phase = "test"

    def __init__(self):
        self.events = []

    def emit(self, name, **k):
        self.events.append((name, k))

    def names(self):
        return [n for n, _ in self.events]


CORPSE = ("We need to continue the process. The user wants a condensed log of all distinct actions "
          "and outcomes. " + "Then attempts to exec command node test.js again, error. " * 40)
REAL = "read_file lookup.js; exec_command node lookup.js goose -> exit 0; edit_file package.json"


def _completion(text, *, ruminated=False, finish="stop"):
    comp = {"choices": [{"message": {"role": "assistant", "content": text},
                         "finish_reason": finish}]}
    if ruminated:
        comp[bodykeys.RUMINATION] = {"degenerate": True}
    return comp


class _Chat:
    """Returns the killed pass first, then whatever the reasoning-off retry should get."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, body, rlog):
        self.calls.append(body)
        return json.dumps(self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]).encode()


class TheCorpseIsRefusedTests(unittest.TestCase):
    def test_a_ruminated_pass_does_not_become_the_summary(self):
        rlog = _Rlog()
        chat = _Chat(_completion(CORPSE, ruminated=True), _completion(REAL))
        out = loop.summarize(chat, None, "system", "user", rlog, phase="compactor")
        self.assertEqual(out, REAL)
        self.assertNotIn("We need to continue the process", out)

    def test_the_finish_reason_spelling_is_caught_too(self):
        """The guard marks the body; the normalizer also stamps the choice. Either is the same fact."""
        rlog = _Rlog()
        chat = _Chat(_completion(CORPSE, finish="rumination"), _completion(REAL))
        self.assertEqual(loop.summarize(chat, None, "s", "u", rlog, phase="compactor"), REAL)

    def test_it_says_it_refused(self):
        """A guard that is silent when it declines cannot be told apart from one that never ran."""
        rlog = _Rlog()
        chat = _Chat(_completion(CORPSE, ruminated=True), _completion(REAL))
        loop.summarize(chat, None, "s", "u", rlog, phase="compactor")
        self.assertIn("summarize.ruminated", rlog.names())

    def test_both_passes_ruminating_yields_nothing_rather_than_the_corpse(self):
        """Fail closed: no summary is a recoverable state, a fabricated one is not."""
        rlog = _Rlog()
        chat = _Chat(_completion(CORPSE, ruminated=True))
        self.assertEqual(loop.summarize(chat, None, "s", "u", rlog, phase="compactor"), "")


class RealAnswersAreUntouchedTests(unittest.TestCase):
    def test_a_normal_reply_needs_no_retry(self):
        rlog = _Rlog()
        chat = _Chat(_completion(REAL))
        self.assertEqual(loop.summarize(chat, None, "s", "u", rlog, phase="compactor"), REAL)
        self.assertEqual(len(chat.calls), 1)
        self.assertNotIn("summarize.ruminated", rlog.names())

    def test_a_long_repetitive_but_UNKILLED_reply_still_ships(self):
        """The rule is what cria DID to the stream, not how the text reads. Only a turn cria aborted
        is refused here; judging the prose is the rumination detector's job, upstream."""
        rlog = _Rlog()
        chat = _Chat(_completion(CORPSE))
        self.assertTrue(loop.summarize(chat, None, "s", "u", rlog, phase="compactor"))


class ItIsTheSameRuleAsTheSteerPathTests(unittest.TestCase):
    def test_both_read_the_same_two_markers(self):
        import inspect
        for fn in (loop.summarize, loop._steer_from_reasoning):
            with self.subTest(fn=fn.__name__):
                src = inspect.getsource(fn)
                self.assertIn("bodykeys.RUMINATION", src)
                self.assertIn('"rumination"', src)


if __name__ == "__main__":
    unittest.main()
