"""The route cria offers must name the binary the coder can actually type.

The incident (cycle 2, shipping-rates-rb x ternary-bonsai): `_tool_present("bundle")` returned True
because `_versioned_variant` found `/usr/bin/bundle3.2`, so the `gem_bundler` route won selection —
and `install_remedy.txt` then printed the literal `bundle`, which does not exist on this box. Ten
refusals carried that sentence; calls 0037-0057 are one continuous install fight; the cell went
80% -> 20%. The coder never tried `bundle3.2` because nothing ever named it.

`install_remedy.txt`'s own header records this same bug as fixed twice. Both earlier fixes repaired
the DISCOVERY and left the SENTENCE alone. This pins them together.
"""
from __future__ import annotations

import unittest

from cria import dirguard


class RouteNamesTheDiscoveredBinary(unittest.TestCase):
    def setUp(self):
        self._which, self._variant = dirguard.toolpath.which, dirguard._versioned_variant

    def tearDown(self):
        dirguard.toolpath.which, dirguard._versioned_variant = self._which, self._variant

    def _box(self, present: dict):
        """A box where `present` maps a plain name to the executable actually on PATH.

        NOTE `ruby` is now one of `gem_bundler`'s needs: the route names a one-off `<ruby> -e`
        command, and a route may only print a binary cria has actually resolved (#5b — the whole
        reason the `{{TOOL}}` tokens exist). A fixture without it falls through to `gem_direct`,
        which is correct behaviour and not what these tests are about."""
        dirguard.toolpath.which = lambda n: n if present.get(n) == n else None
        dirguard._versioned_variant = lambda n: present.get(n) if present.get(n) != n else None

    def test_the_versioned_name_reaches_the_sentence(self):
        """FAILS BEFORE: the advice said `bundle install`, a command this box cannot run."""
        self._box({"bundle": "bundle3.2", "gem": "gem", "ruby": "ruby"})
        advice = dirguard._local_install_advice("gem install countries")
        self.assertIn("bundle3.2 install --path vendor/bundle", advice)
        self.assertNotIn("`bundle install", advice)

    def test_a_plain_name_is_left_alone(self):
        self._box({"bundle": "bundle", "gem": "gem", "ruby": "ruby"})
        self.assertIn("`bundle install --path vendor/bundle`",
                      dirguard._local_install_advice("gem install countries"))

    def test_no_route_when_nothing_is_present(self):
        """An ecosystem with no runnable route gets silence, not an invented command (#3, #5b)."""
        self._box({})
        self.assertEqual("", dirguard._local_install_advice("gem install countries"))

    def test_it_falls_through_to_the_route_that_can_run(self):
        """No bundler of any name -> the gem_direct route, named with the gem binary that exists."""
        self._box({"gem": "gem3.2"})
        advice = dirguard._local_install_advice("gem install countries")
        self.assertIn("gem3.2 install --install-dir vendor/bundle", advice)

    def test_no_unfilled_token_ever_reaches_the_model(self):
        """A `{{TOOL}}` left in the text would be worse than the bug it replaces."""
        self._box({"bundle": "bundle3.2", "gem": "gem", "npm": "npm", "python3": "python3",
                   "cargo": "cargo", "go": "go", "composer": "composer", "mvn": "mvn"})
        for cmd in ("gem install x", "pip install x", "npm install x", "cargo install x",
                    "go install x", "composer global require x", "mvn install"):
            with self.subTest(cmd=cmd):
                self.assertNotIn("{{", dirguard._local_install_advice(cmd))

    def test_resolved_tool_prefers_the_plain_name(self):
        self._box({"gem": "gem"})
        self.assertEqual("gem", dirguard._resolved_tool("gem"))
        self._box({"gem": "gem3.2"})
        self.assertEqual("gem3.2", dirguard._resolved_tool("gem"))
        self._box({})
        self.assertIsNone(dirguard._resolved_tool("gem"))


if __name__ == "__main__":
    unittest.main()
