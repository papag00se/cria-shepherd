"""C38 / #11b: "no command to run them was found" is a false fact when cria simply has not been
TOLD the declared manifest's contents yet.

``probediscovery.tests_with_no_command`` fires whenever a project has discoverable test files but no
Test probe was composed this round. A `Rakefile` that EXISTS but whose BODY has not round-tripped
yet is not a project with no runner — it is a project cria has not finished asking about — and the
two must not share a sentence (see the diagnosis's step 2: Ruby's zero-config floor is deliberately
suppressed by a config's mere PRESENCE, so a body-unknown Rakefile yields the absence sentence AND
no floor probe, i.e. a project the coder is falsely told has no test command at all)."""

import unittest
from pathlib import Path

from cria import probediscovery, wsview
from tests.wsfixture import survey

ROOT = "/workspace"


def _bind_tree(tree_lines: list[str]):
    view = wsview.View(ROOT, "")
    tok = wsview.bind(view)
    assert wsview.apply_survey(view, survey("\n".join(tree_lines), root=ROOT))
    return tok


class TheAbsenceSentenceRespectsAnUnreadManifestTests(unittest.TestCase):
    def test_a_declared_but_unread_rakefile_gets_the_unknown_sentence_not_the_absence_one(self):
        tok = _bind_tree(["F\t1\t80\tRakefile", "F\t1\t10\ttest/test_rates.rb", "D\ttest"])
        self.addCleanup(wsview.unbind, tok)

        self.assertIsNone(wsview.current().read(Path(ROOT) / "Rakefile"))  # body genuinely unknown

        out = probediscovery.tests_with_no_command(Path(ROOT))
        joined = " ".join(out)
        self.assertTrue(out, "cria could not read the Rakefile and must say something about that")
        self.assertNotIn("no command to run them was found", joined)
        self.assertIn("Rakefile", joined)

    def test_a_project_with_genuinely_no_runner_still_gets_the_absence_sentence(self):
        tok = _bind_tree(["F\t1\t10\ttest/test_rates.rb", "D\ttest"])   # no Rakefile/Gemfile/.rspec at all
        self.addCleanup(wsview.unbind, tok)

        out = probediscovery.tests_with_no_command(Path(ROOT))
        self.assertTrue(any("no command to run them was found" in s for s in out))

    def test_once_the_body_arrives_the_sentence_disappears_and_the_real_probe_takes_over(self):
        import base64
        rakefile = (
            'require "rake/testtask"\n'
            'Rake::TestTask.new(:test) do |t|\n'
            '  t.test_files = FileList["test/**/test_*.rb"]\n'
            'end\n'
            'task default: :test\n'
        )
        tree = ["F\t1\t{}\tRakefile".format(len(rakefile)), "F\t1\t10\ttest/test_rates.rb", "D\ttest"]
        view = wsview.View(ROOT, "")
        tok = wsview.bind(view)
        self.addCleanup(wsview.unbind, tok)
        self.assertTrue(wsview.apply_survey(view, survey("\n".join(tree), root=ROOT)))
        blob = ("@" + base64.b64encode(b"Rakefile").decode() + "\n"
                + base64.b64encode(rakefile.encode()).decode())
        self.assertTrue(wsview.apply_survey(view, survey("\n".join(tree), root=ROOT, blob=blob)))

        cands = probediscovery.discover(Path(ROOT))
        self.assertTrue(any(c.kind is probediscovery.ProbeKind.Test for c in cands))
        # `probegate.plan_gate` only consults `tests_with_no_command` when NO Test probe was
        # composed (probegate.py) — mirrored here rather than re-implementing that gate.
        untested = ([] if any(c.kind is probediscovery.ProbeKind.Test for c in cands)
                    else probediscovery.tests_with_no_command(Path(ROOT)))
        self.assertEqual(untested, [], "a composed Test probe means there is nothing left to caveat")


if __name__ == "__main__":
    unittest.main()
