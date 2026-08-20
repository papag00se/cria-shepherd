"""cria was handed a path from another machine and reported nothing.

`workspace_root` is a path the HARNESS announces, about the HARNESS's filesystem. cria hands it
straight to `os.path.isdir`, which only means anything when the two are the same machine — and
nothing in this repo ever said they must be. The likely deployment is cria beside the model server
while the harness runs on someone's workstation.

The failure shape is why this exists. `os.path.isdir` on a foreign path returns False, so every
disk-derived mechanism concludes "nothing there" and abstains — correctly, by #11b — and cria
degrades to almost nothing while reporting no problem at all. Twenty-nine functions take a workspace
path; not one asked whether it could be reached. A silent degradation is the one shape nobody can
notice from the outside.

An unreachable cwd is now treated exactly like an unknown one — None, callers skip disk work — and
the fact is stated ONCE per session on cria's own channel (#12).

THE LEXICAL CALLER IS EXEMPT, and that is the point of the split. `dirguard`'s containment boundary
is a path COMPARISON — is this target inside that prefix — and it is exactly as valid against a
workspace on another machine. Blanking it there would remove the bound on a fledgling model's file
tools, which is the opposite of what this change is for.
"""

import unittest

from cria import server as srv


def _msgs(cwd):
    return [{"role": "user",
             "content": f"<environment_context><cwd>{cwd}</cwd></environment_context>"}]


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


class AnUnreachableWorkspaceIsNotSilentTests(unittest.TestCase):
    def setUp(self):
        srv._CWD_BY_SESSION.clear()
        srv._UNREACHABLE_REPORTED.clear()

    def test_disk_callers_are_told_nothing_rather_than_a_path_that_does_not_resolve(self):
        r = _Rlog()
        self.assertIsNone(srv._session_cwd("s", _msgs("/not/on/this/machine"), r))

    def test_it_says_so_on_crias_own_channel(self):
        r = _Rlog()
        srv._session_cwd("s", _msgs("/not/on/this/machine"), r)
        kinds = [k for k, _ in r.events]
        self.assertIn("server.workspace_unreachable", kinds)
        self.assertEqual(r.events[0][1]["cwd"], "/not/on/this/machine")

    def test_it_says_so_ONCE_per_session_not_once_per_request(self):
        first, second = _Rlog(), _Rlog()
        srv._session_cwd("s", _msgs("/not/on/this/machine"), first)
        srv._session_cwd("s", _msgs("/not/on/this/machine"), second)
        self.assertTrue(first.events)
        self.assertEqual(second.events, [])          # noise, not signal, the second time (#3)

    def test_a_reachable_workspace_is_unchanged_and_silent(self):
        import tempfile
        r = _Rlog()
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(srv._session_cwd("s", _msgs(tmp), r), tmp)
        self.assertEqual(r.events, [])

    def test_no_cwd_at_all_is_still_just_None(self):
        r = _Rlog()
        self.assertIsNone(srv._session_cwd("s", [{"role": "user", "content": "hi"}], r))
        self.assertEqual(r.events, [])               # unknown is not unreachable


class TheContainmentBOUNDARYKeepsItsPathTests(unittest.TestCase):
    def setUp(self):
        srv._CWD_BY_SESSION.clear()
        srv._UNREACHABLE_REPORTED.clear()

    def test_a_lexical_caller_still_gets_the_announced_path(self):
        got = srv._session_cwd("s", _msgs("/not/on/this/machine"), _Rlog(), lexical=True)
        self.assertEqual(got, "/not/on/this/machine")

    def test_the_lexical_read_does_not_warn(self):
        r = _Rlog()
        srv._session_cwd("s", _msgs("/not/on/this/machine"), r, lexical=True)
        self.assertEqual(r.events, [])               # it did not need the disk, so nothing is wrong

    def test_dirguard_is_wired_to_the_lexical_form(self):
        # The bound on a fledgling model's file tools must survive a workspace cria cannot see.
        import inspect
        src = inspect.getsource(srv)
        self.assertIn("self._workspace_root = _session_cwd(sess_key, body.get(\"messages\", []), lexical=True)", src)


if __name__ == "__main__":
    unittest.main()
