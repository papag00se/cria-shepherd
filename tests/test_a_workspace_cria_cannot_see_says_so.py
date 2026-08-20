"""cria was handed a path from another machine and treated it as a path on this one.

`workspace_root` is a path the HARNESS announces, about the HARNESS's filesystem. cria used to hand
it straight to `os.path.isdir`, which only means anything when the two are the same machine — and
nothing in this repo ever said they must be. The likely deployment is cria beside the model server
while the harness runs on someone's workstation.

The first attempt at this treated an unreachable cwd like an unknown one: blank it, and say so once
per session. That was the wrong repair, and this file records why. Blanking the path removes the
workspace from every mechanism that needs it — including `dirguard`'s containment boundary, which is
a string comparison and perfectly valid across machines — so cria answered a co-location problem by
disabling itself. The real repair is that NOTHING asks cria's disk about that path any more: the
name is carried as a name, and every question about what is AT the name goes through
:mod:`cria.wsview`, which is filled by a survey the harness runs.

So the contract asserted here is: the announced cwd survives whether or not it exists on this
machine, and a workspace nobody has surveyed answers "unknown" — never "empty", and never "no".
"""

import unittest

from cria import server as srv
from cria import wsview


def _msgs(cwd):
    return [{"role": "user",
             "content": f"<environment_context><cwd>{cwd}</cwd></environment_context>"}]


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


class TheAnnouncedPathIsCarriedAsANameTests(unittest.TestCase):
    FOREIGN = "/home/someone-else/projects/api"       # exists on the harness, not here

    def test_a_path_that_does_not_exist_here_is_still_the_workspace(self):
        """The old repair returned None here, and took the whole workspace down with it."""
        self.assertEqual(srv._session_cwd("s1", _msgs(self.FOREIGN)), self.FOREIGN)

    def test_it_does_not_warn_about_a_path_it_has_no_business_testing(self):
        rlog = _Rlog()
        srv._session_cwd("s2", _msgs(self.FOREIGN), rlog)
        self.assertEqual([k for k, _ in rlog.events], [])

    def test_the_lexical_and_ordinary_reads_agree(self):
        """They were two answers to one question; only the split is gone, not the callers."""
        self.assertEqual(srv._session_cwd("s3", _msgs(self.FOREIGN)),
                         srv._session_cwd("s3", _msgs(self.FOREIGN), lexical=True))

    def test_it_is_remembered_for_the_session(self):
        srv._session_cwd("s4", _msgs(self.FOREIGN))
        self.assertEqual(srv._session_cwd("s4", []), self.FOREIGN)

    def test_no_cwd_at_all_is_still_just_None(self):
        self.assertIsNone(srv._session_cwd("s5-unseen", []))

    def test_cria_own_dir_is_never_the_workspace(self):
        self.assertIsNone(srv._session_cwd("s6", _msgs(".")))


class AnUnsurveyedWorkspaceAnswersUnknownTests(unittest.TestCase):
    """The direction that matters: not knowing must never render as knowing nothing is there."""

    def setUp(self):
        self.view = wsview.View("/home/someone-else/projects/api", "s")
        self.token = wsview.bind(self.view)
        self.addCleanup(wsview.unbind, self.token)

    def test_existence_is_unknown_not_false(self):
        self.assertIsNone(self.view.isfile("main.py"))
        self.assertIsNone(self.view.isdir("src"))
        self.assertIsNone(self.view.exists("main.py"))

    def test_a_listing_is_unknown_not_empty(self):
        self.assertIsNone(self.view.listdir("."))
        self.assertIsNone(self.view.walk("."))

    def test_a_body_is_unknown_and_the_question_is_remembered(self):
        self.assertIsNone(self.view.read("main.py"))
        bodies, _progs, _outside = wsview.pending("s")
        self.assertIn("main.py", bodies)

    def test_a_path_outside_the_workspace_is_never_answered_from_it(self):
        self.assertIsNone(self.view.rel("/etc/passwd"))
        self.assertIsNone(self.view.isfile("/etc/passwd"))


class TheContainmentBoundaryStillHoldsTests(unittest.TestCase):
    """dirguard bounds a fledgling model's file tools by comparing path strings. That is exactly as
    valid against a workspace on another machine, and the first repair broke it."""

    def test_dirguard_is_given_the_announced_path(self):
        import inspect
        src = inspect.getsource(srv.CriaHandler._setup_translation)
        self.assertIn("_session_cwd(sess_key", src)
        self.assertIn("self._workspace_root", src)


if __name__ == "__main__":
    unittest.main()
