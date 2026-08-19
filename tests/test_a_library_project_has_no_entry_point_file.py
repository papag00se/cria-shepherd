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

# The live-execution seat this file tested was REMOVED on 2026-08-18 (operator: "drop the
# 'something needs to be ran' assertion altogether — it is more trouble than it is worth").
# The classes that exercised it are gone with it; what remains below tests mechanisms that
# outlived it. See docs/audits/finish-and-remeasure-progress.md for the reasoning.


import unittest

from cria import execcheck


GO_MOD = "module cartsvc\n\ngo 1.22\n"


class TheRubyInstallRouteIsReachableTests(unittest.TestCase):
    """`gem_bundler` told the model how to INSTALL and not how to REACH what it installed. Every
    other route in that file carries both halves — pip names the interpreter to run, npm says the
    install is what your code will load, and `gem_direct`, two lines below, explains the load path.

    AND THEN IT REACHED FOR THE WRONG HALF. From 0d2fec4 to 2026-08-18 the route told the coder to
    run `bundle install --path vendor/bundle` and then unshift
    `vendor/bundle/gems/<gem>-<version>/lib`. Bundler writes `vendor/bundle/ruby/<abi>/gems/…`;
    `vendor/bundle/gems` does not exist. Measured in a clean project:

        bundle install --path vendor/bundle   ->  vendor/bundle/ruby/3.2.0/gems/countries-8.1.0
        ls vendor/bundle/gems                 ->  No such file or directory

    That path is `gem install --install-dir`'s, i.e. the OTHER route's, where it is correct. It only
    became reachable when ruby-bundler was installed, because `dirguard._INSTALL_REMEDY` takes the
    first route whose tool is on PATH — installing an apt package flipped cria onto a route carrying
    a different route's path. Walked on `shipping-rates-rb x ternary-bonsai`: the coder pasted the
    dead path into its library file and spent the tail of the run debugging around a no-op line."""

    def route(self, key):
        from cria import prompts
        return prompts.load_map("install_remedy")[key]

    def test_it_never_names_a_directory_bundler_does_not_create(self):
        """The whole defect in one assertion. `--path vendor/bundle` produces
        `vendor/bundle/ruby/<abi>/gems/`, so any sentence naming `vendor/bundle/gems` is describing a
        tree that will not be there."""
        self.assertNotIn("vendor/bundle/gems", self.route("gem_bundler"))

    def test_it_does_not_claim_a_bare_ruby_cannot_see_the_install(self):
        """It said: "That install is reachable only under bundler — anything started as plain `ruby`
        still fails to require it." Measured, in a clean project with `require "bundler/setup"` at
        the top of the library:

            ruby -Ilib -e 'require "shipping/rates"'                    ->  true
            (cd /tmp && ruby -I$D/lib -e 'require "shipping/rates"')    ->  LoadError
            (cd /tmp && BUNDLE_GEMFILE=$D/Gemfile ruby …)               ->  true

        It works from the project directory and fails only from elsewhere. And every check in
        `suite/tasks/shipping-rates-rb/verify.py` runs `subprocess.run(cmd, cwd=ws)` — the project
        directory. The premise that "the checks that judge a library do not start where the Gemfile
        is" is false for this verifier."""
        text = self.route("gem_bundler").lower()
        self.assertNotIn("reachable only under bundler", text)
        self.assertNotIn("still fails to require it", text)

    def test_it_names_the_route_that_WAS_VERIFIED_BY_RUNNING_IT(self):
        """THE TIE-BREAK, because this file used to assert the opposite and the reversal is the
        point. `0d2fec4` demoted `require "bundler/setup"` to "the weaker version" on the strength of
        a 5/5-vs-2/5 comparison **across different runs** — and the measured noise floor at identical
        code is 25 points, more than one check. That is not evidence.

        `f2b8b5b`, later, established the opposite by running it, and its wording is still in the
        test below: `bundler/setup` "was verified by running it rather than recalled: a
        `--path vendor/bundle` install plus that one first line passes all three shapes the verifier
        uses". So the file has been asserting both conclusions at once — the invented path leading,
        the verified line demoted at the end. Running it settles it, twice now; a score delta below
        the floor settles nothing."""
        text = self.route("gem_bundler")
        self.assertIn('require "bundler/setup"', text)
        self.assertNotIn("$LOAD_PATH.unshift", text)
        self.assertNotIn("weaker version", text)

    def test_it_says_what_a_process_started_elsewhere_needs(self):
        """The one true half of the old constraint, kept — and answered rather than restated."""
        self.assertIn("BUNDLE_GEMFILE", self.route("gem_bundler"))

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
        self.assertIn("before the gem require", text)
        self.assertIn("tests and scripts you did not write", text)

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
        `bundle` command would recreate the incident
        tests/test_install_remedy_names_the_real_binary.py exists for. The route now recommends no
        `exec` at all — the remedy is a load-path line — so what is guarded is that every bundler
        COMMAND it does name goes through the token."""
        raw = self.route("gem_bundler")
        self.assertIn("{{BUNDLE}} install", raw)
        self.assertNotIn("`bundle exec", raw)
        self.assertNotIn("`bundle install", raw)

    def test_the_sibling_route_is_unchanged(self):
        self.assertIn("GEM_HOME", self.route("gem_direct"))


if __name__ == "__main__":
    unittest.main()
