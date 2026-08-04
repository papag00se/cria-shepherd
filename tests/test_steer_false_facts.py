"""A delivered steer may not state a false disk fact or an invented auth requirement.

Walked 2026-08-04, run ada-handles_gemma4_codex_poff_1785866157 (1/4): the steer author's own
prompt said `resolve_test.py — 64 lines` and `pyproject.toml — 15 lines`, yet delivered steers
cited "line 245", "lines 30 and 98", "lines 95–99 … in resolve_test.py", and "deleting lines
23-24 from pyproject.toml" — only the colon form (`resolve_handle.py:1428`) was caught. Steer
0191 separately invented "your API key" and told the coder to keep a task-required live test
mocked, in a session whose every fetch was an HTTP 200.
"""

import unittest

from cria.loop import _false_line_citation, _steer_auth_refuted


EVIDENCE = ("FILES ALREADY IN THIS WORKSPACE (on disk right now — do not re-create them):\n"
            "FILE pyproject.toml — 318 bytes, 15 lines\n"
            "FILE resolve_test.py — 2,195 bytes, 64 lines\n")


class FalseLineCitationShapeTests(unittest.TestCase):
    def test_from_preposition_is_checked(self):
        # steer 0222: "deleting lines 23-24 from pyproject.toml" — pyproject.toml has 15 lines
        self.assertIsNotNone(_false_line_citation(
            "Fix it by deleting lines 23-24 from pyproject.toml.", EVIDENCE))

    def test_bare_parenthetical_line_past_every_file(self):
        # steer 0218: "(line 245)" — no file in the workspace has 245 lines
        self.assertIsNotNone(_false_line_citation(
            "Delete the stale assertion comparing to `resolve_had` (line 245).", EVIDENCE))

    def test_bare_and_list_past_every_file(self):
        # steer 0218: "two identical def main() blocks starting on lines 30 and 98"
        self.assertIsNotNone(_false_line_citation(
            "You have two identical def main() blocks starting on lines 30 and 98.", EVIDENCE))

    def test_bare_range_list_past_every_file(self):
        # steer 0222: "lines 9–15, 67–80, AND 95–99 all use names never imported"
        self.assertIsNotNone(_false_line_citation(
            "Lines 9–15, 67–80, and 95–99 all use names never imported.", EVIDENCE))

    def test_bare_reference_within_range_passes(self):
        # A bare line number no bigger than the largest listed file could be true — silence.
        self.assertIsNone(_false_line_citation(
            "Remove them at lines 19-20 and rerun the tests.", EVIDENCE))

    def test_named_file_still_tighter_than_the_ceiling(self):
        # "of/in" form binds to the named file: 40 fits resolve_test.py's 64 but not pyproject's 15.
        self.assertIsNotNone(_false_line_citation(
            "Move both keys on lines 40-41 of pyproject.toml.", EVIDENCE))
        self.assertIsNone(_false_line_citation(
            "Move both keys on lines 40-41 of resolve_test.py.", EVIDENCE))

    def test_no_counts_no_check(self):
        self.assertIsNone(_false_line_citation("Delete line 9999.", "no disk list here"))


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
