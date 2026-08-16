"""A package manager's install prefix is not the coder's source, and cria knows because cria chose it.

The incident (cycle 2, shipping-rates-rb x qwen35, -60 points). cria's install refusal ordered the
gem into the project directory; the workspace gained ~1,950 dependency files; `_self_compact` calls
this walker three times in one compaction. The body went out at 263,205 chars of which 168,559 - 64%
- were `vendor/bundle` lines, estimating 65,801 tokens against an n_ctx of 49,152. The server refused
it six times and the run died with two checks still red. Measured on the same body, without those
lines it estimates 23,661 tokens and fits with room to spare.

TWO DELIBERATE DECISIONS ARE NOT TOUCHED, and this file pins both:
  - `vendor` stays OUT of BUILD_ARTIFACT_DIRS - it is real source in some projects and the cost of
    being wrong is hiding a deliverable. Only the nested install prefix folds.
  - the listing stays COMPLETE - "not listed = does not exist" is the one clause that makes it
    decisive (operator's call), so the tree is FOLDED to a counted line, never dropped.
"""
from __future__ import annotations

import os
import re
import tempfile
import unittest
from pathlib import Path

from cria import groundtruth as g

REMEDY = Path(__file__).resolve().parents[1] / "cria" / "prompts" / "install_remedy.txt"


class FoldsOnlyWhatCriaPrescribed(unittest.TestCase):
    def _tree(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "vendor/bundle/gems/countries-3.1.0/lib"))
        os.makedirs(os.path.join(root, "vendor/mycompany"))
        os.makedirs(os.path.join(root, "lib/shipping"))
        for i in range(300):
            open(os.path.join(root, f"vendor/bundle/gems/countries-3.1.0/lib/f{i}.yaml"), "w").write("x")
        open(os.path.join(root, "vendor/mycompany/real_source.rb"), "w").write("committed source")
        open(os.path.join(root, "lib/shipping/rates.rb"), "w").write("the coder's work")
        return root

    def test_the_prescribed_tree_becomes_one_line(self):
        """FAILS BEFORE: 300 entries, one per gem file."""
        out = g.workspace_inventory(self._tree())
        self.assertEqual(0, out.count("countries-3.1.0/lib/f"), "the gem tree is still enumerated")
        self.assertIn("vendor/bundle/", out)
        self.assertIn("300 files", out)

    def test_committed_vendored_source_is_still_listed_file_by_file(self):
        """The reason `vendor` is deliberately not a build-artifact dir. Fold the prefix, not the name."""
        out = g.workspace_inventory(self._tree())
        self.assertIn("vendor/mycompany/real_source.rb", out)

    def test_the_coders_own_work_is_untouched(self):
        self.assertIn("lib/shipping/rates.rb", g.workspace_inventory(self._tree()))

    def test_the_completeness_clause_survives(self):
        """Folded, not dropped: the directory is still reported, so 'not listed = does not exist'
        still holds. That clause is what makes the listing decisive and it is the operator's call."""
        out = g.workspace_inventory(self._tree())
        self.assertIn("complete", out.lower())
        self.assertIn("vendor/bundle", out)

    def test_it_shrinks_the_body_by_the_measured_order(self):
        root = self._tree()
        folded = len(g.workspace_inventory(root))
        g.INSTALL_PREFIXES, saved = frozenset(), g.INSTALL_PREFIXES
        try:
            whole = len(g.workspace_inventory(root))
        finally:
            g.INSTALL_PREFIXES = saved
        self.assertLess(folded * 10, whole, f"folded {folded} vs whole {whole}")

    def test_every_flavor_folds(self):
        root = self._tree()
        for flavor in ("judge", "planner", "coder", "briefing"):
            with self.subTest(flavor=flavor):
                out = g.workspace_inventory(root, flavor=flavor)
                self.assertEqual(0, out.count("countries-3.1.0/lib/f"))
                self.assertIn("vendor/bundle", out)

    def test_a_workspace_that_is_ONLY_a_prescribed_tree_still_renders(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "vendor/bundle/gems"))
        open(os.path.join(root, "vendor/bundle/gems/a.rb"), "w").write("x")
        out = g.workspace_inventory(root)
        self.assertIn("vendor/bundle", out)
        self.assertNotIn("gems/a.rb", out)


class TheTwoListsCannotDrift(unittest.TestCase):
    """ANTI-DRIFT. Every destination cria's own refusal prescribes must be folded by one list or the
    other, or the bug returns for a different ecosystem the next time a route is added."""

    def test_every_destination_in_the_remedy_is_covered(self):
        text = REMEDY.read_text()
        # the directory each route tells the coder to install into
        dests = {d.strip("`.,;:") for d in
                 re.findall(r"(?:--path|--install-dir)\s+([\w./-]+)", text)}
        dests |= {"node_modules"} if "node_modules" in text else set()
        dests |= {".venv"} if ".venv" in text else set()
        self.assertTrue(dests, "no install destinations found in install_remedy.txt")
        for d in dests:
            with self.subTest(dest=d):
                covered = d in g.INSTALL_PREFIXES or d.split("/")[0] in g.BUILD_ARTIFACT_DIRS \
                    or d in g.BUILD_ARTIFACT_DIRS
                self.assertTrue(covered, f"{d!r} is prescribed by cria and folded by neither list")

    def test_vendor_itself_is_still_not_a_build_artifact_dir(self):
        """Pinned deliberately: reverting this hides a deliverable in a PHP or vendored-Go repo."""
        self.assertNotIn("vendor", g.BUILD_ARTIFACT_DIRS)


if __name__ == "__main__":
    unittest.main()
