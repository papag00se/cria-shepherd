"""cria decided what this machine has by looking at cria's own search path.

cria runs as a systemd service with no login profile, so its PATH is
`/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/snap/bin`. The coder's commands run through the
harness's shell, which loads the user's profile. Measured on this box, the two disagree for cargo,
rustc, node, npm, npx, pytest and pyflakes — every one present for the coder and absent for cria.

Three call sites asked the wrong process a question about the world (#5b):

  * `proberun.program_is_installed` dropped every probe whose program cria could not see. Two Rust
    cells ran no Rust tool at any gate; the empty result published as "the repo's own checks that
    ran reported no error-class problems" over a project with two compile errors. The coder replied
    "Let's compile mentally ... That's fine" and it did not compile for 45 calls.
    to catch a green gate over a broken program reported "the delivered program was not run,
    because FileNotFoundError: [Errno 2] No such file or directory: 'node'".
  * `dirguard._tool_present` picks which install route to RECOMMEND to the coder — advice about a
    command the coder will run, judged against a PATH the coder does not use.

`routing._cli_available` is deliberately NOT changed: cria spawns those CLIs from its own process,
so cria's PATH is the correct oracle there. Answering from the coder's path would advertise a
backend that then fails at call time.
"""

# The live-execution seat this file tested was REMOVED on 2026-08-18 (operator: "drop the
# 'something needs to be ran' assertion altogether — it is more trouble than it is worth").
# The classes that exercised it are gone with it; what remains below tests mechanisms that
# outlived it. See docs/audits/finish-and-remeasure-progress.md for the reasoning.


import os
import shutil
import subprocess
import types
import unittest
from unittest import mock

from cria import dirguard, execcheck, proberun, toolpath


SERVICE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/snap/bin"


def login_shell_path() -> str:
    """What the CODER's shell exports. `-lic`, not `-lc`: version managers (nvm, rbenv, pyenv,
    sdkman, asdf) install their shim into `.bashrc`, which a NON-interactive shell never sources —
    so `bash -lc` finds cargo and ruby and misses node entirely. Measured on this box: `-lc` cannot
    see node, `-lic` finds it at once, and the miss cost cria its whole JavaScript syntax floor."""
    out = subprocess.run([os.environ.get("SHELL", "/bin/bash"), "-lic", 'printf %s "$PATH"'],
                         capture_output=True, text=True).stdout
    lines = [ln.strip() for ln in out.splitlines() if ":" in ln and "/" in ln]
    return max(lines, key=len) if lines else ""


class TheTwoPathsReallyDifferTests(unittest.TestCase):
    """If this ever fails, the bug cannot reproduce on this box and the rest proves nothing."""

    def test_the_service_path_is_missing_toolchains_the_coder_has(self):
        missing = [p for p in ("cargo", "node", "npm", "pytest", "pyflakes")
                   if shutil.which(p, path=login_shell_path())
                   and not shutil.which(p, path=SERVICE_PATH)]
        if not missing:
            self.skipTest("this box installs every toolchain on the service path")
        self.assertTrue(missing)


class ToolpathAsksTheLoginShellTests(unittest.TestCase):
    def setUp(self):
        toolpath.reset_for_tests()
        self.addCleanup(toolpath.reset_for_tests)

    def test_it_reads_the_login_shells_path(self):
        self.assertEqual(toolpath.coder_path(), login_shell_path())

    def test_it_asks_once_and_caches(self):
        with mock.patch.object(toolpath, "_login_shell_path", return_value="/x") as m:
            toolpath.coder_path()
            toolpath.coder_path()
            toolpath.coder_path()
        self.assertEqual(m.call_count, 1)

    def test_no_login_shell_means_crias_own_path(self):
        """Not a fallback — cria never invents a path. It either learned one or reports its own,
        and both callers treat 'do not know' as their documented safe direction."""
        with mock.patch.dict(os.environ, {"SHELL": ""}, clear=False):
            self.assertEqual(toolpath.coder_path(), os.environ.get("PATH") or "")

    def test_env_borrows_only_the_path(self):
        with mock.patch.object(toolpath, "_login_shell_path", return_value="/borrowed"):
            e = toolpath.env()
        self.assertEqual(e["PATH"], "/borrowed")
        for k, v in os.environ.items():
            if k != "PATH":
                self.assertEqual(e.get(k), v)


class ProbeSelectionSeesTheCodersToolsTests(unittest.TestCase):
    def setUp(self):
        toolpath.reset_for_tests()
        self.addCleanup(toolpath.reset_for_tests)

    def cand(self, command):
        return types.SimpleNamespace(command=command, working_dir="")

    def test_a_toolchain_under_the_users_home_is_kept(self):
        for cmd in ("cargo test", "node --check app.js", "pytest -q"):
            if not toolpath.which(cmd.split()[0]):
                continue
            with self.subTest(cmd=cmd):
                self.assertTrue(proberun.program_is_installed(self.cand(cmd)))

    def test_the_original_bundler_case_still_drops(self):
        """The measured case that justified this check: `bundle exec rspec` composed on a box with
        no bundler, every gate, burning a slot and a timeout. It must still be dropped."""
        if toolpath.which("bundle"):
            self.skipTest("bundler is installed here")
        self.assertFalse(proberun.program_is_installed(self.cand("bundle exec rspec")))

    def test_unsure_still_means_keep(self):
        self.assertTrue(proberun.program_is_installed(self.cand("")))

    def test_a_project_local_tool_is_still_resolved_as_a_file(self):
        """The other half of the documented contract: `./gradlew` is checked on disk, not on any
        PATH, so neither path change can affect it."""
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            g = os.path.join(d, "gradlew")
            open(g, "w").close()
            os.chmod(g, 0o755)
            self.assertTrue(proberun.program_is_installed(
                types.SimpleNamespace(command="./gradlew test", working_dir=d)))
            self.assertFalse(proberun.program_is_installed(
                types.SimpleNamespace(command="./nope test", working_dir=d)))


class InstallAdviceIsJudgedOnTheCodersPathTests(unittest.TestCase):
    def setUp(self):
        toolpath.reset_for_tests()
        self.addCleanup(toolpath.reset_for_tests)

    def test_a_route_through_a_home_installed_tool_is_offered(self):
        with mock.patch.object(toolpath, "which", lambda n: "/home/u/.cargo/bin/" + n):
            self.assertTrue(dirguard._tool_present("cargo"))

    def test_a_genuinely_absent_tool_is_still_no_route(self):
        with mock.patch.object(toolpath, "which", lambda n: None):
            self.assertFalse(dirguard._tool_present("cargo"))


class RoutingKeepsItsOwnPathTests(unittest.TestCase):
    """cria spawns these itself; the coder's path would advertise an unrunnable backend."""

    def test_cli_availability_answers_from_crias_own_path(self):
        from cria import routing
        with mock.patch.object(routing.shutil, "which",
                                lambda b: "/usr/bin/" + b if b == "fake-cli" else None):
            self.assertTrue(routing._cli_available("fake-cli"))
            self.assertFalse(routing._cli_available("other-cli"))

    def test_it_ignores_the_coders_path_entirely(self):
        """The coder's oracle says YES; cria's own says NO. If the coder's path ever leaked in
        here, this is the case that would flip — a backend cria cannot actually spawn would be
        advertised as available and then fail at call time."""
        from cria import routing
        with mock.patch.object(toolpath, "which", lambda b: "/home/u/.local/bin/" + b), \
             mock.patch.object(routing.shutil, "which", return_value=None):
            self.assertFalse(routing._cli_available("fake-cli"))


if __name__ == "__main__":
    unittest.main()
