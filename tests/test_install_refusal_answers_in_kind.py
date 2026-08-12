"""A guard that refuses in six ecosystems must remediate in six.

`_GLOBAL_INSTALL` already matched pip, npm/pnpm/yarn -g, gem, cargo, go, composer global and the
system managers — and the entire remedy was pip and a virtualenv. So a refused `gem install
countries` was answered with `python3 -m venv .venv && ./.venv/bin/pip install <pkg>`.

Measured on the six-language battery's Ruby task: the coder was refused, given no Ruby-viable route,
and hand-rolled the EU member list the gem would have supplied — the deliverable the task existed to
test.

Per-manager rows are correct; the defect was that the table lived only on the refusing side. Where
no project-local form exists — apt, brew, dnf install to the machine, full stop — the honest answer
is to say what is forbidden and stop, not to invent a route.
"""
import unittest

from cria import dirguard


def refusal(cmd):
    return dirguard.install_refusal(cmd, "/w", None) or ""


def remedy(cmd):
    return refusal(cmd).split("would not.", 1)[-1].strip()


class TheRemedyMatchesTheManagerTests(unittest.TestCase):
    # Asserted on the ecosystem's OWN TOOL, not on one command line. The ruby entry used to require
    # "bundle install --path", and `bundle` is not installed on the box the battery runs on — cria
    # was prescribing a command that could not run, and two runs followed it into "command not
    # found". A route is now chosen by what is actually on PATH, so the durable expectation is that
    # ruby is answered with ruby's tool, whichever route that turns out to be.
    # See tests/test_install_advice_names_a_tool_that_exists.py.
    CASES = {
        "pip install requests": (".venv",),
        "gem install countries": ("bundle install --path", "gem install --install-dir"),
        "cargo install ripgrep": ("cargo add",),
        "go install example.com/x@v1": ("go get",),
        "npm install -g eslint": ("node_modules",),
        "composer global require x": ("composer require",),
    }

    def test_each_ecosystem_is_answered_in_its_own_terms(self):
        for cmd, wanted in self.CASES.items():
            with self.subTest(cmd=cmd):
                got = remedy(cmd)
                self.assertTrue(any(w in got for w in wanted),
                                f"none of {wanted} in: {got[:160]}")

    def test_no_ecosystem_is_answered_in_pythons_terms_but_python(self):
        for cmd in self.CASES:
            if cmd.startswith("pip"):
                continue
            with self.subTest(cmd=cmd):
                self.assertNotIn("venv", remedy(cmd))
                self.assertNotIn("pip install", remedy(cmd))

    def test_a_system_manager_gets_no_invented_route(self):
        """apt installs to the machine and has no project-local form. Saying nothing is correct."""
        self.assertTrue(refusal("sudo apt install jq"))
        self.assertEqual(remedy("sudo apt install jq"), "")


class TheRoutesWeRecommendAreNotThemselvesRefusedTests(unittest.TestCase):
    def test_the_ruby_project_local_forms_are_allowed(self):
        for cmd in ("gem install --install-dir vendor/bundle countries",
                    "bundle install --path vendor/bundle"):
            with self.subTest(cmd=cmd):
                self.assertFalse(refusal(cmd))

    def test_the_python_project_local_form_is_still_allowed(self):
        self.assertFalse(refusal("./.venv/bin/pip install requests"))

    def test_the_global_form_is_still_refused(self):
        self.assertTrue(refusal("gem install countries"))
        self.assertTrue(refusal("pip install requests"))


if __name__ == "__main__":
    unittest.main()
