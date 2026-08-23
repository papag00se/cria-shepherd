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
        self.assertIn("NOT continuous", marker)
        # …and it now says what fills the gap. A blind head+tail cut removed exactly the lines a
        # checker exists to print: with four probes in a plan each section gets 1,850 bytes, 925 from
        # each end, while a javac error with its symbol lines is ~200 and a minitest failure with a
        # backtrace is ~500. Walked 2026-08-22: four of nine java errors never reached cria at all.
        self.assertIn("carry a file and a line number", marker)

    def test_the_line_after_the_marker_starts_at_a_line_boundary(self):
        """The failure mode, in one assertion: the tail used to open mid-token (`ec"=>"10.38…`)."""
        out = run_with_cap(LONG, 1200)
        lines = out.splitlines()
        # The tail now resumes after the SECOND marker — the recovered diagnostic lines sit between
        # the two. The property under test is unchanged: whatever resumes starts at a line boundary.
        i = next(k for k, l in enumerate(lines) if "recovered from the middle" in l)
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




class TheDiagnosticsSurviveTheCutTests(unittest.TestCase):
    """The middle of a probe's output is where the findings are, and it was the part being removed.

    With four probes in a plan each section gets 1,850 bytes — 925 from each end — while one javac
    error with its `symbol:`/`location:` lines is about 200 bytes and one minitest failure with a
    backtrace is about 500. Walked on the 2026-08-22 runs: four of nine java compile errors never
    reached cria at all, and the ruby run's located failure was cut out of a section whose own marker
    announced 3,504 bytes removed — after which cria told the coder "a specific line could not be
    parsed from the output", with the raw block in the same prompt.

    So the middle is filtered, not dropped: every line carrying `path:line` survives with the lines
    indented under it. That is the shape `probeparse.split_diag` reads, in every language.
    """

    def _run(self, text, cap=1850):
        return run_with_cap(text, cap)

    def test_nine_javac_errors_buried_in_a_build_log_all_survive(self):
        from cria import probeparse
        noise = "\n".join(f"[INFO] downloading artifact part {i} of the reactor" for i in range(60))
        errs = "\n".join(
            f"[ERROR] /w/src/main/java/pipeline/Importer.java:[{100 + i},30] cannot find symbol\n"
            f"  symbol:   class Thing{i}\n  location: package com.opencsv" for i in range(9))
        out = self._run(noise + "\n" + errs + "\n" + noise)
        found = probeparse.parse_generic(out)
        self.assertEqual(len(found), 9, "a diagnostic was cut out of the middle")
        self.assertIn("class Thing4", out)          # one from the deepest part of the removed middle
        self.assertIn("package com.opencsv", out)   # ...with the line that says which package

    def test_a_minitest_failure_behind_five_error_backtraces_survives(self):
        blocks = "\n".join(
            f"  {i}) Error:\nTestRates#test_{i}:\nNoMethodError: undefined method\n"
            + "\n".join(f"    /w/lib/shipping/rates.rb:{20 + j}:in `zone_for'" for j in range(8))
            for i in range(5))
        out = self._run("Run options: --seed 1\n\n" + blocks +
                        "\n\n  6) Failure:\nTestRates#test_threshold "
                        "[/w/test/test_rates.rb:15]:\nExpected: 0.0\n  Actual: 7.24\n\n"
                        "7 runs, 2 assertions, 1 failures, 5 errors, 0 skips\n")
        self.assertIn("test_rates.rb:15", out)

    def test_output_with_no_diagnostics_is_not_padded_with_noise(self):
        """Nothing to recover means nothing is added — the ends still bound it (#3)."""
        out = self._run("\n".join(f"progress line {i} with no location in it" for i in range(400)))
        self.assertIn("elided", out)
        self.assertNotIn("progress line 200", out)

    def test_the_gate_script_stays_portable(self):
        """The filter is a `grep -E` with no POSIX class and no two adjacent `[` — the portability
        check forbids `[[`, and a path token in a diagnostic never contains a space anyway."""
        from cria import proberun
        self.assertNotIn("[[", proberun._DIAG_LINE_RE)
        self.assertNotIn("[:", proberun._DIAG_LINE_RE)




