"""The grid reported noise as progress, and a day of walking went after it.

Measured 2026-08-17 over every row in `suite/results/results.jsonl`:

    same cell, same arm, SAME COMMIT, run more than once   ->  median spread 25 points, max 50
    same cell, across all code states                      ->  median spread 75 of 100
    cells whose spread is >= 60 points                     ->  26 of 47

A check is worth 20-25 points, so one check flips between two runs of the SAME binary, routinely.
Every number the campaign compares is a single run per cell, and the grid printed the difference
between two of them as a bare `(+50)` — a movement that was never measured (#5b).

It cost real work. `shipping-rates-rb x gemma4` was walked as "cria took it from 4/5 to 1/5"; that
cell's fifteen standing runs read 4, 0, 5, 1, 5, 1, 4, 0, 4, 4, 2, 3, 1, 0, 1 — it has scored full
marks twice and zero three times, and its mean is 2.3. The campaign's headline (60% unassisted
against 54% under cria) is 6 points across 24 cells at one run each, against a floor four times
that. And `battery_status` had a selector that sent the walker at the largest single-run gap it
could find, which is the most efficient possible way to spend a day inside the noise.

WHAT SURVIVES, AND WHY THE ANSWER IS NOT "RUN MORE AND WAIT". The findings from the walks are
mechanical — a false sentence in a note, a killed stream handed to a judge as an action log, a
refusal pointing at a path the coder cannot type. Each is proven from the transcript, in one run,
without reference to a score. That is the evidence this campaign actually runs on. Scores rank what
to look at next; they were never able to prove a cause, and now they say so.

The floor is the task's OWN check granularity rather than a constant, because that is the thing that
flips: `100/max_score`. A four-check task cannot move less than 25 points and a five-check task
cannot move less than 20.
"""

import unittest

from suite import battery_status as bs


def _row(task, model, arm, score, mx=5, **kw):
    r = {"task": task, "model": model, "score": score, "max_score": mx,
         "note": f"BATTERY2 {arm} {model} abc1234", "started": 1.0}
    r.update(kw)
    return r


class OneCheckIsNotMovementTests(unittest.TestCase):
    """The `~` that used to prefix such a delta is gone from the cell (operator, 2026-08-21) — it
    did not matter to the reader. What it stood on is not gone: `within_noise` is the same test, and
    the grid still refuses to BOLD a movement smaller than one check, so a flip does not shout."""

    def test_a_one_check_delta_is_inside_the_noise(self):
        now, before = _row("t", "m", "CRIA", 4), _row("t", "m", "CRIA", 3)
        self.assertEqual(bs.delta_of(now, before), " (+20)")
        self.assertTrue(bs.within_noise(now, before))

    def test_the_mark_is_not_printed_at_all(self):
        for a, b in ((4, 3), (5, 3), (3, 3)):
            with self.subTest(scores=(a, b)):
                self.assertNotIn("~", bs.delta_of(_row("t", "m", "CRIA", a),
                                                  _row("t", "m", "CRIA", b)))

    def test_a_two_check_delta_is_real(self):
        now, before = _row("t", "m", "CRIA", 5), _row("t", "m", "CRIA", 3)
        self.assertEqual(bs.delta_of(now, before), " (+40)")
        self.assertFalse(bs.within_noise(now, before))

    def test_the_floor_follows_the_task_not_a_constant(self):
        """A four-check task cannot move less than 25 points; a five-check one, 20. The same 25-point
        delta is therefore noise on one task and movement on the other."""
        self.assertTrue(bs.within_noise(_row("t", "m", "CRIA", 3, mx=4),
                                        _row("t", "m", "CRIA", 2, mx=4)))     # 25 pts = one check
        self.assertFalse(bs.within_noise(_row("t", "m", "CRIA", 5, mx=5),
                                         _row("t", "m", "CRIA", 3.75, mx=5)))  # 25 pts = 1.25 checks
        self.assertEqual(bs.delta_of(_row("t", "m", "CRIA", 3, mx=4),
                                     _row("t", "m", "CRIA", 2, mx=4)), " (+25)")

    def test_a_row_with_no_check_count_still_gets_a_floor(self):
        """Fail toward marking (#13): claiming precision a row cannot support is the bug."""
        self.assertEqual(bs.noise_floor(None), 20.5)
        self.assertEqual(bs.noise_floor({}, {"max_score": 4}), 25.5)

    def test_zero_is_still_zero(self):
        self.assertEqual(bs.delta_of(_row("t", "m", "CRIA", 3), _row("t", "m", "CRIA", 3)), " (0)")


