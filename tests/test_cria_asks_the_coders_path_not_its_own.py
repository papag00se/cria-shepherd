"""cria decided what the coder's machine has by looking at cria's own search path.

cria runs as a systemd service with no login profile, so its PATH is
`/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/snap/bin`. The coder's commands run through the
harness's shell, which loads the user's profile. Measured on one box, the two disagree for cargo,
rustc, node, npm, npx, pytest and pyflakes — every one present for the coder and absent for cria.

Two call sites asked the wrong process a question about the world (#5b):

  * `proberun.program_is_installed` dropped every probe whose program cria could not see. Two Rust
    cells ran no Rust tool at any gate; the empty result published as "the repo's own checks that
    ran reported no error-class problems" over a project with two compile errors. The coder replied
    "Let's compile mentally ... That's fine" and it did not compile for 45 calls.
  * `dirguard._tool_present` picks which install route to RECOMMEND to the coder — advice about a
    command the coder will run, judged against a PATH the coder does not use.

THE FIRST REPAIR ASKED THE WRONG MACHINE TOO. It ran the user's login shell through `subprocess`
from cria's own process and read `$PATH` out of it — which answers for whatever box cria happens to
be on. That is the same co-location assumption in a different costume, and it is gone: the question
now goes to the HARNESS, in the workspace survey, and comes back on a later request.

So the answer has THREE states, and this file is mostly about the third. `resolved(name)` returns
the name the coder must type, `""` when their shell resolves nothing, and **None** when nobody has
asked yet. The two callers pick opposite safe directions for None, on purpose:

  * a PROBE is KEPT when cria is unsure — dropping a real check is worse than running one that
    abstains;
  * a piece of ADVICE is WITHHELD when cria is unsure — naming a command that may not exist is the
    false fact this whole area exists to stop.

`routing._cli_available` is deliberately unchanged: cria spawns those CLIs from its own process, so
cria's PATH is the correct oracle there. Answering from the coder's path would advertise a backend
that then fails at call time.
"""

import types
import unittest
from unittest import mock

from cria import dirguard, proberun, toolpath, wsview


class TheAnswerHasThreeStatesTests(unittest.TestCase):
    """Unanswered is not absent. Collapsing the two is what turns a question into a false fact."""

    def setUp(self):
        self.view = wsview.View("/ws", "sess-progs")
        self.addCleanup(wsview.unbind, wsview.bind(self.view))

    def test_a_name_nobody_asked_about_is_None(self):
        self.assertIsNone(toolpath.resolved("cargo"))

    def test_asking_records_the_question_for_the_next_survey(self):
        toolpath.resolved("cargo")
        _bodies, progs, _outside = wsview.pending("sess-progs")
        self.assertIn("cargo", progs)

    def test_an_answered_absence_is_empty_string_not_None(self):
        wsview.apply_survey(self.view, "___CRIA_SV_tree___\n___CRIA_SV_progs___\ncargo\t\n")
        self.assertEqual(toolpath.resolved("cargo"), "")

    def test_a_versioned_variant_is_what_the_coder_must_type(self):
        wsview.apply_survey(self.view,
                            "___CRIA_SV_tree___\n___CRIA_SV_progs___\nbundle\tbundle3.2\n")
        self.assertEqual(toolpath.resolved("bundle"), "bundle3.2")


class NothingAsksThisMachinesShellTests(unittest.TestCase):
    """The repair that was itself the bug: a login shell spawned from cria's own process."""

    def test_it_cannot_spawn_or_probe_this_machine_at_all(self):
        """Behavioural, not textual: the module does not hold the tools it would need to."""
        self.assertFalse(hasattr(toolpath, "subprocess"))
        self.assertFalse(hasattr(toolpath, "shutil"))
        self.assertFalse(hasattr(toolpath, "os"))

    def test_there_is_no_env_borrowing_left(self):
        self.assertFalse(hasattr(toolpath, "coder_path"))
        self.assertFalse(hasattr(toolpath, "env"))
        self.assertFalse(hasattr(toolpath, "_login_shell_path"))


class ProbeSelectionSeesTheCodersToolsTests(unittest.TestCase):
    """UNSURE MEANS KEEP — the documented safe direction, now that unsure is a state cria can be in."""

    def setUp(self):
        self.view = wsview.View("/ws", "sess-probe")
        self.addCleanup(wsview.unbind, wsview.bind(self.view))

    def cand(self, command, working_dir=""):
        return types.SimpleNamespace(command=command, working_dir=working_dir)

    def _progs(self, **found):
        wsview.apply_survey(self.view, "___CRIA_SV_tree___\n___CRIA_SV_progs___\n"
                            + "".join(f"{k}\t{v}\n" for k, v in found.items()))

    def test_a_toolchain_the_coder_has_is_kept(self):
        self._progs(cargo="cargo", node="node", pytest="pytest")
        for cmd in ("cargo test", "node --check app.js", "pytest -q"):
            with self.subTest(cmd=cmd):
                self.assertTrue(proberun.program_is_installed(self.cand(cmd)))

    def test_the_original_bundler_case_still_drops(self):
        """The measured case that justified this check: `bundle exec rspec` composed on a box with
        no bundler, every gate, burning a slot and a timeout. It must still be dropped."""
        self._progs(bundle="")
        self.assertFalse(proberun.program_is_installed(self.cand("bundle exec rspec")))

    def test_a_program_nobody_has_asked_about_yet_is_KEPT(self):
        """The direction that matters most. A probe dropped on an unanswered question is a check
        that silently never ran — which reads exactly like a check that passed."""
        self.assertTrue(proberun.program_is_installed(self.cand("cargo test")))

    def test_unsure_still_means_keep(self):
        self.assertTrue(proberun.program_is_installed(self.cand("")))

    def test_a_project_local_tool_is_still_asked_of_the_workspace(self):
        """`./gradlew` is a file in the coder's project, so it is a question about the harness's
        filesystem like every other one — and the same three states apply."""
        wsview.apply_survey(self.view, "___CRIA_SV_tree___\nF\t0\t0\tgradlew\n")
        self.assertTrue(proberun.program_is_installed(self.cand("./gradlew test", "/ws")))
        self.assertFalse(proberun.program_is_installed(self.cand("./nope test", "/ws")))


class InstallAdviceIsJudgedOnTheCodersPathTests(unittest.TestCase):
    """The opposite safe direction: advice names a command the coder will TYPE, so unsure is silent."""

    def setUp(self):
        self.view = wsview.View("/ws", "sess-advice")
        self.addCleanup(wsview.unbind, wsview.bind(self.view))

    def _progs(self, **found):
        wsview.apply_survey(self.view, "___CRIA_SV_tree___\n___CRIA_SV_progs___\n"
                            + "".join(f"{k}\t{v}\n" for k, v in found.items()))

    def test_a_route_through_a_tool_the_coder_has_is_offered(self):
        self._progs(cargo="cargo")
        self.assertTrue(dirguard._tool_present("cargo"))

    def test_a_genuinely_absent_tool_is_still_no_route(self):
        self._progs(cargo="")
        self.assertFalse(dirguard._tool_present("cargo"))

    def test_an_unanswered_tool_is_no_route_either(self):
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
        with mock.patch.object(toolpath, "resolved", lambda b: "cli"), \
             mock.patch.object(routing.shutil, "which", return_value=None):
            self.assertFalse(routing._cli_available("fake-cli"))


if __name__ == "__main__":
    unittest.main()