class TheRecoveredMiddleIsWholeLinesToo(unittest.TestCase):
    """The leg added on 2026-08-22 to keep the diagnostics shipped without the whole-line guard its
    two siblings carry, and reproduced the splice they were written to prevent: with 40 errors and a
    six-probe section the recovered band ended `symbol:   ` and the closing marker was glued onto
    that half-line. A shortened record is missing information; a spliced one is information that was
    never true."""

    def _long_javac(self, n=40):
        noise = "\n".join(f"[INFO] downloading part {i}" for i in range(80))
        errs = "\n".join(
            f"[ERROR] /w/A{i}.java:[{i},3] cannot find symbol\n"
            f"  symbol:   class VeryLongClassNameNumber{i}\n"
            f"  location: package com.example.deep" for i in range(n))
        return noise + "\n" + errs + "\n" + noise

    def test_the_recovered_band_ends_on_a_line_boundary(self):
        out = run_with_cap(self._long_javac(), 1233)      # the six-probe share
        # Either closing marker: the band ends with a COUNT when the diagnostics themselves
        # overran the budget, and with a plain end-of-band note when they all fit.
        i = max(out.find("located diagnostics shown here"), out.find("recovered from the middle"))
        self.assertGreater(i, 0, "the closing marker is missing")
        i = out.rfind("...[", 0, i)
        # The last thing before the marker must be a COMPLETE line of the compiler's output, not a
        # fragment the marker is then glued onto.
        band = out[:i].rstrip("\n.[")
        last = band.splitlines()[-1] if band.splitlines() else ""
        self.assertFalse(last.rstrip().endswith(("symbol:", "location:", "class", "package")),
                         f"the band ended mid-diagnostic: {last!r}")

    def test_the_opening_marker_does_not_promise_every_line(self):
        """It said EVERY line carrying a file and a line number is reproduced. The byte bound and the
        context bound can both falsify that, and a promise cria cannot keep is a false fact (#5b)."""
        out = run_with_cap(self._long_javac(), 1233)
        marker = next(l for l in out.splitlines() if "elided here" in l)
        self.assertNotIn("Every line", marker)
        # Names the context it actually keeps — on BOTH sides of the located line, because a compiler
        # writes its message below and a test runner writes it above the first frame.
        self.assertIn("above and below", marker)


class TheCutDiagnosticsAreCounted(unittest.TestCase):
    """The recovered band had its own byte cap and no count, so when the diagnostics themselves
    overran it the block closed with "there may be more of them than fit here" — a maybe, about a
    number cria was holding.

    Walked on feed-pipeline-java x nemotron-elastic 1787436645, prompt 0086: `class Row` reached the
    model ZERO times while `CSVParserBuilder` reached it fifteen. The three that were cut are the
    three that say plainest that the API does not exist, and the model concluded it had one bad
    import line."""

    def _javac(self, n):
        noise = "\n".join(f"[INFO] downloading part {i}" for i in range(80))
        errs = "\n".join(
            f"[ERROR] /w/A{i}.java:[{i},3] cannot find symbol\n"
            f"  symbol:   class VeryLongClassNameNumber{i}\n"
            f"  location: package com.example.deep" for i in range(n))
        return noise + "\n" + errs + "\n" + noise

    def test_the_block_says_how_many_it_left_out(self):
        out = run_with_cap(self._javac(40), 1233)
        self.assertRegex(out, r"\[\d+ of \d+ located diagnostics shown here — the other \d+ were cut")
        self.assertNotIn("There may be more of them", out)

    def test_the_two_numbers_agree_with_what_is_printed(self):
        import re
        out = run_with_cap(self._javac(40), 1233)
        m = re.search(r"\[(\d+) of (\d+) located diagnostics", out)
        self.assertIsNotNone(m, out[-400:])
        shown, total = int(m.group(1)), int(m.group(2))
        self.assertEqual(total, 40)
        band = out[out.find("NOT continuous"):m.start()]
        self.assertEqual(band.count("cannot find symbol"), shown)

    def test_when_they_all_fit_there_is_no_count_to_state(self):
        out = run_with_cap(self._javac(2), 4000)
        self.assertNotIn("located diagnostics shown here", out)


