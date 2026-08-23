"""cria asked for one short directive and shipped a shell script; the coder called it "the user".

After a compaction the coder has lost its own turns and sees only a summary. A weak model in that
state disowns its earlier work and re-creates files that already exist, so cria asks a reasoner to
read the summary and write ONE short orientation — what exists, what remains, inspect before
creating. Its prompt says, in its own words: *"Output ONLY that directive to the coder — no preamble,
no meta-commentary."*

Twice on `feed-pipeline-java x qwen35` (2026-08-19, calls 0066 and 0156) it answered with fenced
bash instead, and cria injected the whole thing verbatim as `⟦ctx:steer⟧`. The coder's very next
reasoning:

    "The user is right - I need to inspect the workspace before continuing.
     Let me run the commands they suggested."

It then worked through the script command by command — roughly fourteen calls at 0067-0080 and ten
more at 0157-0167 — re-deriving facts the continuation summary two messages earlier had already
stated with file:line precision. The run held 4 of 5 deliverables at thirty minutes and finished
with 0.

THE TEST IS SHAPE, NOT SCORE, AND THAT IS MEASURED. Scoring the text and refusing above a bar
refuses **21 of the 59** captured re-orientation notes (36%) — among them "INSPECT the workspace
before creating anything…" and "You have built: - orders/app.py…", good directives that score high
only because they are full of file paths. A fenced block, or three or more independently-command
lines, fires on **2 of 59**: exactly the two failures and nothing else in the whole history.

Refusing is safe HERE, and only here, because the fallback already existed: `_reasoned_reanchor` has
always ended `return text or canned`. A compacted coder is never left without re-orientation.
"""

import json
import unittest

from cria import loop, prompts


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def kinds(self):
        return [k for k, _ in self.events]


# Verbatim from call 0066.
SCRIPT = """I need to inspect the workspace before continuing. The summary claims various states, \
but I must verify what actually exists on disk.

```bash
find . -type f -name "*.java" -o -name "*.md" | head -20
```

Then I'll check if Importer.java exists:

```bash
cat src/main/java/pipeline/Importer.java
```

```bash
mvn compile 2>&1
```
"""

GOOD = ("You already built the CSV importer in src/main/java/pipeline/Importer.java and added "
        "commons-csv to pom.xml. What remains: REVIEW.md has not been created. Inspect the files "
        "on disk before creating anything, then continue.")


def _loop_with(answer):
    from cria.config import Role
    from cria.loop import Loop, LoopContext

    def reasoner(body, rlog):
        return json.dumps({"choices": [{"message": {"content": answer}}]}).encode()

    ctx = LoopContext(planner=None, coder_chat=None, reasoner_chat=reasoner, runs_dir="")
    ctx.reasoner_role = Role(name="reasoner", backend="local")
    lp = Loop.__new__(Loop)
    lp._ctx = ctx
    return lp


# A REAL continuation summary names the files it describes — that is what a summary IS, and the
# re-orientation's prompt tells it to name nothing the summary does not. The old fixture said only
# "earlier work", so every path in a GOOD directive read as an invention.
SUMMARY = ("earlier work: the CSV importer is in src/main/java/pipeline/Importer.java, commons-csv "
           "is declared in pom.xml, the tests are run with `mvn test` and pass, and REVIEW.md has "
           "not been created yet.")


def _body(summary=SUMMARY):
    return {"messages": [{"role": "user", "content": loop.CONTINUATION_MARKER + " " + summary}]}


class AScriptIsRefusedTests(unittest.TestCase):
    def test_the_walked_answer_does_not_reach_the_coder(self):
        rlog = _Rlog()
        out = _loop_with(SCRIPT)._reasoned_reanchor(_body(), rlog)
        self.assertNotIn("```", out)
        self.assertNotIn("mvn compile", out)
        self.assertIn("loop.reanchor_refused", rlog.kinds())

    def test_the_coder_is_still_re_oriented(self):
        """Refusing must not leave a just-compacted model with nothing — that would be worse than a
        bad note. The canned reanchor was always the fallback here."""
        out = _loop_with(SCRIPT)._reasoned_reanchor(_body(), _Rlog())
        self.assertEqual(out, prompts.load("reanchor"))
        self.assertTrue(out.strip())

    def test_a_fence_alone_is_enough(self):
        rlog = _Rlog()
        out = _loop_with("Here is what to do:\n```bash\nls -la\n```")._reasoned_reanchor(
            _body(), rlog)
        self.assertIn("loop.reanchor_refused", rlog.kinds())
        self.assertEqual(out, prompts.load("reanchor"))


