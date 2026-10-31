"""cria offered a model minitest's own source as "the program this project has".

`shipping-rates-rb x gemma4` 1787037372. Its whole answer to the exec-intent prompt's heading
"PROGRAMS THAT ACTUALLY EXIST IN THE PROJECT DIRECTORY RIGHT NOW" was two files belonging to a gem
the model had just vendored:

    vendor/bundle/ruby/3.2.0/gems/minitest-6.0.6/lib/minitest/complete.rb
    vendor/bundle/ruby/3.2.0/gems/minitest-6.0.6/lib/minitest/find_minimal_combination.rb

The same prompt then tells the judge the command "must run something this project actually has: a
file from the list, spelled exactly as it appears there". So cria invited it to run minitest's
internals as the delivered program (#5b; #11b names this exact shape — a workspace reader cannot
judge third-party source).

ONE READER OUT OF STEP, NOT A MISSING RULE. `entrypoints` prunes on `BUILD_ARTIFACT_DIRS`, which is
keyed on directory NAMES and deliberately does not contain `vendor` — a PHP or vendored-Go repo
keeps real deliverables there, and `test_vendor_itself_is_still_not_a_build_artifact_dir` pins that.
An install destination is a relative PATH instead, which is why `INSTALL_PREFIXES` exists and why
the workspace inventory already folds it. This walk was the one reader that did not consult it.
"""

import pathlib
import tempfile
import unittest

from cria import execcheck, groundtruth


class _Project:
    def __init__(self, files):
        self.files = files

    def __enter__(self):
        self._d = tempfile.TemporaryDirectory()
        root = pathlib.Path(self._d.name)
        for rel, body in self.files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body)
        return str(root)

    def __exit__(self, *a):
        self._d.cleanup()
        return False


GEM_ENTRY = "#!/usr/bin/env ruby\nif __FILE__ == $0\n  puts 'x'\nend\n"


class TheVendoredTreeIsNotOursTests(unittest.TestCase):
    def test_the_measured_workspace(self):
        with _Project({
            "Gemfile": "source 'https://rubygems.org'\n",
            "lib/shipping/rates.rb": "module Shipping\nend\n",
            "vendor/bundle/ruby/3.2.0/gems/minitest-6.0.6/lib/minitest/complete.rb": GEM_ENTRY,
        }) as root:
            self.assertEqual(execcheck.entrypoints(root), [])

    def test_the_real_workspace_if_it_survived(self):
        d = pathlib.Path("/home/jesse/src/cria-shepherd/runs/"
                         "suite-shipping-rates-rb_gemma4_codex_poff_1787037372-lb_fk7c_")
        if not d.is_dir():
            self.skipTest("the walked workspace has been cleaned up")
        self.assertEqual(execcheck.entrypoints(str(d)), [])

    def test_it_is_keyed_on_the_path_not_the_directory_name(self):
        """`vendor/` alone is a real place to keep deliverables and must still be walked — which is
        why the rule cannot be a basename."""
        with _Project({"vendor/mytool/main.go":
                       "package main\n\nfunc main() {}\n"}) as root:
            self.assertIn("vendor/mytool/main.go", execcheck.entrypoints(root))

    def test_the_projects_own_program_still_survives(self):
        with _Project({
            "src/main.rs": "fn main() { println!(\"x\"); }\n",
            "vendor/bundle/ruby/3.2.0/gems/rake-13/lib/rake.rb": GEM_ENTRY,
        }) as root:
            self.assertEqual(execcheck.entrypoints(root), ["src/main.rs"])


class OneOwnerForWhatAnInstallLooksLikeTests(unittest.TestCase):
    def test_it_reuses_the_list_the_inventory_already_folds(self):
        # ONE owner, proven by identity, not by searching entrypoints' source for the name: a second
        # copy of this list is exactly how the two drifted before (see groundtruth.BUILD_ARTIFACT_DIRS's
        # own history). That entrypoints() actually CONSULTS the shared list — not just imports it
        # unused — is covered by TheVendoredTreeIsNotOursTests above (test_the_measured_workspace and
        # test_the_projects_own_program_still_survives both fail if the skip is removed).
        self.assertIs(execcheck._SKIP_PREFIXES, groundtruth.INSTALL_PREFIXES)

    def test_vendor_is_still_not_a_build_artifact_dir(self):
        """Pinned in two files now: reverting it hides a deliverable in a vendored repo."""
        self.assertNotIn("vendor", groundtruth.BUILD_ARTIFACT_DIRS)


if __name__ == "__main__":
    unittest.main()