class TheBandSpendsItsBudgetOnDistinctFacts(unittest.TestCase):
    """The recovered band kept whichever diagnostics came FIRST, duplicates included.

    Measured on feed-pipeline-java x nemotron-elastic 1787469110: of the six that fit, two were the
    same missing `ConcurrentHashMap` import, while `method parse()` and javac's constructor candidate
    list — the two lines that say what the library's API really is — were among the fifteen cut. The
    model read what survived and concluded it had one bad import."""

    def _dupes(self):
        noise = "\n".join(f"[INFO] step {i}" for i in range(80))
        errs = ("[ERROR] /w/A.java:[17,5] cannot find symbol\n  symbol:   class ConcurrentHashMap\n"
                "[ERROR] /w/A.java:[17,5] cannot find symbol\n  symbol:   class ConcurrentHashMap\n"
                "[ERROR] /w/A.java:[116,48] cannot find symbol\n  symbol:   method parse()\n"
                "[ERROR] /w/A.java:[114,33] no suitable constructor found for CSVParser(Reader)\n")
        return noise + "\n" + errs + noise

    def test_a_repeated_diagnostic_takes_one_slot_not_two(self):
        out = run_with_cap(self._dupes(), 700)
        self.assertEqual(out.count("class ConcurrentHashMap"), 1)

    def test_the_unique_ones_survive(self):
        out = run_with_cap(self._dupes(), 700)
        self.assertIn("method parse()", out)
        self.assertIn("no suitable constructor", out)


class ADiagnosticKeepsItsOwnMessage(unittest.TestCase):
    """Deduping LINES deletes the part that says what is wrong.

    The dedup above shipped for one day as `awk '!seen[$0]++'`, which drops a repeat of any line
    across the whole stream — and a compiler's continuation lines are identical by design. javac
    prints `symbol:` and `location:` under every error; both survived under the FIRST one and were
    deleted from all the rest. Measured on session 20260823T025404, the only run since it landed:
    78 of 210 `cannot find symbol` headers arrived with no `symbol:` line, and one arrived with
    neither — a compile error whose entire message was the words "cannot find symbol". The block
    ships under a sentence promising "each with the lines just above and below it" (#5b).

    The unit is the RECORD — a located line plus the lines under it — not the line."""

    def _javac_sharing_lines(self):
        noise = "\n".join(f"[INFO] fetching artifact {i}" for i in range(80))
        errs = "\n".join(
            f"[ERROR] /w/{f}:[{ln},22] cannot find symbol\n"
            f"  symbol:   method {sym}\n"
            f"  location: class pipeline.Importer"
            for f, ln, sym in [("Importer.java", 97, "setSkipLines(int)"),
                               ("Importer.java", 99, "setEscapeChar(char)"),
                               ("Importer.java", 101, "setAllowQuotes(boolean)"),
                               # SAME `symbol:` line as the first error, different file and line.
                               ("Row.java", 10, "setSkipLines(int)")])
        return noise + "\n" + errs + "\n" + noise

    def test_every_diagnostic_keeps_the_line_that_says_what_is_wrong(self):
        out = run_with_cap(self._javac_sharing_lines(), 4000)
        band = out[out.find("NOT continuous"):]
        self.assertEqual(band.count("cannot find symbol"), 4)
        self.assertEqual(band.count("symbol:"), 4)
        self.assertEqual(band.count("location: class pipeline.Importer"), 4)

    def test_a_shared_continuation_line_is_not_a_repeat(self):
        """Two errors naming the same missing method share a `symbol:` line and are not duplicates."""
        out = run_with_cap(self._javac_sharing_lines(), 4000)
        band = out[out.find("NOT continuous"):]
        self.assertEqual(band.count("symbol:   method setSkipLines(int)"), 2)

    def test_the_band_keeps_its_last_line_when_nothing_was_cut(self):
        """`head -c | sed '$d'` drops the half-line `head -c` leaves. Applied when nothing was cut,
        it eats a whole real line — and when that line is a `symbol:` the loss is silent, because
        every counted header is still present."""
        out = run_with_cap(self._javac_sharing_lines(), 4000)
        self.assertNotIn("located diagnostics shown here", out)   # they all fit
        band = out[out.find("NOT continuous"):]
        self.assertIn("[ERROR] /w/Row.java:[10,22] cannot find symbol", band)
        self.assertIn("  location: class pipeline.Importer", band.split("Row.java")[-1])


if __name__ == "__main__":
    unittest.main()
