"""A routeless refusal read as "this cannot be done", and a run hardcoded the data instead.

`install_refusal` refuses an install whose destination is shared and appends the project-local
route for that ecosystem. The route is chosen by asking which binaries are on the CODER's PATH, and
that answer arrives on a workspace survey — which rides only on a composed write/edit/list or on a
gate. A coder stuck in a loop of raw `gem install` shell commands triggers neither, so early
refusals had nothing to offer and said nothing at all.

Walked at `~/.cria/calls/20260823T032555-01a02e27/0084-coder-s1.prompt.txt`: the first NINE install
refusals carry no route; the tenth onward do. 580 of 3,704 renderings across the corpus (16%) are
routeless. Fourteen consecutive refused installs later, the refusal escalation authored:

    Directive: Stop trying to install the countries gem — it cannot be installed in this sandbox
    (every gem install attempt fails with "installing into the project directory" denied). Replace
    the require 'countries' … with a hardcoded set of EU two-letter codes …

`countries (8.1.0)` is installed on this box, and `gem install --install-dir vendor/bundle countries`
passes cria's own guard.

Three states, not two (#23c): a route that is known, an ecosystem asked about whose tools are
genuinely absent (silence — say what is forbidden and stop), and an ecosystem nobody has asked about
yet (say that, so nothing concludes the package is unobtainable).

The second half of this file is the guard's other end. `_LOCAL_INSTALL_SCOPE` was one alternation of
eight flag spellings applied to every manager at once, so it tested SPELLING rather than
DESTINATION — the exact words of its own note. Run against it:

    pip install -i https://pypi.org/simple flask   ALLOWED  (-i is pip's --index-url)
    apt-get install -y vim --root x                ALLOWED
    cargo install --path .                         ALLOWED  (--path is cargo's SOURCE)
    pip install -t ./libs requests                 REFUSED  (pip's own --target short form)

and, live at call 0040 of that same session, `gem install countries --user-dir <the workspace>` was
refused with "an install must land inside the project directory (<the same path>)".
"""

import unittest
from unittest import mock

from cria import dirguard, prompts

WS = "/ws"
_R = prompts.load_map("install_remedy")


def _tools(answer):
    return mock.patch.object(dirguard, "_resolved_tool", answer)


class TheThreeStatesOfARouteTests(unittest.TestCase):
    def test_a_known_route_is_named(self):
        with _tools(lambda t: t):
            out = dirguard.install_refusal("gem install countries", "none", WS)
        self.assertIn("vendor/bundle", out)
        self.assertNotIn(_R["route_unknown_yet"], out)

    def test_asked_and_absent_still_says_nothing_rather_than_guessing(self):
        """#3, #5b — cria may not send the coder after a command that cannot run."""
        with _tools(lambda t: ""):
            out = dirguard.install_refusal("gem install countries", "none", WS)
        self.assertNotIn(_R["route_unknown_yet"], out)
        self.assertNotIn("vendor/bundle", out)

    def test_unasked_says_so_instead_of_reading_as_impossible(self):
        with _tools(lambda t: None):
            out = dirguard.install_refusal("gem install countries", "none", WS)
        self.assertIn(_R["route_unknown_yet"], out)

    def test_a_manager_with_no_project_local_form_is_still_silent(self):
        """apt, dnf, brew, pacman install to the machine. There is no route to not-know."""
        for cmd in ("apt-get install vim", "brew install jq", "dnf install curl"):
            with self.subTest(cmd=cmd):
                with _tools(lambda t: None):
                    out = dirguard.install_refusal(cmd, "none", WS)
                self.assertNotIn(_R["route_unknown_yet"], out)


class TheGuardJudgesTheDestinationNotTheSpellingTests(unittest.TestCase):
    ALLOWED = (
        ("pip install -t ./libs requests", "pip's own --target short form"),
        ("pip install --target=/ws/libs requests", "absolute, inside the workspace"),
        ("gem install -i local_gems europe", "gem's --install-dir short form"),
        ("gem install --install-dir vendor/bundle countries", "the route cria itself prescribes"),
        ("bundle install --path vendor/bundle", "bundler's form"),
        ("cargo install --root ./tools ripgrep", "cargo's real destination flag"),
        ("npm install express", "project-local by default"),
        ("./.venv/bin/pip install requests", "a venv interpreter inside the project"),
    )
    REFUSED = (
        ("pip install -i https://pypi.org/simple flask", "-i is pip's index URL, not a destination"),
        ("pip install --target=/usr/lib requests", "absolute, outside the workspace"),
        ("pip install requests", "no destination at all"),
        ("apt-get install -y vim --root x", "apt has no project-local form"),
        ("cargo install --path .", "cargo's --path is the SOURCE; the binary goes to ~/.cargo/bin"),
        ("gem install countries --user-dir /ws", "not one of gem's destination flags"),
        ("npm install -g typescript", "the global flag"),
    )

    def test_an_install_aimed_into_the_project_is_ordinary_work(self):
        for cmd, why in self.ALLOWED:
            with self.subTest(cmd=cmd):
                self.assertIsNone(dirguard.install_refusal(cmd, "none", WS), why)

    def test_an_install_aimed_anywhere_else_is_refused(self):
        for cmd, why in self.REFUSED:
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(dirguard.install_refusal(cmd, "none", WS), why)

    def test_a_url_is_never_a_destination(self):
        """The whole of the pip hole: a flag value with a scheme is not a place on this disk."""
        self.assertFalse(dirguard._lands_in_the_project("https://pypi.org/simple", WS))
        self.assertTrue(dirguard._lands_in_the_project("./libs", WS))


if __name__ == "__main__":
    unittest.main()
