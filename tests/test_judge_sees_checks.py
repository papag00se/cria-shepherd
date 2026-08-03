"""`_is_cria_scaffolding` treated every check block as cria's own orchestration and stripped it.

That is right for a log describing what the CODER did, and wrong for the judge that decides whether
the task is DONE — the one reader for whom "did the checks pass" is the question.

Walked on ada-handles_mellum2_codex_poff_1785714194 call 0033: the satisfaction judge wrote "the
test suite test_resolve_handle.py passes" with nothing in its evidence saying so. The string
`4 passed` appears nowhere in its prompt; the only pytest result it could see was the original
`3 failed, 1 passed`. cria then filled the gap in its own words — "Everything else the checks cover
passed" — and the judge's verdict repeated that sentence back.
"""
import inspect
import unittest

from cria import loop, probegate

GREEN = probegate.CHECKS_MARKER + " the repo's own checks that ran reported no error-class problems."
RED = probegate.CHECKS_MARKER + " the repo's own checks report these problems:\nx.py:1: boom"


class ScaffoldingSplitTests(unittest.TestCase):
    def test_a_check_block_is_hidden_from_the_coders_log(self):
        for payload in (GREEN, RED):
            with self.subTest(payload=payload[:26]):
                self.assertTrue(loop._is_cria_scaffolding(payload))

    def test_and_kept_for_the_judge(self):
        for payload in (GREEN, RED):
            with self.subTest(payload=payload[:26]):
                self.assertFalse(loop._is_cria_scaffolding(payload, keep_checks=True))

    def test_raw_probe_plumbing_stays_scaffolding_for_both_readers(self):
        for keep in (True, False):
            with self.subTest(keep_checks=keep):
                self.assertTrue(loop._is_cria_scaffolding(
                    probegate.SECTION_PREFIX + "1\npytest -q", keep_checks=keep))
                self.assertTrue(loop._is_cria_scaffolding("EXIT:0", keep_checks=keep))


class WiringTests(unittest.TestCase):
    def test_the_completion_judges_evidence_asks_for_them(self):
        self.assertIn("keep_checks=True", inspect.getsource(loop._satisfaction_evidence))

    def test_the_default_is_the_old_behaviour(self):
        self.assertIn("keep_checks: bool = False", inspect.getsource(loop._work_log))
        self.assertIn("keep_checks: bool = False", inspect.getsource(loop._is_cria_scaffolding))


if __name__ == "__main__":
    unittest.main()