class AGoodDirectiveIsUntouchedTests(unittest.TestCase):
    def test_it_reaches_the_coder_verbatim(self):
        rlog = _Rlog()
        out = _loop_with(GOOD)._reasoned_reanchor(_body(), rlog)
        self.assertEqual(out, GOOD)
        self.assertNotIn("loop.reanchor_refused", rlog.kinds())

    def test_naming_ONE_command_is_not_a_script(self):
        """The seat may legitimately say how the build is run. Two is a sentence naming a command and
        then another; three is a listing."""
        one = ("The tests are run with `mvn test` and they currently pass. What remains is "
               "REVIEW.md. Inspect the files on disk before creating anything.")
        out = _loop_with(one)._reasoned_reanchor(_body(), _Rlog())
        self.assertEqual(out, one)


class TheFallbackContractIsUnchangedTests(unittest.TestCase):
    def test_no_summary_still_yields_the_canned_note(self):
        """#11b: no marked turn means no summary reached this turn, so there is nothing to describe
        and the canned reanchor says the true thing without claiming to know."""
        out = _loop_with(GOOD)._reasoned_reanchor({"messages": [{"role": "user", "content": "hi"}]},
                                                  _Rlog())
        self.assertEqual(out, prompts.load("reanchor"))

    def test_an_empty_answer_still_yields_the_canned_note(self):
        out = _loop_with("")._reasoned_reanchor(_body(), _Rlog())
        self.assertEqual(out, prompts.load("reanchor"))


class ADirectiveNamesNothingTheSummaryDoesNotTests(unittest.TestCase):
    """The prompt says "Never name a project, crate, file, module or command the summary does not
    already name" and "Never fill either gap with a guess" — in prose, to a small model, with nothing
    checking. Both walked failures are exactly that shape:

    * cart-billing-go x nemotron-elastic 1787434778 — "upgrade to a version that includes those
      methods (e.g. `v1.5.0` or later)". No version of that library has the method. It turned an
      answerable question into an unanswerable one and cost eleven calls and a `go get`.
    * shipping-rates-rb x nemotron-elastic 1787432916 — "Existing files in the workspace:
      - lib/shipping.rb". The file is lib/shipping/rates.rb. The coder read the phantom, was refused,
      and spent six of its last twenty calls finding the real path, at minute 27 of 30."""

    def test_an_invented_file_path_is_refused(self):
        out = _loop_with("Existing files in the workspace: - lib/shipping.rb. Inspect before "
                         "creating anything.")._reasoned_reanchor(_body(), _Rlog())
        self.assertNotIn("lib/shipping.rb", out)

    def test_an_invented_version_is_refused(self):
        out = _loop_with("Upgrade to a version that includes those methods (e.g. v1.5.0 or later)."
                         )._reasoned_reanchor(_body(), _Rlog())
        self.assertNotIn("v1.5.0", out)

    def test_a_shortened_path_is_still_grounded(self):
        """`Importer.java` is a substring of the path the summary names — that is a paraphrase, not
        an invention, and it must reach the coder."""
        good = "Importer.java already exists. Inspect the files on disk before creating anything."
        self.assertEqual(_loop_with(good)._reasoned_reanchor(_body(), _Rlog()), good)

    def test_the_refusal_is_logged_with_what_it_caught(self):
        rlog = _Rlog()
        _loop_with("Read lib/shipping.rb now.")._reasoned_reanchor(_body(), rlog)
        self.assertTrue(any(k == "loop.reanchor_ungrounded" for k, _ in rlog.events))


if __name__ == "__main__":
    unittest.main()
