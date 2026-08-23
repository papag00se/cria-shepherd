"""When the failing require resolves to the coder's own file, cria says so instead of going quiet.

`names_a_workspace_file` exists so cria never calls the project's own module a missing dependency, and
a false YES is the safe direction — silence. That is right when cria is guessing. It was not guessing:
it walked the tree and found the file.

Walked on shipping-rates-rb x nemotron-elastic 1787465385. The coder asked to write scratch to
/tmp/europe.rb; cria refused with "use a path within the project instead" and it wrote
`lib/europe.rb`. The Rakefile puts `lib` on the load path, so `require "europe"` found that file
rather than the installed gem and died on its first line, failing every test at load — including the
seven that passed at seed. cria held the answer and said nothing, and three of its own voices then
filled the gap with "the gem is not installed", which cost eight more install attempts."""
import os
import tempfile
import unittest
from pathlib import Path

from cria import probeparse, proberun, wsview
from cria.probeparse import ProbeResult
from cria.proberun import ProbeReport


class TheShadowIsNamedTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(wsview.unbind, wsview.bind(wsview.DirectView()))
        self.ws = tempfile.mkdtemp()
        Path(self.ws, "lib").mkdir()
        Path(self.ws, "lib", "europe.rb").write_text("require 'europe/version'\n")

    def _note(self, err):
        return proberun.dependency_note(
            ProbeReport(["ruby"], [], [ProbeResult("rake test", 1, err, [])]), self.ws)

    def test_it_names_the_file_the_require_actually_finds(self):
        note = self._note("cannot load such file -- europe/version (LoadError)")
        self.assertIn("lib/europe.rb", note)
        self.assertIn("resolves to", note)

    def test_it_says_the_fix_is_the_file_not_the_install(self):
        note = self._note("cannot load such file -- europe/version (LoadError)")
        self.assertIn("the fix is the file, not the install", note)

    def test_a_genuinely_missing_gem_still_gets_the_install_note(self):
        note = self._note("cannot load such file -- nowhere_at_all (LoadError)")
        self.assertNotIn("resolves to", note)

    def test_the_resolver_answers_with_the_path(self):
        self.assertEqual(probeparse.resolves_to_workspace_file("europe/version", self.ws),
                         os.path.join("lib", "europe.rb"))

    def test_it_answers_empty_when_the_tree_is_unknown(self):
        self.assertEqual(probeparse.resolves_to_workspace_file("europe", ""), "")

    def test_the_model_never_reads_the_shims_name(self):
        from cria import prompts
        self.assertNotIn("cria", prompts.load_map("dependency_note")["shadowed"].lower())


if __name__ == "__main__":
    unittest.main()