class TheTotalIsAllowedToBeMoreSensitiveTests(unittest.TestCase):
    def test_pooling_six_cells_lowers_the_floor_but_does_not_remove_it(self):
        """Independent flips partly cancel, so a total may resolve movement no single cell can —
        `grain/sqrt(n)` — but it still may not call one flipped check a trend."""
        self.assertLess(bs.noise_floor(_row("t", "m", "CRIA", 4)) / (6 ** 0.5),
                        bs.noise_floor(_row("t", "m", "CRIA", 4)))
        self.assertGreater(bs.noise_floor(_row("t", "m", "CRIA", 4)) / (6 ** 0.5), 0.5)


class TheWalkerIsNotSentAfterNoiseTests(unittest.TestCase):
    def test_a_one_check_gap_is_not_a_loss(self):
        """The selector's whole job is to find where cria made a run WORSE. A gap it cannot
        distinguish from a re-run is not that, and chasing one costs a day."""
        rs = [_row("shipping-rates-rb", "gemma4", "BASE", 4),
              _row("shipping-rates-rb", "gemma4", "CRIA", 3)]
        b = bs.cell(rs, "BASE", "gemma4", "shipping-rates-rb")
        c = bs.cell(rs, "CRIA", "gemma4", "shipping-rates-rb")
        self.assertLessEqual((bs.pct(b) or 0) - (bs.pct(c) or 0), bs.noise_floor(c, b))

    def test_a_three_check_gap_still_is(self):
        rs = [_row("shipping-rates-rb", "gemma4", "BASE", 5),
              _row("shipping-rates-rb", "gemma4", "CRIA", 1)]
        b = bs.cell(rs, "BASE", "gemma4", "shipping-rates-rb")
        c = bs.cell(rs, "CRIA", "gemma4", "shipping-rates-rb")
        self.assertGreater((bs.pct(b) or 0) - (bs.pct(c) or 0), bs.noise_floor(c, b))


class TheClaimBehindTheMarkIsCheckableTests(unittest.TestCase):
    def test_the_legend_states_the_measurement_from_the_rows(self):
        """A threshold whose basis is a sentence someone typed rots. This one is recomputed from
        results.jsonl every regeneration (#12)."""
        rs = [_row("t", "m", "CRIA", 2), _row("t", "m", "CRIA", 4)]
        said = bs.repeat_evidence(rs)
        self.assertIn("IDENTICAL CODE", said)
        self.assertIn("40 points", said)      # 2/5 -> 4/5 is a 40-point spread at one commit

    def test_no_repeats_makes_no_claim(self):
        self.assertEqual(bs.repeat_evidence([_row("t", "m", "CRIA", 2)]), "")

    def test_the_real_report_carries_it(self):
        rs = bs.rows()
        body = bs.report(rs)
        self.assertIn("one check flips", body)
        if bs.repeat_evidence(rs):
            self.assertIn("IDENTICAL CODE", body)


class NothingElseSubtractsScoresTests(unittest.TestCase):
    def test_delta_of_is_the_only_place_a_difference_is_taken(self):
        """Two copies of an arithmetic is two places for it to be wrong, and the terminal table's
        own copy was — it skipped both the cross-measure guard and the noise mark."""
        import inspect
        src = inspect.getsource(bs)
        body = src.split("def delta_of", 1)[1].split("\ndef ", 1)[1]  # everything after delta_of
        self.assertNotIn("pct(c) or 0) - (pct(b)", body)
        self.assertNotIn("pct(b) or 0) - (pct(c)", body.split("def main")[0])


if __name__ == "__main__":
    unittest.main()
