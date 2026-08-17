"""A project whose entry point is a RUNNER, not a file, must not be refused for having no file.

`corroborate` answers "did the delivered program actually run?". Two of its arms disagreed about
what an entry point is. `entrypoints()` looks for a file by each language's convention — `main.go`,
`src/main.rs`, an `if __name__` guard. `_PROJECT_RUNNERS` exists because for `go test`, `cargo run`
and `mvn exec:java` the target is the whole project and any filename on the line is an INPUT, so
asking whether "go test" is a file on disk can only ever answer no.

The file test used to run FIRST and return, so the branch written for runners never got asked. A
library-shaped project — the common shape in Go, Rust, Maven and npm — was told "no file in the
workspace is an entry point by its language's convention" while its own manifest declared the
command that had just run successfully. That reaches the completion judge as cria's own voice, and
the coder reads it as a fact about its workspace (#5b): one run answered "The context says tests are
not running and cargo run is not an entry point. Let me check the actual state of the workspace" —
after it had run both.

The manifest is consulted first now, and the file test only decides the case the runner branch does
not claim.
"""

import unittest

from cria import execcheck


GO_MOD = "module cartsvc\n\ngo 1.22\n"


class TheRunnerBranchAnswersFirstTests(unittest.TestCase):
    def _go_project(self, tmp):
        (tmp / "go.mod").write_text(GO_MOD)
        (tmp / "cart.go").write_text("package cartsvc\n\nfunc Total() int { return 0 }\n")
        return str(tmp)

    def test_go_test_is_corroborated_with_no_entry_point_file(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as d:
            root = self._go_project(pathlib.Path(d))
            ok, why = execcheck.corroborate("go test ./...", [], execcheck.entrypoints(root), root)
            self.assertTrue(ok, why)
            self.assertEqual(why, "")

    def test_the_manifest_is_what_makes_it_true(self):
        """No manifest declaring it → still refused, and the reason names the real problem."""
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as d:
            root = str(pathlib.Path(d))
            ok, why = execcheck.corroborate("go test ./...", [], [], root)
            self.assertFalse(ok)
            self.assertIn("declares", why)

    def test_a_file_shaped_project_still_gets_the_file_answer(self):
        """The file test is not deleted — it decides the case the runner branch does not claim."""
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as d:
            root = str(pathlib.Path(d))
            ok, why = execcheck.corroborate("python3 app.py", [], [], root)
            self.assertFalse(ok)
            self.assertIn("entry point", why)


class TheRubyInstallRouteIsReachableTests(unittest.TestCase):
    """`gem_bundler` told the model how to INSTALL and not how to REACH what it installed. Every
    other route in that file carries both halves — pip names the interpreter to run, npm says the
    install is what your code will load, and `gem_direct`, two lines below, explains the load path.
    A bundler `--path` install is visible only under bundler, so a bare `ruby -Ilib` still raises
    LoadError — including for a test file the model did not write and cannot add a require to."""

    def route(self, key):
        from cria import prompts
        return prompts.load_map("install_remedy")[key]

    def test_it_says_the_install_is_only_reachable_under_bundler(self):
        text = self.route("gem_bundler").lower()
        self.assertIn("exec", text)
        self.assertTrue("plain `ruby`" in text or "without bundler" in text,
                        "the route never says a bare ruby cannot see it")

    def test_it_names_the_one_line_that_makes_it_reachable(self):
        """STATING THE CONSTRAINT IS NOT ANSWERING IT. The route said the install is reachable only
        under bundler and then offered "or make the library loadable without bundler" — a restatement
        of the problem. Cycle 4 cell 1, gemma4 on shipping-rates-rb: the gem installed correctly into
        `vendor/bundle`, the library opened `require "iso3166"`, and FOUR of five checks died on one
        `kernel_require.rb:86` LoadError because every verifier probe runs bare `ruby -Ilib`. The
        model diagnosed it in its own words — "it installed everything into vendor/bundle, but
        because I am running with ruby -Ilib -Itest, it's not looking in the bundle path" — and had
        nowhere to go. 20%, down 40.

        `require "bundler/setup"` is the answer, and it was verified by running it rather than
        recalled: a `--path vendor/bundle` install plus that one first line passes all three shapes
        the verifier uses — `ruby -Ilib -e`, `ruby -Ilib -I. <test>.rb`, and the repo-suite
        `ruby -Ilib -Itest -e`. It is a fact about bundler, named without naming any gem (#20)."""
        text = self.route("gem_bundler")
        self.assertIn('require "bundler/setup"', text)
        self.assertIn("FIRST line", text)

    def test_the_direct_route_answers_it_in_code_too(self):
        """GEM_HOME is an environment variable, and the tests that judge the deliverable are launched
        without it. The route led with the env var and mentioned `$LOAD_PATH.unshift` as an
        afterthought; the afterthought is the only half that survives a runner you do not control."""
        text = self.route("gem_direct")
        self.assertIn("$LOAD_PATH.unshift", text)
        self.assertLess(text.index("$LOAD_PATH.unshift"), text.index("GEM_HOME"),
                        "the in-code fix must lead; the env var only covers self-launched commands")

    def test_neither_route_names_a_gem(self):
        """#20: a remedy keyed to one task's library is inert on every other."""
        for key in ("gem_bundler", "gem_direct"):
            with self.subTest(route=key):
                low = self.route(key).lower()
                for gem in ("countries", "iso3166", "money", "activesupport"):
                    self.assertNotIn(gem, low)

    def test_it_names_the_binary_through_the_token_never_literally(self):
        """The token resolves to whatever this box actually has (`bundle3.2` here). A literal
        `bundle exec` would recreate the incident tests/test_install_remedy_names_the_real_binary.py
        exists for."""
        raw = self.route("gem_bundler")
        self.assertIn("{{BUNDLE}} exec", raw)
        self.assertNotIn("`bundle exec", raw)

    def test_the_sibling_route_is_unchanged(self):
        self.assertIn("GEM_HOME", self.route("gem_direct"))


if __name__ == "__main__":
    unittest.main()
