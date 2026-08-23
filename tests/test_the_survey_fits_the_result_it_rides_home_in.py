"""The workspace survey was 4.7x the size of the tool result it rode home in, and was destroyed.

`plan_gate` appends the survey to the gate script, so the probe sections and the survey travel in
ONE tool result. The probe sections are already budgeted to fill that result on their own
(`probe_output_budget` divides `INLINE_RESULT_MAX_BYTES` less the marker overhead). The survey was
appended on top under a bound of its own — `TREE_MAX_BYTES = 48_000` — beneath a comment claiming
those bounds "keep the whole survey comfortably inside a normal cap".

Measured two ways. Across 401 real harness-truncated results in `~/.cria/calls` the retained size is
9,292 min / 10,212 median / 10,223 p90. Running the real survey program against all 87 archived run
workspaces: **10 of 10 rust and 22 of 35 ruby workspaces produced a survey over the bound**, median
40-49 KB — and those are the two task families that have been running. This repo surveys at 55,289.

`apply_survey` refuses a survey that arrived cut, which is correct and is why nothing looked broken:
the view simply stayed NEVER SURVEYED. That is the state `_confirm_completion` returns CONFIRMED on,
the state that gives the judge no tools and no seeded files, and the state in which
`linterprobe.collect_files` finds nothing to probe.

The arithmetic is self-balancing, which is what makes budgeting it safe: an unsurveyed view yields
no probe candidates, so the first gate of a session spends nearly the whole result on the survey;
once the survey has landed and the probes exist, the survey folds to what is left and says it is
incomplete — which every downstream reader already handles as unknown rather than absent.

And a survey that does not land is now an EVENT rather than an absence (#12).
"""

import pathlib
import subprocess
import tempfile
import unittest

from cria import content_reduce, probegate, proberun, wsview


def _tree(files, per_dir=40):
    d = tempfile.mkdtemp()
    for i in range(files):
        p = pathlib.Path(d, "vendor", "bundle", f"g{i // per_dir}", f"f{i}.rb")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    pathlib.Path(d, "lib").mkdir(exist_ok=True)
    pathlib.Path(d, "lib", "shipping.rb").write_text("class Shipping; end")
    return d


def _run(root, budget=None):
    cmd = wsview.survey_command("s", cd=root, budget=budget)
    out = subprocess.run(["sh", "-c", cmd], capture_output=True, text=True).stdout
    return wsview.strip_survey(out)[1]


class ASurveyFitsOneResultTests(unittest.TestCase):
    def test_a_dependency_tree_still_fits_the_bound_a_tool_result_is_held_to(self):
        survey = _run(_tree(1200))
        self.assertLess(len(survey), content_reduce.INLINE_RESULT_MAX_BYTES)

    def test_it_lands_instead_of_being_refused(self):
        root = _tree(1200)
        view = wsview.View(root, "s")
        self.assertTrue(wsview.apply_survey(view, _run(root)))
        self.assertTrue(view.surveyed)

    def test_what_did_not_fit_is_folded_not_dropped(self):
        """A folded directory is named and its interior reads as unknown — never as absent."""
        root = _tree(1200)
        view = wsview.View(root, "s")
        wsview.apply_survey(view, _run(root))
        self.assertTrue(view._folded)
        folded_dir = sorted(view._folded)[0]
        self.assertIsNone(view.isfile(folded_dir + "/anything.rb"),
                          "a path inside a folded directory must read as unknown, never absent")

    def test_the_old_bound_really_did_overrun(self):
        """Not a hypothetical: the previous value produces a survey five times the cap."""
        survey = _run(_tree(1200), budget=48_000)
        self.assertGreater(len(survey), 4 * content_reduce.INLINE_RESULT_MAX_BYTES)

    def test_a_survey_cut_in_transit_is_still_refused_wholesale(self):
        """The guard that made this silent must stay: a listing cut in transit is indistinguishable
        from a listing of a smaller repo, so every file past the cut would read as deleted."""
        root = _tree(1200)
        view = wsview.View(root, "s")
        self.assertFalse(wsview.apply_survey(view, _run(root, budget=48_000)[:10_212]))
        self.assertFalse(view.surveyed)


class TheGateGivesTheSurveyWhatIsLeftTests(unittest.TestCase):
    def test_a_gate_with_no_probes_hands_over_nearly_the_whole_result(self):
        root = _tree(600)
        plan = probegate.plan_gate(root)
        budget = (content_reduce.INLINE_RESULT_MAX_BYTES
                  - proberun.probe_output_budget(len(plan.candidates))[0] * len(plan.candidates)
                  - proberun.MARKER_OVERHEAD_BYTES)
        if plan.candidates:
            self.skipTest("this workspace produced probes; the no-probe arm is covered by the unit above")
        self.assertGreater(budget, 5_000)

    def test_the_whole_gate_script_still_fits_when_probes_and_survey_share_it(self):
        """The property the sweep found broken: sections + overhead + survey inside one result."""
        for probes in (0, 1, 4, 6):
            with self.subTest(probes=probes):
                cap, _ = proberun.probe_output_budget(probes) if probes else (0, True)
                left = (content_reduce.INLINE_RESULT_MAX_BYTES - cap * probes
                        - proberun.MARKER_OVERHEAD_BYTES)
                carried = max(left, 0) if left >= wsview.TREE_MIN_BYTES else 0
                self.assertLessEqual(cap * probes + proberun.MARKER_OVERHEAD_BYTES + carried,
                                     content_reduce.INLINE_RESULT_MAX_BYTES)

    def test_a_ranked_plan_still_leaves_the_survey_a_real_share(self):
        """Up to the ranked cap the survey must still be worth carrying — otherwise every gate after
        the first stops feeding the view, and an unsurveyed view is what `_confirm_completion` fails
        open on. (A plan can exceed this count via the per-file syntax floor; that plan already
        reports `fits=False`, which is its own finding.)"""
        for probes in range(1, proberun.MAX_RANKED_GATE_PROBES + 1):
            with self.subTest(probes=probes):
                cap, fits = proberun.probe_output_budget(probes)
                self.assertTrue(fits)
                left = (content_reduce.INLINE_RESULT_MAX_BYTES - cap * probes
                        - proberun.MARKER_OVERHEAD_BYTES)
                self.assertGreaterEqual(left, wsview.TREE_MIN_BYTES)


if __name__ == "__main__":
    unittest.main()
