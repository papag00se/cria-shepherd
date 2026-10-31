"""`_is_hard_failure` called a dataclass field and caught its own TypeError, so it never fired.

Found by executing it, not by reading it: given a Test candidate — whose kind IS in
`proberun._HARD_FAILURE_KINDS` — it answered False. `ProbeCandidate.kind` is a field; `.kind()`
raises `TypeError`; `TypeError` was in the function's own `except`. It has returned False for every
probe since it was written.

WHAT THAT TURNED OFF. The branch that reports a non-zero exit as a REAL failure regardless of how
its output looks. A test/typecheck/build probe that exits non-zero is failing, full stop — that is
the whole point of the "hard" set. With this dead, a build whose output looks like warnings was
summarised to the model as clean:

    -Werror              a C/C++ compile that fails on a warning
    #![deny(warnings)]   the same in Rust
    noUnusedLocals       the same in TypeScript

which is the fail-OPEN on missing ground truth (#13) that this file exists to prevent, and the same
shape as the discarded-gate bug found in cycle 1 — cria holding the failure and reporting green.

WHY IT SURVIVED. A DIFFERENT function with the same name in `focustrim.py` is tested and correct, so
the name looked covered. Grep says "tested"; the caller says otherwise.

`TypeError` is no longer caught. Nothing here legitimately raises it, and catching it is what let
this live.
"""

import tempfile
import unittest

from cria import probediscovery, probegate, proberun
from cria.probediscovery import ProbeCandidate, ProbeCost, ProbeKind


def cand(kind: ProbeKind) -> ProbeCandidate:
    return ProbeCandidate(kind=kind, command=["x"], working_dir=tempfile.gettempdir(),
                          confidence=90, expected_value=80, cost=ProbeCost.Cheap,
                          mutates_code=False, may_hang=False, may_need_services=False, reason="t")


def plan(*kinds: ProbeKind) -> probegate.GatePlan:
    return probegate.GatePlan(workspace="/tmp", candidates=[cand(k) for k in kinds])


class AHardFailureIsReportedTests(unittest.TestCase):
    def test_a_failing_test_probe_is_hard(self):
        """The regression, stated as the thing that was false for the whole life of the function."""
        self.assertTrue(probegate._is_hard_failure(plan(ProbeKind.Test), "probe-0"))

    def test_every_kind_in_the_hard_set_is_hard(self):
        for kind in proberun._HARD_FAILURE_KINDS:
            with self.subTest(kind=kind):
                self.assertTrue(probegate._is_hard_failure(plan(kind), "probe-0"))

    def test_the_right_candidate_is_read_for_the_section(self):
        """probe-N is candidate N; reading the wrong one would be the same class of silent wrong."""
        p = plan(ProbeKind.Lint, ProbeKind.Test)
        self.assertFalse(probegate._is_hard_failure(p, "probe-0"))
        self.assertTrue(probegate._is_hard_failure(p, "probe-1"))


class WhatMustStayFalseTests(unittest.TestCase):
    def test_a_lint_probe_is_advisory(self):
        """Preserved exactly: a lint finding is not a hard failure, which is why the set is a set."""
        self.assertFalse(probegate._is_hard_failure(plan(ProbeKind.Lint), "probe-0"))

    def test_a_section_that_is_not_a_probe(self):
        self.assertFalse(probegate._is_hard_failure(plan(ProbeKind.Test), "git"))

    def test_an_index_past_the_plan(self):
        self.assertFalse(probegate._is_hard_failure(plan(ProbeKind.Test), "probe-9"))

    def test_no_plan_at_all(self):
        self.assertFalse(probegate._is_hard_failure(None, "probe-0"))


class TheExceptNoLongerHidesTheDefectTests(unittest.TestCase):
    """Asserted by RAISING one, not by reading the except clause.

    The first version searched the source for the word `TypeError` inside the `except`. That passes
    the moment the word is deleted, whatever the function then does with a real one — and the defect
    it guards is precisely that a swallowed exception looks like a `False`."""

    class _Exploding:
        """A plan whose candidate access raises the exception that hid for months."""
        @property
        def candidates(self):
            raise TypeError("kind is a field, not a method")

    def test_a_type_error_propagates_instead_of_becoming_False(self):
        with self.assertRaises(TypeError):
            probegate._is_hard_failure(self._Exploding(), "probe-0")

    def test_the_three_expected_shapes_are_still_absorbed(self):
        """What the except is FOR: a malformed id, a short plan, a plan-shaped object with no
        candidates. Each is a legitimate False, and none of them may start raising."""
        class _NoCandidates:
            pass
        for bad, label in ((None, "no plan"), (_NoCandidates(), "no candidates attr"),
                           (plan(ProbeKind.Test), "index past the plan")):
            with self.subTest(case=label):
                self.assertFalse(probegate._is_hard_failure(bad, "probe-9"))

    def test_it_reads_the_field_not_a_method(self):
        """The original defect, stated as behaviour: a Test candidate IS a hard failure. If `kind`
        were called rather than read, this returns False — which is exactly what it did."""
        self.assertTrue(probegate._is_hard_failure(plan(ProbeKind.Test), "probe-0"))


class TheOtherFunctionOfThisNameIsUnrelatedTests(unittest.TestCase):
    """It is why this one looked covered. Pinned so the next reader is not fooled the same way."""

    def test_focustrim_has_its_own(self):
        from cria import focustrim
        self.assertIsNot(getattr(focustrim, "_is_hard_failure", None), probegate._is_hard_failure)


if __name__ == "__main__":
    unittest.main()
