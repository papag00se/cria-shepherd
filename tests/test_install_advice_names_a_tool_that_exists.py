"""cria refused a real command and answered with an imaginary one.

When a machine-wide install is refused, cria offers the project-local route for that ecosystem. The
ruby row said:

    add the gem to a `Gemfile` and run `bundle install --path vendor/bundle`

`bundle` is not installed on the box the battery runs on. Two runs followed the advice into
`bundle: command not found` and spent the rest of the run on transport instead of the task. cria was
prescribing a tool it had never checked for — a claim about the world it could have settled with one
call to `which` (#5b).

Each ecosystem now lists its routes in preference order and each route names the tools it needs. The
first route whose tools are all present wins; when none are, the answer is empty — say what is
forbidden and stop, which is already how apt, dnf, brew and pacman are handled.

The ruby fallback also carries the sentence the failure actually needed. Installing to
`vendor/bundle` and not putting it on the load path is what destroyed a 100% ruby run: gems went in,
`require` failed, and three checks that had been passing went red.
"""

import unittest
from unittest import mock

from cria import dirguard, prompts


def _with_tools(*present):
    """Pin PATH lookups so these assertions do not depend on what this machine happens to have."""
    return mock.patch.object(dirguard, "_tool_present", lambda t: t in present)


class ARouteIsOnlyOfferedIfItsToolExistsTests(unittest.TestCase):
    def test_bundler_present_gets_the_bundler_route(self):
        with _with_tools("bundle", "gem"):
            self.assertIn("bundle install --path vendor/bundle",
                          dirguard._local_install_advice("gem install countries"))

    def test_bundler_absent_falls_to_the_route_the_box_can_take(self):
        """The measured case. bundle is not on the battery box; gem is."""
        with _with_tools("gem"):
            advice = dirguard._local_install_advice("gem install countries")
        self.assertIn("gem install --install-dir vendor/bundle", advice)
        self.assertNotIn("bundle install", advice)

    def test_neither_present_says_nothing_rather_than_guessing(self):
        with _with_tools():
            self.assertEqual(dirguard._local_install_advice("gem install countries"), "")

    def test_the_ruby_fallback_says_how_to_make_the_gem_LOADABLE(self):
        """Installing to vendor/bundle without putting it on the load path is the failure that took
        three passing checks down with it."""
        with _with_tools("gem"):
            advice = dirguard._local_install_advice("gem install countries")
        self.assertIn("load path", advice)
        self.assertIn("GEM_HOME", advice)

    def test_every_ecosystem_behaves_the_same_way(self):
        cases = [("pip install requests", "python3", "venv"),
                 ("npm install -g typescript", "npm", "node_modules"),
                 ("cargo install ripgrep", "cargo", "cargo add"),
                 ("go install example.com/x", "go", "go get"),
                 ("composer global require x", "composer", "composer require")]
        for command, tool, marker in cases:
            with self.subTest(command=command):
                with _with_tools(tool):
                    self.assertIn(marker, dirguard._local_install_advice(command))
                with _with_tools():
                    self.assertEqual(dirguard._local_install_advice(command), "",
                                     "offered a route with none of its tools installed")


class WhatWasAlreadyRightStaysRightTests(unittest.TestCase):
    def test_a_machine_manager_still_gets_no_invented_route(self):
        for command in ("apt-get install ruby-dev", "brew install ruby", "dnf install ruby",
                        "pacman -S ruby"):
            with self.subTest(command=command):
                with _with_tools("apt-get", "brew", "dnf", "pacman", "gem", "python3"):
                    self.assertEqual(dirguard._local_install_advice(command), "")

    def test_an_unrelated_command_gets_nothing(self):
        with _with_tools("gem", "npm", "python3"):
            self.assertEqual(dirguard._local_install_advice("ls -la"), "")

    def test_the_refusal_still_renders_with_the_route_inside_it(self):
        with _with_tools("gem"):
            out = dirguard.refusal_for("gem install countries", "/tmp/ws") \
                if hasattr(dirguard, "refusal_for") else None
        if out is not None:
            self.assertIn("gem install --install-dir", out)


class TheAdviceLivesInAPromptFileTests(unittest.TestCase):
    """Rule 22 — every model-facing string is tunable without a code change."""

    def test_the_routes_are_loaded_not_inlined(self):
        routes = prompts.load_map("install_remedy")
        for key in ("pip_venv", "npm_local", "gem_bundler", "gem_direct",
                    "cargo_add", "go_get", "composer_local"):
            with self.subTest(route=key):
                self.assertTrue(routes.get(key, "").strip())

    def test_every_route_named_in_code_exists_in_the_file(self):
        routes = prompts.load_map("install_remedy")
        for _pat, options in dirguard._INSTALL_REMEDY:
            for key, needs in options:
                with self.subTest(route=key):
                    self.assertIn(key, routes)
                    self.assertTrue(needs, "a route must name the tools it needs")

    def test_no_route_prose_is_left_in_the_source(self):
        src = open(dirguard.__file__).read()
        self.assertNotIn("Drop the global flag", src)
        self.assertNotIn("bundle install --path", src.split("_INSTALL_REMEDY")[-1])


if __name__ == "__main__":
    unittest.main()
