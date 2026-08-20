"""One owner for "is this a shell command", with a score instead of a verdict.

cria answered this question in three places and they disagreed. The gap between two of them cost a
run: on `feed-pipeline-java x qwen35` (2026-08-19) call 0270 the flail steer told the coder

    Run `cat > REVIEW.md << 'EOF'` with file name and line numbers for each issue found.

The heredoc appears nowhere the coder had written — the reasoner invented it — but `loop._CODE_LINE`
matched nothing in that string, so `_strip_invented_code` reported zero spans, so the restate path
(gated on that count) never ran, and cria delivered a shell command the coder's own system prompt
forbids it from using.

THE SEPARATION IS THE WHOLE POINT, so these tests are two lists: text that must score BELOW the
restate bar, and text that must score above it. Everything in the first list is drawn from real
steers, task text, or judge prose in the captures; everything in the second is a real command from
the same runs.

Operator, 2026-08-19: "I don't like having deterministic fuzzy code, but this one comes up enough."
The answer to that is the score being accountable — `signals()` names what fired, so a number cria
acts on can always be read back (#12).
"""

import unittest

from cria import shellshape


# Real prose from the captures: steers, task text, judge reasons, briefing lines.
PROSE = (
    "Use grep -n to find it, then read that line.",
    "It returns Some(v) if v > 0, otherwise None.",
    "Compare a.b > c.d and decide which is larger.",
    "Add a README explaining how to build (cargo run), use, and test (cargo test) the tool.",
    "Set WORKERS_ENABLED to true in the source, not on the command line.",
    "Find the bug in the parser and make it work.",
    "Move the assertions inside the if let block, or restructure to avoid binding.",
    "Fix line 78 to match the constructor signature used on line 83.",
    "Make the key lookup compile, then run the build and report what it prints.",
    "Stop rewriting Importer.java and create the missing REVIEW.md instead.",
    "Register the live marker the warning names, then re-run the tests.",
    "The awk '$3 > 100' pattern in their script is a read, not a write.",
    "REVIEW.md does not exist in the workspace (confirmed via list_dir).",
)

# Real commands from the same runs.
COMMANDS = (
    "Run `cat > REVIEW.md << 'EOF'` with file name and line numbers for each issue found.",
    "echo done > out.txt",
    "cargo test --no-fail-fast 2>&1",
    "cd /ws && git log --oneline -5 | head -n 5",
    "sed -i 's/a/b/' src/main.rs",
    "```bash\nfind . -type f -name '*.java'\n```",
    "rm -f src/main/java/pipeline/Importer.java",
    "mvn -q exec:java -Dexec.mainClass=pipeline.Importer",
    "WORKERS_ENABLED=true mvn test",
    "pip install commons-csv",
    "git checkout -- src/main/java/pipeline/Importer.java",
    "python3 -m pytest -q",
    "tee -a build.log",
)


class ProseIsNotACommandTests(unittest.TestCase):
    def test_none_of_it_reaches_the_restate_bar(self):
        for text in PROSE:
            with self.subTest(text=text[:52]):
                self.assertFalse(shellshape.looks_like_command(text),
                                 f"scored {shellshape.confidence(text)} {shellshape.signals(text)}")

    def test_an_english_word_binary_alone_says_nothing(self):
        """`find the bug`, `make it work`, `cat the file` — the words are commands and the sentences
        are not. One weak signal is prose."""
        for text in ("cat the file and tell me what it says", "ls of the directory", "echo of that"):
            with self.subTest(text=text):
                self.assertEqual(shellshape.signals(text), [])

    def test_a_bare_comparison_is_not_a_redirect(self):
        self.assertEqual(shellshape.confidence("if v > 0 then bail"), 0.0)
        self.assertEqual(shellshape.confidence("rows > 100 is the threshold"), 0.0)


class CommandsAreRecognisedTests(unittest.TestCase):
    def test_all_of_them_clear_the_restate_bar(self):
        for text in COMMANDS:
            with self.subTest(text=text[:52]):
                self.assertTrue(shellshape.looks_like_command(text),
                                f"scored {shellshape.confidence(text)} {shellshape.signals(text)}")

    def test_the_walked_heredoc_scores_near_certainty(self):
        """The one that cost the run. It should not be a marginal call."""
        text = "Run `cat > REVIEW.md << 'EOF'` with file name and line numbers for each issue found."
        self.assertGreaterEqual(shellshape.confidence(text), shellshape.REFUSE_BAR)
        self.assertIn("heredoc", shellshape.signals(text))


class TheScoreIsAccountableTests(unittest.TestCase):
    def test_it_names_what_fired(self):
        """A number with no account of itself is one cria cannot defend (#12)."""
        self.assertIn("pipe", shellshape.signals("cat x | grep y"))
        self.assertIn("chain", shellshape.signals("cd /w && ls"))

    def test_prose_names_nothing(self):
        self.assertEqual(shellshape.signals("please read the file"), [])

    def test_more_evidence_never_lowers_the_score(self):
        """Combined as independent evidence, so a new signal can only raise it."""
        base = shellshape.confidence("mvn compile")
        self.assertGreaterEqual(shellshape.confidence("mvn compile 2>&1 | tail -5"), base)

    def test_the_two_bars_are_ordered_and_the_gap_is_real(self):
        self.assertLess(shellshape.RESTATE_BAR, shellshape.REFUSE_BAR)
        top_prose = max(shellshape.confidence(t) for t in PROSE)
        low_cmd = min(shellshape.confidence(t) for t in COMMANDS)
        self.assertLess(top_prose, shellshape.RESTATE_BAR, "prose reaches the bar")
        self.assertGreater(low_cmd, shellshape.RESTATE_BAR, "a real command misses the bar")


class PerLineTests(unittest.TestCase):
    def test_it_finds_the_command_inside_a_directive(self):
        """A directive is mostly prose with a command in it; the prose is the part worth keeping."""
        d = ("The build fails on line 78.\n"
             "Fix the constructor call so both sites agree.\n"
             "mvn -q compile 2>&1 | tail -20\n")
        self.assertEqual(shellshape.command_lines(d), ["mvn -q compile 2>&1 | tail -20"])

    def test_an_all_prose_directive_yields_nothing(self):
        self.assertEqual(shellshape.command_lines("Read the file. Fix the scope. Re-run."), [])


if __name__ == "__main__":
    unittest.main()
