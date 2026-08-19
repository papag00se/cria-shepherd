"""cria told the coder "You do not need to install it" and "Install it into the project instead" — in
one message, about two different packages.

`shipping-rates-rb x ternary-bonsai`, run 1787102312. The coder typed `which bundler; gem install
bundler`, having decided it needed bundler before it could vendor the gem the task requires. What
came back, as one ⟦ctx:denied⟧ block:

    bundler is already installed on this machine — the executable is named `bundle`, so type that
    instead of `bundler`. You do not need to install it. Install it into the project instead: add the
    gem to a `Gemfile` and run `bundle install --path vendor/bundle`. …

The two halves answer different questions. The ROUTE says how to add a DEPENDENCY to the project.
`_already_here` fires only when the package being installed IS the route's own tool — that is its
whole trigger condition — so by the time it speaks, the command was never a dependency install and
there is nothing left for the route to route. Its "it" is a different "it".

The concatenation was deliberate and the reasoning is in the docstring: *"The fact goes FIRST,
because the route below it is the part the coder already read past six times."* Putting the new fact
first is right; keeping the stale one underneath is what made it a contradiction.

That run scored 0 of 5. Three of its install attempts were refused and it never reached
`bundle install`, which is the command both halves of this message were arguing about.
"""

import unittest

from cria import dirguard, prompts


def refusal(command, workspace="/tmp/ws"):
    return dirguard._install_remedy(command) if hasattr(dirguard, "_install_remedy") else None


class TheToolFactStandsAloneTests(unittest.TestCase):
    """`_INSTALL_REMEDY` is the composer; these go through it the way the guard does."""

    def remedy(self, command):
        import re
        routes = prompts.load_map("install_remedy")
        for pat, options in dirguard._INSTALL_REMEDY:
            if not pat.search(command):
                continue
            for key, needs in options:
                found = {t: dirguard._resolved_tool(t) for t in needs}
                if all(found.values()) and routes.get(key):
                    here = dirguard._already_here(command, found, routes)
                    if here:
                        return here
                    return " " + prompts.fill(routes[key],
                                              **{t.upper(): n for t, n in found.items()})
            return ""
        return ""

    def test_the_measured_command(self):
        """`gem install bundler`, with bundler present. One fact, no route."""
        if not dirguard._resolved_tool("bundle"):
            self.skipTest("bundler is not installed on this box")
        said = self.remedy("cd /tmp/ws && which bundler; gem install bundler 2>&1 | tail -5")
        self.assertIn("already installed on this machine", said)
        self.assertNotIn("Install it into the project instead", said)
        self.assertNotIn("Gemfile", said)

    def test_it_does_not_contradict_itself(self):
        if not dirguard._resolved_tool("bundle"):
            self.skipTest("bundler is not installed on this box")
        said = self.remedy("gem install bundler")
        self.assertIn("You do not need to install it", said)
        self.assertNotIn("run `bundle install", said)

    def test_an_ordinary_gem_still_gets_the_whole_route(self):
        """The route is the answer when the command really is a dependency install — which is every
        case `_already_here` does not fire on."""
        if not dirguard._resolved_tool("bundle"):
            self.skipTest("bundler is not installed on this box")
        said = self.remedy("gem install countries")
        self.assertIn("add the gem to a `Gemfile`", said)
        self.assertNotIn("already installed on this machine", said)

    def test_the_route_still_names_the_binary_that_was_found(self):
        """f2b8b5b's fix, unchanged: the route prints the tool cria actually resolved."""
        tool = dirguard._resolved_tool("bundle")
        if not tool:
            self.skipTest("bundler is not installed on this box")
        self.assertIn(str(tool), self.remedy("gem install countries"))


class OnlyOneOfThemCanSpeakTests(unittest.TestCase):
    def test_the_composer_returns_the_fact_instead_of_appending_to_it(self):
        """`_INSTALL_REMEDY_FN` has never existed on `dirguard` — that `hasattr` guard always fell
        through to scanning the WHOLE module's source, which could pass on an unrelated match
        anywhere in the file and could not prove anything about the real composer,
        `_local_install_advice`. Drive it directly instead."""
        if not dirguard._resolved_tool("bundle"):
            self.skipTest("bundler is not installed on this box")
        said = dirguard._local_install_advice("gem install bundler")
        self.assertIn("You do not need to install it", said)
        self.assertNotIn("Install it into the project instead", said)

    def test_already_here_only_fires_for_the_routes_own_tool(self):
        """Its trigger IS the reason the route does not apply — worth pinning, because if this ever
        widened to ordinary packages the two would start answering the same question again."""
        routes = prompts.load_map("install_remedy")
        found = {"bundle": "/usr/bin/bundle"}
        self.assertTrue(dirguard._already_here("gem install bundler", found, routes))
        self.assertEqual(dirguard._already_here("gem install countries", found, routes), "")


if __name__ == "__main__":
    unittest.main()
