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
    def test_type_error_is_not_swallowed(self):
        """Catching TypeError is what let a field-called-as-a-method return False for months."""
        import inspect
        src = inspect.getsource(probegate._is_hard_failure)
        self.assertIn("except (AttributeError, IndexError, ValueError)", src)
        self.assertNotIn("TypeError", src.split("except")[1].split(":")[0])

    def test_it_reads_the_field_not_a_method(self):
        import inspect
        self.assertIn("].kind\n", inspect.getsource(probegate._is_hard_failure))


class TheOtherFunctionOfThisNameIsUnrelatedTests(unittest.TestCase):
    """It is why this one looked covered. Pinned so the next reader is not fooled the same way."""

    def test_focustrim_has_its_own(self):
        from cria import focustrim
        self.assertIsNot(getattr(focustrim, "_is_hard_failure", None), probegate._is_hard_failure)


if __name__ == "__main__":
    unittest.main()
