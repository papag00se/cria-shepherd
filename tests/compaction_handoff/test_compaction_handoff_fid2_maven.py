"""Maven's own output (log-level prefix, per-class lines, BUILD FAILURE) read by the typed build lens (wave 10, FID2)."""
import pytest

from cria import probeparse, writerecord
from compaction_handoff_helpers import shell, write
from test_compaction_handoff_lenses import TASK

# Real surefire 3 output (captured: calls/20261008T133953…/0087-coder-s1.json): a per-class line AND the run's total.
PASSED = ("[INFO] Running pipeline.ImporterTest\n"
          "[INFO] Tests run: 3, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.024 s -- in pipeline.ImporterTest\n"
          "[INFO] \n[INFO] Results:\n[INFO] \n[INFO] Tests run: 3, Failures: 0, Errors: 0, Skipped: 0\n[INFO] \n"
          "[INFO] BUILD SUCCESS\n")
FAILED = ("[ERROR] Tests run: 3, Failures: 1, Errors: 0, Skipped: 0, Time elapsed: 0.03 s <<< FAILURE! -- in pipeline.ImporterTest\n"
          "[INFO] Results:\n[ERROR] Failures: \n[ERROR]   ImporterTest.rows:12 expected 5 but was 4\n"
          "[ERROR] Tests run: 3, Failures: 1, Errors: 0, Skipped: 0\n[INFO] BUILD FAILURE\n")
COMPILE = ("[INFO] Compiling 1 source file with javac [debug release 21] to target/classes\n"
           "[ERROR] COMPILATION ERROR : \n[ERROR] /ws/src/main/java/pipeline/Importer.java:[105,31] cannot find symbol\n"
           "[INFO] 1 error\n[INFO] ------------------------------------------------------------------------\n"
           "[INFO] BUILD FAILURE\n[INFO] ------------------------------------------------------------------------\n")

@pytest.mark.parametrize("out,tally", [
    (PASSED, "0f/3p"),                                       # the per-class line is NOT summed with the total (it read 0f/6p)
    (FAILED, "1f/2p"),
    ("[WARNING] Tests run: 4, Failures: 0, Errors: 0, Skipped: 1\n", "0f/4p"),
    ("Tests run: 3, Failures: 0, Errors: 0, Skipped: 0\n", "0f/3p"),   # surefire 2 / ant, unprefixed, as before
    ("[INFO] Tests run: 2, Failures: 0, Errors: 0, Skipped: 0\n[INFO] Tests run: 5, Failures: 1, Errors: 1, Skipped: 0\n", "2f/5p"),   # two modules: totals summed
    ("Tests run: 2, Failures: 1, Errors: 0, Skipped: 0, Time elapsed: 0.1 sec <<< FAILURE!\n", "1f/1p"),  # output cut before the total: the per-class line
    ("[\x1b[1;34mINFO\x1b[m] Tests run: 7, Failures: 0, Errors: 0, Skipped: 0\n", "0f/7p"),   # a coloured terminal run
    ("[INFO] No tests to run.\n[INFO] BUILD SUCCESS\n", "")])
def test_a_maven_tally_is_read_through_its_log_level_prefix_and_counted_once(out, tally):
    """`[INFO] Tests run:` was never recognised (the row anchored on the bare words), and per-class lines were summed with the total."""
    assert probeparse.runner_tally(out) == tally
    assert probeparse.runner_and_tally(out)[0] == ("junit" if tally else "")

def test_a_maven_tally_line_is_never_picked_as_the_failure_message():
    """The tally-shape guard knew only the bare `Tests run:` line, so Maven's prefixed one could be shipped as the diagnosis."""
    assert probeparse._TALLY_SHAPED.search("[ERROR] Tests run: 3, Failures: 1, Errors: 0, Skipped: 0")
    assert not probeparse._TALLY_SHAPED.search("[ERROR]   ImporterTest.rows:12 expected 5 but was 4")

@pytest.mark.parametrize("out,code,state", [
    (FAILED, 1, "red"),                    # a Maven test failure: the prefixed tally, now read
    (PASSED, 0, "green"),
    (COMPILE, 1, "red"),                   # a compile failure prints NO tally: the build tool's own verdict is the summary
    (COMPILE, 0, "unknown"),               # ...but only beside a non-zero exit (a pipeline's status is a filter's)
    ("[INFO] BUILD SUCCESS\n", 0, "unknown"),
    ("[ERROR] build failure is the topic of README\n", 1, "unknown"),   # a sentence that merely mentions it
    ("cat build.log\n", 1, "unknown")])
def test_the_check_record_reads_a_maven_run_as_red_or_green_from_the_tools_own_lines(out, code, state):
    """Across 120 captured Java sessions / 8,883 coder histories no run was ever red or green to the build lens: every `BUILD FAILURE` was unknown."""
    record = writerecord.CheckRecord(TASK + write("w") + shell("m", "mvn test", out, code))
    assert record.events[-1] == ("exec", state)
    assert record.unsupported() == ("the newest run failed" if state == "red" else "")

