"""cria handed the coder a test failure that never happened.

`shipping-rates-rb x ternary-bonsai` 1787111689. The gate's output was over budget, so
`compose_probe_command` kept the head and the tail and dropped the middle. Both cuts were made with
`head -c` / `tail -c` — BYTE offsets — and the two halves were printed as one block under the label
"the checker's OWN message and the line it flagged". What the model read:

    1) Error:
    TestRates#test_zone_for_non_eu_country_is_international:
    NoMethodError: undefined method `eu_member?' for #<ISO3166::Country … "region"=>"Americas", "subregio
    ...[middle 6838 bytes elided; head+tail kept so an early failure survives]...
    ec"=>"10.382203102111816", … "translations"=>{"en"=>"Germany"}, …>
        …/lib/shipping/rates.rb:40:in `zone_for'
        …/test/test_rates.rb:56:in `test_zone_for_eu_member_is_eu'

One record headed `..._non_eu_country_is_international`, holding a **US** country object, ending in
**Germany** data, attributed to `test_zone_for_eu_member_is_eu`. It is the head of error 1 welded to
the tail of error 5, and the join is invisible because the cut fell inside `"subregio` / `ec"=>`.

**A shortened record is missing information. A spliced record is information that was never true.**

The fix keeps whole lines on both sides — `sed '$d'` drops the head's trailing partial line, `sed
'1d'` drops the tail's leading partial line — so neither half can contain a token the tool never
printed. It costs at most one whole line per side and parses no runner's format (#20). The marker
now says outright that the two halves are not continuous.

This does not stop a reader mis-joining two COMPLETE records; it stops cria manufacturing a line
that no tool emitted.
"""

import pathlib
import subprocess
import tempfile
import unittest

from cria import probediscovery, proberun


def run_with_cap(body: str, cap: int) -> str:
    d = tempfile.mkdtemp()
    pathlib.Path(d, "emit.sh").write_text("cat <<'XEOFX'\n" + body + "XEOFX\n")
    c = probediscovery.ProbeCandidate(
        kind=probediscovery.ProbeKind.Test, command=["sh", "emit.sh"], working_dir=pathlib.Path(d),
        confidence=1, expected_value=1, cost=probediscovery.ProbeCost.Cheap, mutates_code=False,
        may_hang=False, may_need_services=False, reason="t")
    return subprocess.run(["bash", "-c", proberun.compose_probe_command(c, 60, cap=cap)],
                          capture_output=True, text=True, timeout=60).stdout


LONG = "".join(f'row{i:03d} "region"=>"Americas", "subregion"=>"North", "pad"=>"{"x" * 40}"\n'
               for i in range(200))


class NoHalfLineSurvivesTheCutTests(unittest.TestCase):
    def test_every_kept_line_is_a_whole_line(self):
        out = run_with_cap(LONG, 1200)
        kept = [l for l in out.splitlines() if l.startswith("row")]
        self.assertTrue(kept, "nothing survived the cut at all")
        for l in kept:
            with self.subTest(line=l[:40]):
                self.assertTrue(l.endswith('"'), "a line was cut mid-token")
                self.assertRegex(l, r'^row\d{3} ')

    def test_the_marker_says_the_halves_are_not_continuous(self):
        out = run_with_cap(LONG, 1200)
        marker = next(l for l in out.splitlines() if "elided" in l)
        self.assertIn("NOT continuous", marker)
        self.assertIn("START and the END", marker)

    def test_the_line_after_the_marker_starts_at_a_line_boundary(self):
        """The failure mode, in one assertion: the tail used to open mid-token (`ec"=>"10.38…`)."""
        out = run_with_cap(LONG, 1200)
        lines = out.splitlines()
        i = next(k for k, l in enumerate(lines) if "elided" in l)
        after = next(l for l in lines[i + 1:] if l.strip())
        self.assertRegex(after, r'^row\d{3} ', "the tail resumed mid-line")

    def test_the_line_before_the_marker_ends_at_a_line_boundary(self):
        out = run_with_cap(LONG, 1200)
        lines = out.splitlines()
        i = next(k for k, l in enumerate(lines) if "elided" in l)
        before = next(l for l in reversed(lines[:i]) if l.strip())
        self.assertTrue(before.endswith('"'), "the head stopped mid-line")


class OutputThatFitsIsUntouchedTests(unittest.TestCase):
    def test_a_small_result_is_passed_through_whole(self):
        out = run_with_cap("1) Failure:\nTestX#test_y\nExpected true\n", 4000)
        self.assertIn("1) Failure:", out)
        self.assertIn("Expected true", out)
        self.assertNotIn("elided", out)

    def test_both_ends_still_survive_a_cut(self):
        """The reason head+tail exists: an early failure AND a late one both have to land."""
        body = "FIRST_FAILURE_HERE\n" + ("filler line padding padding padding\n" * 400) + "LAST_FAILURE_HERE\n"
        out = run_with_cap(body, 1200)
        self.assertIn("FIRST_FAILURE_HERE", out)
        self.assertIn("LAST_FAILURE_HERE", out)


if __name__ == "__main__":
    unittest.main()
