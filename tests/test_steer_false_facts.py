"""A delivered steer may not state a false disk fact or an invented auth requirement.

Walked 2026-08-04, run ada-handles_gemma4_codex_poff_1785866157 (1/4): the steer author's own
prompt said `resolve_test.py — 64 lines` and `pyproject.toml — 15 lines`, yet delivered steers
cited "line 245", "lines 30 and 98", "lines 95–99 … in resolve_test.py", and "deleting lines
23-24 from pyproject.toml" — only the colon form (`resolve_handle.py:1428`) was caught. Steer
0191 separately invented "your API key" and told the coder to keep a task-required live test
mocked, in a session whose every fetch was an HTTP 200.
"""

import pathlib
import tempfile
import unittest

from cria.loop import _false_line_citation, _steer_auth_refuted


def _workspace():
    """The run's real workspace: `pyproject.toml` at 15 lines and `resolve_test.py` at 64, the two
    counts the author's own prompt carried while its steers cited 245.

    A DIRECTORY, not the sentence cria wrote about one. The check used to re-parse its own
    `FILE x — 318 bytes, 15 lines` list back out of the evidence blob; it now asks the file."""
    ws = tempfile.mkdtemp()
    pathlib.Path(ws, "pyproject.toml").write_text("\n".join(f"# line {i}" for i in range(1, 16)))
    pathlib.Path(ws, "tests").mkdir()
    pathlib.Path(ws, "tests", "resolve_test.py").write_text(
        "\n".join(f"# line {i}" for i in range(1, 65)))
    return ws


WS = _workspace()
# The files the coder has been touching — the set the composed disk list was always built from,
# now handed over as paths instead of recovered from the sentence that listed them.
TOUCHED = ["pyproject.toml", "tests/resolve_test.py"]


def _cite(directive, root=None, touched=None):
    return _false_line_citation(directive, WS if root is None else root,
                                TOUCHED if touched is None else touched)


class FalseLineCitationShapeTests(unittest.TestCase):
    def test_from_preposition_is_checked(self):
        # steer 0222: "deleting lines 23-24 from pyproject.toml" — pyproject.toml has 15 lines
        self.assertIsNotNone(_cite("Fix it by deleting lines 23-24 from pyproject.toml."))

    def test_bare_parenthetical_line_past_every_file(self):
        # steer 0218: "(line 245)" — no file in the workspace has 245 lines
        self.assertIsNotNone(_cite("Delete the stale assertion comparing to `resolve_had` (line 245)."))

    def test_bare_and_list_past_every_file(self):
        # steer 0218: "two identical def main() blocks starting on lines 30 and 98"
        self.assertIsNotNone(_cite("You have two identical def main() blocks starting on lines 30 and 98."))

    def test_bare_range_list_past_every_file(self):
        # steer 0222: "lines 9–15, 67–80, AND 95–99 all use names never imported"
        self.assertIsNotNone(_cite("Lines 9–15, 67–80, and 95–99 all use names never imported."))

    def test_bare_reference_within_range_passes(self):
        # A bare line number no bigger than the largest listed file could be true — silence.
        self.assertIsNone(_cite("Remove them at lines 19-20 and rerun the tests."))

    def test_named_file_still_tighter_than_the_ceiling(self):
        # "of/in" form binds to the named file: 40 fits resolve_test.py's 64 but not pyproject's 15.
        self.assertIsNotNone(_cite("Move both keys on lines 40-41 of pyproject.toml."))
        self.assertIsNone(_cite("Move both keys on lines 40-41 of resolve_test.py."))

    def test_no_counts_no_check(self):
        self.assertIsNone(_cite("Delete line 9999.", root=tempfile.mkdtemp(), touched=[]))
        self.assertIsNone(_cite("Delete line 9999.", root=None, touched=[]))

    def test_a_name_that_matches_two_files_is_not_guessed_at(self):
        """The old dict was keyed on the basename, so the second `client.py` silently replaced the
        first and every citation was checked against whichever came last."""
        ws = tempfile.mkdtemp()
        for d in ("a", "b"):
            pathlib.Path(ws, d).mkdir()
        pathlib.Path(ws, "a", "client.py").write_text("x\n" * 10)
        pathlib.Path(ws, "b", "client.py").write_text("x\n" * 200)
        self.assertIsNone(_cite("Fix client.py:150 now.", root=ws, touched=[]))
        self.assertIsNotNone(_cite("Fix a/client.py:150 now.", root=ws, touched=[]))

    def test_a_file_named_only_by_its_basename_is_still_checked(self):
        """`resolve_test.py` lives in `tests/`, and a steer says it the way a person would."""
        self.assertIsNotNone(_cite("Delete resolve_test.py:245."))
        self.assertIsNone(_cite("Delete resolve_test.py:60."))


class _Sess:
    def __init__(self, task, pages=None):
        self.plan = type("P", (), {"task": task})()
        self.fetched_pages = pages or {}


STEER_0191 = ("Don't add live network calls here, they will fail without your API key; "
              "keep tests mocked but verify against known public handles.")
TASK = ("Write a Python script that resolves an Ada Handle to the Cardano address using the "
        "Ada Handles API (api.handle.me). Unit tests are required, plus a live test.")


class _Rlog:
    def __init__(self):
        self.kinds = []

    def emit(self, kind, **kw):
        self.kinds.append(kind)


class SteerAuthClaimTests(unittest.TestCase):
    def _ask(self, answer):
        def ask(system, _user):
            self.asked = system
            return answer
        self.asked = ""
        return ask

    def test_invented_auth_claim_is_refutable(self):
        # FAILS BEFORE THE FIX: 0191 was delivered with no question asked.
        sess = _Sess(TASK, {"https://api.handle.me/openapi.json": ("HTTP 200", "", "", "")})
        rlog = _Rlog()
        self.assertTrue(_steer_auth_refuted(STEER_0191, "all fetches clean", sess,
                                            self._ask("REFUTED"), rlog))
        self.assertIn("loop.steer_auth_refuted", rlog.kinds)
        self.assertIn("HTTP 200", self.asked)          # the gathered facts reached the judge

    def test_stands_delivers(self):
        sess = _Sess(TASK, {"https://api.example.com": ("HTTP 401", "", "", "")})
        self.assertFalse(_steer_auth_refuted(STEER_0191, "got 401 Unauthorized", sess,
                                             self._ask("STANDS"), _Rlog()))

    def test_task_naming_a_key_never_asks(self):
        sess = _Sess(TASK + " Use the api key I gave you.")
        self.assertFalse(_steer_auth_refuted(STEER_0191, "", sess, self._ask("REFUTED"), _Rlog()))
        self.assertEqual(self.asked, "")               # the claim has a source — no call spent

    def test_no_auth_shape_never_asks(self):
        sess = _Sess(TASK)
        self.assertFalse(_steer_auth_refuted("Rename the file to test_resolve.py and rerun.",
                                             "", sess, self._ask("REFUTED"), _Rlog()))
        self.assertEqual(self.asked, "")

    def test_no_reasoner_delivers(self):
        self.assertFalse(_steer_auth_refuted(STEER_0191, "", _Sess(TASK), None, _Rlog()))

    def test_unreadable_answer_delivers(self):
        self.assertFalse(_steer_auth_refuted(STEER_0191, "", _Sess(TASK),
                                             self._ask("well, maybe…"), _Rlog()))


if __name__ == "__main__":
    unittest.main()
