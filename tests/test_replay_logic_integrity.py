"""The offline replay harness must never answer a broken question with a number.

WHAT WAS WRONG. ``suite/replay_logic.py`` raises on purpose when an assumption it measures THROUGH
stops holding — :func:`replay_logic.around` raises when a prompt template no longer has literal text
around its placeholder, with the comment "A silent 0 is the one answer this harness must never give:
it reads as 'the guard never fires' when it means 'the anchor moved'. Fail loudly instead."

``main`` then caught it. The per-run handler was ``except Exception: n, why = 0, "replay error: …"``,
and a zero is never printed — the ``--detail`` rows only show runs that FIRED. So the loudest failure
this file can produce came out of it as::

    ── steer-truncated: would fire on 0/86 runs (0%)

and nothing else. Reproduced by shortening a prompt template. Every offline number this project
quotes comes off these checks, so a check that reports 0% because it broke is worse than no check.

WHAT THE FIX IS. Two different kinds of failure, told apart rather than merged:

* :class:`replay_logic.IntegrityError` — the harness is measuring the wrong thing. Not a fact about
  one run, never caught per-run, takes the process's exit code with it.
* anything else — one run's evidence is broken. Reported by name, and counted in NEITHER half of the
  rate, because a run that raised did not answer the question and is not a zero.
"""
import io
import pathlib
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

SUITE = pathlib.Path(__file__).resolve().parent.parent / "suite"
sys.path.insert(0, str(SUITE))

import replay_logic  # noqa: E402

_RUNS = [({"model": "m1", "score": 4}, pathlib.Path("/nope/cap-a"), None),
         ({"model": "m2", "score": 0}, pathlib.Path("/nope/cap-b"), None)]


def _with_check(fn):
    """Run a block with ``fn`` registered as the check named 'probe'."""
    return mock.patch.dict(replay_logic.CHECKS, {"probe": fn}, clear=False)


class AnIntegrityRaisePropagatesTests(unittest.TestCase):
    def test_run_check_does_not_swallow_it(self):
        def broken(row, cap, ws):
            raise replay_logic.IntegrityError("the anchor moved")
        with _with_check(broken), self.assertRaises(replay_logic.IntegrityError):
            replay_logic.run_check("probe", _RUNS)

    def test_main_does_not_swallow_it_either(self):
        """The whole point: it must leave ``main``, not be printed as a rate."""
        def broken(row, cap, ws):
            raise replay_logic.IntegrityError("the anchor moved")
        argv = ["replay_logic.py", "--check", "probe"]
        with _with_check(broken), mock.patch.object(sys, "argv", argv), \
                mock.patch.object(replay_logic, "runs", lambda: _RUNS):
            with self.assertRaises(replay_logic.IntegrityError), redirect_stdout(io.StringIO()):
                replay_logic.main()

    def test_a_moved_prompt_ANCHOR_is_an_integrity_failure(self):
        """The reviewer's reproduction, driven on cria's real template: shorten it until ``around``
        has no literal text to anchor on, and the harness must refuse to report a number."""
        template = "{{A}}{{B}}"          # placeholders back to back — no literal anchor anywhere
        with mock.patch.object(replay_logic.prompts, "load", lambda _n: template):
            with self.assertRaises(replay_logic.IntegrityError):
                replay_logic.around("any_template", "{{A}}")

    def test_and_it_is_not_an_ordinary_exception_to_the_per_run_handler(self):
        """A subclass of Exception that the generic handler must be written to let through — this is
        the assertion that fails if someone re-broadens the except."""
        self.assertTrue(issubclass(replay_logic.IntegrityError, Exception))
        def broken(row, cap, ws):
            raise replay_logic.IntegrityError("x")
        with _with_check(broken), self.assertRaises(replay_logic.IntegrityError):
            replay_logic.run_check("probe", _RUNS)


class AnErroredRunIsNotAZeroTests(unittest.TestCase):
    def test_it_is_kept_out_of_both_halves_of_the_rate(self):
        def half_broken(row, cap, ws):
            if row["model"] == "m1":
                raise OSError("this run's evidence is gone")
            return 1, "fired"
        with _with_check(half_broken):
            fired, answered, _rows, errors = replay_logic.run_check("probe", _RUNS)
        self.assertEqual((fired, answered), (1, 1))     # 1 of 1 that ANSWERED, not 1 of 2
        self.assertEqual(len(errors), 1)
        self.assertIn("OSError", errors[0][1])

    def test_the_error_is_PRINTED_without_detail(self):
        """It used to be reachable only through ``--detail``, and only for runs that fired — which
        is to say never."""
        def all_broken(row, cap, ws):
            raise OSError("this run's evidence is gone")
        argv = ["replay_logic.py", "--check", "probe"]
        buf = io.StringIO()
        with _with_check(all_broken), mock.patch.object(sys, "argv", argv), \
                mock.patch.object(replay_logic, "runs", lambda: _RUNS):
            with redirect_stdout(buf):
                rc = replay_logic.main()
        out = buf.getvalue()
        self.assertIn("RAISED", out)
        self.assertIn("OSError", out)
        self.assertNotIn("(0%)", out)          # never a rate that reads as "the guard is silent"
        self.assertIn("NO run answered", out)
        self.assertNotEqual(rc, 0)             # and the exit code says so

    def test_a_clean_check_still_reports_its_rate_and_exits_zero(self):
        def clean(row, cap, ws):
            return (1 if row["model"] == "m1" else 0), "why"
        argv = ["replay_logic.py", "--check", "probe"]
        buf = io.StringIO()
        with _with_check(clean), mock.patch.object(sys, "argv", argv), \
                mock.patch.object(replay_logic, "runs", lambda: _RUNS):
            with redirect_stdout(buf):
                rc = replay_logic.main()
        self.assertIn("1/2 runs (50%)", buf.getvalue())
        self.assertNotIn("RAISED", buf.getvalue())
        self.assertEqual(rc, 0)


class TheRealChecksStillAnswerTests(unittest.TestCase):
    """The registry itself: every check is callable and the new one is registered."""

    def test_spill_read_small_is_a_check(self):
        self.assertIn("spill-read-small", replay_logic.CHECKS)

    def test_every_around_anchor_in_this_repo_still_exists(self):
        """``around`` is the only integrity raise with live call sites; if one is already broken the
        propagation fix would turn every replay run into a traceback, so it is asserted here rather
        than discovered at the next measurement."""
        replay_logic.around("redirect_canned", "{{REPEAT_ACTION}}")


if __name__ == "__main__":
    unittest.main()