def test_a_later_unreadable_run_hides_an_older_red_maven_run():
    """Only the NEWEST run counts: a red compile followed by a run nothing can read abstains."""
    messages = TASK + write("w") + shell("m", "mvn compile", COMPILE, 1) + shell("l", "ls target", "classes\n", 0)
    assert writerecord.CheckRecord(messages).unsupported() == ""

def test_the_last_build_verdict_of_a_script_that_ran_two_builds_is_the_newest_state():
    assert probeparse.build_verdict("[INFO] BUILD FAILURE\n[INFO] BUILD SUCCESS\n") == "passed"
    assert probeparse.build_verdict("BUILD SUCCESSFUL in 3s\nBUILD FAILED in 1m 2s\n") == "failed"      # gradle's closing line carries its duration
    assert probeparse.build_verdict("the BUILD FAILED banner is printed when it fails\n") == ""
    assert probeparse.build_verdict("BUILD FAILED\n") == "failed" and probeparse.build_verdict("") == ""


# --- a write to a prose document after the last run cannot change that run's result -------------------------------------
from cria import cleanup_languages, denial, probediscovery
from compaction_handoff_helpers import call, result

GREEN_MVN = shell("m", "mvn test", PASSED, 0)
RED_MVN = shell("m", "mvn test", COMPILE, 1)

@pytest.mark.parametrize("path,counts", [
    ("REVIEW.md", False), ("docs/notes.rst", False), ("/ws/NOTES.markdown", False),       # prose documents
    ("src/main/java/pipeline/Importer.java", True), ("pom.xml", True), ("requirements.txt", True),
    ("src/test/resources/orders.csv", True), ("scratch.log", True), ("Makefile", True), ("a.tmp", True)])   # a source, manifest, fixture, or a type the registry does not know
def test_only_a_prose_document_is_a_write_that_cannot_change_a_build(path, counts):
    assert writerecord.may_change_a_build(path) is counts

def test_no_source_extension_manifest_or_config_cria_knows_ever_types_as_a_prose_document():
    """The prose rule must never swallow a build input the project's own registries name (a future entry fails here)."""
    names = list(probediscovery.RELEVANT_EXACT) + list(probediscovery.PRIMARY_MANIFESTS)
    names += [c for conv in probediscovery.TEST_CONVENTIONS for c in conv.configs]
    names += [f"Main.{ext}" for conv in probediscovery.TEST_CONVENTIONS for ext in conv.exts]
    names += [f"Main{ext}" for ext in cleanup_languages.LANGUAGES]
    assert len(names) > 60 and [n for n in names if not writerecord.may_change_a_build(n)] == []

def doc_write(cid, path="REVIEW.md", outcome=denial.LANDED):
    return [call(cid, "write_file", path=path, content="# Review\n" * 30), result(cid, "Wrote", outcome)]

@pytest.mark.parametrize("parts,reason", [
    ([GREEN_MVN, doc_write("d")], ""),                                           # a REVIEW.md after the green compile: the green is still current
    ([GREEN_MVN, doc_write("d", "src/Importer.java")], "a write landed after the last run"),
    ([GREEN_MVN, doc_write("d"), write("w")], "a write landed after the last run"),   # ...but a source write alongside it still is
    ([GREEN_MVN, [call("p", "apply_patch", input="*** Add File: REVIEW.md\n+x\n*** Update File: pom.xml\n"), result("p", "Done", denial.LANDED)]],
     "a write landed after the last run"),                                       # one build input among the patch's targets
    ([GREEN_MVN, [call("w", "write_file", content="x"), result("w", "Wrote", denial.LANDED)]], "a write landed after the last run"),   # unreadable target
    ([RED_MVN, doc_write("d", outcome=None)], "the newest run failed"),          # a notes write no longer masks the red run behind a 'maybe'
    ([RED_MVN, doc_write("d", "pom.xml", outcome=None)], "")])                   # an unproven write to a build input still does
def test_a_prose_write_after_the_last_run_neither_stales_a_green_nor_hides_a_red(parts, reason):
    """A false refusal of 'it compiles' because REVIEW.md was written last; and a red newest run masked by the same write."""
    messages = TASK + write("w0") + [m for part in parts for m in part]
    assert writerecord.CheckRecord(messages).unsupported() == reason

from test_compaction_handoff_lenses import GREEN, validate

def test_a_green_briefing_is_not_refused_for_a_notes_file_written_after_the_green_run_but_is_for_a_source_write():
    """Through the whole gate: the build lens asks nothing (the typed record backs the claim) after a REVIEW.md write."""
    notes = TASK + write("w0") + GREEN_MVN + doc_write("d")
    ok, asked, _, _ = validate(GREEN, messages=notes, build=f"{GREEN} | GREEN")
    assert ok is True and "build" not in asked
    ok, asked, answers, _ = validate(GREEN, messages=TASK + write("w0") + GREEN_MVN + write("w1"), build=f"{GREEN} | GREEN")
    assert ok is False and answers["build"].startswith("UNRUN") and "build" in asked
